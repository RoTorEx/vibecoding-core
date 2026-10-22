"""Durable private Telegram transport. Agent execution belongs to Engine."""

import asyncio
import contextlib
import io
import json
import logging
import os
import signal
import time
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramConflictError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from aiogram_dialog import DialogManager, setup_dialogs
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState

from codex_relay.config import Settings
from codex_relay.dialogs import Screens, make_dialog, open_screen
from codex_relay.engine import EngineClient
from codex_relay.presentation import event_text, split_text
from codex_relay.store import BotStore

log = logging.getLogger(__name__)


def authorized(body: dict, owner: int) -> bool:
    event = body.get("message") or body.get("callback_query")
    if not event or event.get("from", {}).get("id") != owner:
        return False
    message = event.get("message", event)
    chat = message.get("chat", {})
    return chat.get("type") == "private" and chat.get("id") == owner


class SQLiteFSM(BaseStorage):
    def __init__(self, store: BotStore):
        self.store = store

    def key(self, key: StorageKey, field: str) -> str:
        return "fsm:" + json.dumps(asdict(key), sort_keys=True) + ":" + field

    async def set_state(self, key: StorageKey, state=None) -> None:
        self.store.set(
            self.key(key, "state"), (state.state or "") if isinstance(state, State) else state or ""
        )

    async def get_state(self, key: StorageKey) -> str | None:
        return self.store.get(self.key(key, "state")) or None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        self.store.set(self.key(key, "data"), json.dumps(dict(data)))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return json.loads(self.store.get(self.key(key, "data"), "{}"))

    async def close(self) -> None:
        pass


