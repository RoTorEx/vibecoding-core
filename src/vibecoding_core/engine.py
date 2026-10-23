"""Host-owned sessions and execution, independent from the Telegram process."""

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections import defaultdict
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, UnixConnector, web

from vibecoding_core import __version__
from vibecoding_core.codex import CodexClient, RpcError, UnknownOutcome
from vibecoding_core.config import Settings
from vibecoding_core.host import inspect_directory
from vibecoding_core.speech import Speech
from vibecoding_core.store import EngineStore, identifier

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        settings.prepare()
        self.store = EngineStore(settings.data_dir / "engine.db")
        self.client = client or CodexClient(
            settings.codex_command, self.on_event, self.on_request, self.disconnected
        )
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.loaded: dict[str, int] = {}
        self.live: dict[str, dict] = {}
        self.tasks: set[asyncio.Task] = set()
        self.accepting = True
        self.speech = Speech(settings.speech_model_dir.expanduser())
        self.preprocessing: dict[str, asyncio.Task] = {}

    def spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self._task_done)

    @staticmethod
    def _task_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            log.error("Engine task failed: %s", type(task.exception()).__name__)

    def start(self) -> None:
        self.store.recover()
        self.store.register_project("Home", str(Path.home()))
        for row in self.store.rows("SELECT DISTINCT cwd FROM sessions"):
            self.store.register_session_location(Path(row["cwd"]))
        for row in self.store.rows("SELECT * FROM requests WHERE state='queued' ORDER BY created"):
            self.spawn(self.dispatch(row["id"]))

    def submit(self, payload: dict) -> dict:
        if not self.accepting:
            raise ValueError("Engine is preparing a snapshot/update; try again shortly")
        rid = payload.get("request_id")
        sid = payload.get("session_id")
        if not isinstance(sid, str):
            raise ValueError("session_id is required")
        if not isinstance(rid, str) or not rid or len(rid) > 200:
            raise ValueError("request_id is required")
        session = self.store.session(sid)
        if session["archived"]:
            raise ValueError("Reopen the archived session before sending a message")
        text, images = payload.get("text", ""), payload.get("images", [])
        if (
            not isinstance(text, str)
            or not isinstance(images, list)
            or not all(isinstance(x, str) for x in images)
        ):
            raise ValueError("Invalid message input")
        audio = payload.get("audio", [])
        if not isinstance(audio, list) or not all(isinstance(x, str) for x in audio) or len(audio) > 1:
            raise ValueError("Use one voice recording per message")
        if not text and not images and not audio:
            raise ValueError("A message needs text, an image or voice")
        for image in images + audio:
            p = Path(image).resolve(strict=True)
            if not p.is_file() or p.stat().st_size > 20_000_000:
                raise ValueError("Media must be an existing file of at most 20 MB")
        if old := self.store.request(rid):
            if old["session_id"] != sid or json.loads(old["payload"]) != payload:
                raise ValueError("request_id already belongs to a different message")
            return {"request_id": rid, "state": old["state"]}
        self.store.accept(rid, sid, payload)
        self.store.event(sid, "user", {"text": text, "images": images, "audio": audio, "request_id": rid})
        if session["name"] == "New session" and text.strip():
            self.store.update_session(sid, name=" ".join(text.split())[:70])
        if not session["turn_id"]:
            self.store.update_session(sid, status="transcribing" if audio else "connecting")
            self.live[sid] = {
                "text": "",
                "activity": "Transcribing" if audio else "Connecting",
                "started": time.time(),
                "summaries": {},
            }
        self.spawn(self.dispatch(rid))
        return {"request_id": rid, "state": "queued"}

    async def ensure_thread(self, sid: str) -> dict:
        await self.client.start()
        s = self.store.session(sid)
        params = {"cwd": s["cwd"], "approvalPolicy": "never", "sandbox": "danger-full-access"}
        if s["model"]:
            params["model"] = s["model"]
        if not s["thread_id"]:
            result = await self.client.request("thread/start", params)
            self.store.update_session(sid, thread_id=result["thread"]["id"])
        elif self.loaded.get(sid) != self.client.generation:
            await self.client.request("thread/resume", {"threadId": s["thread_id"], **params})
        self.loaded[sid] = self.client.generation
        s = self.store.session(sid)
        return s

    async def dispatch(self, rid: str) -> None:
        row = self.store.request(rid)
        sid = row["session_id"]
        async with self.locks[sid]:
            if self.store.request(rid)["state"] != "queued":
                return
            dispatched = False
            try:
                p = json.loads(row["payload"])
                transcripts = []
                if p.get("audio"):
                    if not self.store.session(sid)["turn_id"]:
                        self.store.update_session(sid, status="transcribing")
                        self.live[sid] = {
                            "text": "",
                            "activity": "Transcribing",
                            "started": time.time(),
                            "summaries": {},
                        }
                    task = asyncio.current_task()
                    assert task is not None
                    self.preprocessing[sid] = task
                    try:
                        for index, path in enumerate(p["audio"]):
                            cached = self.store.one(
                                "SELECT payload FROM events WHERE session_id=? AND kind='transcription' "
                                "AND json_extract(payload,'$.request_id')=? "
                                "AND json_extract(payload,'$.audio_index')=?",
                                (sid, rid, index),
                            )
                            result = (
                                json.loads(cached["payload"])
                                if cached
                                else await self.speech.transcribe(path)
                            )
                            if not cached:
                                self.store.event(
                                    sid,
                                    "transcription",
                                    {
                                        **result,
                                        "request_id": rid,
                                        "audio_index": index,
                                    },
                                )
                            transcripts.append(result["text"])
                    finally:
                        self.preprocessing.pop(sid, None)
                s = await self.ensure_thread(sid)
                if not s["turn_id"]:
                    self.store.update_session(sid, status="connecting")
                    self.live.setdefault(sid, {"text": "", "started": time.time()})["activity"] = "Connecting"
                inputs = [{"type": "text", "text": p["text"]}] if p.get("text") else []
                inputs += [{"type": "text", "text": text} for text in transcripts]
                inputs += [{"type": "localImage", "path": x} for x in p.get("images", [])]
                self.store.request_state(rid, "dispatching")
                dispatched = True
                start_params = {
                    "threadId": s["thread_id"],
                    "input": inputs,
                    "clientUserMessageId": rid,
                    "cwd": s["cwd"],
                    "effort": s["effort"],
                    "summary": "auto",
                    "approvalPolicy": "never",
                    "sandboxPolicy": {"type": "dangerFullAccess"},
                }
                if s["model"]:
                    start_params["model"] = s["model"]
                model = s["model"]
                if not model:
                    catalog = (await self.client.request("model/list", {})).get("data", [])
                    default = next((m for m in catalog if m.get("isDefault")), catalog[0] if catalog else {})
                    model = default.get("model") or default.get("id")
                if model:
                    start_params["collaborationMode"] = {
                        "mode": s["collaboration_mode"],
                        "settings": {
                            "model": model,
                            "reasoning_effort": s["effort"],
                            "developer_instructions": None,
                        },
                    }
                if s["turn_id"]:
                    try:
                        result = await self.client.request(
                            "turn/steer",
                            {
                                "threadId": s["thread_id"],
                                "expectedTurnId": s["turn_id"],
                                "input": inputs,
                                "clientUserMessageId": rid,
                            },
                        )
                    except RpcError as exc:
                        # Explicit rejection is safe to turn into a new request; lost replies are not.
                        if "no active turn" not in str(exc).lower():
                            raise
                        self.store.update_session(sid, turn_id=None)
                        result = await self.client.request("turn/start", start_params)
                else:
                    result = await self.client.request("turn/start", start_params)
                    # Notifications own turn state; a quick completed turn may precede this reply.
                self.store.request_state(rid, "accepted", result)
            except Exception as exc:
                uncertain = dispatched and isinstance(exc, (UnknownOutcome, ConnectionError, TimeoutError))
                self.store.request_state(rid, "uncertain" if uncertain else "failed")
                if self.store.session(sid)["status"] in {"connecting", "transcribing"}:
                    self.store.update_session(sid, status="uncertain" if uncertain else "failed")
                    self.live.pop(sid, None)
                message = (
                    str(exc)
                    if isinstance(exc, (RpcError, ValueError, UnknownOutcome))
                    else type(exc).__name__
                )
                self.store.event(sid, "error", {"text": message, "request_id": rid, "uncertain": uncertain})

    def session_for_thread(self, thread_id: str | None) -> dict | None:
        if not thread_id:
            return None
        return self.store.one("SELECT * FROM sessions WHERE thread_id=?", (thread_id,))

    def on_event(self, method: str, params: dict) -> None:
        s = self.session_for_thread(params.get("threadId"))
        if not s:
            return
        sid = s["id"]
        if method == "turn/started":
            self.store.update_session(sid, status="working", turn_id=params["turn"]["id"])
            started = self.live.get(sid, {}).get("started", time.time())
            self.live[sid] = {
                "text": "",
                "activity": "Working",
                "started": started,
                "updated": time.time(),
                "summaries": {},
            }
        elif method in {"item/reasoning/summaryTextDelta", "item/reasoning/summaryPartAdded"}:
            # Only public summaries are consumed; raw reasoning/textDelta is ignored.
            live = self.live.setdefault(sid, {"text": "", "started": time.time()})
            parts = live.setdefault("summaries", {}).setdefault(params["itemId"], {})
            index = str(params.get("summaryIndex", 0))
            parts[index] = parts.get(index, "") + params.get("delta", "")
            live["updated"] = time.time()
        elif method == "item/agentMessage/delta":
            live = self.live.setdefault(sid, {"text": "", "activity": "Working"})
            live["text"] += params.get("delta", "")
            live["text"] = live["text"][-12000:]
            live["updated"] = time.time()
        elif method == "item/started":
            item = params.get("item", {})
            activity = {
                "commandExecution": "Running command",
                "fileChange": "Editing files",
                "webSearch": "Searching",
                "mcpToolCall": "Using tool",
            }.get(item.get("type"))
            if activity:
                self.live.setdefault(sid, {"text": ""}).update(activity=activity, updated=time.time())
        elif method == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "reasoning":
                self.finish_summary(sid, item["id"], item.get("summary"))
            elif item.get("type") in {"agentMessage", "plan"}:
                self.store.event(
                    sid,
                    "message",
                    {
                        "text": item.get("text", ""),
                        "item_id": item.get("id"),
                        "phase": "plan" if item.get("type") == "plan" else item.get("phase"),
                    },
                )
                if sid in self.live:
                    self.live[sid]["text"] = ""
            elif item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "webSearch"}:
                self.store.event(sid, "tool", {"item": item})
        elif method == "turn/completed":
            turn = params["turn"]
            for item_id in list(self.live.get(sid, {}).get("summaries", {})):
                self.finish_summary(sid, item_id)
            self.store.update_session(
                sid, status="idle" if turn["status"] == "completed" else turn["status"], turn_id=None
            )
            self.live.pop(sid, None)
            with self.store.db:
                self.store.db.execute(
                    "UPDATE questions SET status='expired' WHERE session_id=? AND status='pending'", (sid,)
                )
            self.store.event(sid, "completed", {"status": turn["status"], "error": turn.get("error")})
        elif method == "error":
            error = params.get("error") or {}
            self.store.event(sid, "error", {"text": error.get("message", "Codex reported an error")})
        elif method == "serverRequest/resolved":
            with self.store.db:
                self.store.db.execute(
                    "UPDATE questions SET status='resolved' WHERE rpc_id=?",
                    (json.dumps(params.get("requestId")),),
                )

    def finish_summary(self, sid: str, item_id: str, summary: list | None = None) -> None:
        pending = self.live.get(sid, {}).get("summaries", {}).pop(item_id, {})
        parts = summary or [pending[key] for key in sorted(pending, key=int)]
        parts = [text for text in parts if isinstance(text, str) and text.strip()]
        if parts and not self.store.one(
            "SELECT id FROM events WHERE session_id=? AND kind='reasoning_summary' "
            "AND json_extract(payload,'$.item_id')=?",
            (sid, item_id),
        ):
            self.store.event(
                sid, "reasoning_summary", {"text": "\n\n".join(parts), "parts": parts, "item_id": item_id}
            )

    def disconnected(self) -> None:
        self.loaded.clear()
        for sid, live in list(self.live.items()):
            for item_id in list(live.get("summaries", {})):
                self.finish_summary(sid, item_id)
        self.live.clear()
        for s in self.store.sessions():
            if s["turn_id"]:
                self.store.update_session(s["id"], status="interrupted", turn_id=None)
                self.store.event(
                    s["id"],
                    "completed",
                    {"status": "interrupted", "text": "Codex exited; history is retained."},
                )
        with self.store.db:
            self.store.db.execute("UPDATE questions SET status='expired' WHERE status='pending'")

    def on_request(self, rpc_id, method: str, params: dict) -> None:
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            self.spawn(self.client.respond(rpc_id, {"decision": "accept"}))
            return
        if method == "item/permissions/requestApproval":
            self.spawn(
                self.client.respond(
                    rpc_id, {"permissions": params.get("permissions", {}), "scope": "session"}
                )
            )
            return
        s = self.session_for_thread(params.get("threadId"))
        if s and method in {"item/tool/requestUserInput", "mcpServer/elicitation/request"}:
            qid = identifier()
            with self.store.db:
                self.store.db.execute(
                    "INSERT INTO questions(id,session_id,rpc_id,method,payload) VALUES(?,?,?,?,?)",
                    (qid, s["id"], json.dumps(rpc_id), method, json.dumps(params)),
                )
            self.store.update_session(s["id"], status="waiting")
            self.store.event(s["id"], "question", {"question_id": qid, "method": method, **params})
        else:
            self.spawn(
                self.client.respond(rpc_id, error={"code": -32601, "message": "Unsupported client request"})
            )

    async def answer(self, qid: str, answers: dict) -> dict:
        q = self.store.one("SELECT * FROM questions WHERE id=? AND status='pending'", (qid,))
        if not q:
            raise ValueError("This question is no longer pending")
        if q["method"] == "item/tool/requestUserInput":
            questions = json.loads(q["payload"]).get("questions", [])
            expected = {x["id"] for x in questions}
            if set(answers) != expected:
                raise ValueError("Answer every question in this request")
            result: dict = {"answers": {k: {"answers": [v]} for k, v in answers.items()}}
        else:
            result = {"action": answers.get("action", "decline"), "content": answers.get("content")}
        await self.client.respond(json.loads(q["rpc_id"]), result)
        with self.store.db:
            self.store.db.execute("UPDATE questions SET status='resolved' WHERE id=?", (qid,))
        self.store.update_session(q["session_id"], status="working")
        self.store.event(
            q["session_id"],
            "user",
            {
                "text": "\n\n".join(str(v) for v in answers.values()),
                "question_id": qid,
            },
        )
        return {"ok": True}

    async def stop(self, sid: str) -> dict:
        # Cancel local preprocessing before waiting on the per-session dispatch lock.
        task = self.preprocessing.get(sid)
        with self.store.db:
            self.store.db.execute(
                "UPDATE requests SET state='cancelled' WHERE session_id=? AND state='queued'", (sid,)
            )
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.store.session(sid)["status"] == "transcribing":
            if not self.store.session(sid)["turn_id"]:
                self.store.update_session(sid, status="interrupted")
                self.live.pop(sid, None)
                self.store.event(
                    sid, "completed", {"status": "interrupted", "text": "Voice processing stopped."}
                )
        async with self.locks[sid]:
            s = self.store.session(sid)
            if s["turn_id"]:
                await self.client.request(
                    "turn/interrupt", {"threadId": s["thread_id"], "turnId": s["turn_id"]}
                )
            return {"ok": True}

    async def change(self, sid: str, action: str, body: dict) -> dict:
        if action == "stop":
            return await self.stop(sid)
        if action == "archive":
            await self.stop(sid)
            # Wait for native completion before archiving, without dropping active work.
            for _ in range(100):
                if not self.store.session(sid)["turn_id"]:
                    break
                await asyncio.sleep(0.1)
            else:
                raise ValueError("The turn is still stopping; retry Close after completion")
        async with self.locks[sid]:
            s = self.store.session(sid)
            if action == "rename":
                name = str(body.get("name", "")).strip()
                if not name or len(name) > 100:
                    raise ValueError("Use a name between 1 and 100 characters")
                if s["thread_id"]:
                    await self.ensure_thread(sid)
                    await self.client.request("thread/name/set", {"threadId": s["thread_id"], "name": name})
                self.store.update_session(sid, name=name)
            elif action == "archive":
                if s["thread_id"]:
                    await self.ensure_thread(sid)
                    await self.client.request("thread/archive", {"threadId": s["thread_id"]})
                self.store.update_session(sid, archived=1)
                self.loaded.pop(sid, None)
            elif action == "reopen":
                if s["thread_id"]:
                    await self.client.start()
                    await self.client.request("thread/unarchive", {"threadId": s["thread_id"]})
                self.store.update_session(sid, archived=0)
            elif action == "settings":
                if s["turn_id"] and "cwd" in body:
                    raise ValueError("Wait for the current turn before changing its model or folder")
                values = {}
                if "cwd" in body:
                    info = await inspect_directory(self.settings, body["cwd"])
                    values["cwd"] = info["path"]
                if "model" in body or "effort" in body:
                    await self.client.start()
                    models = (await self.client.request("model/list", {})).get("data", [])
                    model = body.get("model", s["model"])
                    selected = next((m for m in models if m["id"] == model or m.get("model") == model), None)
                    if model is None:
                        selected = next(
                            (m for m in models if m.get("isDefault")), models[0] if models else None
                        )
                        if selected:
                            model = selected.get("model") or selected["id"]
                    if not selected:
                        raise ValueError("Choose a model from the live catalog")
                    effort = body.get("effort", s["effort"])
                    options = {x["reasoningEffort"] for x in selected.get("supportedReasoningEfforts", [])}
                    if options and effort not in options:
                        raise ValueError("Reasoning effort is not supported by this model")
                    values.update(model=model, effort=effort)
                if "collaboration_mode" in body:
                    if body["collaboration_mode"] not in {"default", "plan"}:
                        raise ValueError("Choose Default or Plan mode")
                    values["collaboration_mode"] = body["collaboration_mode"]
                self.store.update_session(sid, **values)
                if "cwd" in values:
                    self.loaded.pop(sid, None)
            else:
                raise ValueError("Unsupported session action")
            return self.store.session(sid)

    async def close(self) -> None:
        self.accepting = False
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.close()
        self.store.close()


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except (ValueError, KeyError, FileNotFoundError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (RpcError, UnknownOutcome) as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except Exception as exc:
        log.error("Engine request failed: %s", type(exc).__name__)
        return web.json_response({"error": "Engine request failed; inspect service health"}, status=500)


def application(engine: Engine) -> web.Application:
    app = web.Application(middlewares=[errors], client_max_size=2 * 1024 * 1024)

    async def api(request):
        path = request.path
        body = await request.json() if request.method == "POST" else {}
        if path == "/health":
            return web.json_response(
                {
                    "ok": True,
                    "protocol_version": 1,
                    "version": __version__,
                    "revision": os.environ.get("VIBECODING_CORE_REVISION", "development"),
                    "host_id": engine.settings.host_id,
                    "codex_running": engine.client.running,
                    "accepting": engine.accepting,
                    "busy": any(s["turn_id"] for s in engine.store.sessions()),
                    "pending_requests": len(
                        engine.store.rows("SELECT id FROM requests WHERE state IN ('queued','dispatching')")
                    ),
                }
            )
        if path == "/projects":
            data = (
                engine.store.register_project(
                    body["name"],
                    (await inspect_directory(engine.settings, body["path"]))["path"],
                    validated=True,
                )
                if body
                else engine.store.projects()
            )
        elif path == "/sessions":
            data = (
                engine.store.create_session(
                    (await inspect_directory(engine.settings, body["cwd"]))["path"],
                    body.get("name", "New session"),
                    engine.settings.effort,
                    engine.settings.model,
                    validated=True,
                )
                if body
                else engine.store.sessions(request.query.get("archived") == "1")
            )
        elif path == "/messages":
            if not engine.accepting:
                return web.json_response(
                    {"error": "Engine is draining; input remains queued in the bot"}, status=503
                )
            data = engine.submit(body)
        elif path == "/events":
            data = engine.store.events(int(request.query.get("after", "0")))
        elif path == "/live":
            data = engine.live
        elif path == "/models":
            await engine.client.start()
            data = await engine.client.request("model/list", {})
        elif path == "/account":
            await engine.client.start()
            result = await engine.client.request("account/read", {})
            data = {"account": result.get("account"), "requiresOpenaiAuth": result.get("requiresOpenaiAuth")}
        elif path == "/drain":
            engine.accepting = not body.get("enabled", True)
            data = {"accepting": engine.accepting}
        elif path.startswith("/questions/"):
            data = await engine.answer(path.rsplit("/", 1)[1], body["answers"])
        elif path.startswith("/sessions/"):
            parts = path.strip("/").split("/")
            sid = parts[1]
            if len(parts) == 2:
                data = engine.store.session(sid)
            elif parts[2] == "history":
                data = engine.store.history(sid)
            elif parts[2] == "conversation":
                anchor = request.query.get("anchor")
                data = engine.store.conversation(sid, int(anchor) if anchor else None)
            elif parts[2] == "details":
                data = engine.store.details(sid)
                info = await inspect_directory(engine.settings, data["cwd"])
                data.update(
                    host_id=engine.settings.host_id,
                    disk_free=info["disk_free"],
                    disk_total=info["disk_total"],
                )
            elif parts[2] == "questions":
                data = [
                    {**q, "payload": json.loads(q["payload"])}
                    for q in engine.store.rows(
                        "SELECT * FROM questions WHERE session_id=? AND status='pending'", (sid,)
                    )
                ]
            else:
                data = await engine.change(sid, parts[2], body)
        else:
            raise web.HTTPNotFound()
        return web.json_response(data)

    app.router.add_get("/{tail:.*}", api)
    app.router.add_post("/{tail:.*}", api)
    return app


class EngineClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http: ClientSession | None = None

    async def call(self, path: str, body: dict | None = None):
        if self.http is None:
            self.http = ClientSession(
                connector=UnixConnector(path=str(self.settings.socket)), timeout=ClientTimeout(total=90)
            )
        async with self.http.request(
            "POST" if body is not None else "GET", "http://engine" + path, json=body
        ) as r:
            value = await r.json()
            if r.status >= 500:
                raise ConnectionError(value.get("error", "Engine temporarily unavailable"))
            if r.status >= 400:
                raise ValueError(value.get("error", f"Engine returned {r.status}"))
            return value

    async def close(self):
        if self.http:
            await self.http.close()


async def serve(settings: Settings) -> None:
    import fcntl

    settings.prepare()
    lock = (settings.runtime_dir / "engine.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("Another engine already owns this runtime directory") from None
    engine = Engine(settings)
    runner = web.AppRunner(application(engine), access_log=None)
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, done.set)
    try:
        settings.socket.unlink(missing_ok=True)
        await runner.setup()
        await web.UnixSite(runner, str(settings.socket)).start()
        settings.socket.chmod(0o600)
        engine.start()
        log.info("Engine ready; host=%s version=%s", settings.host_id, __version__)
        await done.wait()
    finally:
        await runner.cleanup()
        await engine.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(settings.socket)
        lock.close()
