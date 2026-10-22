"""Small transactional stores. No database transaction crosses an await."""

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
            CREATE TABLE IF NOT EXISTS questions(
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                rpc_id TEXT NOT NULL, method TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending');
        """)

    def register_project(self, name: str, path: str) -> dict:
        resolved = Path(path).expanduser().resolve(strict=True)
        if not resolved.is_dir() or not name.strip():
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

    def create_session(self, cwd: str, name: str, effort: str, model: str | None = None) -> dict:
        path = Path(cwd).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Working directory is not a directory")
        sid = identifier()
        now = time.time()
        with self.db:
            self.db.execute(
                """INSERT INTO sessions(id,name,cwd,effort,model,created,updated)
                VALUES(?,?,?,?,?,?,?)""",
                (sid, name.strip() or "New session", str(path), effort, model, now, now),
            )
        return self.session(sid)

    def session(self, sid: str) -> dict:
        value = self.one("SELECT * FROM sessions WHERE id=?", (sid,))
        if value is None:
            raise ValueError("Session not found")
        return value

    def sessions(self, archived: bool = False) -> list[dict]:
        return self.rows("SELECT * FROM sessions WHERE archived=? ORDER BY updated DESC", (int(archived),))

    def update_session(self, sid: str, **values) -> None:
        if set(values) - {"name", "cwd", "thread_id", "turn_id", "status", "archived", "model", "effort"}:
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
                "('user','message','completed','error','question') ORDER BY id DESC LIMIT 200) ORDER BY id",
                (sid,),
            )
        ]

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
        for row in self.rows("SELECT * FROM sessions WHERE status IN ('working','waiting','connecting')"):
            self.update_session(row["id"], status="interrupted", turn_id=None)
            self.event(
                row["id"],
                "completed",
                {"status": "interrupted", "text": "Engine restarted; conversation is retained."},
            )
        with self.db:
            self.db.execute("UPDATE questions SET status='expired' WHERE status='pending'")


class BotStore(Database):
    def __init__(self, path: Path):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox(
                id INTEGER PRIMARY KEY, body TEXT NOT NULL, session_id TEXT, mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', request_id TEXT, payload TEXT,
                error TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL,
                part INTEGER NOT NULL, body TEXT NOT NULL, markup TEXT, status TEXT NOT NULL DEFAULT 'pending',
                telegram_id INTEGER, UNIQUE(event_id,part));
        """)

    def get(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def accept(self, update_id: int, body: dict, sid: str | None, mode: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO inbox(id,body,session_id,mode,created) VALUES(?,?,?,?,?)",
                (update_id, json.dumps(body), sid, mode, time.time()),
            )
            self.db.execute(
                "INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(update_id + 1),),
            )
        return cur.rowcount == 1

    def processed(self, update_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE inbox SET status='done' WHERE id=?", (update_id,))

    def prepare_request(self, update_ids: list[int], rid: str, payload: dict) -> None:
        with self.db:
            self.db.executemany(
                "UPDATE inbox SET request_id=?,payload=? WHERE id=?",
                [(rid, json.dumps(payload), uid) for uid in update_ids],
            )

    def queue_event(self, event_id: int, parts: list[str], markup: dict | None) -> None:
        with self.db:
            for i, body in enumerate(parts):
                self.db.execute(
                    "INSERT OR IGNORE INTO outbox(event_id,part,body,markup) VALUES(?,?,?,?)",
                    (event_id, i, body, json.dumps(markup) if markup and i == len(parts) - 1 else None),
                )
            self.db.execute(
                "INSERT INTO meta VALUES('event_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(event_id),),
            )
