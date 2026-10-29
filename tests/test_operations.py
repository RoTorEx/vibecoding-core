import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("workspace_ops", Path(__file__).parents[1] / "scripts/ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


@pytest.fixture
def operations(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = tmp_path / "state"
    (tmp_path / ".env").write_text(
        f"APP_HOME={home}\nAPP_STATE_DIR={state}\nCORE_REVISION=core-old\nBOT_REVISION=bot-old\n"
    )
    operations = ops.Operations(tmp_path)
    monkeypatch.setattr(operations, "cleanup_images", lambda component: None)
    monkeypatch.setattr(operations, "notifier_image", lambda revision: True)
    return operations


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


def test_scheduled_worker_uses_one_stable_source_path(operations, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "run", lambda argv, **kwargs: calls.append(argv))
    operations.schedule_core("a" * 40)
    assert str(operations.root / "vibecoding-core/scripts/ops.py") in calls[0]
    assert not (operations.private.parent.parent / "share/remote-vibecoding/ops").exists()


def test_duplicate_snapshot_defers_and_preserves_previous_copy(operations, capsys):
    operations.api = lambda path: {"accepting": True, "busy": False, "pending_requests": 0}
    output = operations.state / "snapshots"
    output.mkdir(parents=True)
    (output / "latest.tar.gz").write_bytes(b"previous verified copy")
    with (output / "snapshot.lock").open("a") as lock:
        ops.fcntl.flock(lock, ops.fcntl.LOCK_EX | ops.fcntl.LOCK_NB)
        operations.snapshot()
    assert (output / "latest.tar.gz").read_bytes() == b"previous verified copy"
    assert "Snapshot deferred" in capsys.readouterr().out


def test_rollback_rebuild_streams_only_the_requested_git_source(operations, monkeypatch):
    import io
    import subprocess
    import tarfile

    repo = operations.root / "telegram-vibecoding"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "Dockerfile").write_text("FROM scratch\n")
    (repo / "source.txt").write_text("recorded source")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "source.txt").write_text("working changes to preserve")
    operations.values.update(APP_UID="1002", APP_GID="1002")
    original = subprocess.run
    builds = []

    def run(argv, **kwargs):
        if argv[:3] == ["sudo", "-n", "docker"]:
            builds.append((argv, kwargs["input"]))
            return subprocess.CompletedProcess(argv, 0)
        return original(argv, **kwargs)

    monkeypatch.setattr(ops.subprocess, "run", run)
    operations.rebuild("bot", revision)
    assert (repo / "source.txt").read_text() == "working changes to preserve"
    with tarfile.open(fileobj=io.BytesIO(builds[0][1])) as archive:
        assert archive.extractfile("source.txt").read() == b"recorded source"
        assert not any(name.startswith(".git/") for name in archive.getnames())
    assert "remote-vibecoding-bot:" + revision in builds[0][0]


def test_failed_cutover_never_reactivates_interactive_bot(operations):
    calls = []
    operations.notifier_image = lambda revision: revision == "bot-new"
    operations.compose = lambda args, revisions=None, **kwargs: calls.append((args, revisions))
    operations.container_id = lambda component: "unchanged-core"
    operations.wait_ready = lambda *args: (_ for _ in ()).throw(RuntimeError("not ready"))
    with pytest.raises(RuntimeError, match="not ready"):
        operations.activate("bot", "bot-new")
    assert calls == [
        (["up", "--detach", "--no-deps", "--force-recreate", "bot"], {"BOT_REVISION": "bot-new"}),
        (["stop", "bot"], None),
    ]
    assert operations.image_revision("core") == "core-old"


def test_interactive_bot_candidate_is_rejected_before_activation(operations):
    operations.notifier_image = lambda revision: False
    operations.compose = lambda *args, **kwargs: pytest.fail("must not activate")
    with pytest.raises(ValueError, match="notification-only"):
        operations.activate("bot", "interactive-old")
