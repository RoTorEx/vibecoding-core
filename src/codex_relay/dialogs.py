"""Shallow aiogram-dialog navigation. Agent history never lives in a dialog."""

from aiogram.fsm.state import State, StatesGroup
from aiogram_dialog import Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, Column, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.text import Const, Format

from codex_relay.presentation import label


class Screens(StatesGroup):
    deck = State()
    sessions = State()
    projects = State()
    chat = State()
    actions = State()
    settings = State()
    input = State()
    archived = State()
    models = State()
    efforts = State()


def runtime(manager: DialogManager):
    return manager.middleware_data["runtime"]


async def data(dialog_manager: DialogManager, **_) -> dict:
    app = runtime(dialog_manager)
    screen = dialog_manager.current_context().state
    sid = app.store.get("selected")
    session = None
    if sid:
        try:
            session = await app.engine.call(f"/sessions/{sid}")
        except ValueError:
            app.store.set("selected", "")
    value: dict = {"text": "🏠 Codex Relay", "has_selected": bool(session), "session": session, "rows": []}
    if screen == Screens.deck:
        value["text"] += f"\n{app.settings.host_id}\n\nChoose a session or start a new one."
        value["continue_label"] = f"▶️ {session['name'][:45]}" if session else "▶️ Continue"
    elif screen in {Screens.sessions, Screens.archived}:
        archived = screen == Screens.archived
        sessions = await app.engine.call("/sessions" + ("?archived=1" if archived else ""))
        value["rows"] = [(label(s), s["id"]) for s in sessions]
        value["text"] = ("🗃 Archived sessions" if archived else "💬 Sessions") + (
            "\n\nNo sessions yet." if not sessions else ""
        )
    elif screen == Screens.projects:
        projects = await app.engine.call("/projects")
        value["rows"] = [(p["name"], p["id"]) for p in projects]
        value["text"] = "📁 New session\n\nChoose its working directory."
    elif screen in {Screens.chat, Screens.actions} and session:
        siblings = [
            s
            for s in await app.engine.call("/sessions")
            if s["cwd"] == session["cwd"] and s["id"] != sid and s["turn_id"]
        ]
        value["text"] = (
            f"💬 {session['name']}\n{app.settings.host_id} · {session['status']}\n"
            f"{session['cwd']}\nModel: {session['model'] or 'Codex default'} · {session['effort']}"
        )
        if siblings:
            value["text"] += f"\n\nAlso working here: {', '.join(s['name'][:40] for s in siblings)}"
        value["text"] += "\n\nSend text or an image. New messages steer active work."
    elif screen == Screens.settings:
        value["text"] = (
            f"⚙️ Settings\nHost: {app.settings.host_id}\nOwner: {app.settings.allowed_user_id}\n"
            "Full host access · steering enabled\n\nModel settings belong to each session."
        )
    elif screen == Screens.input:
        value["text"] = app.store.get("input_prompt", "Send a value.")
    elif screen == Screens.models:
        models = (await app.engine.call("/models")).get("data", [])
        value["rows"] = [(m.get("displayName") or m["id"], str(i)) for i, m in enumerate(models)]
        app.store.set("model_catalog", __import__("json").dumps(models))
        value["text"] = "Choose a model from this host's live Codex catalog."
    elif screen == Screens.efforts:
        import json

        models = json.loads(app.store.get("model_catalog", "[]"))
        selected = int(app.store.get("model_index", "0"))
        model = models[selected]
        choices = model.get("supportedReasoningEfforts", [])
        value["rows"] = [(x["reasoningEffort"], x["reasoningEffort"]) for x in choices] or [
            ("Apply", "medium")
        ]
        value["text"] = f"{model.get('displayName') or model['id']}\nChoose reasoning effort."
    return value


async def go(manager: DialogManager, screen: State) -> None:
    app = runtime(manager)
    app.store.set("mode", "chat" if screen == Screens.chat else "menu")
    app.store.set("input_action", "")
    await manager.switch_to(screen, show_mode=ShowMode.SEND)


async def deck(c, b, manager):
    await go(manager, Screens.deck)


async def sessions(c, b, manager):
    await go(manager, Screens.sessions)


async def projects(c, b, manager):
    await go(manager, Screens.projects)


async def selected(c, b, manager):
    if runtime(manager).store.get("selected"):
        await go(manager, Screens.chat)
    else:
        await go(manager, Screens.sessions)


async def choose_session(c, widget, manager, item_id):
    app = runtime(manager)
    s = await app.engine.call(f"/sessions/{item_id}")
    if s["archived"]:
        await app.engine.call(f"/sessions/{item_id}/reopen", {})
    app.store.set("selected", item_id)
    await go(manager, Screens.chat)


async def choose_project(c, widget, manager, item_id):
    app = runtime(manager)
    project = next(p for p in await app.engine.call("/projects") if p["id"] == item_id)
    s = await app.engine.call("/sessions", {"cwd": project["path"]})
    app.store.set("selected", s["id"])
    await go(manager, Screens.chat)


async def actions(c, b, manager):
    await go(manager, Screens.actions)


async def settings(c, b, manager):
    await go(manager, Screens.settings)


