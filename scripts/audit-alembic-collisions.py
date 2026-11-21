#!/usr/bin/env python3
"""Read-only, cross-branch Alembic revision collision audit for ReefVision.

Usage (from a checkout with both remote refs fetched):
    python scripts/audit-alembic-collisions.py \
        origin/develop/reefvision-1.1 origin/develop/reefvision-1.6

The output is JSON. Exit 2 means colliding revisions, branch-only revisions,
or invalid branch ancestry require reviewed integration; exit 1 means an unreadable
ref or migration declaration.
No checkout, migrations or writes.
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
DEFAULT_REFS = (
    "origin/develop/reefvision-1.1",
    "origin/develop/reefvision-1.6",
    "origin/fix/reefvision-1.9-pose-planner-20261018",
)


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



def _branch_graph_errors(migrations: list[dict[str, object]]) -> list[str]:
    """Fail closed on invalid migration ancestry within each inspected ref."""
    by_id: dict[str, list[dict[str, object]]] = defaultdict(list)
    for entry in migrations:
        by_id[str(entry["revision"])].append(entry)

    errors: list[str] = []
    parents: dict[str, list[str]] = {}
    for revision, entries in sorted(by_id.items()):
        if len(entries) != 1:
            errors.append(f"duplicate revision {revision} within branch")
        entry = entries[0]
        ancestry = list(entry["down_revision"])
        parents[revision] = ancestry
        if len(ancestry) > 1:
            errors.append(f"nonlinear merge revision {revision}")
        if entry["depends_on"]:
            errors.append(f"nonlinear dependency for {revision}")
        for parent in ancestry:
            if parent not in by_id:
                errors.append(f"missing parent {parent} for {revision}")

    children = {parent for ancestry in parents.values() for parent in ancestry}
    heads = sorted(set(by_id) - children)
    if len(heads) != 1:
        errors.append(f"expected one revision head, got {heads}")

    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(revision: str) -> None:
        if revision in visiting:
            errors.append(f"cycle involving {revision}")
            return
        if revision in visited:
            return
        visiting.add(revision)
        for parent in parents[revision]:
            if parent in parents:
                visit(parent)
        visiting.remove(revision)
        visited.add(revision)

    for revision in sorted(parents):
        visit(revision)
    return sorted(set(errors))


def audit(refs: list[str]) -> dict[str, object]:
    if len(refs) < 2 or len(refs) != len(set(refs)):
        raise ValueError("Provide at least two distinct, locally available Git refs")

    records: dict[str, dict[str, object]] = {}
    by_revision: dict[str, list[dict[str, object]]] = defaultdict(list)
    invalid_branch_graphs: dict[str, list[str]] = {}
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
        graph_errors = _branch_graph_errors(migrations)
        if graph_errors:
            invalid_branch_graphs[ref] = graph_errors

    collisions = []
    for revision, entries in sorted(by_revision.items()):
        # Common ancestor migrations have the same byte identity across refs.
        # Identical revision IDs with different SQL operations are unsafe to
        # combine or interpret from the alembic_version table alone.
        fingerprints = {entry["file_sha256"] for entry in entries}
        if len(fingerprints) > 1 or len({entry["ref"] for entry in entries}) != len(entries):
            collisions.append({"revision": revision, "declarations": entries})
    # A revision present on only some refs must also be reviewed before
    # integrating branches: distinct IDs can form multiple heads without any
    # duplicate-ID collision. Record the missing ref(s) rather than treating
    # that union as a clean, automatically mergeable history.
    branch_only = []
    for revision, entries in sorted(by_revision.items()):
        present = {str(entry["ref"]) for entry in entries}
        if len(present) != len(refs):
            branch_only.append(
                {
                    "revision": revision,
                    "present_in": sorted(present),
                    "absent_in": sorted(set(refs) - present),
                }
            )
    return {
        "schema_version": "reefvision-cross-branch-alembic-audit-0002",
        "scope": MIGRATION_DIR,
        "refs": records,
        "collision_count": len(collisions),
        "collisions": collisions,
        "branch_only_revision_count": len(branch_only),
        "branch_only_revisions": branch_only,
        "invalid_branch_graph_count": len(invalid_branch_graphs),
        "invalid_branch_graphs": invalid_branch_graphs,
        "requires_reviewed_data_preserving_reconciliation": bool(
            collisions or branch_only or invalid_branch_graphs
        ),
    }


def main() -> int:
    refs = sys.argv[1:] or list(DEFAULT_REFS)
    try:
        result = audit(refs)
    except (ValueError, SyntaxError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"error": str(exc), "refs": refs}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["requires_reviewed_data_preserving_reconciliation"] else 0


if __name__ == "__main__":
    sys.exit(main())
