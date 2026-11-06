#!/usr/bin/env python3
"""Fail-closed Alembic revision collision audit; never modifies migrations or data."""

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path


def revision_from_source(path: Path) -> str | None:
    """Read a literal revision assignment without importing migration side effects."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revisions = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "revision" for target in targets):
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    raise ValueError(f"{path}: revision must be a literal string")
                revisions.append(value.value)
    if len(revisions) > 1:
        raise ValueError(f"{path}: multiple revision assignments")
    return revisions[0] if revisions else None


def audit(roots: list[Path]) -> dict:
    by_revision: dict[str, list[str]] = defaultdict(list)
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Migration directory missing: {root}")
        for path in sorted(root.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            revision = revision_from_source(path)
            if revision is not None:
                if not revision.strip() or revision != revision.strip():
                    raise ValueError(f"{path}: noncanonical revision")
                by_revision[revision].append(str(path))
    collisions = {
        revision: paths
        for revision, paths in sorted(by_revision.items())
        if len(paths) > 1
    }
    return {
        "safe_to_reconcile_automatically": False,
        "revision_count": len(by_revision),
        "collisions": collisions,
        "collision_free": not bool(collisions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_dirs", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.migration_dirs)
    except (OSError, SyntaxError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["collision_free"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
