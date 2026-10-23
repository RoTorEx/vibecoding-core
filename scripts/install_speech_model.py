"""Install pinned multilingual base weights; never send recordings to a model hub."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPOSITORY = "Systran/faster-whisper-base"
REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
MODEL_SHA256 = "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"


def install(destination: Path) -> None:
    os.umask(0o077)
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]:
        path = destination / name
        if not path.exists():
            temp = path.with_suffix(".part")
            with (
                urllib.request.urlopen(
                    f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}", timeout=120
                ) as response,
                temp.open("wb") as output,
            ):
                while block := response.read(1024 * 1024):
                    output.write(block)
            if (
                name == "model.bin"
                and hashlib.file_digest(temp.open("rb"), "sha256").hexdigest() != MODEL_SHA256
            ):
                temp.unlink()
                raise ValueError("Speech model checksum mismatch")
            temp.replace(path)
        with path.open("rb") as source:
            hashes[name] = hashlib.file_digest(source, "sha256").hexdigest()
    if hashes["model.bin"] != MODEL_SHA256:
        raise ValueError("Installed speech model checksum mismatch")
    (destination / "manifest.json").write_text(
        json.dumps({"repository": REPOSITORY, "revision": REVISION, "files": hashes}, indent=2) + "\n"
    )
    print(f"Speech model ready: {destination}")


if __name__ == "__main__":
    install(Path.home() / ".cache/remote-vibecoding/whisper-base")
