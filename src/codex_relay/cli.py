"""Supported noninteractive interface for agents and host operators."""

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from codex_relay import __version__
from codex_relay.config import Settings
from codex_relay.engine import EngineClient
from codex_relay.store import BotStore, EngineStore, identifier


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codex-relay", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["engine", "bot", "doctor"]:
        sub.add_parser(name)
    project = sub.add_parser("project").add_subparsers(dest="action", required=True)
    project.add_parser("list")
    add = project.add_parser("add")
    add.add_argument("path")
    add.add_argument("--name", required=True)
    clone = project.add_parser("clone")
    clone.add_argument("url")
    clone.add_argument("--name", required=True)
    clone.add_argument(
        "--category",
        default="bots",
        choices=[
            "bots",
            "cli",
            "apps",
            "infrastructure",
            "web-apps",
            "sandbox",
            "agents",
            "automations",
            "extensions",
            "products",
        ],
    )
    session = sub.add_parser("session").add_subparsers(dest="action", required=True)
    session.add_parser("list").add_argument("--archived", action="store_true")
    new = session.add_parser("new")
    new.add_argument("path")
    new.add_argument("--name", default="New session")
    for name in ["send", "stop", "archive", "reopen", "history"]:
        command = session.add_parser(name)
        command.add_argument("id")
        if name == "send":
            command.add_argument("text", nargs="?", default="")
            command.add_argument("--image", action="append", default=[])
            command.add_argument("--request-id")
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument(
        "--include-codex",
        action="store_true",
        help="Include private native Codex history and auth; keep the archive private",
    )
    backup.add_argument(
        "--project-sources",
        action="store_true",
        help="Include registered Git sources and uncommitted changes, excluding build caches",
    )
    backup.add_argument("--wait", type=int, default=300)
    return p


async def snapshot(settings: Settings, client: EngineClient, args) -> dict:
    destination = args.destination.expanduser().resolve()
    if destination.exists():
        raise ValueError("Backup destination already exists; choose a new path")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    health = await client.call("/health")
    if not health["accepting"]:
        raise ValueError("Engine is already draining; do not interfere with another operation")
    await client.call("/drain", {"enabled": True})
    stage = destination.parent / (".snapshot-" + identifier())
    try:
        deadline = time.monotonic() + args.wait
        while True:
            health = await client.call("/health")
            if not health["busy"] and not health["pending_requests"]:
                break
            if time.monotonic() >= deadline:
                raise ValueError("Active turns did not finish; backup deferred without interrupting work")
            await asyncio.sleep(1)
        stage.mkdir(mode=0o700)
        for cls, name in [(EngineStore, "engine.db"), (BotStore, "bot.db")]:
            store = cls(settings.data_dir / name)
            try:
                store.backup(stage / name)
            finally:
                store.close()
        projects = await client.call("/projects")
        (stage / "manifest.json").write_text(
            json.dumps(
                {
                    "version": __version__,
                    "host_id": settings.host_id,
                    "created": time.time(),
                    "private": True,
                    "projects": projects,
                    "includes_codex": args.include_codex,
                    "includes_sources": args.project_sources,
                },
                indent=2,
            )
        )
        config = (
            args.config
            or Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()
        )
        with tarfile.open(destination, "x:gz") as archive:
            archive.add(stage, arcname="relay")
            if config.exists():
                archive.add(config, arcname="config/config.toml")
            if settings.token_file.exists():
                archive.add(settings.token_file, arcname="config/bot-token")
            uploads = settings.data_dir / "uploads"
            if uploads.exists():
                archive.add(uploads, arcname="relay/uploads")
            if args.include_codex:
                codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
                if codex_home.exists():

                    def codex_filter(member):
                        relative = Path(member.name).relative_to("codex")
                        if relative.parts and relative.parts[0] in {"cache", "log", ".tmp", "tmp"}:
                            return None
                        if relative.parts[:2] == ("plugins", "cache"):
                            return None
                        if member.name.endswith(
                            (".db", ".sqlite", ".sqlite3", "-wal", "-shm", ".sock", ".lock")
                        ):
                            return None
                        return member

                    archive.add(codex_home, arcname="codex", filter=codex_filter)
                    for source in codex_home.glob("*"):
                        if source.is_file() and source.suffix in {".db", ".sqlite", ".sqlite3"}:
                            if source.name.startswith("logs_"):
                                continue
                            import sqlite3

                            with (
                                sqlite3.connect(f"file:{source}?mode=ro", uri=True) as db,
                                sqlite3.connect(stage / source.name) as out,
                            ):
                                db.backup(out)
                            archive.add(stage / source.name, arcname="codex/" + source.name)
            if args.project_sources:
                excluded = {
                    ".venv",
                    "node_modules",
                    "target",
                    "dist",
                    "build",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                }
                for project in projects:
                    source = Path(project["path"])
                    # Home is a launch directory, never a blanket home-directory backup.
                    if not (source / ".git").exists():
                        continue

                    def source_filter(member):
                        return None if any(p in excluded for p in Path(member.name).parts) else member

                    archive.add(source, arcname="projects/" + project["id"], filter=source_filter)
        destination.chmod(0o600)
        with tarfile.open(destination) as archive:
            for member in archive:
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream:
                        while stream.read(1024 * 1024):
                            pass
        import hashlib

        with destination.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            checksum + "  " + destination.name + "\n"
        )
        return {"archive": str(destination), "sha256": checksum, "private": True}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        await client.call("/drain", {"enabled": False})


