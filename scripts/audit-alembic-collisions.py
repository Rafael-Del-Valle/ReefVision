#!/usr/bin/env python3
"""Read-only, cross-branch Alembic revision collision audit for ReefVision.

Usage (from a checkout with both remote refs fetched):
    python scripts/audit-alembic-collisions.py \
        origin/develop/reefvision-1.1 origin/develop/reefvision-1.6

The output is JSON. Exit 2 means conflicting revision identities; exit 1 means
an unreadable ref or migration declaration. No checkout, migrations or writes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

MIGRATION_DIR = "apps/api/migrations/versions"
DEFAULT_REFS = ("origin/develop/reefvision-1.1", "origin/develop/reefvision-1.6")


def _git(*args: str) -> bytes:
    command = ["git", *args]
    completed = subprocess.run(command, check=True, capture_output=True)
    return completed.stdout


def _declaration(source: bytes, path: str) -> tuple[str, list[str], list[str]]:
    values: dict[str, object] = {}
    for statement in ast.parse(source.decode("utf-8"), filename=path).body:
        if isinstance(statement, ast.Assign):
            names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names = [statement.target.id]
            value = statement.value
        else:
            continue
        for name in names:
            if name in {"revision", "down_revision", "depends_on"} and value is not None:
                values[name] = ast.literal_eval(value)

    def links(name: str) -> list[str]:
        value = values.get(name)
        if value is None:
            return []
        candidates = [value] if isinstance(value, str) else value
        if not isinstance(candidates, (tuple, list)) or any(
            not isinstance(item, str) or not item for item in candidates
        ):
            raise ValueError(f"Invalid Alembic {name}: {path}")
        return list(candidates)

    revision = values.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError(f"Invalid Alembic revision: {path}")
    return revision, links("down_revision"), links("depends_on")


def audit(refs: list[str]) -> dict[str, object]:
    if len(refs) < 2 or len(refs) != len(set(refs)):
        raise ValueError("Provide at least two distinct, locally available Git refs")

    records: dict[str, dict[str, object]] = {}
    by_revision: dict[str, list[dict[str, object]]] = defaultdict(list)
    for ref in refs:
        # Resolve once: a branch advancing during inspection must not mix files
        # from multiple commits in a supposedly reproducible migration report.
        commit = _git("rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
        paths = _git("ls-tree", "-r", "--name-only", commit, MIGRATION_DIR).decode().splitlines()
        migrations: list[dict[str, object]] = []
        for path in paths:
            if not path.endswith(".py") or Path(path).name == "__init__.py":
                continue
            source = _git("show", f"{commit}:{path}")
            revision, parents, dependencies = _declaration(source, path)
            entry = {
                "ref": ref,
                "commit": commit,
                "path": path,
                "revision": revision,
                "down_revision": parents,
                "depends_on": dependencies,
                "file_sha256": hashlib.sha256(source).hexdigest(),
            }
            migrations.append(entry)
            by_revision[revision].append(entry)
        if not migrations:
            raise ValueError(f"No Alembic migration files found at {ref}")
        records[ref] = {"commit": commit, "migration_count": len(migrations)}

    collisions = []
    for revision, entries in sorted(by_revision.items()):
        # Common ancestor migrations have the same byte identity across refs.
        # Identical revision IDs with different SQL operations are unsafe to
        # combine or interpret from the alembic_version table alone.
        fingerprints = {entry["file_sha256"] for entry in entries}
        if len(fingerprints) > 1 or len({entry["ref"] for entry in entries}) != len(entries):
            collisions.append({"revision": revision, "declarations": entries})
    return {
        "schema_version": "reefvision-cross-branch-alembic-audit-0001",
        "scope": MIGRATION_DIR,
        "refs": records,
        "collision_count": len(collisions),
        "collisions": collisions,
        "requires_reviewed_data_preserving_reconciliation": bool(collisions),
    }


def main() -> int:
    refs = sys.argv[1:] or list(DEFAULT_REFS)
    try:
        result = audit(refs)
    except (ValueError, SyntaxError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"error": str(exc), "refs": refs}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["collision_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
