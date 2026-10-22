import time
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
)
from aiogram.types import Chat, Message, User
from conftest import settle

from codex_relay.bot import BotRuntime, SQLiteFSM, authorized
from codex_relay.presentation import split_text


class TelegramFake(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.counter = 100

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Relay", username="GardenSandbox_bot")
        if isinstance(method, (SendMessage, EditMessageText, SendDocument)):
            self.counter += 1
            return Message(
                message_id=getattr(method, "message_id", None) or self.counter,
                date=datetime.now(UTC),
                chat=Chat(id=42, type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Relay"),
                text=getattr(method, "text", None) or "document",
                reply_markup=getattr(method, "reply_markup", None),
            )
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage, EditMessageReplyMarkup)):
            return True
        raise AssertionError(type(method).__name__)

    async def stream_content(self, *args, **kwargs):
        yield b""


def update(uid=1, text="hello", owner=42, **extra):
    return {
        "update_id": uid,
        "message": {
            "message_id": uid,
            "date": int(time.time()),
            "from": {"id": owner, "is_bot": False, "first_name": "Operator"},
            "chat": {"id": owner, "type": "private"},
            "text": text,
            **extra,
        },
    }


@pytest.fixture
async def app(host):
    settings, engine, native, client = host
    transport = TelegramFake()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=transport)
    app = BotRuntime(settings, bot=bot, engine=client)

    async def throttle():
        pass

    app.throttle = throttle
    yield app, transport, engine, native
    await bot.session.close()
    app.store.close()


