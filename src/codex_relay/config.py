"""Explicit configuration; tokens never appear in the configuration object."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path


def config_path() -> Path:
    return Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runtime_dir: Path
    development_root: Path
    token_file: Path
    allowed_user_id: int = 0
    host_id: str = "vps"
    bot_username: str = ""
    codex_command: str = "codex"
    model: str | None = None
    effort: str = "medium"

    @property
    def socket(self) -> Path:
        return self.runtime_dir / "engine.sock"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_path()
        values = tomllib.loads(path.read_text()) if path.exists() else {}
        allowed = {f for f in cls.__dataclass_fields__}
        if unknown := set(values) - allowed:
            raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
        data_dir = Path(values.get("data_dir", "~/.local/state/codex-relay")).expanduser()
        kwargs = dict(values)
        kwargs["data_dir"] = data_dir
        kwargs["runtime_dir"] = Path(values.get("runtime_dir", str(data_dir / "run"))).expanduser()
        kwargs["development_root"] = Path(
            values.get("development_root", "~/Development/personal")
        ).expanduser()
        kwargs["token_file"] = Path(values.get("token_file", "~/.config/codex-relay/bot-token")).expanduser()
        kwargs["codex_command"] = values.get(
            "codex_command", shutil.which("codex") or str(Path.home() / ".local/bin/codex")
        )
        if not isinstance(kwargs.get("allowed_user_id", 0), int):
            raise ValueError("allowed_user_id must be a numeric Telegram user ID")
        return cls(**kwargs)

    def prepare(self) -> None:
        for path in [self.data_dir, self.runtime_dir, self.data_dir / "uploads"]:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        if len(os.fsencode(self.socket)) > 100:
            raise ValueError("runtime_dir is too long for a portable Unix socket path")

    def read_token(self) -> str:
        if self.allowed_user_id <= 0:
            raise ValueError("Configure allowed_user_id before starting the bot")
        if self.token_file.stat().st_mode & 0o077:
            raise ValueError("The bot token file must have mode 600")
        token = self.token_file.read_text().strip()
        if ":" not in token or any(c.isspace() for c in token):
            raise ValueError("Invalid bot token file")
        return token
