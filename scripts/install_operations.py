#!/usr/bin/env python3
"""Install host CLI after Compose migration succeeds."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    os.umask(0o077)
    if os.getuid() == 0:
        raise ValueError("Run as the developer account")
    repo = root / "vibecoding-core"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip():
        raise ValueError("Commit the reviewed host controls before installation")
    source_worker = repo / "scripts/ops.py"
    if not source_worker.is_file():
        raise ValueError("The reviewed operations script is missing")
    room = Path("/srv/remote-vibecoding")
    runtime = room / "runtime/core"
    subprocess.run(["sudo", "-n", "install", "-d", "-m", "755", str(runtime)], check=True)
    for source, name in [
        (source_worker, "ops.py"),
        (repo / "scripts/host_executor.py", "host_executor.py"),
    ]:
        subprocess.run(["sudo", "-n", "install", "-m", "644", str(source), str(runtime / name)], check=True)
    subprocess.run(
        [
            "sudo",
            "-n",
            "install",
            "-m",
            "644",
            str(repo / "deployment/workspace/compose.yaml"),
            str(runtime / "compose.yaml"),
        ],
        check=True,
    )
    subprocess.run(
        ["sudo", "-n", "tee", str(runtime / "HOST-CONTROLS-REVISION")],
        input=revision + "\n",
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    worker = runtime / "ops.py"
    wrapper = Path.home() / ".local/bin/remote-vibecoding"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/bin/sh\nexec /usr/bin/python3 "
        + shlex.quote(str(worker))
        + " --root "
        + shlex.quote(str(room))
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    subprocess.run(["sudo", "-n", "systemctl", "daemon-reload"], check=True)
    pending = json.loads(
        subprocess.check_output(
            ["sudo", "-n", "systemctl", "list-units", "--all", "--output=json", "remote-vibecoding-update-*"],
            text=True,
        )
    )
    active = any(row.get("active") in ("active", "activating", "reloading") for row in pending)
    legacy = Path.home() / ".local/share/remote-vibecoding/ops"
    if legacy.is_dir() and not legacy.is_symlink() and not active:
        for directory in legacy.iterdir():
            if (
                re.fullmatch(r"[0-9a-f]{40}", directory.name)
                and directory.is_dir()
                and not directory.is_symlink()
                and {item.name for item in directory.iterdir()} <= {"ops.py", "__pycache__"}
            ):
                shutil.rmtree(directory)
        if not any(legacy.iterdir()):
            legacy.rmdir()
    print("Host CLI installed at source revision " + revision)
    if active:
        print("Legacy worker cleanup deferred until the in-flight update finishes")


if __name__ == "__main__":
    main()
