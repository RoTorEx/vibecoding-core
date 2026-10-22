import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("relay_deploy", Path(__file__).parents[1] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


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
