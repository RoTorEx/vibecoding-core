#!/usr/bin/env python3
"""Create workspace entrypoints without adding a third Git repository."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    for name in ["README.md", "AGENTS.md", "Makefile", "compose.yaml", "workspace.toml", ".env.example"]:
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
