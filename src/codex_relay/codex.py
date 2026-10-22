"""Native JSON-RPC transport, without model prompts or output rewriting."""

import asyncio
import contextlib
import json
import logging
import os
import signal
from collections.abc import Callable
from typing import Any

from codex_relay import __version__

log = logging.getLogger(__name__)


class RpcError(Exception):
    def __init__(self, error: dict):
        self.error = error
        super().__init__(str(error.get("message", "Codex RPC failed")))


class UnknownOutcome(Exception):
    """The connection ended or timed out after an RPC may have been accepted."""


class CodexClient:
    def __init__(
        self,
        command: str,
        on_event: Callable[[str, dict], None],
        on_request: Callable[[Any, str, dict], None],
        on_disconnect: Callable[[], None],
    ):
        self.command = command
        self.on_event = on_event
        self.on_request = on_request
        self.on_disconnect = on_disconnect
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.counter = 0
        self.generation = 0
        self.lock = asyncio.Lock()
        self.tasks: list[asyncio.Task] = []
        self.closing = False

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        async with self.lock:
            if self.running:
                return
            self.closing = False
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                "app-server",
                "--listen",
                "stdio://",
                "-c",
                "features.multi_agent=false",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                limit=16 * 1024 * 1024,
            )
            self.generation += 1
            process = self.process
            self.tasks = [
                asyncio.create_task(self._read(process)),
                asyncio.create_task(self._drain_stderr(process)),
            ]
            await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_relay",
                        "title": "Codex Relay",
                        "version": __version__,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self.send({"method": "initialized", "params": {}})

    async def send(self, payload: dict) -> None:
        if not self.running or self.process is None or self.process.stdin is None:
            raise ConnectionError("Codex is not running")
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float = 60) -> dict:
        self.counter += 1
        rid = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.send({"id": rid, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        except (TimeoutError, BrokenPipeError, ConnectionError) as exc:
            raise UnknownOutcome(
                f"Codex connection lost during {method}; outcome requires inspection"
            ) from exc
        finally:
            self.pending.pop(rid, None)

    async def respond(self, rid: Any, result: dict | None = None, error: dict | None = None) -> None:
        await self.send({"id": rid, **({"error": error} if error else {"result": result or {}})})

    async def _read(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout
        try:
            while line := await process.stdout.readline():
                msg = json.loads(line)
                if "method" in msg:
                    if "id" in msg:
                        self.on_request(msg["id"], msg["method"], msg.get("params") or {})
                    else:
                        self.on_event(msg["method"], msg.get("params") or {})
                elif (future := self.pending.get(msg.get("id"))) is not None and not future.done():
                    if "error" in msg:
                        future.set_exception(RpcError(msg["error"]))
                    else:
                        future.set_result(msg.get("result") or {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Codex reader failed: %s", type(exc).__name__)
        finally:
            # Do not start a replacement until the old process has been reaped.
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(UnknownOutcome("Codex process exited; request was not replayed"))
            if not self.closing:
                self.on_disconnect()

    @staticmethod
    async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
        assert process.stderr
        # Native stderr can contain paths or credentials. Drain it without logging payloads.
        while await process.stderr.read(65536):
            pass

    async def close(self) -> None:
        self.closing = True
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
