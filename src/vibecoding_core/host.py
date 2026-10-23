"""Host path inspection without changing the native execution boundary."""

import asyncio
import json
import shutil
from pathlib import Path

from vibecoding_core.config import Settings


async def inspect_directory(settings: Settings, value: str) -> dict:
    if settings.inspect_command:
        process = await asyncio.create_subprocess_exec(
            *settings.inspect_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(json.dumps({"path": value}).encode()),
                20,
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise ValueError("Host directory inspection failed")
        result = json.loads(output)
        if result.get("error"):
            raise ValueError(result["error"])
        return result
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Working directory is not a directory")
    usage = shutil.disk_usage(path)
    return {"path": str(path), "disk_free": usage.free, "disk_total": usage.total}
