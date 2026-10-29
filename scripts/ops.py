#!/usr/bin/env python3
"""Host-side operations for one Remote Vibecoding Compose project."""

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import pwd
import re
import socket
import subprocess
import time
from pathlib import Path


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def read_env(path: Path) -> dict:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def atomic_text(path: Path, text: str, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


class Operations:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.env_file = (self.root / ".env").resolve()
        if not self.env_file.exists():
            raise ValueError("Provision host configuration before running Compose operations")
        self.values = read_env(self.env_file)
        self.private = Path(self.values["APP_HOME"]) / ".config/remote-vibecoding"
        self.state = Path(self.values["APP_STATE_DIR"])

    def compose(self, args, revisions=None, **kwargs):
        environment = {**os.environ, **read_env(self.env_file), **(revisions or {})}
        argv = [
            "sudo",
            "-n",
            "--preserve-env=CORE_REVISION,BOT_REVISION,REMOTE_VIBECODING_ROOT,APP_HOME,APP_UID,APP_GID,APP_STATE_DIR",
            "docker",
            "compose",
            "--project-directory",
            str(self.root),
            "--env-file",
            str(self.env_file),
            "--file",
            str(self.root / "compose.yaml"),
            "--project-name",
            "remote-vibecoding",
            *args,
        ]
        return run(argv, env=environment, **kwargs)

    def api(self, path, body=None):
        connection = http.client.HTTPConnection("localhost", timeout=20)
        channel = socket.socket(socket.AF_UNIX)
        channel.settimeout(20)
        channel.connect(str(self.state / "run/engine.sock"))
        connection.sock = channel
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
                raise RuntimeError(result.get("error", "Core request failed"))
            return result
        finally:
            connection.close()

    def image_revision(self, component):
        return read_env(self.env_file)[component.upper() + "_REVISION"]

    def container_id(self, component):
        return self.compose(["ps", "-q", component], capture_output=True).stdout.strip()

    def wait_ready(self, component, revision, timeout=150):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cid = self.container_id(component)
            if cid:
                result = run(
                    [
                        "sudo",
                        "-n",
                        "docker",
                        "inspect",
                        "--format",
                        "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                        cid,
                    ],
                    capture_output=True,
                )
                if result.stdout.strip() == "healthy":
                    if component != "core" or self.api("/health").get("revision") == revision:
                        return
            time.sleep(1)
        raise RuntimeError(f"{component} did not become ready at the requested revision")

    def build(self, component):
        repo = self.root / ("vibecoding-core" if component == "core" else "telegram-vibecoding")
        if run(["git", "status", "--porcelain"], cwd=repo, capture_output=True).stdout.strip():
            raise ValueError(f"Commit {component} source before deployment; working changes are preserved")
        run(["make", "check"], cwd=repo)
        revision = run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True).stdout.strip()
        self.compose(["build", component], {component.upper() + "_REVISION": revision})
        return revision

    def rebuild(self, component, revision):
        """Rebuild a recorded revision without another persistent source checkout."""
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Rollback requires a complete recorded Git revision")
        repo = self.root / ("vibecoding-core" if component == "core" else "telegram-vibecoding")
        probe = subprocess.run(
            ["git", "cat-file", "-e", revision + "^{commit}"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode:
            run(["git", "fetch", "origin", revision], cwd=repo)
        source = subprocess.check_output(["git", "archive", "--format=tar", revision], cwd=repo)
        command = [
            "sudo",
            "-n",
            "docker",
            "build",
            "--tag",
            "remote-vibecoding-" + component + ":" + revision,
        ]
        for key in ("APP_UID", "APP_GID", "APP_HOME"):
            command.extend(["--build-arg", key + "=" + self.values[key]])
        command.extend(["--build-arg", "REVISION=" + revision, "-"])
        subprocess.run(command, input=source, check=True)

    def cleanup_images(self, component):
        helper = Path("/usr/local/sbin/prune-service-images")
        if helper.is_file():
            try:
                run(["sudo", "-n", str(helper), "--apply", "--repository", "remote-vibecoding-" + component])
            except subprocess.CalledProcessError:
                print("Deployment is healthy but obsolete-image cleanup failed")

    def notifier_image(self, revision):
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "/app/.venv/bin/telegram-vibecoding",
                "remote-vibecoding-bot:" + revision,
                "--capabilities",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and result.stdout.strip() == "notifications-only"

    def activate(self, component, revision):
        if component == "bot" and not self.notifier_image(revision):
            raise ValueError("Refusing a Telegram image without the notification-only contract")
        key = component.upper() + "_REVISION"
        old = self.image_revision(component)
        core_before = self.container_id("core") if component == "bot" else None
        try:
            self.compose(["up", "--detach", "--no-deps", "--force-recreate", component], {key: revision})
            self.wait_ready(component, revision)
            if component == "bot" and core_before != self.container_id("core"):
                raise RuntimeError("Bot update unexpectedly replaced Core")
        except BaseException:
            if old and (component != "bot" or self.notifier_image(old)):
                self.compose(["up", "--detach", "--no-deps", "--force-recreate", component], {key: old})
                self.wait_ready(component, old)
            elif component == "bot":
                self.compose(["stop", "bot"])
                print("Telegram stopped: the previous interactive image is not a safe fallback")
            raise
        values = read_env(self.env_file)
        values[key] = revision
        atomic_text(self.env_file, "".join(f"{k}={v}\n" for k, v in values.items()))
        record = self.private / "deployment.json"
        history = json.loads(record.read_text()) if record.exists() else {}
        history[component] = {"current": revision, "previous": old}
        atomic_text(record, json.dumps(history, indent=2) + "\n")
        self.cleanup_images(component)

    def schedule_core(self, revision):
        repo = self.root / "vibecoding-core"
        worker = repo / "scripts/ops.py"
        unit = "remote-vibecoding-update-" + str(time.time_ns())
        user = pwd.getpwuid(os.getuid()).pw_name
        run(
            [
                "sudo",
                "-n",
                "systemd-run",
                "--collect",
                "--unit=" + unit,
                "--property=User=" + user,
                "--setenv=HOME=" + self.values["APP_HOME"],
                "/usr/bin/python3",
                str(worker),
                "--root",
                str(self.root),
                "--revision",
                revision,
                "apply-core",
            ]
        )
        print("Core update scheduled: " + unit)

    def apply_core(self, revision):
        health = self.api("/health")
        if not health["accepting"]:
            raise RuntimeError("Another operation is draining Core")
        self.api("/drain", {"enabled": True})
        try:
            deadline = time.monotonic() + 900
            while True:
                health = self.api("/health")
                if not health["busy"] and not health["pending_requests"]:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Active work did not finish; Core update deferred")
                time.sleep(1)
            self.activate("core", revision)
        finally:
            with contextlib.suppress(Exception):
                self.api("/drain", {"enabled": False})

    def snapshot(self):
        health = self.api("/health")
        if not health["accepting"] or health["busy"] or health["pending_requests"]:
            print("Snapshot deferred while Core is busy; previous copy retained")
            return
        output = self.state / "snapshots"
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (output / "snapshot.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Snapshot deferred while another snapshot is running; previous copy retained")
                return
            target = output / "next.tar.gz"
            checksum = output / "next.tar.gz.sha256"
            target.unlink(missing_ok=True)
            checksum.unlink(missing_ok=True)
            try:
                self.compose(
                    [
                        "exec",
                        "-T",
                        "core",
                        "vibecoding-core",
                        "backup",
                        str(target),
                        "--include-codex",
                        "--project-sources",
                        "--wait",
                        "0",
                    ]
                )
                with target.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                atomic_text(checksum, digest + "  latest.tar.gz\n")
                target.replace(output / "latest.tar.gz")
                checksum.replace(output / "latest.tar.gz.sha256")
                print("Private consistent snapshot published")
            finally:
                target.unlink(missing_ok=True)
                checksum.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "action",
        choices=[
            "build",
            "up",
            "status",
            "logs",
            "stop",
            "deploy-bot",
            "deploy-core",
            "apply-core",
            "rollback-bot",
            "snapshot",
            "core-cli",
        ],
    )
    parser.add_argument("--revision")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    operations = Operations(args.root)
    if args.action == "status":
        operations.compose(["ps"])
    elif args.action == "logs":
        operations.compose(["logs", "--tail", "80", *args.arguments])
    elif args.action == "stop":
        operations.compose(["stop"])
    elif args.action == "core-cli":
        operations.compose(["exec", "-T", "core", "vibecoding-core", *args.arguments])
    elif args.action == "snapshot":
        operations.snapshot()
    else:
        operations.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (operations.private / "deployment.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX if args.action == "apply-core" else fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "build":
                for component in ["core", "bot"]:
                    operations.build(component)
            elif args.action == "up":
                operations.compose(["up", "--detach"])
                for component in ["core", "bot"]:
                    operations.wait_ready(component, operations.image_revision(component))
            elif args.action == "deploy-bot":
                operations.activate("bot", operations.build("bot"))
            elif args.action == "deploy-core":
                operations.schedule_core(operations.build("core"))
            elif args.action == "apply-core":
                if not args.revision:
                    raise ValueError("--revision is required")
                operations.apply_core(args.revision)
            elif args.action == "rollback-bot":
                state = json.loads((operations.private / "deployment.json").read_text())
                previous = state.get("bot", {}).get("previous")
                if not previous:
                    raise ValueError("No previous container image is recorded")
                operations.rebuild("bot", previous)
                operations.activate("bot", previous)


if __name__ == "__main__":
    main()
