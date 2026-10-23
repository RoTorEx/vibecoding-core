"""Bounded, offline speech decoding in a disposable CPU worker."""

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path


class Speech:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.slot = asyncio.Semaphore(1)

    async def transcribe(self, path: str) -> dict:
        async with self.slot:
            if not (self.model_dir / "model.bin").is_file():
                raise ValueError("Local speech model is not installed on this host")
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "vibecoding_core.speech_worker",
                str(self.model_dir),
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env={
                    **os.environ,
                    "HF_HUB_OFFLINE": "1",
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                },
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=600)
                if process.returncode:
                    raise ValueError("Voice recognition failed; check the recording and local speech model")
                result = json.loads(stdout)
                if not result["text"].strip():
                    raise ValueError("No speech detected in this recording")
                return result
            finally:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
