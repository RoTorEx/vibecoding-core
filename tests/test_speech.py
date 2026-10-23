import asyncio
import sys

from vibecoding_core.speech import Speech


async def test_cancellation_reaps_worker_and_releases_single_slot(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"fixture")
    speech = Speech(tmp_path)
    original = asyncio.create_subprocess_exec
    launched = asyncio.Event()
    processes = []

    async def worker(*args, **kwargs):
        process = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        processes.append(process)
        launched.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", worker)
    first = asyncio.create_task(speech.transcribe("first.ogg"))
    await launched.wait()
    second = asyncio.create_task(speech.transcribe("second.ogg"))
    await asyncio.sleep(0)
    assert len(processes) == 1
    launched.clear()
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    await launched.wait()
    assert processes[0].returncode is not None
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    assert processes[1].returncode is not None