class BotRuntime:
    def __init__(self, settings: Settings, bot=None, engine=None):
        self.settings = settings
        settings.prepare()
        self.store = BotStore(settings.data_dir / "bot.db")
        self.bot = bot or Bot(settings.read_token())
        self.engine = engine or EngineClient(settings)
        self.dp = Dispatcher(storage=SQLiteFSM(self.store))
        self.dp["runtime"] = self
        self.last_send = 0.0
        self.send_lock = asyncio.Lock()
        self.ui_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.previews: dict[str, str] = {}
        self._setup()

    def _setup(self):
        controls = Router()

        @controls.message(Command("start", "menu", "sessions", "new", "stop", "help"))
        async def command(message: Message, dialog_manager: DialogManager):
            command = (message.text or "").split()[0].split("@")[0]
            if command == "/stop":
                sid = self.store.get("selected")
                if sid:
                    await self.engine.call(f"/sessions/{sid}/stop", {})
                    await self.send("Stop requested.")
            elif command == "/help":
                await self.send(
                    "Choose a session, then send text or images. New messages steer active work.\n"
                    "/menu leaves the conversation running. /stop interrupts its current turn.\n"
                    "/sessions switches conversations. /new chooses a working directory."
                )
            else:
                screen = {"/sessions": Screens.sessions, "/new": Screens.projects}.get(command, Screens.deck)
                await open_screen(dialog_manager, screen)

        @controls.callback_query(F.data.startswith("open:"))
        async def open_session(callback: CallbackQuery, dialog_manager: DialogManager):
            sid = (callback.data or "").split(":", 1)[1]
            session = await self.engine.call(f"/sessions/{sid}")
            if session["archived"]:
                await callback.answer("This session is archived. Reopen it from Archived.")
                return
            self.store.set("selected", sid)
            await open_screen(dialog_manager, Screens.chat)
            await callback.answer()

        @controls.callback_query(F.data.startswith("answer:"))
        async def answer(callback: CallbackQuery):
            _, qid, question_index, option_index = (callback.data or "").split(":")
            q = await self.question(qid)
            questions = q["payload"].get("questions", [])
            question = questions[int(question_index)]
            option = question["options"][int(option_index)]
            await self.answer_question(q, question["id"], option["label"])
            await callback.answer("Answer recorded")

        @controls.callback_query(F.data.startswith("mcp:"))
        async def answer_mcp(callback: CallbackQuery):
            _, qid, action = (callback.data or "").split(":")
            await self.engine.call(f"/questions/{qid}", {"answers": {"action": action}})
            await callback.answer("Response sent")

        self.dp.include_router(controls)
        self.dp.include_router(make_dialog())
        setup_dialogs(self.dp)

    @staticmethod
    def open_markup(sid: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💬 Open session", callback_data="open:" + sid)]]
        )

    async def throttle(self):
        await asyncio.sleep(max(0, self.last_send + 1.05 - time.monotonic()))
        self.last_send = time.monotonic()

    async def send(self, text: str, markup=None):
        last = None
        async with self.send_lock:
            for part in split_text(text):
                while True:
                    await self.throttle()
                    try:
                        last = await self.bot.send_message(
                            self.settings.allowed_user_id, part, reply_markup=markup, parse_mode=None
                        )
                        break
                    except TelegramRetryAfter as exc:
                        await asyncio.sleep(exc.retry_after)
        return last

    async def send_history(self, sid: str):
        session = await self.engine.call(f"/sessions/{sid}")
        events = await self.engine.call(f"/sessions/{sid}/history")
        text = "\n\n".join(
            f"{'You' if e['kind'] == 'user' else e['kind'].capitalize()}: "
            + (e["payload"].get("text") or json.dumps(e["payload"], ensure_ascii=False))
            for e in events
        )
        if not text:
            await self.send("No retained messages yet.")
            return
        async with self.send_lock:
            await self.throttle()
            await self.bot.send_document(
                self.settings.allowed_user_id,
                BufferedInputFile(text.encode(), filename=f"session-{sid}.txt"),
                caption=session["name"][:1000],
                reply_markup=self.open_markup(sid),
            )

    async def question(self, qid: str) -> dict:
        # Persisted delivery metadata binds a button to its original session.
        sid = self.store.get("question_session:" + qid)
        if not sid:
            raise ValueError("Question no longer exists")
        qs = await self.engine.call(f"/sessions/{sid}/questions")
        q = next((q for q in qs if q["id"] == qid), None)
        if not q:
            raise ValueError("This question is no longer pending")
        return q

    async def answer_question(self, q: dict, key: str, value: str):
        qid = q["id"]
        answers = json.loads(self.store.get("answers:" + qid, "{}"))
        answers[key] = value
        self.store.set("answers:" + qid, json.dumps(answers))
        questions = q["payload"].get("questions", [])
        remaining = [x for x in questions if x["id"] not in answers]
        if remaining:
            await self.send(
                f"Answer recorded. Next: {remaining[0]['question']}", self.open_markup(q["session_id"])
            )
        else:
            await self.engine.call(f"/questions/{qid}", {"answers": answers})

    def capture(self, update: dict):
        if not authorized(update, self.settings.allowed_user_id):
            # Still advance the transport cursor so unauthorized updates do not loop.
            self.store.set("offset", str(update["update_id"] + 1))
            return False
        sid, mode = self.store.get("selected") or None, self.store.get("mode", "menu")
        message = update.get("message", {})
        if group := message.get("media_group_id"):
            first = self.store.one(
                "SELECT session_id,mode FROM inbox WHERE json_extract(body,'$.message.media_group_id')=? ORDER BY id LIMIT 1",
                (group,),
            )
            if first:
                sid, mode = first["session_id"], first["mode"]
        body = {
            **update,
            "_relay": {
                "input_action": self.store.get("input_action"),
                "input_session": self.store.get("input_session"),
            },
        }
        return self.store.accept(update["update_id"], body, sid, mode)

    @staticmethod
    def is_control(body: dict) -> bool:
        return bool(body.get("callback_query")) or (
            body.get("message", {}).get("text", "").split(" ", 1)[0].split("@")[0]
            in {"/start", "/menu", "/sessions", "/new", "/stop", "/help"}
        )

    async def process_control(self, row: dict):
        body = json.loads(row["body"])
        if not authorized(body, self.settings.allowed_user_id):
            self.store.processed(row["id"])
            return
        async with self.ui_lock:
            try:
                await self.dp.feed_update(
                    self.bot,
                    Update.model_validate({k: v for k, v in body.items() if k != "_relay"}),
                    runtime=self,
                )
            except (UnknownIntent, UnknownState):
                await self.send("That menu expired. Use /menu for fresh controls.")
            except (ValueError, IndexError, KeyError) as exc:
                await self.send(str(exc)[:1000] + "\nUse /menu to continue.")
            self.store.processed(row["id"])

    async def process_input(self, row: dict, body: dict):
        message = body.get("message", {})
        text = (message.get("text") or "").strip()
        action = body.get("_relay", {}).get("input_action", "")
        sid = body.get("_relay", {}).get("input_session")
        if not text:
            raise ValueError("Send text for this step, or use /menu to cancel.")
        if action == "rename":
            await self.engine.call(f"/sessions/{sid}/rename", {"name": text})
        elif action == "folder":
            await self.engine.call(f"/sessions/{sid}/settings", {"cwd": text})
        elif action == "path":
            s = await self.engine.call("/sessions", {"cwd": text})
            self.store.set("selected", s["id"])
        elif action == "register":
            parts = text.splitlines()
            if len(parts) != 2:
                raise ValueError("Use two lines: project name, then existing directory path.")
            await self.engine.call("/projects", {"name": parts[0], "path": parts[1]})
        else:
            raise ValueError("That input step expired. Use /menu.")
        self.store.set("mode", "menu")
        self.store.set("input_action", "")
        await self.send(
            "Saved. Use /menu or open the session below.",
            self.open_markup(self.store.get("selected")) if self.store.get("selected") else None,
        )

    async def download_image(self, message: dict, sid: str) -> str | None:
        image = None
        if message.get("photo"):
            image = max(
                message["photo"],
                key=lambda p: (p.get("width", 0) * p.get("height", 0), p.get("file_size", 0)),
            )
        elif message.get("document"):
            image = message["document"]
            if image.get("mime_type") not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                raise ValueError("MVP accepts text and JPEG, PNG, WebP or GIF images. Voice comes later.")
        elif any(k in message for k in ["voice", "audio", "video", "sticker", "animation"]):
            raise ValueError("MVP accepts text and images. Voice and other attachments come later.")
        if image is None:
            return None
        if image.get("file_size", 0) > 20_000_000:
            raise ValueError("Telegram cloud downloads support files up to 20 MB.")
        folder = self.settings.data_dir / "uploads" / sid
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Stable Telegram message identity prevents duplicate downloads across retries.
        existing = [
            p
            for p in folder.glob(str(message["message_id"]) + ".*")
            if p.suffix in {".png", ".jpg", ".gif", ".webp"}
        ]
        if existing:
            return str(existing[0])
        data = io.BytesIO()
        await self.bot.download(image["file_id"], destination=data)
        raw = data.getvalue()
        if len(raw) > 20_000_000:
            raise ValueError("Image exceeds 20 MB.")
        suffix = (
            ".png"
            if raw.startswith(b"\x89PNG\r\n\x1a\n")
            else ".jpg"
            if raw.startswith(b"\xff\xd8\xff")
            else ".gif"
            if raw.startswith((b"GIF87a", b"GIF89a"))
            else ".webp"
            if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
            else None
        )
        if suffix is None:
            raise ValueError("The downloaded file is not a supported image.")
        dest = folder / (str(message["message_id"]) + suffix)
        temp = folder / (str(message["message_id"]) + ".part")
        temp.write_bytes(raw)
        temp.chmod(0o600)
        temp.replace(dest)
        return str(dest)

    async def process_messages(self, rows: list[dict]):
        row = rows[0]
        bodies = [json.loads(r["body"]) for r in rows]
        if not all(authorized(b, self.settings.allowed_user_id) for b in bodies):
            for r in rows:
                self.store.processed(r["id"])
            return
        if row["mode"] == "input":
            await self.process_input(row, bodies[0])
        elif row["mode"] != "chat" or not row["session_id"]:
            await self.send("Choose a session first: /sessions or /new.")
        else:
            sid = row["session_id"]
            messages = [b["message"] for b in bodies]
            text = "\n\n".join(m.get("text") or m.get("caption") or "" for m in messages)
            questions = await self.engine.call(f"/sessions/{sid}/questions")
            if questions and len(messages) == 1 and messages[0].get("text"):
                q = questions[0]
                if q["method"] != "item/tool/requestUserInput":
                    raise ValueError("Use the MCP request buttons to respond.")
                answers = json.loads(self.store.get("answers:" + q["id"], "{}"))
                next_question = next(x for x in q["payload"]["questions"] if x["id"] not in answers)
                await self.answer_question(q, next_question["id"], text)
            else:
                rid = row["request_id"] or f"telegram:{row['id']}"
                if row["payload"]:
                    payload = json.loads(row["payload"])
                else:
                    images = []
                    for message in messages:
                        if image := await self.download_image(message, sid):
                            images.append(image)
                    payload = {"request_id": rid, "session_id": sid, "text": text, "images": images}
                    self.store.prepare_request([r["id"] for r in rows], rid, payload)
                await self.engine.call("/messages", payload)
        for r in rows:
            self.store.processed(r["id"])

    async def inbox_loop(self):
        while not self.stop_event.is_set():
            rows = self.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY id LIMIT 100")
            used: set[int] = set()
            blocked: set[str] = set()
            for row in rows:
                if row["id"] in used or row["session_id"] in blocked:
                    continue
                body = json.loads(row["body"])
                if self.is_control(body) or row["mode"] == "input":
                    # Controls are owned by the polling loop and serialized with dialog input.
                    continue
                group = body.get("message", {}).get("media_group_id")
                batch = (
                    [
                        r
                        for r in rows
                        if group and json.loads(r["body"]).get("message", {}).get("media_group_id") == group
                    ]
                    if group
                    else [row]
                )
                if group and time.time() - max(r["created"] for r in batch) < 1:
                    blocked.add(row["session_id"])
                    continue
                try:
                    await self.process_messages(batch)
                    used.update(r["id"] for r in batch)
                except ValueError as exc:
                    await self.send(
                        str(exc)[:1200], self.open_markup(row["session_id"]) if row["session_id"] else None
                    )
                    for r in batch:
                        self.store.processed(r["id"])
                except Exception as exc:
                    log.warning("Inbox retained for retry: %s", type(exc).__name__)
                    blocked.add(row["session_id"])
            await asyncio.sleep(0.3)

    def queue_question(self, event: dict, session: dict):
        p = event["payload"]
        qid = p["question_id"]
        self.store.set("question_session:" + qid, session["id"])
        text = f"💬 {session['name']}\n\n"
        buttons = []
        if p["method"] == "item/tool/requestUserInput":
            for qi, q in enumerate(p.get("questions", [])):
                text += f"{q.get('header', '')}\n{q['question']}\n"
                for oi, option in enumerate(q.get("options") or []):
                    text += f"• {option['label']}: {option.get('description', '')}\n"
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                text=option["label"][:60], callback_data=f"answer:{qid}:{qi}:{oi}"
                            )
                        ]
                    )
                text += "\n"
            text += "Open this session to type a free-text answer."
        else:
            text += "MCP request:\n" + str(p.get("message") or p.get("url") or p.get("request", {}))
            buttons += [
                [
                    InlineKeyboardButton(text="Accept", callback_data=f"mcp:{qid}:accept"),
                    InlineKeyboardButton(text="Decline", callback_data=f"mcp:{qid}:decline"),
                ]
            ]
        buttons.append([InlineKeyboardButton(text="💬 Open session", callback_data="open:" + session["id"])])
        self.store.queue_event(
            event["id"],
            split_text(text),
            InlineKeyboardMarkup(inline_keyboard=buttons).model_dump(exclude_none=True),
        )

    async def events_loop(self):
        while not self.stop_event.is_set():
            try:
                events = await self.engine.call("/events?after=" + self.store.get("event_cursor", "0"))
                for event in events:
                    sid = event["session_id"]
                    if event["kind"] not in {"message", "error", "completed", "question"}:
                        self.store.queue_event(event["id"], [], None)
                        continue
                    session = await self.engine.call(f"/sessions/{sid}") if sid else None
                    if event["kind"] == "question" and session:
                        self.queue_question(event, session)
                    else:
                        self.store.queue_event(
                            event["id"],
                            split_text(event_text(event, session, self.settings.host_id)),
                            self.open_markup(sid).model_dump(exclude_none=True) if sid else None,
                        )
                    if event["kind"] == "completed" and sid:
                        await self.remove_preview(sid)
            except Exception as exc:
                log.warning("Event poll will retry: %s", type(exc).__name__)
            await asyncio.sleep(0.7)

    async def delivery_loop(self):
        while not self.stop_event.is_set():
            row = self.store.one("SELECT * FROM outbox WHERE status='pending' ORDER BY id LIMIT 1")
            if not row:
                await asyncio.sleep(0.3)
                continue
            try:
                markup = (
                    InlineKeyboardMarkup.model_validate(json.loads(row["markup"])) if row["markup"] else None
                )
                message = await self.send(row["body"], markup)
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE outbox SET status='sent',telegram_id=? WHERE id=?",
                        (message.message_id, row["id"]),
                    )
            except TelegramBadRequest:
                # A malformed/stale keyboard must not prevent delivery of the agent text.
                try:
                    message = await self.send(row["body"])
                    with self.store.db:
                        self.store.db.execute(
                            "UPDATE outbox SET status='sent',telegram_id=? WHERE id=?",
                            (message.message_id, row["id"]),
                        )
                except Exception as exc:
                    log.warning("Delivery retained: %s", type(exc).__name__)
                    await asyncio.sleep(3)
            except Exception as exc:
                log.warning("Delivery retained: %s", type(exc).__name__)
                await asyncio.sleep(3)

    async def remove_preview(self, sid: str):
        key = "preview:" + sid
        mid = self.store.get(key)
        if mid:
            async with self.send_lock:
                await self.throttle()
                with contextlib.suppress(TelegramBadRequest):
                    await self.bot.delete_message(self.settings.allowed_user_id, int(mid))
            self.store.set(key, "")
        self.previews.pop(sid, None)

    async def preview_loop(self):
        while not self.stop_event.is_set():
            try:
                live = await self.engine.call("/live")
                # Render only the currently viewed conversation; other hosts/sessions continue independently.
                sid = self.store.get("selected")
                if self.store.get("mode") == "chat" and sid in live:
                    s = await self.engine.call(f"/sessions/{sid}")
                    p = live[sid]
                    text = f"💬 {s['name']} · {p.get('activity', 'Working')}\n\n" + p.get("text", "")[-1500:]
                    if self.previews.get(sid) != text:
                        key = "preview:" + sid
                        mid = self.store.get(key)
                        async with self.send_lock:
                            await self.throttle()
                            if mid:
                                try:
                                    await self.bot.edit_message_text(
                                        text,
                                        chat_id=self.settings.allowed_user_id,
                                        message_id=int(mid),
                                        parse_mode=None,
                                    )
                                except TelegramBadRequest:
                                    self.store.set(key, "")
                            else:
                                message = await self.bot.send_message(
                                    self.settings.allowed_user_id, text, parse_mode=None
                                )
                                self.store.set(key, str(message.message_id))
                        self.previews[sid] = text
                for preview_row in self.store.rows(
                    "SELECT key,value FROM meta WHERE key LIKE 'preview:%' AND value!=''"
                ):
                    old_sid = preview_row["key"].split(":", 1)[1]
                    if old_sid not in live:
                        await self.remove_preview(old_sid)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                log.warning("Preview deferred: %s", type(exc).__name__)
            await asyncio.sleep(1.5)

    async def poll(self):
        me = await self.bot.get_me()
        if (
            self.settings.bot_username
            and (me.username or "").lower() != self.settings.bot_username.lstrip("@").lower()
        ):
            raise RuntimeError("Configured token belongs to another Telegram bot")
        webhook = await self.bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError(
                "This bot already has a webhook. Resolve the existing consumer before polling."
            )
        await self.engine.call("/health")
        self.store.set("bot_pid", str(os.getpid()))
        log.info("Bot connected: @%s; owner=%s", me.username, self.settings.allowed_user_id)
        while not self.stop_event.is_set():
            try:
                # UI/input operations must finish before a newer selection can overtake them.
                for pending_row in self.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY id"):
                    if self.is_control(json.loads(pending_row["body"])) or pending_row["mode"] == "input":
                        await self.process_navigation(pending_row)
                updates = await self.bot.get_updates(
                    offset=int(self.store.get("offset", "0")),
                    timeout=25,
                    allowed_updates=["message", "callback_query"],
                    request_timeout=35,
                )
                for update in updates:
                    body = update.model_dump(mode="json", exclude_none=True, by_alias=True)
                    if self.capture(body):
                        current_row = self.store.one("SELECT * FROM inbox WHERE id=?", (update.update_id,))
                        if current_row and (self.is_control(body) or current_row["mode"] == "input"):
                            await self.process_navigation(current_row)
            except TelegramConflictError:
                raise RuntimeError(
                    "Another process is polling this dev bot. Stop that consumer before continuing."
                ) from None
            except TelegramNetworkError:
                log.warning("Telegram unavailable; retrying without discarding updates")
                await asyncio.sleep(3)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                log.warning("Polling retained state: %s", type(exc).__name__)
                await asyncio.sleep(3)

    async def process_navigation(self, row: dict):
        if self.is_control(json.loads(row["body"])):
            await self.process_control(row)
        else:
            async with self.ui_lock:
                try:
                    await self.process_messages([row])
                except ValueError as exc:
                    await self.send(str(exc)[:1200] + "\nCorrect the value or use /menu to cancel.")
                    self.store.processed(row["id"])

    async def run(self):
        import fcntl

        lock = (self.settings.runtime_dir / "bot.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Another bot already owns this runtime directory") from None
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)
        tasks = [
            asyncio.create_task(fn())
            for fn in [self.poll, self.inbox_loop, self.events_loop, self.delivery_loop, self.preview_loop]
        ]
        stopped = asyncio.create_task(self.stop_event.wait())
        try:
            done, _ = await asyncio.wait([*tasks, stopped], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopped:
                    await task
        finally:
            for task in [*tasks, stopped]:
                task.cancel()
            await asyncio.gather(*tasks, stopped, return_exceptions=True)
            await self.engine.close()
            await self.bot.session.close()
            self.store.close()
            lock.close()


async def run(settings: Settings):
    await BotRuntime(settings).run()
