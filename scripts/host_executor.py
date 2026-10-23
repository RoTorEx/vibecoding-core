#!/usr/bin/env python3
"""Forced SSH entrypoint: native Codex stdio or read-only directory inspection."""

import json
import os
import shlex
import shutil
import sys
from pathlib import Path


def main():
    os.umask(0o077)
    os.environ["PATH"] = str(Path.home() / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin"
    argv = shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    if argv and argv[0] == "app-server":
        executable = Path.home() / ".local/bin/codex"
        os.execv(str(executable), [str(executable), *argv])
    if argv == ["inspect-path"]:
        try:
            request = json.load(sys.stdin)
            path = Path(request["path"]).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError("Working directory is not a directory")
            usage = shutil.disk_usage(path)
            print(json.dumps({"path": str(path), "disk_free": usage.free, "disk_total": usage.total}))
        except (OSError, ValueError, KeyError):
            print(json.dumps({"error": "Choose an existing absolute host directory"}))
            return 1
        return 0
    print("Unsupported executor operation", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
