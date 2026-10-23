#!/usr/bin/env python3
"""Install host CLI and snapshot timer after Compose migration succeeds."""

import argparse
import os
import pwd
import shlex
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
    worker = Path.home() / ".local/share/remote-vibecoding/ops" / revision / "ops.py"
    worker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not worker.exists():
        worker.write_bytes(subprocess.check_output(["git", "show", revision + ":scripts/ops.py"], cwd=repo))
        worker.chmod(0o700)
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
    print("Host CLI and hourly snapshot timer installed")


if __name__ == "__main__":
    main()
