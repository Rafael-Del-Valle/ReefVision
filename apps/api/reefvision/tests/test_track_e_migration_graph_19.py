"""Cross-version migration guard: do not silently combine colliding revisions.

This tests declarations without importing migration modules or modifying a DB.
It is deliberately scoped to the migrations in the checked-out branch; it
cannot certify the safety of other branches until they are integrated.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path


def _declarations(path: Path) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    values: dict[str, object] = {}
    for statement in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(statement, ast.Assign):
            names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names, value = [statement.target.id], statement.value
        else:
            continue
        for name in names:
            if name in {"revision", "down_revision", "depends_on"} and value is not None:
                values[name] = ast.literal_eval(value)
    revision = values.get("revision")
    parent = values.get("down_revision")
    assert isinstance(revision, str) and revision, f"Bad revision in {path}"
    assert parent is None or isinstance(parent, (str, tuple)), path
    parents = (parent,) if isinstance(parent, str) else tuple(parent or ())
    assert all(isinstance(item, str) and item for item in parents), path
    dependency = values.get("depends_on")
    assert dependency is None or isinstance(dependency, (str, tuple, list)), path
    dependencies = (dependency,) if isinstance(dependency, str) else tuple(dependency or ())
    assert all(isinstance(item, str) and item for item in dependencies), path
    return revision, parents, dependencies


def _graph_errors(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    owners: dict[str, list[str]] = defaultdict(list)
    edges: dict[str, tuple[str, ...]] = {}
    for path in paths:
        revision, parents, dependencies = _declarations(path)
        if dependencies:
            errors.append(f"nonlinear dependency for {revision}: {', '.join(dependencies)}")
        owners[revision].append(path.name)
        edges[revision] = parents
    for revision, names in owners.items():
        if len(names) != 1:
            errors.append(f"duplicate revision {revision}: {', '.join(names)}")
    for revision, parents in edges.items():
        # Cross-track migration collisions must be resolved by a reviewed
        # linear revision chain, not hidden behind a merge migration.
        if len(parents) > 1:
            errors.append(f"nonlinear merge revision {revision}: {', '.join(parents)}")
        for parent in parents:
            if parent not in owners:
                errors.append(f"missing parent {parent} for {revision}")
    if not errors:
        children = {parent for parents in edges.values() for parent in parents}
        heads = set(edges) - children
        if len(heads) != 1:
            errors.append(f"expected one head, got {sorted(heads)}")
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(current: str) -> None:
            if current in visiting:
                errors.append(f"cycle involving {current}")
                return
            if current in visited:
                return
            visiting.add(current)
            for parent in edges[current]:
                visit(parent)
            visiting.remove(current)
            visited.add(current)

        for start in edges:
            visit(start)
    return sorted(set(errors))


def test_integrated_alembic_migrations_form_one_valid_graph() -> None:
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    paths = sorted(versions.glob("*.py"))
    assert paths, f"Missing migration files: {versions}"
    assert not (errors := _graph_errors(paths)), errors


def test_cross_track_0038_collision_and_missing_parent_are_rejected(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "0037.py"
    science = tmp_path / "0038_science.py"
    review = tmp_path / "0038_review.py"
    baseline.write_text('revision = "0037"\ndown_revision = None\n')
    science.write_text('revision = "0038"\ndown_revision = "0037"\n')
    review.write_text('revision: str = "0038"\ndown_revision = "0037"\n')
    assert any(
        "duplicate revision 0038" in error for error in _graph_errors([baseline, science, review])
    )
    review.write_text('revision = "0039"\ndown_revision = "0038"\n')
    assert _graph_errors([baseline, science, review]) == []
    # Alembic depends_on can conceal a cross-branch edge despite one down_revision.
    review.write_text(
        'revision = "0039"\ndown_revision = "0038"\ndepends_on = "0037"\n'
    )
    assert any(
        "nonlinear dependency for 0039" in error
        for error in _graph_errors([baseline, science, review])
    )
    review.write_text('revision = "0039"\ndown_revision = "missing"\n')
    assert any("missing parent" in error for error in _graph_errors([baseline, science, review]))


def test_cycle_is_rejected_without_loading_migration_code(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text('revision = "a"\ndown_revision = "b"\n')
    b.write_text('revision = "b"\ndown_revision = "a"\n')
    assert any("cycle" in error for error in _graph_errors([a, b]))


def test_cross_track_merge_requires_linear_reconciliation(tmp_path: Path) -> None:
    declarations = {
        "root": None,
        "left": "root",
        "right": "root",
        "merged": ("left", "right"),
    }
    paths = []
    for revision, parent in declarations.items():
        path = tmp_path / f"{revision}.py"
        path.write_text(f"revision = {revision!r}\ndown_revision = {parent!r}\n")
        paths.append(path)
    assert any("nonlinear merge revision merged" in error for error in _graph_errors(paths))
