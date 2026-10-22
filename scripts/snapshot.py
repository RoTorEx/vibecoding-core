#!/usr/bin/env python3
"""Publish a private, consistent idle snapshot for the existing backup service."""

import argparse
import contextlib
import fcntl
import hashlib
import os
import subprocess
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    os.umask(0o077)
    config = Path(os.environ.get("CODEX_RELAY_CONFIG", "~/.config/codex-relay/config.toml")).expanduser()
    values = tomllib.loads(config.read_text()) if config.exists() else {}
    data = Path(values.get("data_dir", "~/.local/state/codex-relay")).expanduser()
    output = data / "snapshots"
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (output / "snapshot.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        temporary = output / "next.tar.gz"
        temporary.unlink(missing_ok=True)
        checksum = temporary.with_suffix(".gz.sha256")
        try:
            binary = Path.home() / ".local/share/codex-relay/engine-current/.venv/bin/codex-relay"
            subprocess.run(
                [
                    str(binary),
                    "--config",
                    str(config),
                    "backup",
                    str(temporary),
                    "--include-codex",
                    "--project-sources",
                    "--wait",
                    "0",
                ],
                check=True,
            )
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            checksum.write_text(digest + "  latest.tar.gz\n")
            temporary.replace(output / "latest.tar.gz")
            checksum.replace(output / "latest.tar.gz.sha256")
            print("Private idle snapshot published for off-host backup")
        finally:
            temporary.unlink(missing_ok=True)
            checksum.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                (output / "snapshot.lock").chmod(0o600)


if __name__ == "__main__":
    main()
