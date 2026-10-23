import argparse
import sqlite3
import tarfile

import pytest
from conftest import settle

from vibecoding_core.cli import snapshot


async def test_snapshot_restores_valid_databases_and_releases_drain(host, tmp_path):
    settings, engine, native, client = host
    session = engine.store.create_session(str(tmp_path), "Retained", "medium")
    target = tmp_path / "private-backup.tar.gz"
    args = argparse.Namespace(
        destination=target, wait=0, include_codex=False, project_sources=False, config=None
    )
    result = await snapshot(settings, client, args)
    assert target.stat().st_mode & 0o077 == 0
    assert result["sha256"]
    restored = tmp_path / "restore"
    restored.mkdir()
    with tarfile.open(target) as archive:
        archive.extractall(restored, filter="data")
    with sqlite3.connect(restored / "relay/engine.db") as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            db.execute("SELECT name FROM sessions WHERE id=?", (session["id"],)).fetchone()[0] == "Retained"
        )
    assert (await client.call("/health"))["accepting"]
    assert target.with_suffix(".gz.sha256").exists()


async def test_busy_snapshot_defers_without_interrupting_or_overwriting(host, tmp_path):
    settings, engine, native, client = host
    s = engine.store.create_session(str(tmp_path), "Busy", "medium")
    await client.call("/messages", {"request_id": "busy", "session_id": s["id"], "text": "work"})
    await settle(engine)
    args = argparse.Namespace(
        destination=tmp_path / "deferred.tar.gz",
        wait=0,
        include_codex=False,
        project_sources=False,
        config=None,
    )
    with pytest.raises(ValueError, match="deferred"):
        await snapshot(settings, client, args)
    assert not args.destination.exists()
    assert (await client.call("/health"))["accepting"]
    assert engine.store.session(s["id"])["turn_id"]
    assert not any(m == "turn/interrupt" for m, p in native.calls)


async def test_native_snapshot_keeps_live_state_and_sources_without_caches(host, tmp_path, monkeypatch):
    settings, engine, native, client = host
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    retained = ["auth.json", "sessions/rollout.jsonl", "plugins/config.json"]
    omitted = [
        "cache/catalog.json",
        "plugins/cache/template.bin",
        "log/runtime.log",
        ".tmp/socket",
        "tmp/arg0-linux/apply_patch",
    ]
    for name in retained + omitted:
        path = codex_home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith("apply_patch"):
            path.symlink_to("/")
        else:
            path.write_text("fixture: " + name)
    project = tmp_path / "source"
    (project / ".git").mkdir(parents=True)
    (project / "uncommitted.txt").write_text("unfinished user work")
    (project / ".venv").mkdir()
    (project / ".venv/cache").write_text("rebuildable")
    registered = engine.store.register_project("Source", str(project))
    target = tmp_path / "native.tar.gz"
    args = argparse.Namespace(
        destination=target, wait=0, include_codex=True, project_sources=True, config=None
    )
    # The writer remains open with WAL data so a raw database copy would lose the row.
    with sqlite3.connect(codex_home / "state_5.sqlite") as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE history(message TEXT)")
        writer.execute("INSERT INTO history VALUES ('retained native turn')")
        writer.commit()
        with sqlite3.connect(codex_home / "logs_2.sqlite") as logs:
            logs.execute("CREATE TABLE logs(value TEXT)")
        await snapshot(settings, client, args)
    restored = tmp_path / "restore-native"
    with tarfile.open(target) as archive:
        names = archive.getnames()
        assert all("codex/" + name in names for name in retained)
        assert all("codex/" + name not in names for name in omitted)
        assert "codex/logs_2.sqlite" not in names
        assert not any(name.endswith(("-wal", "-shm")) for name in names)
        archive.extractall(restored, filter="data")
    with sqlite3.connect(restored / "codex/state_5.sqlite") as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT message FROM history").fetchone()[0] == "retained native turn"
    restored_source = restored / "projects" / registered["id"]
    assert (restored_source / "uncommitted.txt").read_text() == "unfinished user work"
    assert not (restored_source / ".venv").exists()
    assert all((codex_home / name).exists() for name in omitted)


async def test_drain_preserves_input_for_retry_instead_of_rejecting_permanently(host, tmp_path):
    settings, engine, native, client = host
    s = engine.store.create_session(str(tmp_path), "Pending", "medium")
    body = {"request_id": "held", "session_id": s["id"], "text": "later"}
    await client.call("/drain", {"enabled": True})
    with pytest.raises(ConnectionError, match="queued"):
        await client.call("/messages", body)
    assert not engine.store.request("held")
    await client.call("/drain", {"enabled": False})
    await client.call("/messages", body)
    await settle(engine)
    assert engine.store.request("held")["state"] == "accepted"


async def test_workspace_snapshot_includes_both_independent_git_sources(host, tmp_path):
    settings, engine, native, client = host
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "workspace.toml").write_text('repositories = ["telegram-vibecoding", "vibecoding-core"]\n')
    for name in ["telegram-vibecoding", "vibecoding-core"]:
        repo = workspace / name
        (repo / ".git").mkdir(parents=True)
        (repo / "uncommitted.py").write_text(name)
    project = engine.store.register_project("Remote Vibecoding", str(workspace))
    target = tmp_path / "workspace.tar.gz"
    args = argparse.Namespace(
        destination=target, wait=0, include_codex=False, project_sources=True, config=None
    )
    await snapshot(settings, client, args)
    with tarfile.open(target) as archive:
        for name in ["telegram-vibecoding", "vibecoding-core"]:
            stream = archive.extractfile(f"projects/{project['id']}/{name}/uncommitted.py")
            assert stream.read().decode() == name
