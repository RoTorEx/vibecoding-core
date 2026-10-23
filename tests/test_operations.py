import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("workspace_ops", Path(__file__).parents[1] / "scripts/ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


@pytest.fixture
def operations(tmp_path):
    home = tmp_path / "home"
    state = tmp_path / "state"
    (tmp_path / ".env").write_text(
        f"APP_HOME={home}\nAPP_STATE_DIR={state}\nCORE_REVISION=core-old\nBOT_REVISION=bot-old\n"
    )
    return ops.Operations(tmp_path)


def test_bot_update_recreates_only_bot_and_keeps_core_identity(operations):
    calls = []
    operations.compose = lambda args, revisions=None, **kwargs: calls.append((args, revisions))
    operations.container_id = lambda component: "unchanged-core"
    operations.wait_ready = lambda component, revision: None
    operations.activate("bot", "bot-new")
    assert calls == [
        (["up", "--detach", "--no-deps", "--force-recreate", "bot"], {"BOT_REVISION": "bot-new"})
    ]
    assert operations.image_revision("core") == "core-old"
    assert operations.image_revision("bot") == "bot-new"


def test_failed_bot_update_restores_previous_image_without_switching_core(operations):
    calls = []
    operations.compose = lambda args, revisions=None, **kwargs: calls.append((args, revisions))
    operations.container_id = lambda component: "unchanged-core"

    def ready(component, revision):
        if revision == "bot-new":
            raise RuntimeError("new image is not ready")

    operations.wait_ready = ready
    with pytest.raises(RuntimeError, match="not ready"):
        operations.activate("bot", "bot-new")
    assert [r["BOT_REVISION"] for _, r in calls] == ["bot-new", "bot-old"]
    assert all(args[-1] == "bot" and "--no-deps" in args for args, _ in calls)
    assert operations.image_revision("bot") == "bot-old"


def test_core_update_waits_for_active_work_then_releases_drain(operations, monkeypatch):
    calls = []
    health = iter(
        [
            {"accepting": True},
            {"busy": True, "pending_requests": 1},
            {"busy": False, "pending_requests": 0},
        ]
    )

    def api(path, body=None):
        calls.append((path, body))
        return next(health) if path == "/health" else {}

    operations.api = api
    operations.activate = lambda component, revision: calls.append(("activate", (component, revision)))
    monkeypatch.setattr(ops.time, "sleep", lambda _: None)
    operations.apply_core("core-new")
    assert calls.index(("activate", ("core", "core-new"))) > calls.index(("/drain", {"enabled": True}))
    assert calls[-1] == ("/drain", {"enabled": False})