def test_unicode_split_is_lossless_and_within_telegram_limit():
    original = "Привет 🚀\n<code>& 🎉 " * 900
    parts = split_text(original)
    assert "".join(parts) == original
    assert all(len(p.encode("utf-16-le")) // 2 <= 3500 for p in parts)


def test_authorization_covers_callbacks_missing_senders_and_groups():
    assert authorized(update(), 42)
    assert not authorized(update(owner=7), 42)
    u = update()
    u["message"]["chat"]["type"] = "group"
    assert not authorized(u, 42)
    c = {"callback_query": {"from": {"id": 42}, "message": {"chat": {"id": 42, "type": "private"}}}}
    assert authorized(c, 42)
    c["callback_query"]["from"]["id"] = 7
    assert not authorized(c, 42)
    assert not authorized({"channel_post": {}}, 42)


async def test_message_target_is_captured_before_switching_and_restart(app, host):
    runtime, transport, engine, native = app
    a = engine.store.create_session(str(host[0].development_root.parent), "A", "medium")
    b = engine.store.create_session(str(host[0].development_root.parent), "B", "medium")
    runtime.store.set("selected", a["id"])
    runtime.store.set("mode", "chat")
    runtime.capture(update(1, "message for A"))
    runtime.store.set("selected", b["id"])
    row = runtime.store.one("SELECT * FROM inbox WHERE id=1")
    await runtime.process_messages([row])
    await settle(engine)
    assert engine.store.request("telegram:1")["session_id"] == a["id"]
    assert engine.store.session(b["id"])["thread_id"] is None
    assert runtime.store.get("offset") == "2"
    assert not runtime.capture(update(1, "message for A"))


async def test_menu_text_does_not_reach_previous_agent(app):
    runtime, transport, engine, native = app
    runtime.store.set("mode", "menu")
    runtime.capture(update(10, "this is not a prompt"))
    await runtime.process_messages([runtime.store.one("SELECT * FROM inbox WHERE id=10")])
    assert not native.calls
    assert any(isinstance(m, SendMessage) and "Choose a session" in m.text for m in transport.calls)


async def test_album_remains_bound_to_first_session(app, host):
    runtime, transport, engine, native = app
    a = engine.store.create_session(str(host[0].development_root.parent), "A", "medium")
    b = engine.store.create_session(str(host[0].development_root.parent), "B", "medium")
    runtime.store.set("mode", "chat")
    runtime.store.set("selected", a["id"])
    first = update(20, caption="look", media_group_id="album")
    first["message"].pop("text")
    first["message"]["photo"] = [{"file_id": "a", "file_unique_id": "a", "width": 5, "height": 5}]
    runtime.capture(first)
    runtime.store.set("selected", b["id"])
    second = update(21, media_group_id="album")
    second["message"].pop("text")
    second["message"]["photo"] = [{"file_id": "b", "file_unique_id": "b", "width": 5, "height": 5}]
    runtime.capture(second)

    async def fake_download(message, sid):
        p = runtime.settings.data_dir / "uploads" / f"{message['message_id']}.png"
        p.write_bytes(b"fixture")
        return str(p)

    runtime.download_image = fake_download
    rows = runtime.store.rows("SELECT * FROM inbox ORDER BY id")
    assert all(r["session_id"] == a["id"] for r in rows)
    await runtime.process_messages(rows)
    await settle(engine)
    turn = next(p for m, p in native.calls if m == "turn/start")
    assert [x["type"] for x in turn["input"]] == ["text", "localImage", "localImage"]
    assert engine.store.session(b["id"])["thread_id"] is None


async def test_real_dialog_deck_and_navigation_do_not_start_native_work(app):
    runtime, transport, engine, native = app
    runtime.capture(update(30, "/menu"))
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=30"))
    messages = [m for m in transport.calls if isinstance(m, SendMessage)]
    assert messages
    markup = messages[-1].reply_markup
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert "💬 Sessions" in texts and "➕ New session" in texts
    assert runtime.store.get("mode") == "menu"
    assert not native.calls


async def test_fsm_survives_new_storage_instance(app):
    from aiogram.fsm.storage.base import StorageKey

    from codex_relay.dialogs import Screens

    runtime, *_ = app
    key = StorageKey(bot_id=123456, chat_id=42, user_id=42)
    a = SQLiteFSM(runtime.store)
    await a.set_state(key, Screens.chat)
    await a.set_data(key, {"stack": {"session": "test"}})
    b = SQLiteFSM(runtime.store)
    assert await b.get_state(key) == Screens.chat.state
    assert await b.get_data(key) == {"stack": {"session": "test"}}


async def test_unauthorized_input_never_enters_durable_inbox(app):
    runtime, *_ = app
    assert not runtime.capture(update(40, "run commands", owner=8))
    assert runtime.store.rows("SELECT * FROM inbox") == []
    assert runtime.store.get("offset") == "41"


async def test_download_rejects_oversized_and_mislabeled_images(app):
    runtime, *_ = app
    with pytest.raises(ValueError, match="20 MB"):
        await runtime.download_image(
            {
                "message_id": 50,
                "document": {"mime_type": "image/png", "file_id": "x", "file_size": 21_000_000},
            },
            "session",
        )

    async def download(file_id, destination):
        destination.write(b"this is not a PNG")

    runtime.bot.download = download
    with pytest.raises(ValueError, match="not a supported image"):
        await runtime.download_image(
            {"message_id": 51, "document": {"mime_type": "image/png", "file_id": "x"}}, "session"
        )


async def test_session_picker_uses_real_dialog_callbacks(app, host):
    runtime, transport, engine, native = app
    target = engine.store.create_session(str(host[0].development_root.parent), "Pick me", "medium")
    runtime.capture(update(70, "/sessions"))
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=70"))
    panel = next(m for m in reversed(transport.calls) if isinstance(m, SendMessage))
    button = next(b for row in panel.reply_markup.inline_keyboard for b in row if "Pick me" in b.text)
    callback = {
        "update_id": 71,
        "callback_query": {
            "id": "cb-71",
            "chat_instance": "test",
            "from": {"id": 42, "is_bot": False, "first_name": "Operator"},
            "data": button.callback_data,
            "message": {
                "message_id": transport.counter,
                "date": int(time.time()),
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 123456, "is_bot": True, "first_name": "Relay"},
                "text": panel.text,
            },
        },
    }
    runtime.capture(callback)
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=71"))
    assert runtime.store.get("selected") == target["id"]
    assert runtime.store.get("mode") == "chat"
    assert not native.calls


async def test_valid_image_download_persists_once_and_keeps_permissions(app):
    runtime, *_ = app
    raw = b"\x89PNG\r\n\x1a\nfixture-image-content"
    calls = []

    async def download(file_id, destination):
        calls.append(file_id)
        destination.write(raw)

    runtime.bot.download = download
    message = {"message_id": 80, "document": {"mime_type": "image/png", "file_id": "native-image"}}
    first = await runtime.download_image(message, "session")
    second = await runtime.download_image(message, "session")
    from pathlib import Path

    assert first == second
    assert Path(first).read_bytes() == raw
    assert Path(first).stat().st_mode & 0o077 == 0
    assert calls == ["native-image"]
