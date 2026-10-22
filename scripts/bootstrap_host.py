#!/usr/bin/env python3
"""First installation only; later deployments use the independent update commands."""

import json
import os
import pwd
import shlex
import subprocess
import time
import tomllib
import urllib.request
from pathlib import Path

from deploy import installation_root, stage, switch


def main():
    os.umask(0o077)
    if os.geteuid() == 0:
        raise RuntimeError("Run bootstrap as the developer, not root")
    root = installation_root()
    if (root / "engine-current").exists() or (root / "bot-current").exists():
        raise RuntimeError("Installation already exists; use make deploy-bot or make deploy-engine")
    config = Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()
    settings = tomllib.loads(config.read_text())
    owner_id = settings.get("allowed_user_id", 0)
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise ValueError("Configure the numeric Telegram owner ID first")
    token_file = Path(settings.get("token_file", "~/.config/codex-relay/bot-token")).expanduser()
    if token_file.stat().st_mode & 0o077:
        raise ValueError("Token file must have mode 600")
    token = token_file.read_text().strip()
    try:
        with urllib.request.urlopen(
            "https://api.telegram.org/bot" + token + "/getMe", timeout=20
        ) as response:
            identity = json.load(response)["result"]
        with urllib.request.urlopen(
            "https://api.telegram.org/bot" + token + "/getWebhookInfo", timeout=20
        ) as response:
            webhook = json.load(response)["result"]
    except Exception:
        raise RuntimeError("Telegram identity check failed; credentials were not logged") from None
    if webhook.get("url"):
        raise RuntimeError("Bot already has a webhook; preserve the existing consumer")
    expected = settings.get("bot_username")
    if expected and identity["username"].lower() != expected.lstrip("@").lower():
        raise ValueError("The token belongs to a different Telegram bot")
    print("Verified Telegram target: @" + identity["username"])
    source = Path(__file__).resolve().parent.parent
    release = stage(source, root)
    switch(root / "engine-current", release)
    switch(root / "bot-current", release)
    launcher = Path.home() / ".local/bin/codex-relay"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        "#!/bin/sh\nexec " + shlex.quote(str(root / "engine-current/.venv/bin/codex-relay")) + ' "$@"\n'
    )
    launcher.chmod(0o755)
    user = pwd.getpwuid(os.getuid()).pw_name
    subprocess.run(
        [
            "sudo",
            "-n",
            "python3",
            str(release / "scripts/install_host.py"),
            "--user",
            user,
            "--start",
            "engine",
        ],
        check=True,
    )
    for _ in range(30):
        result = subprocess.run([str(launcher), "doctor"], capture_output=True, text=True)
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Engine startup check failed; inspect its journal")
    subprocess.run([str(launcher), "project", "add", str(source), "--name", "Codex Relay"], check=True)
    subprocess.run(["sudo", "-n", "systemctl", "start", "codex-relay-bot"], check=True)
    print(
        "Engine and bot installed. Verify Telegram interaction and recovery before enabling snapshot timer."
    )


if __name__ == "__main__":
    main()
