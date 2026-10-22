import argparse
import sqlite3
import tarfile

import pytest
from conftest import settle

from codex_relay.cli import snapshot


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
