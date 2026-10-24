import json
import os
import time

import pytest


async def test_retention_expires_content_and_media_without_replaying_or_losing_native_identity(
    host, tmp_path
):
    settings, engine, native, client = host
    now = time.time()
    cutoff = now - 7 * 86400
    session = engine.store.create_session(str(tmp_path), "Keep session", "medium")
    sid = session["id"]
    engine.store.update_session(sid, thread_id="native-identity")
    old = engine.store.event(sid, "user", {"text": "Expired private content"})
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    expired = engine.attach(sid, {"path": str(source), "anchor": old})
    source.write_bytes(b"\x89PNG\r\n\x1a\nnew-image")
    retained = engine.attach(sid, {"path": str(source), "anchor": old})
    engine.store.accept(
        "old-request",
        sid,
        {"request_id": "old-request", "session_id": sid, "text": "Expired private content"},
    )
    engine.store.request_state("old-request", "accepted", {"text": "Old result"})
    with engine.store.db:
        engine.store.db.execute("UPDATE events SET created=?", (cutoff,))
        engine.store.db.execute("UPDATE attachments SET created=? WHERE id=?", (cutoff, expired["id"]))
        engine.store.db.execute("UPDATE requests SET created=?", (cutoff,))
    fresh = engine.store.event(sid, "user", {"text": "Retained"})
    before = len(native.calls)
    result = engine.expire_history(now)
    assert result["events"] == 3 and result["files"] == 1
    assert not settings.data_dir.joinpath("uploads", sid, "attachments", expired["id"] + ".png").exists()
    assert engine.attachments(sid)[0]["id"] == retained["id"]
    assert engine.attachments(sid)[0]["user_event_id"] is None
    assert engine.store.conversation(sid)["user"]["id"] == fresh
    assert engine.store.session(sid)["thread_id"] == "native-identity"
    request = engine.store.request("old-request")
    assert json.loads(request["payload"]) == {"expired": True} and request["result"] is None
    with pytest.raises(ValueError, match="expired"):
        engine.submit({"request_id": "old-request", "session_id": sid, "text": "Expired private content"})
    assert len(native.calls) == before
    assert engine.store.event(sid, "message", {"text": "Next"}) > fresh
    assert engine.store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert engine.expire_history(now)["events"] == 0


async def test_retention_pins_queued_and_active_work_and_retries_orphan_cleanup(host, tmp_path):
    settings, engine, native, client = host
    now = time.time()
    cutoff = now - 7 * 86400
    session = engine.store.create_session(str(tmp_path), "Pending", "medium")
    sid = session["id"]
    event = engine.store.event(sid, "user", {"text": "Not delivered yet"})
    engine.store.accept("queued", sid, {"text": "Not delivered yet"})
    with engine.store.db:
        engine.store.db.execute("UPDATE events SET created=?", (cutoff,))
        engine.store.db.execute("UPDATE requests SET created=?", (cutoff,))
    directory = settings.data_dir / "uploads" / sid / "attachments"
    directory.mkdir(parents=True)
    orphan = directory / "old.part"
    orphan.write_bytes(b"old upload")
    os.utime(orphan, (cutoff, cutoff))
    outside = tmp_path / "unrelated.png"
    outside.write_bytes(b"keep")
    (directory / "link.png").symlink_to(outside)
    assert engine.expire_history(now)["events"] == 0 and orphan.exists()
    engine.store.request_state("queued", "accepted")
    engine.store.update_session(sid, turn_id="active", status="working")
    assert engine.expire_history(now)["events"] == 0 and orphan.exists()
    engine.store.update_session(sid, turn_id=None, status="idle")
    assert engine.expire_history(now)["files"] == 1
    assert not orphan.exists() and outside.read_bytes() == b"keep"
    assert engine.store.one("SELECT id FROM events WHERE id=?", (event,)) is None