async def execute(args):
    settings = Settings.load(args.config)
    if args.command == "engine":
        from codex_relay.engine import serve

        return await serve(settings)
    if args.command == "bot":
        from codex_relay.bot import run

        return await run(settings)
    client = EngineClient(settings)
    try:
        if args.command == "doctor":
            result = {
                "engine": await client.call("/health"),
                "account": await client.call("/account"),
                "token_file_present": settings.token_file.exists(),
                "owner_configured": settings.allowed_user_id > 0,
            }
        elif args.command == "project":
            if args.action == "list":
                result = await client.call("/projects")
            elif args.action == "add":
                result = await client.call("/projects", {"name": args.name, "path": args.path})
            else:
                if not args.name or Path(args.name).name != args.name or args.name in {".", ".."}:
                    raise ValueError("Project name must be one directory component")
                if not (args.url.startswith(("git@github.com:", "https://github.com/"))):
                    raise ValueError("Use a GitHub SSH or HTTPS repository URL")
                path = settings.development_root / args.category / args.name
                if path.exists():
                    raise ValueError("Destination already exists; register it with project add")
                path.parent.mkdir(parents=True, exist_ok=True)
                # Avoid exposing an embedded HTTPS credential through subprocess output.
                if "https://" in args.url and "@" in args.url:
                    raise ValueError("Do not embed credentials in repository URLs")
                subprocess.run(["git", "clone", "--", args.url, str(path)], check=True)
                result = await client.call("/projects", {"name": args.name, "path": str(path)})
        elif args.command == "session":
            if args.action == "list":
                result = await client.call("/sessions" + ("?archived=1" if args.archived else ""))
            elif args.action == "new":
                result = await client.call("/sessions", {"cwd": args.path, "name": args.name})
            elif args.action == "send":
                result = await client.call(
                    "/messages",
                    {
                        "request_id": args.request_id or "cli:" + identifier(),
                        "session_id": args.id,
                        "text": args.text,
                        "images": [str(Path(p).expanduser().resolve(strict=True)) for p in args.image],
                    },
                )
            elif args.action == "history":
                result = await client.call(f"/sessions/{args.id}/history")
            else:
                result = await client.call(f"/sessions/{args.id}/{args.action}", {})
        elif args.command == "backup":
            result = await snapshot(settings, client, args)
        else:
            raise ValueError("Unknown command")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await client.close()


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP library diagnostics can contain Telegram URLs with the bot token.
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
    try:
        asyncio.run(execute(parser().parse_args()))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Do not print arbitrary HTTP exceptions: they may embed token-bearing URLs.
        message = (
            str(exc) if isinstance(exc, (ValueError, FileNotFoundError, RuntimeError)) else type(exc).__name__
        )
        print("Error: " + message, file=sys.stderr)
        raise SystemExit(1) from None
