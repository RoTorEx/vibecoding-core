#!/usr/bin/env python3
"""Repair Core-owned links in the independent workspace repository."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not (root / ".git").exists():
        raise ValueError("Clone RoTorEx/remote-vibecoding for the workspace entrypoint first")
    for name in ["AGENTS.md", "README.md"]:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Restore the workspace-owned entry from its root repository: {path}")
    for name in ["Makefile", "compose.yaml", "workspace.toml", ".env.example"]:
        target = "vibecoding-core/deployment/workspace/" + name
        path = root / name
        if path.is_symlink() and path.readlink() == Path(target):
            continue
        if path.exists() or path.is_symlink():
            raise ValueError(f"Preserve existing workspace entry: {path}")
        path.symlink_to(target)
    for name, target in {"TASK.md": "vibecoding-core/TASK.md", "docs": "vibecoding-core/docs"}.items():
        path = root / name
        if not path.exists() and not path.is_symlink():
            path.symlink_to(target)
    print("Linked workspace entrypoints to their Core owner")


if __name__ == "__main__":
    main()
