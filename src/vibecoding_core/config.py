"""Core configuration; host credentials stay in their designated stores."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runtime_dir: Path
    development_root: Path
    host_id: str = "vps"
    codex_command: str = "codex"
    model: str | None = None
    effort: str = "medium"
    inspect_command: list[str] = field(default_factory=list)
    host_root: Path = Path("/")
    private_config_dir: Path = Path("~/.config/remote-vibecoding")

    @property
    def socket(self) -> Path:
        return self.runtime_dir / "engine.sock"

    def host_path(self, path: Path | str) -> Path:
        path = Path(path).expanduser()
        return self.host_root / str(path).lstrip("/") if self.host_root != Path("/") else path

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = (
            path
            or Path(
                os.environ.get("VIBECODING_CORE_CONFIG", "~/.config/remote-vibecoding/core.toml")
            ).expanduser()
        )
        values = tomllib.loads(path.read_text()) if path.exists() else {}
        if unknown := set(values) - set(cls.__dataclass_fields__):
            raise ValueError(f"Unknown Core configuration keys: {', '.join(sorted(unknown))}")
        data = Path(values.pop("data_dir", "~/.local/state/remote-vibecoding")).expanduser()
        runtime = Path(values.pop("runtime_dir", str(data / "run"))).expanduser()
        development = Path(values.pop("development_root", "~/Development/personal")).expanduser()
        for key in ["host_root", "private_config_dir"]:
            if key in values:
                values[key] = Path(values[key]).expanduser()
        values.setdefault("codex_command", shutil.which("codex") or str(Path.home() / ".local/bin/codex"))
        return cls(data_dir=data, runtime_dir=runtime, development_root=development, **values)

    def prepare(self) -> None:
        for path in [self.data_dir, self.runtime_dir, self.data_dir / "uploads"]:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        if len(os.fsencode(self.socket)) > 100:
            raise ValueError("runtime_dir is too long for a portable Unix socket")
