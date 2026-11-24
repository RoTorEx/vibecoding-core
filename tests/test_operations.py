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
        f"APP_HOME={home}\nAPP_STATE_DIR={state}\nREMOTE_VIBECODING_ROOT={tmp_path}\nCORE_REVISION=core-old\nBOT_REVISION=bot-old\n"
    )
    operations = ops.Operations(tmp_path)
    monkeypatch.setattr(operations, "cleanup_images", lambda component: None)
    monkeypatch.setattr(operations, "notifier_image", lambda revision: True)
    return operations


def test_source_compose_uses_the_core_manifest(operations, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "run", lambda argv, **kwargs: calls.append(argv))

    operations.compose(["config", "--quiet"])

    argv = calls[0]
    assert Path(argv[argv.index("--file") + 1]) == (
        operations.root / "vibecoding-core/deployment/workspace/compose.yaml"
    )
    assert Path(argv[argv.index("--project-directory") + 1]) == operations.root


def test_bot_activation_belongs_to_independent_notifier(operations):
    operations.compose = lambda *args, **kwargs: pytest.fail("must not touch shared containers")
    with pytest.raises(ValueError, match="independently deployed"):
        operations.activate("bot", "bot-new")
    with pytest.raises(ValueError, match="independently deployed"):
        operations.build("bot")
    assert operations.image_revision("core") == "core-old"
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


def test_scheduled_worker_uses_installed_operator_path(operations, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "run", lambda argv, **kwargs: calls.append(argv))
    worker = Path("/srv/remote-vibecoding/runtime/core/ops.py")
    monkeypatch.setattr(ops, "__file__", str(worker))
    operations.schedule_core("a" * 40)
    assert str(worker) in calls[0]
    assert not (operations.private.parent.parent / "share/remote-vibecoding/ops").exists()


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


def test_workspace_startup_owns_only_core(operations):
    calls = []
    operations.compose = lambda args, revisions=None, **kwargs: calls.append(args)
    operations.wait_ready = lambda component, revision: calls.append((component, revision))
    operations.notifier_image = lambda revision: pytest.fail("must not inspect or start old notifier")
    operations.up()
    assert calls == [["up", "--detach"], ("core", "core-old")]
    manifest = (Path(__file__).parents[1] / "deployment/workspace/compose.yaml").read_text()
    assert "  bot:" not in manifest


@pytest.mark.parametrize("fail_candidate", [False, True, "metadata"])
def test_web_activation_and_failure_recovery_leave_core_and_bot_unchanged(
    operations, monkeypatch, fail_candidate
):
    import json
    from types import SimpleNamespace

    old = "ghcr.io/strelkov-inc/web-vibecoding:v0.1.16"
    candidate = "ghcr.io/strelkov-inc/web-vibecoding:v0.1.17"
    values = ops.read_env(operations.env_file)
    values["WEB_VIBECODING_IMAGE"] = old
    operations.env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    calls = []
    operations.compose = lambda args, revisions=None, **kwargs: calls.append((args, revisions))
    operations.container_id = lambda component: "stable-core-instance"
    operations.api = lambda path: {"media_read": True}
    monkeypatch.setattr(ops.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=3))

    def command(argv, **kwargs):
        labels = {
            "org.opencontainers.image.title": "web-vibecoding",
            "org.opencontainers.image.version": "0.1.17",
            "org.opencontainers.image.revision": "a" * 40,
        }
        return SimpleNamespace(stdout=json.dumps(labels))

    monkeypatch.setattr(ops, "run", command)

    def ready(component, revision):
        if fail_candidate is True and revision == "0.1.17":
            raise RuntimeError("candidate listener unavailable")

    operations.wait_ready = ready
    if fail_candidate == "metadata":
        original = ops.atomic_text
        failed = False

        def write(path, content, mode=0o600):
            nonlocal failed
            if path.name == "deployment.json" and not failed:
                failed = True
                raise RuntimeError("candidate metadata unavailable")
            original(path, content, mode)

        monkeypatch.setattr(ops, "atomic_text", write)
    if fail_candidate:
        with pytest.raises(RuntimeError, match="unavailable"):
            operations.deploy_web(candidate)
        assert calls[-1] == (
            ["up", "--detach", "--no-deps", "--force-recreate", "web"],
            {"WEB_VIBECODING_IMAGE": old},
        )
        assert ops.read_env(operations.env_file)["WEB_VIBECODING_IMAGE"] == old
    else:
        operations.deploy_web(candidate)
        assert ops.read_env(operations.env_file)["WEB_VIBECODING_IMAGE"] == candidate
    assert all(args[-1] == "web" for args, _ in calls)
    assert all("--no-deps" in args for args, _ in calls if args[0] == "up")
    assert operations.image_revision("core") == "core-old"
    assert operations.image_revision("bot") == "bot-old"
