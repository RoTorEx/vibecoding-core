#!/usr/bin/env python3
"""Install independent system services; no credentials or production service changes."""

import argparse
import os
import pwd
import subprocess
from pathlib import Path


def unit(component: str, user: str, home: Path) -> str:
    name, alias = {
        "bot": ("Telegram Vibecoding", "telegram-vibecoding.service"),
        "engine": ("Vibecoding Core", "vibecoding-core.service"),
    }[component]
    binary = home / ".local/share/codex-relay" / (component + "-current") / ".venv/bin/codex-relay"
    return f"""[Unit]
Description={name}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User={user}
Group={pwd.getpwuid(pwd.getpwnam(user).pw_uid).pw_name}
Environment=HOME={home}
Environment=PATH={home}/.local/bin:/usr/local/bin:/usr/bin:/bin
WorkingDirectory={home}
ExecStart={binary} {component}
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
KillMode=mixed
UMask=0077
Nice=5
LogRateLimitIntervalSec=30
LogRateLimitBurst=200

[Install]
WantedBy=multi-user.target
Alias={alias}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--start", choices=["engine", "bot", "both"])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Install service units with sudo")
    owner = pwd.getpwnam(args.user)
    if owner.pw_uid == 0:
        raise ValueError("The agent must run as a non-root developer")
    home = Path(owner.pw_dir)
    for component in ["engine", "bot"]:
        target = Path("/etc/systemd/system") / f"codex-relay-{component}.service"
        content = unit(component, args.user, home)
        if target.exists() and target.read_text() != content:
            previous = target.with_suffix(".service.before-relay-install")
            if not previous.exists():
                previous.write_bytes(target.read_bytes())
        target.write_text(content)
        target.chmod(0o644)
    snapshot = home / ".local/share/codex-relay/engine-current/scripts/snapshot.py"
    Path("/etc/systemd/system/codex-relay-snapshot.service").write_text(f"""[Unit]
Description=Vibecoding Core recovery snapshot
After=codex-relay-engine.service

[Service]
Type=oneshot
User={args.user}
Environment=HOME={home}
Environment=PATH={home}/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 {snapshot}
UMask=0077
Nice=10
""")
    Path("/etc/systemd/system/codex-relay-snapshot.timer").write_text("""[Unit]
Description=Vibecoding Core hourly snapshot timer

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
Unit=codex-relay-snapshot.service

[Install]
WantedBy=timers.target
""")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for helper in ["service", "timer"]:
        Path(f"/etc/systemd/system/codex-relay-snapshot.{helper}").chmod(0o644)
    for component in ["engine", "bot"]:
        subprocess.run(["systemctl", "enable", "codex-relay-" + component], check=True)
    if args.start:
        selected = ["engine", "bot"] if args.start == "both" else [args.start]
        for component in selected:
            subprocess.run(["systemctl", "start", "codex-relay-" + component], check=True)
    print("Telegram Vibecoding and Vibecoding Core units installed. Existing services were not restarted.")


if __name__ == "__main__":
    main()
