#!/usr/bin/env python3
"""Copy this repository's contents to a destination folder.

The destination may already exist (e.g. an existing project root) or not
(it will be created). Files/folders are merged into the destination,
overwriting any same-named files that already exist there.

Usage:
    python scripts/copy_repo.py /path/to/destination
    python scripts/copy_repo.py /path/to/destination --include-git
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    ".DS_Store",
    "node_modules",
    ".venv",
}


def copy_repo(destination: Path, include_git: bool = False) -> None:
    excludes = set(DEFAULT_EXCLUDES)
    if include_git:
        excludes.discard(".git")

    def ignore(dir_path: str, names: list[str]) -> set[str]:
        return {name for name in names if name in excludes}

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT, destination, ignore=ignore, dirs_exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Target folder (created if it doesn't exist)")
    parser.add_argument(
        "--include-git",
        action="store_true",
        help="Also copy the .git directory (excluded by default)",
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if destination == REPO_ROOT:
        sys.exit("Destination cannot be the repo root itself.")

    copy_repo(destination, include_git=args.include_git)
    print(f"Copied {REPO_ROOT} -> {destination}")


if __name__ == "__main__":
    main()
