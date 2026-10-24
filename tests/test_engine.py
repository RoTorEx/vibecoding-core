import pytest
from conftest import settle

from vibecoding_core.codex import UnknownOutcome


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
    from vibecoding_core.codex import RpcError

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


async def test_plan_mode_uses_native_settings_and_can_change_for_next_turn(host):
    settings, engine, native, client = host
    s = await new(host)
    await client.call("/sessions/" + s["id"] + "/settings", {"collaboration_mode": "plan"})
    await client.call(
        "/messages", {"request_id": "plan", "session_id": s["id"], "text": "Original plan request"}
    )
    await settle(engine)
    params = next(p for m, p in native.calls if m == "turn/start")
    assert params["input"] == [{"type": "text", "text": "Original plan request"}]
    assert params["collaborationMode"] == {
        "mode": "plan",
        "settings": {"model": "test-model", "reasoning_effort": "medium", "developer_instructions": None},
    }
    active = engine.store.session(s["id"])
    await client.call(
        "/sessions/" + s["id"] + "/settings", {"collaboration_mode": "default", "effort": "high"}
    )
    assert engine.store.session(s["id"])["turn_id"] == active["turn_id"]
    native.finish(active["thread_id"])
    await client.call("/messages", {"request_id": "execute", "session_id": s["id"], "text": "Continue"})
    await settle(engine)
    params = [p for m, p in native.calls if m == "turn/start"][-1]
    assert params["collaborationMode"]["mode"] == "default"
    assert params["collaborationMode"]["settings"]["reasoning_effort"] == "high"


async def test_conversation_cursors_reach_old_history_and_details_track_events(host):
    settings, engine, native, client = host
    s = await new(host)
    first = None
    for i in range(220):
        eid = engine.store.event(s["id"], "user", {"text": f"Request {i}"})
        first = first or eid
        engine.store.event(s["id"], "message", {"text": f"Answer {i}"})
        engine.store.event(s["id"], "completed", {"status": "completed"})
    latest = await client.call("/sessions/" + s["id"] + "/conversation")
    assert latest["index"] == latest["total"] == 220
    assert latest["user"]["payload"]["text"] == "Request 219"
    oldest = await client.call(f"/sessions/{s['id']}/conversation?anchor={first}")
    assert oldest["previous"] is None and oldest["next"] is not None
    assert oldest["replies"][0]["payload"]["text"] == "Answer 0"
    details = await client.call("/sessions/" + s["id"] + "/details")
    assert (
        details["created"] <= details["last_request"] <= details["last_response"] <= details["last_finished"]
    )
    assert details["disk_total"] >= details["disk_free"] > 0