async def archived(c, b, manager):
    await go(manager, Screens.archived)


async def models(c, b, manager):
    await go(manager, Screens.models)


async def choose_model(c, widget, manager, item_id):
    runtime(manager).store.set("model_index", item_id)
    await go(manager, Screens.efforts)


async def choose_effort(c, widget, manager, item_id):
    import json

    app = runtime(manager)
    catalog = json.loads(app.store.get("model_catalog", "[]"))
    model = catalog[int(app.store.get("model_index", "0"))]
    sid = app.store.get("selected")
    await app.engine.call(
        f"/sessions/{sid}/settings", {"model": model.get("model") or model["id"], "effort": item_id}
    )
    await go(manager, Screens.chat)


async def stop(c, b, manager):
    app = runtime(manager)
    await app.engine.call(f"/sessions/{app.store.get('selected')}/stop", {})
    await c.answer("Stop requested")


async def close_session(c, b, manager):
    app = runtime(manager)
    await app.engine.call(f"/sessions/{app.store.get('selected')}/archive", {})
    app.store.set("selected", "")
    await go(manager, Screens.sessions)


async def history(c, b, manager):
    app = runtime(manager)
    await app.send_history(app.store.get("selected"))


async def prompt(c, b, manager):
    app = runtime(manager)
    choices = {
        "rename": "Send the new session name.",
        "folder": "Send an existing absolute working-directory path.",
        "path": "Send an existing directory path for a new session.",
        "register": "Send a project name and its existing path on separate lines:\nMy Project\n/home/alex/Development/personal/...",
    }
    app.store.set("mode", "input")
    app.store.set("input_action", b.widget_id)
    app.store.set("input_prompt", choices[b.widget_id])
    app.store.set("input_session", app.store.get("selected"))
    await manager.switch_to(Screens.input, show_mode=ShowMode.SEND)


def navigation(back=deck):
    return Row(
        Button(Const("⬅️ Back"), id="back", on_click=back), Button(Const("🏠 Deck"), id="deck", on_click=deck)
    )


def picker(callback, gid):
    return ScrollingGroup(
        Select(
            Format("{item[0]}"), id="pick", items="rows", item_id_getter=lambda x: x[1], on_click=callback
        ),
        id=gid,
        width=1,
        height=6,
        hide_on_single_page=True,
    )


def make_dialog() -> Dialog:
    return Dialog(
        Window(
            Format("{text}"),
            Button(Format("{continue_label}"), id="continue", on_click=selected, when="has_selected"),
            Row(
                Button(Const("💬 Sessions"), id="sessions", on_click=sessions),
                Button(Const("➕ New session"), id="new", on_click=projects),
            ),
            Row(
                Button(Const("📁 Projects"), id="projects", on_click=projects),
                Button(Const("⚙️ Settings"), id="settings", on_click=settings),
            ),
            state=Screens.deck,
        ),
        Window(
            Format("{text}"),
            picker(choose_session, "session_pages"),
            Row(
                Button(Const("➕ New"), id="new", on_click=projects),
                Button(Const("🗃 Archived"), id="archived", on_click=archived),
            ),
            navigation(),
            state=Screens.sessions,
        ),
        Window(
            Format("{text}"),
            picker(choose_session, "archive_pages"),
            navigation(sessions),
            state=Screens.archived,
        ),
        Window(
            Format("{text}"),
            picker(choose_project, "project_pages"),
            Row(
                Button(Const("📂 Other folder"), id="path", on_click=prompt),
                Button(Const("➕ Register"), id="register", on_click=prompt),
            ),
            navigation(),
            state=Screens.projects,
        ),
        Window(
            Format("{text}"),
            Row(
                Button(Const("⏹ Stop"), id="stop", on_click=stop),
                Button(Const("💬 Sessions"), id="sessions", on_click=sessions),
            ),
            Row(
                Button(Const("⋯ Actions"), id="actions", on_click=actions),
                Button(Const("🏠 Deck"), id="deck", on_click=deck),
            ),
            state=Screens.chat,
        ),
        Window(
            Format("{text}"),
            Column(
                Button(Const("✏️ Rename"), id="rename", on_click=prompt),
                Button(Const("📜 History"), id="history", on_click=history),
                Button(Const("🧠 Model / effort"), id="models", on_click=models),
                Button(Const("📂 Change folder"), id="folder", on_click=prompt),
                Button(Const("🗃 Close session"), id="close", on_click=close_session),
            ),
            navigation(selected),
            state=Screens.actions,
        ),
        Window(Format("{text}"), navigation(), state=Screens.settings),
        Window(Format("{text}"), navigation(), state=Screens.input),
        Window(
            Format("{text}"), picker(choose_model, "model_pages"), navigation(actions), state=Screens.models
        ),
        Window(
            Format("{text}"), picker(choose_effort, "effort_pages"), navigation(models), state=Screens.efforts
        ),
        getter=data,
    )


async def open_screen(manager: DialogManager, screen: State) -> None:
    app = runtime(manager)
    app.store.set("mode", "chat" if screen == Screens.chat else "menu")
    app.store.set("input_action", "")
    await manager.start(screen, mode=StartMode.RESET_STACK, show_mode=ShowMode.SEND)
