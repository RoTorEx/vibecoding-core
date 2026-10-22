import pytest
from conftest import settle

from codex_relay.codex import UnknownOutcome


async def new(host, name="Session"):
    settings, engine, native, client = host
    return await client.call("/sessions", {"cwd": str(settings.development_root.parent), "name": name})


async def test_native_thread_steering_and_no_prompt_injection(host):
    settings, engine, native, client = host
    s = await new(host)
    text = "Привет! Preserve  spaces\nand `code` exactly."
    body = {"request_id": "m1", "session_id": s["id"], "text": text, "images": []}
    assert (await client.call("/messages", body))["state"] == "queued"
    await settle(engine)
    assert (await client.call("/messages", body))["state"] == "accepted"
    starts = [p for m, p in native.calls if m == "turn/start"]
    assert len(starts) == 1
    assert starts[0]["input"] == [{"type": "text", "text": text}]
    assert starts[0]["approvalPolicy"] == "never"
    assert starts[0]["sandboxPolicy"] == {"type": "dangerFullAccess"}
    assert not any(k in starts[0] for k in ["baseInstructions", "developerInstructions"])
    await client.call("/messages", {**body, "request_id": "m2", "text": "Actually focus here"})
    await settle(engine)
    assert native.calls[-1][0] == "turn/steer"
    assert native.calls[-1][1]["expectedTurnId"]
    with pytest.raises(ValueError, match="different message"):
        await client.call("/messages", {**body, "text": "reuse wrong input"})


async def test_multiple_sessions_same_directory_and_background_ownership(host):
    settings, engine, native, client = host
    a, b = await new(host, "A"), await new(host, "B")
    assert a["cwd"] == b["cwd"]
    for s in [a, b]:
        await client.call("/messages", {"request_id": s["id"], "session_id": s["id"], "text": s["name"]})
    await settle(engine)
    a, b = engine.store.session(a["id"]), engine.store.session(b["id"])
    assert a["thread_id"] != b["thread_id"]
    native.finish(a["thread_id"], text="Answer for A")
    native.finish(b["thread_id"], text="Answer for B")
    ah = await client.call("/sessions/" + a["id"] + "/history")
    bh = await client.call("/sessions/" + b["id"] + "/history")
    assert [x["payload"]["text"] for x in ah if x["kind"] == "message"] == ["Answer for A"]
    assert [x["payload"]["text"] for x in bh if x["kind"] == "message"] == ["Answer for B"]


async def test_archive_stops_native_turn_keeps_files_and_reopens(host):
    settings, engine, native, client = host
    file = settings.development_root.parent / "keep.txt"
    file.write_text("source survives")
    s = await new(host)
    await client.call("/messages", {"request_id": "start", "session_id": s["id"], "text": "work"})
    await settle(engine)
    result = await client.call("/sessions/" + s["id"] + "/archive", {})
    assert result["archived"] == 1
    assert file.read_text() == "source survives"
    assert any(m == "turn/interrupt" for m, p in native.calls)
    assert any(m == "thread/archive" for m, p in native.calls)
    with pytest.raises(ValueError, match="archived"):
        await client.call("/messages", {"request_id": "later", "session_id": s["id"], "text": "work"})
    reopened = await client.call("/sessions/" + s["id"] + "/reopen", {})
    assert reopened["archived"] == 0


async def test_connection_loss_never_replays_ambiguous_turn(host):
    settings, engine, native, client = host
    s = await new(host)
    native.fail_method = "turn/start"
    native.failure = UnknownOutcome("connection disappeared")
    body = {"request_id": "ambiguous", "session_id": s["id"], "text": "change a file"}
    await client.call("/messages", body)
    await settle(engine)
    assert engine.store.request("ambiguous")["state"] == "uncertain"
    await client.call("/messages", body)
    await settle(engine)
    assert sum(m == "turn/start" for m, p in native.calls) == 1
    engine.store.recover()
    assert engine.store.request("ambiguous")["state"] == "uncertain"