def test_old_session_schema_migrates_without_losing_identity_or_events(tmp_path):
    import sqlite3

    from vibecoding_core.store import EngineStore

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions(
                id TEXT PRIMARY KEY,name TEXT,cwd TEXT,thread_id TEXT,turn_id TEXT,status TEXT,
                archived INTEGER,model TEXT,effort TEXT,created REAL,updated REAL);
            INSERT INTO sessions VALUES('original','Kept','/home/alex','native-id',NULL,'idle',0,NULL,'medium',1,2);
        """)
    store = EngineStore(path)
    assert store.session("original")["thread_id"] == "native-id"
    assert store.session("original")["collaboration_mode"] == "default"
    store.event("original", "user", {"text": "kept"})
    store.close()
    store = EngineStore(path)
    assert store.session("original")["name"] == "Kept"
    assert store.conversation("original")["user"]["payload"]["text"] == "kept"
    store.close()


async def test_public_summary_stream_is_durable_and_raw_reasoning_is_ignored(host):
    settings, engine, native, client = host
    s = await new(host)
    await client.call("/messages", {"request_id": "summary", "session_id": s["id"], "text": "Work"})
    await settle(engine)
    thread = engine.store.session(s["id"])["thread_id"]
    base = {"threadId": thread, "itemId": "summary-item", "summaryIndex": 0}
    engine.on_event("item/reasoning/summaryTextDelta", {**base, "delta": "Checking "})
    engine.on_event("item/reasoning/summaryTextDelta", {**base, "delta": "the behavior."})
    engine.on_event("item/reasoning/summaryPartAdded", {**base, "summaryIndex": 1})
    engine.on_event(
        "item/reasoning/summaryTextDelta", {**base, "summaryIndex": 1, "delta": "Verifying recovery."}
    )
    engine.on_event("item/reasoning/textDelta", {**base, "delta": "RAW_REASONING_MUST_NOT_APPEAR"})
    live = (await client.call("/live"))[s["id"]]
    assert live["started"] > 0
    assert live["summaries"]["summary-item"] == {"0": "Checking the behavior.", "1": "Verifying recovery."}
    assert "RAW_REASONING" not in str(live)
    completion = {
        "threadId": thread,
        "item": {
            "id": "summary-item",
            "type": "reasoning",
            "summary": ["Checked the behavior.", "Verified recovery."],
            "content": ["PRIVATE_RAW"],
        },
    }
    engine.on_event("item/completed", completion)
    engine.on_event("item/completed", completion)
    native.finish(thread, text="Final answer")
    conversation = await client.call("/sessions/" + s["id"] + "/conversation")
    summaries = [r for r in conversation["replies"] if r["kind"] == "reasoning_summary"]
    assert len(summaries) == 1
    assert summaries[0]["payload"]["parts"] == ["Checked the behavior.", "Verified recovery."]
    assert "PRIVATE_RAW" not in str(conversation)
    assert "RAW_REASONING" not in str(await client.call("/sessions/" + s["id"] + "/history"))
    start = next(p for method, p in native.calls if method == "turn/start")
    assert start["summary"] == "auto"


async def test_connecting_feedback_exists_before_native_reply_and_clears_on_failure(host):
    settings, engine, native, client = host
    s = await new(host)
    engine.submit({"request_id": "connecting", "session_id": s["id"], "text": "Work"})
    assert engine.live[s["id"]]["activity"] == "Connecting"
    assert engine.store.session(s["id"])["status"] == "connecting"
    native.fail_method = "thread/start"
    native.failure = ValueError("Test failure")
    await settle(engine)
    assert s["id"] not in engine.live
    assert engine.store.session(s["id"])["status"] == "failed"


async def test_session_list_last_response_ignores_configuration_and_progress(host):
    settings, engine, native, client = host
    session = await new(host)
    assert (await client.call("/sessions"))[0]["last_response"] is None
    engine.store.event(session["id"], "message", {"text": "Working", "phase": "commentary"})
    engine.store.event(session["id"], "reasoning_summary", {"text": "Checking"})
    assert (await client.call("/sessions"))[0]["last_response"] is None
    final = engine.store.event(session["id"], "message", {"text": "Done", "phase": "final_answer"})
    stamp = engine.store.one("SELECT created FROM events WHERE id=?", (final,))["created"]
    engine.store.update_session(session["id"], name="Renamed")
    listed = (await client.call("/sessions"))[0]
    assert listed["name"] == "Renamed"
    assert listed["last_response"] == stamp


async def test_voice_is_durable_cached_and_passed_verbatim_without_blocking_text(host):
    import asyncio
    import json

    settings, engine, native, client = host
    a, b = await new(host, "Voice"), await new(host, "Text")
    voice = settings.data_dir / "recording.ogg"
    voice.write_bytes(b"OggS")
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    transcript = "Проверь голос,  текст и картинки."

    async def transcribe(path):
        calls.append(path)
        started.set()
        await release.wait()
        return {"text": transcript, "language": "ru", "wall_seconds": 1.5}

    engine.speech.transcribe = transcribe
    body = {"request_id": "voice", "session_id": a["id"], "audio": [str(voice)]}
    await client.call("/messages", body)
    await started.wait()
    assert engine.store.session(a["id"])["status"] == "transcribing"
    await client.call("/messages", {"request_id": "text", "session_id": b["id"], "text": "text"})
    for _ in range(100):
        if engine.store.request("text")["state"] == "accepted":
            break
        await asyncio.sleep(0.001)
    assert engine.store.request("text")["state"] == "accepted"
    release.set()
    await settle(engine)
    assert [p["input"] for m, p in native.calls if m == "turn/start"][-1] == [
        {"type": "text", "text": transcript}
    ]
    assert json.loads(engine.store.request("voice")["payload"]) == body
    conversation = engine.store.conversation(a["id"])
    assert conversation["replies"][0]["kind"] == "transcription"
    assert conversation["replies"][0]["payload"]["text"] == transcript
    # Safe local preprocessing retry reuses its durable result, without recognizing again.
    engine.store.request_state("voice", "queued")
    await engine.dispatch("voice")
    assert calls == [str(voice)]
    assert await client.call("/messages", body) == {"request_id": "voice", "state": "accepted"}


async def test_stop_cancels_voice_and_shutdown_keeps_it_replayable(host):
    import asyncio

    settings, engine, native, client = host
    s = await new(host)
    voice = settings.data_dir / "voice.ogg"
    voice.write_bytes(b"OggS")
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def transcribe(path):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    engine.speech.transcribe = transcribe
    body = {"request_id": "stop-voice", "session_id": s["id"], "audio": [str(voice)]}
    await client.call("/messages", body)
    await entered.wait()
    await client.call(f"/sessions/{s['id']}/stop", {})
    assert cancelled.is_set()
    assert engine.store.request(body["request_id"])["state"] == "cancelled"
    assert not any(m == "turn/start" for m, _ in native.calls)
    assert engine.store.session(s["id"])["status"] == "interrupted"
    entered.clear()
    await client.call("/messages", {**body, "request_id": "restart-voice"})
    await entered.wait()
    # Shutdown cancels tasks without marking local queued work uncertain or cancelled.
    for task in list(engine.tasks):
        task.cancel()
    await asyncio.gather(*engine.tasks, return_exceptions=True)
    engine.store.recover()
    assert engine.store.request("restart-voice")["state"] == "queued"
    assert voice.read_bytes() == b"OggS"


async def test_voice_failure_does_not_start_native_work(host):
    settings, engine, native, client = host
    s = await new(host)
    voice = settings.data_dir / "bad.ogg"
    voice.write_bytes(b"invalid")

    async def transcribe(path):
        raise ValueError("No speech detected in this recording")

    engine.speech.transcribe = transcribe
    await client.call("/messages", {"request_id": "bad-voice", "session_id": s["id"], "audio": [str(voice)]})
    await settle(engine)
    assert engine.store.request("bad-voice")["state"] == "failed"
    assert engine.store.session(s["id"])["status"] == "failed"
    assert not native.calls


async def test_completion_cursor_distinguishes_new_outcomes_from_metadata(host):
    settings, engine, native, client = host
    s = await new(host)
    sid = s["id"]
    assert (await client.call("/sessions"))[0]["last_completed_event"] is None
    engine.store.event(sid, "message", {"text": "Partial", "phase": "commentary"})
    assert (await client.call("/sessions"))[0]["last_completed_event"] is None
    first = engine.store.event(sid, "completed", {"status": "completed"})
    engine.store.update_session(sid, name="Renamed")
    assert (await client.call("/sessions"))[0]["last_completed_event"] == first
    second = engine.store.event(sid, "completed", {"status": "failed"})
    assert (await client.call("/sessions"))[0]["last_completed_event"] == second > first


async def test_session_overview_orders_captured_input_and_excludes_progress(host):
    settings, engine, native, client = host
    a, b = await new(host, "A"), await new(host, "B")
    with engine.store.db:
        engine.store.db.execute("UPDATE sessions SET created=1,updated=1 WHERE id=?", (a["id"],))
        engine.store.db.execute("UPDATE sessions SET created=2,updated=2 WHERE id=?", (b["id"],))
    assert [s["id"] for s in await client.call("/sessions")] == [b["id"], a["id"]]
    event = engine.store.event(a["id"], "user", {"text": "A followup"})
    engine.store.accept("pending", a["id"], {"text": "A followup"})
    listed = (await client.call("/sessions"))[0]
    assert listed["id"] == a["id"] and listed["pending_requests"] == 1
    assert (
        listed["last_interaction"]
        == engine.store.one("SELECT created FROM events WHERE id=?", (event,))["created"]
    )
    engine.store.event(b["id"], "reasoning_summary", {"text": "Still working"})
    engine.store.event(b["id"], "message", {"text": "Progress", "phase": "commentary"})
    engine.store.event(b["id"], "tool", {"item": {}})
    assert (await client.call("/sessions"))[0]["id"] == a["id"]
    engine.store.request_state("pending", "accepted")
    assert (await client.call("/sessions"))[0]["pending_requests"] == 0
    engine.store.event(b["id"], "message", {"text": "Finished", "phase": "final_answer"})
    assert (await client.call("/sessions"))[0]["id"] == b["id"]
    for session in [a, b]:
        engine.store.update_session(session["id"], archived=1)
    archived = await client.call("/sessions?archived=1")
    assert archived[0]["last_interaction"] >= archived[1]["last_interaction"]


async def test_question_counts_and_status_follow_all_pending_native_requests(host):
    settings, engine, native, client = host
    s = await new(host)
    engine.store.update_session(
        s["id"], thread_id="thread-overview", turn_id="turn-overview", status="working"
    )
    for rid in [71, 72]:
        engine.on_request(
            rid,
            "item/tool/requestUserInput",
            {"threadId": "thread-overview", "questions": [{"id": str(rid), "question": "Choose"}]},
        )
    assert (await client.call("/sessions"))[0]["pending_questions"] == 2
    questions = await client.call(f"/sessions/{s['id']}/questions")
    await client.call(f"/questions/{questions[0]['id']}", {"answers": {"71": "Yes"}})
    listed = (await client.call("/sessions"))[0]
    assert listed["pending_questions"] == 1 and listed["status"] == "waiting"
    engine.on_event("serverRequest/resolved", {"requestId": 72})
    listed = (await client.call("/sessions"))[0]
    assert listed["pending_questions"] == 0 and listed["status"] == "working"
    assert listed["turn_id"] == "turn-overview"


async def test_native_limits_cache_updates_and_unavailable_do_not_run_turns(host):
    settings, engine, native, client = host
    original = native.request
    calls = []

    async def request(method, params, **kwargs):
        if method == "account/rateLimits/read":
            calls.append(method)
            return {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {"usedPercent": 23, "windowDurationMins": 300, "resetsAt": 1792900000},
                }
            }
        return await original(method, params, **kwargs)

    native.request = request
    first = await client.call("/limits")
    assert first["available"] and first["rateLimits"]["primary"]["usedPercent"] == 23
    assert await client.call("/limits") == first and len(calls) == 1
    engine.on_event(
        "account/rateLimits/updated", {"rateLimits": {"limitId": "other", "primary": {"usedPercent": 40}}}
    )
    updated = await client.call("/limits")
    assert updated["rateLimitsByLimitId"]["other"]["primary"]["usedPercent"] == 40
    engine.limits_checked = 0
    native.fail_method = "account/rateLimits/read"
    native.failure = ConnectionError("offline")
    native.request = original
    assert not (await client.call("/limits"))["available"]
    assert not any(method == "turn/start" for method, _ in native.calls)


async def test_session_creation_request_id_keeps_target_across_retries(host, tmp_path):
    settings, engine, native, client = host
    body = {"cwd": str(tmp_path), "request_id": "telegram:new:123"}
    first = await client.call("/sessions", body)
    engine.store.update_session(first["id"], name="Already renamed")
    second = await client.call("/sessions", body)
    assert second["id"] == first["id"] and second["name"] == "Already renamed"
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="different directory"):
        await client.call("/sessions", {**body, "cwd": str(other)})
    assert len(engine.store.sessions()) == 1


async def test_attachment_registration_copies_image_and_preserves_request_history(host, tmp_path):
    settings, engine, native, client = host
    session = await new(host)
    sid = session["id"]
    anchor = engine.store.event(sid, "user", {"text": "Draw this"})
    image = tmp_path / "avatar.png"
    original = b"\x89PNG\r\n\x1a\nfixture-image-content"
    image.write_bytes(original)
    body = {"path": str(image), "anchor": anchor}
    record = await client.call(f"/sessions/{sid}/attachments", body)
    assert await client.call(f"/sessions/{sid}/attachments", body) == record
    from pathlib import Path

    assert Path(record["path"]).read_bytes() == original
    assert Path(record["path"]).stat().st_mode & 0o777 == 0o600
    image.unlink()
    assert Path(record["path"]).read_bytes() == original
    assert len(await client.call(f"/sessions/{sid}/attachments?anchor={anchor}")) == 1
    conversation = await client.call(f"/sessions/{sid}/conversation")
    assert any(
        e["kind"] == "attachment" and e["payload"]["attachment_id"] == record["id"]
        for e in conversation["replies"]
    )
    bad = tmp_path / "not-an-image.png"
    bad.write_text("Keep private files private")
    with pytest.raises(ValueError, match="PNG"):
        await client.call(f"/sessions/{sid}/attachments", {"path": str(bad)})
    other = await new(host, "Other")
    with pytest.raises(ValueError, match="anchor"):
        await client.call(f"/sessions/{other['id']}/attachments", {"path": record["path"], "anchor": anchor})
