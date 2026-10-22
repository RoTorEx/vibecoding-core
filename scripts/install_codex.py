#!/usr/bin/env python3
"""Install matching official CLI and code-mode host assets with SHA-256 checks."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.163.0")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("This MVP installer supports the existing Linux x86_64 VPS")
    request = urllib.request.Request(
        "https://api.github.com/repos/openai/codex/releases/tags/rust-v" + args.version,
        headers={"User-Agent": "codex-relay-setup"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    target = Path.home() / ".local/bin"
    target.mkdir(parents=True, exist_ok=True)
    scratch = Path.home() / "construction_side/codex-relay"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix="native-install-") as temporary:
        stage = Path(temporary)
        for binary in ["codex", "codex-code-mode-host"]:
            name = binary + "-x86_64-unknown-linux-musl"
            asset = next(a for a in release["assets"] if a["name"] == name + ".tar.gz")
            expected = asset.get("digest", "")
            if not expected.startswith("sha256:"):
                raise RuntimeError("Official asset has no SHA-256 digest")
            archive = stage / (binary + ".tar.gz")
            digest = hashlib.sha256()
            with (
                urllib.request.urlopen(asset["browser_download_url"], timeout=120) as response,
                archive.open("wb") as out,
            ):
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
            if expected != "sha256:" + digest.hexdigest():
                raise RuntimeError("Official asset checksum mismatch")
            with tarfile.open(archive) as tar:
                member = tar.getmember(name)
                if not member.isfile():
                    raise RuntimeError("Expected binary is not a regular file")
                stream = tar.extractfile(member)
                if stream is None:
                    raise RuntimeError("Expected binary is absent")
                (stage / binary).write_bytes(stream.read())
                (stage / binary).chmod(0o755)
        version = subprocess.check_output([str(stage / "codex"), "--version"], text=True).strip()
        if version != "codex-cli " + args.version:
            raise RuntimeError("Staged CLI version differs from the requested version")
        # Validate and stage both before replacing either runtime component.
        for binary in ["codex-code-mode-host", "codex"]:
            os.replace(stage / binary, target / binary)
        print(version + "; matching code-mode host installed; both SHA-256 digests verified")


if __name__ == "__main__":
    main()