async def test_recovery_marks_dispatching_unknown_and_expires_questions(host):
    settings, engine, native, client = host
    s = await new(host)
    engine.store.accept("at-crash", s["id"], {"text": "modify"})
    engine.store.request_state("at-crash", "dispatching")
    engine.store.update_session(s["id"], status="working", turn_id="turn-crash")
    engine.store.recover()
    assert engine.store.request("at-crash")["state"] == "uncertain"
    assert engine.store.session(s["id"])["status"] == "interrupted"
    assert engine.store.session(s["id"])["turn_id"] is None


async def test_questions_use_native_response_and_expire(host):
    settings, engine, native, client = host
    s = await new(host)
    await client.call("/messages", {"request_id": "qstart", "session_id": s["id"], "text": "plan"})
    await settle(engine)
    s = engine.store.session(s["id"])
    params = {
        "threadId": s["thread_id"],
        "questions": [{"id": "goal", "question": "Which goal?", "options": []}],
    }
    engine.on_request(99, "item/tool/requestUserInput", params)
    q = engine.store.one("SELECT * FROM questions")
    with pytest.raises(ValueError, match="every question"):
        await client.call("/questions/" + q["id"], {"answers": {}})
    await client.call("/questions/" + q["id"], {"answers": {"goal": "Keep it simple"}})
    assert native.calls[-1] == (
        "response",
        {"id": 99, "result": {"answers": {"goal": {"answers": ["Keep it simple"]}}}, "error": None},
    )
    with pytest.raises(ValueError, match="no longer pending"):
        await client.call("/questions/" + q["id"], {"answers": {"goal": "second answer"}})


async def test_projects_and_live_model_settings(host):
    settings, engine, native, client = host
    project = settings.development_root.parent / "new-project"
    project.mkdir()
    first = await client.call("/projects", {"name": "Before", "path": str(project)})
    second = await client.call("/projects", {"name": "After", "path": str(project)})
    assert first["id"] == second["id"]
    assert any(p["name"] == "After" for p in await client.call("/projects"))
    s = await new(host)
    changed = await client.call(
        "/sessions/" + s["id"] + "/settings", {"model": "test-model", "effort": "high"}
    )
    assert changed["model"] == "test-model" and changed["effort"] == "high"
    with pytest.raises(ValueError, match="supported"):
        await client.call("/sessions/" + s["id"] + "/settings", {"model": "test-model", "effort": "unknown"})
    await client.call("/messages", {"request_id": "model-turn", "session_id": s["id"], "text": "work"})
    await settle(engine)
    with pytest.raises(ValueError, match="Wait"):
        await client.call("/sessions/" + s["id"] + "/settings", {"cwd": str(project)})


async def test_explicit_no_active_turn_rejection_starts_once_but_unknown_outcome_does_not(host):
    from codex_relay.codex import RpcError

    settings, engine, native, client = host
    s = await new(host)
    await client.call("/messages", {"request_id": "race-initial", "session_id": s["id"], "text": "first"})
    await settle(engine)
    original = native.request

    async def racing_request(method, params, **kwargs):
        if method == "turn/steer":
            engine.on_event(
                "turn/completed",
                {
                    "threadId": params["threadId"],
                    "turn": {"id": params["expectedTurnId"], "status": "completed"},
                },
            )
            raise RpcError({"code": -32600, "message": "No active turn found for thread"})
        return await original(method, params, **kwargs)

    native.request = racing_request
    await client.call("/messages", {"request_id": "race-followup", "session_id": s["id"], "text": "second"})
    await settle(engine)
    starts = [p for m, p in native.calls if m == "turn/start"]
    assert len(starts) == 2
    assert starts[-1]["input"] == [{"type": "text", "text": "second"}]
    assert engine.store.request("race-followup")["state"] == "accepted"
