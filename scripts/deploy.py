#!/usr/bin/env python3
"""Deploy checked private commits with independent bot/engine release links."""

import argparse
import contextlib
import fcntl
import http.client
import io
import json
import os
import socket
import sqlite3
import subprocess
import tarfile
import time
import tomllib
from pathlib import Path


def installation_root() -> Path:
    return Path(os.environ.get("CODEX_RELAY_INSTALL_ROOT", "~/.local/share/codex-relay")).expanduser()


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def api(path: str, body=None):
    config = Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()
    values = tomllib.loads(config.read_text()) if config.exists() else {}
    data = Path(values.get("data_dir", "~/.local/state/codex-relay")).expanduser()
    runtime = Path(values.get("runtime_dir", str(data / "run"))).expanduser()
    connection = http.client.HTTPConnection("localhost", timeout=15)
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(15)
    sock.connect(str(runtime / "engine.sock"))
    connection.sock = sock
    try:
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(
            "POST" if body is not None else "GET",
            path,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status >= 400:
            raise RuntimeError(result.get("error", "Engine request failed"))
        return result
    finally:
        connection.close()


def switch(link: Path, target: Path):
    temporary = link.with_name(link.name + ".new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(link)


def bot_database() -> Path:
    config = Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()
    values = tomllib.loads(config.read_text()) if config.exists() else {}
    return Path(values.get("data_dir", "~/.local/state/codex-relay")).expanduser() / "bot.db"


def restart(component: str, release: Path, runner):
    unit = "codex-relay-" + component
    database = bot_database()
    if component == "bot" and database.exists():
        marker = release / ".relay-ui-version"
        expected = marker.read_text().strip() if marker.exists() else "1"
        with contextlib.closing(sqlite3.connect(database)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='ui_version'").fetchone()
        if (row[0] if row else "1") != expected:
            # Reset incompatible navigation only while its sole writer is stopped.
            runner(["sudo", "-n", "systemctl", "stop", unit])
            with contextlib.closing(sqlite3.connect(database)) as db, db:
                db.execute("DELETE FROM meta WHERE key LIKE 'fsm:%'")
                db.executemany(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                    [("ui_version", expected), ("screen", ""), ("mode", "menu"), ("input_action", "")],
                )
            runner(["sudo", "-n", "systemctl", "start", unit])
            return
    runner(["sudo", "-n", "systemctl", "restart", unit])


def activate(component: str, release: Path, root: Path, runner=run, verify=None):
    if component not in {"bot", "engine"}:
        raise ValueError("Unknown deployment component")
    link = root / (component + "-current")
    previous = link.resolve() if link.is_symlink() else None
    switch(link, release)
    unit = "codex-relay-" + component
    try:
        restart(component, release, runner)
        if verify:
            verify()
        else:
            time.sleep(2)
            runner(["systemctl", "is-active", "--quiet", unit])
            if component == "engine":
                expected = (release / ".relay-revision").read_text().strip()
                health = api("/health")
                if health.get("revision") != expected:
                    raise RuntimeError("Engine did not activate the staged revision")
            else:
                config = Path(
                    os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")
                ).expanduser()
                values = tomllib.loads(config.read_text()) if config.exists() else {}
                database = Path(values.get("data_dir", "~/.local/state/codex-relay")).expanduser() / "bot.db"
                for _ in range(30):
                    pid = runner(
                        ["systemctl", "show", unit, "-p", "MainPID", "--value"], capture_output=True
                    ).stdout.strip()
                    with contextlib.closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
                        ready = db.execute("SELECT value FROM meta WHERE key='bot_pid'").fetchone()
                    if pid != "0" and ready and ready[0] == pid:
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("New bot process did not confirm Telegram and engine readiness")
    except BaseException:
        if previous:
            switch(link, previous)
            restart(component, previous, runner)
        else:
            link.unlink(missing_ok=True)
        raise
    if previous and previous != release:
        switch(root / (component + "-previous"), previous)


def stage(source: Path, root: Path) -> Path:
    status = run(["git", "status", "--porcelain"], cwd=source, capture_output=True).stdout
    if status.strip():
        raise RuntimeError("Commit the source changes before deployment; dirty checkouts are preserved")
    run(["make", "check"], cwd=source)
    commit = run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True).stdout.strip()
    release = root / "releases" / commit
    if not release.exists():
        release.mkdir(parents=True, mode=0o700)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", commit], cwd=source, check=True, stdout=subprocess.PIPE
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
            tf.extractall(release, filter="data")
        (release / ".relay-revision").write_text(commit + "\n")
    if (release / ".relay-revision").read_text().strip() != commit:
        raise RuntimeError("Release directory does not match the source revision")
    run(["uv", "sync", "--frozen", "--no-dev"], cwd=release)
    run([str(release / ".venv/bin/codex-relay"), "--version"], capture_output=True)
    return release


def apply_engine(release: Path, root: Path):
    if not api("/health")["accepting"]:
        raise RuntimeError("Another operation is already draining this engine")
    api("/drain", {"enabled": True})
    try:
        deadline = time.monotonic() + 900
        while True:
            health = api("/health")
            if not health["busy"] and not health["pending_requests"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Active turns did not finish within 15 minutes; update deferred")
            time.sleep(1)
        activate("engine", release, root)
    finally:
        with contextlib.suppress(Exception):
            api("/drain", {"enabled": False})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["bot", "engine", "rollback", "apply-engine"])
    parser.add_argument("--release", type=Path)
    args = parser.parse_args()
    if os.uname().sysname != "Linux":
        raise RuntimeError("Deploy on the Linux host, from its source checkout")
    root = installation_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "deployment.lock").open("a") as lock:
        fcntl.flock(
            lock, fcntl.LOCK_EX if args.component == "apply-engine" else fcntl.LOCK_EX | fcntl.LOCK_NB
        )
        if args.component == "rollback":
            previous = root / "bot-previous"
            if not previous.is_symlink():
                raise RuntimeError("No previous bot release is retained")
            activate("bot", previous.resolve(), root)
            print("Bot rollback verified. Engine was not restarted.")
        elif args.component == "apply-engine":
            if not args.release:
                raise ValueError("--release is required")
            release = args.release.resolve(strict=True)
            if release.parent != (root / "releases").resolve():
                raise ValueError("Release must belong to this installation")
            apply_engine(release, root)
            print("Engine update verified.")
        else:
            source = Path(__file__).resolve().parent.parent
            release = stage(source, root)
            if args.component == "bot":
                activate("bot", release, root)
                print("Bot update verified. Engine was not restarted.")
            else:
                unit = "codex-relay-update-" + str(time.time_ns())
                run(
                    [
                        "sudo",
                        "-n",
                        "systemd-run",
                        "--collect",
                        "--unit=" + unit,
                        "--property=User=" + __import__("pwd").getpwuid(os.getuid()).pw_name,
                        "--setenv=PATH=" + os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                        "/usr/bin/python3",
                        str(release / "scripts/deploy.py"),
                        "apply-engine",
                        "--release",
                        str(release),
                    ]
                )
                print(f"Engine update scheduled independently: {unit}. Inspect its journal for completion.")


if __name__ == "__main__":
    main()
