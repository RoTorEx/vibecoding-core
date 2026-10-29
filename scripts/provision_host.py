#!/usr/bin/env python3
"""Prepare private host configuration and a restricted native executor SSH key."""

import argparse
import json
import os
import pwd
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def write_new(path, content, mode=0o600):
    if path.exists():
        return
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(content)
    temporary.chmod(mode)
    temporary.replace(path)


def toml_text(values):
    return "".join(f"{key} = {json.dumps(value)}\n" for key, value in values.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--executor-subnet")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError("Run as the existing developer, not root")
    os.umask(0o077)
    root = args.root.resolve(strict=True)
    home = Path.home()
    private = home / ".config/remote-vibecoding"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    legacy_path = home / ".config/codex-relay/config.toml"
    legacy = tomllib.loads(legacy_path.read_text())
    data = str(Path(legacy.get("data_dir", str(home / ".local/state/codex-relay"))).expanduser())
    token = private / "notifier-token"
    if not token.exists():
        source = Path(legacy.get("token_file", str(home / ".config/codex-relay/bot-token"))).expanduser()
        shutil.copyfile(source, token)
        token.chmod(0o600)
    write_new(
        private / "core.toml",
        toml_text(
            {
                "data_dir": data,
                "runtime_dir": data + "/run",
                "development_root": legacy.get("development_root", str(home / "Development/personal")),
                "host_id": legacy.get("host_id", "vps"),
                **({"model": legacy["model"]} if legacy.get("model") else {}),
                "effort": legacy.get("effort", "medium"),
                "codex_command": "/usr/local/bin/codex-host",
                "inspect_command": [
                    "ssh",
                    "-T",
                    "-F",
                    str(private / "executor-ssh.conf"),
                    "vibecoding-host",
                    "inspect-path",
                ],
                "host_root": "/host",
                "private_config_dir": str(private),
            }
        ),
    )
    write_new(
        private / "bot.toml",
        toml_text(
            {
                "data_dir": str(home / ".local/state/remote-vibecoding-notifier"),
                "runtime_dir": data + "/run",
                "token_file": str(token),
                "web_url": "https://vibecoding.com",
                "allowed_user_id": legacy["allowed_user_id"],
                "bot_username": "",
                "host_id": legacy.get("host_id", "vps"),
            }
        ),
    )
    notifier_state = home / ".local/state/remote-vibecoding-notifier"
    notifier_state.mkdir(parents=True, exist_ok=True, mode=0o700)
    revisions = {
        "CORE_REVISION": run(
            ["git", "rev-parse", "HEAD"], cwd=root / "vibecoding-core", capture_output=True
        ).stdout.strip(),
        "BOT_REVISION": run(
            ["git", "rev-parse", "HEAD"], cwd=root / "telegram-vibecoding", capture_output=True
        ).stdout.strip(),
    }
    write_new(
        private / "compose.env",
        "".join(
            f"{k}={v}\n"
            for k, v in {
                "REMOTE_VIBECODING_ROOT": str(root),
                "APP_HOME": str(home),
                "APP_UID": str(os.getuid()),
                "APP_GID": str(os.getgid()),
                "APP_STATE_DIR": data,
                **revisions,
            }.items()
        ),
    )
    env = root / ".env"
    if not env.exists() and not env.is_symlink():
        env.symlink_to(private / "compose.env")
    elif env.resolve() != private / "compose.env":
        raise ValueError("Workspace .env belongs to another owner; preserve it")

    key = private / "executor-key"
    if not key.exists():
        run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(key),
                "-C",
                "remote-vibecoding-host-executor",
            ]
        )
    public = key.with_suffix(".pub").read_text().strip()
    revision = revisions["CORE_REVISION"]
    destination = home / ".local/share/remote-vibecoding/executor" / revision / "host_executor.py"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = run(
        ["git", "show", revision + ":scripts/host_executor.py"],
        cwd=root / "vibecoding-core",
        capture_output=True,
    ).stdout
    write_new(destination, content, mode=0o700)
    host_key = Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().split()
    write_new(private / "known_hosts", "vibecoding-host " + " ".join(host_key[:2]) + "\n")
    user = pwd.getpwuid(os.getuid()).pw_name
    write_new(
        private / "executor-ssh.conf",
        f"""Host vibecoding-host
    HostName host.docker.internal
    HostKeyAlias vibecoding-host
    User {user}
    IdentityFile {key}
    IdentitiesOnly yes
    UserKnownHostsFile {private / "known_hosts"}
    StrictHostKeyChecking yes
    BatchMode yes
    ConnectTimeout 10
    ServerAliveInterval 15
    ServerAliveCountMax 2
""",
    )
    allowed = "127.0.0.1,::1" + ("," + args.executor_subnet if args.executor_subnet else "")
    command = shlex.join(["/usr/bin/python3", str(destination)])
    line = f'restrict,from="{allowed}",command={json.dumps(command)} {public}'
    authorized = home / ".ssh/authorized_keys"
    original = authorized.read_text() if authorized.exists() else ""
    blob = public.split()[1]
    existing = [row for row in original.splitlines() if blob not in row.split()]
    pending = authorized.with_name(".authorized_keys.remote-vibecoding")
    pending.write_text("\n".join([*existing, line]) + "\n")
    pending.chmod(0o600)
    pending.replace(authorized)
    print("Private configuration and dedicated host executor prepared; credential values were not printed")


if __name__ == "__main__":
    main()
