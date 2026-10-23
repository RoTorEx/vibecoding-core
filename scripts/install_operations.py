#!/usr/bin/env python3
"""Install host CLI and snapshot timer after Compose migration succeeds."""

import argparse
import json
import os
import pwd
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
    user = pwd.getpwuid(os.getuid()).pw_name
    if os.getuid() == 0:
        raise ValueError("Run as the developer account")
    repo = root / "vibecoding-core"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    worker = repo / "scripts/ops.py"
    if not worker.is_file():
        raise ValueError("The reviewed operations script is missing")
    units = {
        "remote-vibecoding-snapshot.service": f"""[Unit]
Description=Remote Vibecoding private consistent snapshot
After=docker.service

[Service]
Type=oneshot
User={user}
Environment=HOME={Path.home()}
UMask=0077
ExecStart=/usr/bin/python3 {worker} --root {root} snapshot
TimeoutStartSec=900
""",
        "remote-vibecoding-snapshot.timer": """[Unit]
Description=Remote Vibecoding hourly private snapshot

[Timer]
OnBootSec=15min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
""",
    }
    for name, content in units.items():
        subprocess.run(
            ["sudo", "-n", "tee", "/etc/systemd/system/" + name],
            input=content,
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
    wrapper = Path.home() / ".local/bin/remote-vibecoding"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/bin/sh\nexec /usr/bin/python3 "
        + shlex.quote(str(repo / "scripts/ops.py"))
        + " --root "
        + shlex.quote(str(root))
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    subprocess.run(["sudo", "-n", "systemctl", "daemon-reload"], check=True)
    subprocess.run(
        ["sudo", "-n", "systemctl", "enable", "--now", "remote-vibecoding-snapshot.timer"], check=True
    )
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
    print("Host CLI and hourly snapshot timer installed at source revision " + revision)
    if active:
        print("Legacy worker cleanup deferred until the in-flight update finishes")


if __name__ == "__main__":
    main()
