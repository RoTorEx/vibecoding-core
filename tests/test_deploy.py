import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("relay_deploy", Path(__file__).parents[1] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.fixture(autouse=True)
def private_deployment_config(tmp_path, monkeypatch):
    config = tmp_path / "deployment.toml"
    config.write_text(f'data_dir = "{tmp_path / "isolated-state"}"\n')
    monkeypatch.setenv("CODEX_RELAY_CONFIG", str(config))


def test_bot_activation_does_not_restart_or_switch_engine(tmp_path):
    old, new, engine = [tmp_path / x for x in ["old", "new", "engine"]]
    for p in [old, new, engine]:
        p.mkdir()
    (tmp_path / "bot-current").symlink_to(old)
    (tmp_path / "engine-current").symlink_to(engine)
    commands = []
    deploy.activate("bot", new, tmp_path, runner=commands.append, verify=lambda: None)
    assert (tmp_path / "bot-current").resolve() == new
    assert (tmp_path / "bot-previous").resolve() == old
    assert (tmp_path / "engine-current").resolve() == engine
    assert commands == [["sudo", "-n", "systemctl", "restart", "codex-relay-bot"]]


def test_failed_bot_activation_restores_previous_release(tmp_path):
    old, new = [tmp_path / x for x in ["old", "new"]]
    old.mkdir()
    new.mkdir()
    (tmp_path / "bot-current").symlink_to(old)
    commands = []

    def failure():
        raise RuntimeError("New bot did not start")

    with pytest.raises(RuntimeError, match="did not start"):
        deploy.activate("bot", new, tmp_path, runner=commands.append, verify=failure)
    assert (tmp_path / "bot-current").resolve() == old
    assert commands == [["sudo", "-n", "systemctl", "restart", "codex-relay-bot"]] * 2
    assert not (tmp_path / "bot-previous").exists()


def test_ui_schema_transition_and_rollback_preserve_sessions_and_delivery(tmp_path, monkeypatch):
    from codex_relay.store import BotStore

    config = tmp_path / "config.toml"
    data = tmp_path / "state"
    config.write_text(f'data_dir = "{data}"\n')
    monkeypatch.setenv("CODEX_RELAY_CONFIG", str(config))
    store = BotStore(data / "bot.db")
    store.set("selected", "retained-session")
    store.set("fsm:old:state", "Screens:projects")
    store.accept(7, {"message": {"text": "retained request"}}, "retained-session", "chat")
    store.queue_event(8, ["retained answer"], None)
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / ".relay-ui-version").write_text("2\n")
    (tmp_path / "bot-current").symlink_to(old)
    commands = []
    deploy.activate("bot", new, tmp_path, runner=commands.append, verify=lambda: None)
    assert store.get("ui_version") == "2"
    assert store.get("fsm:old:state") == ""
    store.set("fsm:new:state", "Screens:details")
    deploy.activate("bot", old, tmp_path, runner=commands.append, verify=lambda: None)
    assert store.get("ui_version") == "1"
    assert store.get("fsm:new:state") == ""
    assert store.get("selected") == "retained-session"
    assert store.one("SELECT body FROM inbox WHERE id=7")
    assert store.one("SELECT body FROM outbox WHERE event_id=8")["body"] == "retained answer"
    assert commands == [
        ["sudo", "-n", "systemctl", action, "codex-relay-bot"]
        for action in ["stop", "start", "stop", "start"]
    ]
    store.close()
