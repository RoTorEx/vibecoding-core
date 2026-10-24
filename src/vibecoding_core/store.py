"""Small transactional stores. No database transaction crosses an await."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any


def identifier() -> str:
    return uuid.uuid4().hex[:16]


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def backup(self, path: Path) -> None:
        with closing(sqlite3.connect(path)) as dest:
            self.db.backup(dest)
            if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Snapshot integrity check failed")
        path.chmod(0o600)


class EngineStore(Database):
    def __init__(self, path: Path):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, cwd TEXT NOT NULL,
                thread_id TEXT UNIQUE, turn_id TEXT, status TEXT NOT NULL DEFAULT 'idle',
                archived INTEGER NOT NULL DEFAULT 0, model TEXT, effort TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES sessions(id), kind TEXT NOT NULL,
                payload TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attachments(
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                user_event_id INTEGER REFERENCES events(id), name TEXT NOT NULL, path TEXT NOT NULL,
                mime_type TEXT NOT NULL, size INTEGER NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS questions(
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                rpc_id TEXT NOT NULL, method TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending');
            CREATE INDEX IF NOT EXISTS events_session_kind_id ON events(session_id,kind,id);
        """)

        columns = {r[1] for r in self.db.execute("PRAGMA table_info(sessions)")}
        if "collaboration_mode" not in columns:
            with self.db:
                self.db.execute(
                    "ALTER TABLE sessions ADD COLUMN collaboration_mode TEXT NOT NULL DEFAULT 'default'"
                )

    def register_project(self, name: str, path: str, *, validated=False) -> dict:
        resolved = Path(path) if validated else Path(path).expanduser().resolve(strict=True)
        if (not validated and not resolved.is_dir()) or not resolved.is_absolute() or not name.strip():
            raise ValueError("A project needs a name and an existing directory")
        with self.db:
            self.db.execute(
                """INSERT INTO projects(id,name,path) VALUES(?,?,?)
                ON CONFLICT(path) DO UPDATE SET name=excluded.name,enabled=1""",
                (identifier(), name.strip(), str(resolved)),
            )
        return self.one("SELECT * FROM projects WHERE path=?", (str(resolved),)) or {}

    def projects(self) -> list[dict]:
        return self.rows("SELECT * FROM projects WHERE enabled=1 ORDER BY name COLLATE NOCASE")

    def create_session(
        self,
        cwd: str,
        name: str,
        effort: str,
        model: str | None = None,
        *,
        validated=False,
        request_id: str | None = None,
    ) -> dict:
        path = Path(cwd) if validated else Path(cwd).expanduser().resolve(strict=True)
        if not path.is_absolute() or (not validated and not path.is_dir()):
            raise ValueError("Working directory is not a directory")
        if request_id is not None and (
            not isinstance(request_id, str) or not request_id or len(request_id) > 200
        ):
            raise ValueError("Session request_id must contain 1–200 characters")
        sid = (
            hashlib.sha256(("session:" + request_id).encode()).hexdigest()[:16]
            if request_id
            else identifier()
        )
        existing = self.one("SELECT * FROM sessions WHERE id=?", (sid,))
        if existing:
            if existing["cwd"] != str(path):
                raise ValueError("Session request_id belongs to a different directory")
            return existing
        if validated:
            if not self.one("SELECT id FROM projects WHERE path=?", (str(path),)):
                self.register_project(path.name or "/", str(path), validated=True)
        else:
            self.register_session_location(path)
        now = time.time()
        with self.db:
            self.db.execute(
                """INSERT INTO sessions(id,name,cwd,effort,model,created,updated)
                VALUES(?,?,?,?,?,?,?)""",
                (sid, name.strip() or "New session", str(path), effort, model, now, now),
            )
        return self.session(sid)

    def register_session_location(self, path: Path):
        if path.is_dir() and not self.one("SELECT id FROM projects WHERE path=?", (str(path),)):
            self.register_project("Home" if path == Path.home() else path.name or "/", str(path))

    def session(self, sid: str) -> dict:
        value = self.one("SELECT * FROM sessions WHERE id=?", (sid,))
        if value is None:
            raise ValueError("Session not found")
        return value

    def sessions(self, archived: bool = False) -> list[dict]:
        return self.rows(
            "SELECT s.*, (SELECT MAX(e.created) FROM events e WHERE e.session_id=s.id "
            "AND e.kind='message' AND COALESCE(json_extract(e.payload,'$.phase'),'')!='commentary') "
            "AS last_response, (SELECT MAX(e.id) FROM events e WHERE e.session_id=s.id "
            "AND e.kind='completed') AS last_completed_event, "
            "MAX(s.updated, COALESCE((SELECT MAX(e.created) FROM events e WHERE e.session_id=s.id "
            "AND (e.kind IN ('user','question','completed','attachment') OR (e.kind='message' "
            "AND COALESCE(json_extract(e.payload,'$.phase'),'')!='commentary'))), s.created)) "
            "AS last_interaction, "
            "(SELECT COUNT(*) FROM questions q WHERE q.session_id=s.id AND q.status='pending') "
            "AS pending_questions, "
            "(SELECT COUNT(*) FROM requests r WHERE r.session_id=s.id "
            "AND r.state IN ('queued','dispatching')) AS pending_requests "
            "FROM sessions s WHERE archived=? ORDER BY last_interaction DESC, s.id DESC",
            (int(archived),),
        )

    def update_session(self, sid: str, **values) -> None:
        if set(values) - {
            "name",
            "cwd",
            "thread_id",
            "turn_id",
            "status",
            "archived",
            "model",
            "effort",
            "collaboration_mode",
        }:
            raise ValueError("Unsupported session field")
        values["updated"] = time.time()
        with self.db:
            self.db.execute(
                "UPDATE sessions SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), sid),
            )

    def event(self, sid: str | None, kind: str, payload: dict) -> int:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO events(session_id,kind,payload,created) VALUES(?,?,?,?)",
                (sid, kind, json.dumps(payload), time.time()),
            )
        return int(cursor.lastrowid or 0)

    def events(self, after: int, limit: int = 100) -> list[dict]:
        return [
            {**r, "payload": json.loads(r["payload"])}
            for r in self.rows("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit))
        ]

    def history(self, sid: str) -> list[dict]:
        self.session(sid)
        return [
            {**r, "payload": json.loads(r["payload"])}
            for r in self.rows(
                "SELECT * FROM (SELECT * FROM events WHERE session_id=? AND kind IN "
                "('user','message','reasoning_summary','completed','error','question','attachment') ORDER BY id DESC LIMIT 200) ORDER BY id",
                (sid,),
            )
        ]

    def conversation(self, sid: str, anchor: int | None = None) -> dict:
        """Read one request and its replies, with stable cursors across all retained history."""
        self.session(sid)
        user = self.one(
            "SELECT * FROM events WHERE session_id=? AND kind='user' "
            + ("AND id=? " if anchor is not None else "")
            + "ORDER BY id DESC LIMIT 1",
            (sid, anchor) if anchor is not None else (sid,),
        )
        if not user:
            return {"user": None, "replies": [], "previous": None, "next": None, "index": 0, "total": 0}
        previous = self.one(
            "SELECT id FROM events WHERE session_id=? AND kind='user' AND id<? ORDER BY id DESC LIMIT 1",
            (sid, user["id"]),
        )
        following = self.one(
            "SELECT id FROM events WHERE session_id=? AND kind='user' AND id>? ORDER BY id LIMIT 1",
            (sid, user["id"]),
        )
        replies = self.rows(
            "SELECT * FROM events WHERE session_id=? AND id>? AND id<? "
            "AND kind IN ('message','reasoning_summary','error','completed','question','attachment') ORDER BY id",
            (sid, user["id"], following["id"] if following else 9223372036854775807),
        )
        user_payload = json.loads(user["payload"])
        transcriptions = self.rows(
            "SELECT * FROM events WHERE session_id=? AND kind='transcription' "
            "AND json_extract(payload,'$.request_id')=? ORDER BY id",
            (sid, user_payload.get("request_id")),
        )
        counts = self.one(
            "SELECT COUNT(*) AS total, SUM(id<=?) AS position FROM events WHERE session_id=? AND kind='user'",
            (user["id"], sid),
        )
        assert counts is not None
        return {
            "user": {**user, "payload": json.loads(user["payload"])},
            "replies": [{**r, "payload": json.loads(r["payload"])} for r in transcriptions + replies],
            "previous": previous["id"] if previous else None,
            "next": following["id"] if following else None,
            "index": counts["position"],
            "total": counts["total"],
        }

    def details(self, sid: str) -> dict:
        session = self.session(sid)
        stamps = self.one(
            "SELECT MAX(CASE WHEN kind='user' THEN created END) AS last_request, "
            "MAX(CASE WHEN kind='message' THEN created END) AS last_response, "
            "MAX(CASE WHEN kind='completed' THEN created END) AS last_finished "
            "FROM events WHERE session_id=?",
            (sid,),
        )
        return {**session, **(stamps or {})}

    def accept(self, rid: str, sid: str, payload: dict) -> bool:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO requests VALUES(?,?,?,'queued',NULL,?)",
                (rid, sid, json.dumps(payload), time.time()),
            )
        return cur.rowcount == 1

    def request(self, rid: str) -> dict:
        return self.one("SELECT * FROM requests WHERE id=?", (rid,)) or {}

    def request_state(self, rid: str, state: str, result: dict | None = None) -> None:
        with self.db:
            self.db.execute(
                "UPDATE requests SET state=?,result=? WHERE id=?",
                (state, json.dumps(result) if result is not None else None, rid),
            )

    def recover(self) -> None:
        for row in self.rows("SELECT * FROM requests WHERE state='dispatching'"):
            self.request_state(row["id"], "uncertain")
            self.event(
                row["session_id"],
                "error",
                {
                    "text": "Engine restarted while sending a message. Check History before retrying; it was not replayed."
                },
            )
        for row in self.rows(
            "SELECT * FROM sessions WHERE status IN ('working','waiting','connecting','transcribing')"
        ):
            self.update_session(row["id"], status="interrupted", turn_id=None)
            self.event(
                row["id"],
                "completed",
                {"status": "interrupted", "text": "Engine restarted; conversation is retained."},
            )
        with self.db:
            self.db.execute("UPDATE questions SET status='expired' WHERE status='pending'")
