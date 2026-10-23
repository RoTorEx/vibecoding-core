import subprocess
import sys
from pathlib import Path


def test_link_repair_preserves_root_owned_router_and_readme(tmp_path):
    (tmp_path / ".git").mkdir()
    agents = tmp_path / "AGENTS.md"
    readme = tmp_path / "README.md"
    agents.write_text("root-owned router")
    readme.write_text("root-owned instructions")
    script = Path(__file__).parents[1] / "scripts/link_workspace.py"
    for _ in range(2):
        subprocess.run([sys.executable, str(script), str(tmp_path)], check=True, capture_output=True)
    assert agents.read_text() == "root-owned router" and not agents.is_symlink()
    assert readme.read_text() == "root-owned instructions" and not readme.is_symlink()
    assert (tmp_path / "compose.yaml").readlink() == Path("vibecoding-core/deployment/workspace/compose.yaml")
