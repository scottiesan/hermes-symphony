#!/usr/bin/env python3
"""Install the Hermes Symphony skill bundle into a Hermes skills directory."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = REPO_ROOT / ".hermes" / "skills" / "hermes-symphony"


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()


def read_frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"{skill_file} is missing YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{skill_file} frontmatter is not closed")
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        values[key] = value.strip().strip('"').strip("'")
    if not values.get("name") or not values.get("description"):
        raise ValueError("SKILL.md frontmatter must include name and description")
    return values


def resolve_destination(args: argparse.Namespace, skill_name: str) -> Path:
    if args.dest_dir:
        return Path(args.dest_dir).expanduser().resolve() / skill_name
    if args.profile:
        category = args.category or "orchestration"
        return (
            Path.home()
            / ".hermes"
            / "profiles"
            / args.profile
            / "skills"
            / category
            / skill_name
        ).resolve()
    return (hermes_home() / "skills" / skill_name).resolve()


def install(source: Path, dest: Path, overwrite: bool, dry_run: bool) -> tuple[Path, Path | None]:
    if not source.exists():
        raise FileNotFoundError(f"source skill not found: {source}")
    backup = None
    if dest.exists():
        if not overwrite:
            raise FileExistsError(f"{dest} already exists; pass --overwrite to replace it")
        backup = dest.with_name(dest.name + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S"))
    if dry_run:
        return dest, backup
    dest.parent.mkdir(parents=True, exist_ok=True)
    if backup is not None:
        shutil.move(str(dest), str(backup))
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest, backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Hermes Symphony skill bundle")
    parser.add_argument("--source", default=str(SOURCE_SKILL), help="source skill directory")
    parser.add_argument("--dest-dir", help="skills directory to install into")
    parser.add_argument("--profile", help="Hermes profile name, for ~/.hermes/profiles/<profile>/skills/<category>")
    parser.add_argument("--category", default="orchestration", help="profile skill category")
    parser.add_argument("--name", help="override installed skill folder name")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing install with a timestamped backup")
    parser.add_argument("--dry-run", action="store_true", help="validate and print planned install without writing")
    args = parser.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    metadata = read_frontmatter(source / "SKILL.md")
    skill_name = args.name or metadata["name"]
    dest = resolve_destination(args, skill_name)
    installed, backup = install(source, dest, args.overwrite, args.dry_run)

    mode = "dry-run" if args.dry_run else "installed"
    print(f"{mode}: {source} -> {installed}")
    if backup:
        print(f"backup: {backup}")
    print("restart Hermes to load the skill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
