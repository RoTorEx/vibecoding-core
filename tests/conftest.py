import asyncio
import tempfile
from pathlib import Path

import pytest
from aiohttp import web

from vibecoding_core.config import Settings
from vibecoding_core.engine import Engine, EngineClient, application


class NativeFake:
    def __init__(self):
        self.calls = []
        self.generation = 1
        self.running = True
        self.engine = None
        self.count = 0
        self.fail_method = None
        self.failure = None

    async def start(self):
        self.running = True

    async def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        if method == self.fail_method:
            raise self.failure
        if method == "thread/start":
            self.count += 1
            return {"thread": {"id": f"thread-{self.count}"}}
        if method == "turn/start":
            turn = {"id": f"turn-{len(self.calls)}", "status": "inProgress"}
            self.engine.on_event("turn/started", {"threadId": params["threadId"], "turn": turn})
            return {"turn": turn}
        if method == "turn/interrupt":
            self.finish(params["threadId"], "interrupted")
        if method == "model/list":
            return {
                "data": [
                    {
                        "id": "test-model",
                        "model": "test-model",
                        "displayName": "Test",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "medium"},
                            {"reasoningEffort": "high"},
                        ],
                    }
                ]
            }
        return {}

    async def respond(self, rid, result=None, error=None):
        self.calls.append(("response", {"id": rid, "result": result, "error": error}))

    def finish(self, thread, status="completed", text="Native response"):
        self.engine.on_event(
            "item/completed",
            {"threadId": thread, "item": {"id": "answer-" + thread, "type": "agentMessage", "text": text}},
        )
        self.engine.on_event("turn/completed", {"threadId": thread, "turn": {"id": "last", "status": status}})

    async def close(self):
        self.running = False


@pytest.fixture
async def host(tmp_path):
    runtime = tempfile.TemporaryDirectory(prefix="relay-test-", dir="/tmp")
    settings = Settings(
        data_dir=tmp_path / "state",
        runtime_dir=Path(runtime.name),
        development_root=tmp_path / "projects",
        codex_command="unused",
        private_config_dir=tmp_path / "config",
    )
    native = NativeFake()
    engine = Engine(settings, native)
    native.engine = engine
    engine.start()
    runner = web.AppRunner(application(engine), access_log=None)
    await runner.setup()
    await web.UnixSite(runner, str(settings.socket)).start()
    client = EngineClient(settings)
    yield settings, engine, native, client
    await client.close()
    await runner.cleanup()
    await engine.close()
    runtime.cleanup()


async def settle(engine):
    for _ in range(100):
        if not engine.tasks:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Engine task did not settle")
