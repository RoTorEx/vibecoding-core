import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path


async def test_remote_path_inspection_uses_host_canonical_path_without_container_directory(host):
    settings, engine, native, client = host
    program = (
        "import json,sys; request=json.load(sys.stdin); "
        "print(json.dumps({'path':'/host-only/canonical','disk_free':10,'disk_total':20}))"
    )
    engine.settings = replace(settings, inspect_command=[sys.executable, "-c", program])
    project = await client.call("/projects", {"name": "Host project", "path": "/host-only/input"})
    assert project["path"] == "/host-only/canonical"
    session = await client.call("/sessions", {"cwd": "/host-only/input"})
    assert session["cwd"] == "/host-only/canonical"
    details = await client.call(f"/sessions/{session['id']}/details")
    assert details["disk_free"] == 10 and details["disk_total"] == 20


def test_forced_executor_inspects_paths_and_rejects_shell_commands(tmp_path):
    script = Path(__file__).parents[1] / "scripts/host_executor.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"path": str(tmp_path)}),
        env={**os.environ, "SSH_ORIGINAL_COMMAND": "inspect-path"},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout)["path"] == str(tmp_path)
    marker = tmp_path / "must-not-exist"
    result = subprocess.run(
        [sys.executable, str(script)],
        env={**os.environ, "SSH_ORIGINAL_COMMAND": f"touch {marker}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1 and not marker.exists()
