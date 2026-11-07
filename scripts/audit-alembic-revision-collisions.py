#!/usr/bin/env python3
"""Fail-closed Alembic revision collision audit; never modifies migrations or data."""

import argparse
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def revision_from_source(path: Path) -> str | None:
    """Read a literal revision assignment without importing migration side effects."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revisions = []
    for node in tree.body:
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
        ):
            raise ValueError(f"{path}: augmented revision assignment is not permitted")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(name, ast.Name) and name.id == "revision"
                for target in targets
                for name in ast.walk(target)
            ):
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    raise ValueError(f"{path}: revision must be a literal string")
                revisions.append(value.value)
    # Nested writes can change the effective revision at import time. Never
    # execute migrations to discover that value; reject ambiguous source.
    for statement in ast.walk(tree):
        if statement in tree.body:
            continue
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(
                isinstance(name, ast.Name) and name.id == "revision"
                for target in targets
                for name in ast.walk(target)
            ):
                raise ValueError(f"{path}: nested revision assignment is not permitted")
    if len(revisions) > 1:
        raise ValueError(f"{path}: multiple revision assignments")
    return revisions[0] if revisions else None


def audit(roots: list[Path]) -> dict:
    by_revision: dict[str, list[str]] = defaultdict(list)
    source_sha256: dict[str, str] = {}
    migration_files = 0
    seen_roots: set[Path] = set()
    for root in roots:
        # A repeated directory must not manufacture a revision collision.
        # Check each path component before resolving so symlinked ancestors
        # cannot silently redirect the audit outside the requested tree.
        if any(part.is_symlink() for part in (root, *root.parents)):
            raise ValueError(f"Migration directory has a symbolic-link ancestor: {root}")
        canonical_root = root.resolve(strict=False)
        if canonical_root in seen_roots:
            raise ValueError(f"Migration directory specified more than once: {root}")
        if any(
            canonical_root in previous.parents or previous in canonical_root.parents
            for previous in seen_roots
        ):
            raise ValueError(f"Migration directories overlap: {root}")
        seen_roots.add(canonical_root)
        if not root.is_dir():
            raise ValueError(f"Migration directory missing: {root}")
        if root.is_symlink():
            raise ValueError(f"Migration directory is a symbolic link: {root}")
        # rglob may silently omit symlinked directories; fail closed rather than
        # reporting a misleading collision-free audit of an incomplete tree.
        for entry in root.rglob("*"):
            if entry.is_symlink():
                raise ValueError(f"Migration tree contains a symbolic link: {entry}")
        for path in sorted(root.rglob("*.py")):
            if path.is_symlink():
                raise ValueError(f"Migration file is a symbolic link: {path}")
            if path.name == "__init__.py":
                continue
            migration_files += 1
            revision = revision_from_source(path)
            if revision is None:
                raise ValueError(f"{path}: missing literal revision assignment")
            if not revision.strip() or revision != revision.strip():
                raise ValueError(f"{path}: noncanonical revision")
            by_revision[revision].append(str(path))
            source_sha256[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if migration_files == 0:
        raise ValueError("No migration revision files found")
    collisions = {
        revision: paths for revision, paths in sorted(by_revision.items()) if len(paths) > 1
    }
    return {
        "safe_to_reconcile_automatically": False,
        "revision_count": len(by_revision),
        "collisions": collisions,
        "collision_source_sha256": {
            revision: {path: source_sha256[path] for path in paths}
            for revision, paths in collisions.items()
        },
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
