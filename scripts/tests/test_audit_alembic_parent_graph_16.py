"""Read-only, branch-isolated Alembic parent-graph regression checks for Track D."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "audit-alembic-revision-collisions.py"


def _module():
    spec = importlib.util.spec_from_file_location("alembic_collision_graph_16", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration(root: Path, name: str, revision: str, parent_source: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(
        f'revision: str = "{revision}"\ndown_revision: str | None = {parent_source}\n',
        encoding="utf-8",
    )
    return path


def test_linear_parent_dag_remains_read_only(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    paths = [
        _migration(root, "0001.py", "0001", "None"),
        _migration(root, "0002.py", "0002", '"0001"'),
        _migration(root, "0003.py", "0003", '"0002"'),
    ]
    before = [path.read_bytes() for path in paths]
    report = _module().audit([root], verify_parent_graph=True)
    assert report["collision_free"] is True
    assert report["parent_graph_consistent"] is True
    assert report["safe_to_reconcile_automatically"] is False
    assert report["parent_graphs"][str(root)] == {
        "consistent": True,
        "root_revisions": ["0001"],
        "head_revisions": ["0003"],
        "missing_parent_revisions": [],
        "cycle_revisions": [],
        "duplicate_revision_ids": [],
    }
    assert [path.read_bytes() for path in paths] == before


def test_valid_explicit_merge_has_single_head(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    _migration(root, "root.py", "root", "None")
    _migration(root, "science.py", "science", '"root"')
    _migration(root, "review.py", "review", '"root"')
    _migration(root, "merge.py", "merge", '("science", "review")')
    graph = _module().audit([root], verify_parent_graph=True)["parent_graphs"][str(root)]
    assert graph["consistent"] is True
    assert graph["head_revisions"] == ["merge"]


@pytest.mark.parametrize(
    ("parents", "expected_key", "expected"),
    [
        (("missing",), "missing_parent_revisions", ["missing"]),
        (("0001",), "head_revisions", ["0002", "0003"]),
    ],
)
def test_missing_parent_or_unmerged_heads_fail_closed(
    tmp_path: Path,
    parents: tuple[str, ...],
    expected_key: str,
    expected: list[str],
) -> None:
    root = tmp_path / "versions"
    _migration(root, "0001.py", "0001", "None")
    _migration(root, "0002.py", "0002", f'"{parents[0]}"')
    if expected_key == "head_revisions":
        _migration(root, "0003.py", "0003", '"0001"')
    report = _module().audit([root], verify_parent_graph=True)
    assert report["parent_graph_consistent"] is False
    assert report["parent_graphs"][str(root)][expected_key] == expected
    assert report["safe_to_reconcile_automatically"] is False


def test_cycle_refused_without_running_migration(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    _migration(root, "a.py", "a", '"b"')
    _migration(root, "b.py", "b", '"a"')
    graph = _module().audit([root], verify_parent_graph=True)["parent_graphs"][str(root)]
    assert graph["consistent"] is False
    assert graph["cycle_revisions"] == ["a", "b"]


@pytest.mark.parametrize(
    "parent_source",
    [
        "compute_parent()",
        '" 0001"',
        '("0001", "0001")',
        '("0001", compute_parent())',
        "[]",
    ],
)
def test_dynamic_or_noncanonical_parents_are_refused(tmp_path: Path, parent_source: str) -> None:
    root = tmp_path / "versions"
    _migration(root, "0001.py", "0001", "None")
    file = _migration(root, "0002.py", "0002", parent_source)
    before = file.read_bytes()
    with pytest.raises(ValueError):
        _module().audit([root], verify_parent_graph=True)
    assert file.read_bytes() == before


@pytest.mark.parametrize(
    "extra",
    [
        'if True:\n    down_revision = "forged"\n',
        'down_revision += "forged"\n',
        "del down_revision\n",
        'for down_revision in ("forged",):\n    pass\n',
        "import json as down_revision\n",
        'def down_revision():\n    return "forged"\n',
    ],
)
def test_runtime_rebinding_is_never_evaluated(tmp_path: Path, extra: str) -> None:
    root = tmp_path / "versions"
    file = _migration(root, "0001.py", "0001", "None")
    file.write_text(file.read_text(encoding="utf-8") + extra, encoding="utf-8")
    before = file.read_bytes()
    with pytest.raises(ValueError, match="down_revision"):
        _module().audit([root], verify_parent_graph=True)
    assert file.read_bytes() == before


def test_optional_graph_checks_leave_legacy_output_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    _migration(root, "0001.py", "0001", "None")
    _migration(root, "0002.py", "0002", '"missing"')
    report = _module().audit([root])
    assert report["collision_free"] is True
    assert "parent_graphs" not in report
    assert "parent_graph_consistent" not in report


def test_graphs_are_checked_individually_before_cross_branch_reconciliation(
    tmp_path: Path,
) -> None:
    scientific, review = tmp_path / "scientific", tmp_path / "review"
    for root in (scientific, review):
        _migration(root, "0001.py", "0001", "None")
    _migration(scientific, "0038.py", "0038", '"0001"')
    _migration(review, "0038_review.py", "0038", '"0001"')
    report = _module().audit([scientific, review], verify_parent_graph=True)
    assert report["parent_graph_consistent"] is True
    assert report["collision_free"] is False
    assert report["collisions"]["0038"]
    assert report["safe_to_reconcile_automatically"] is False


def test_cli_exits_nonzero_on_disconnected_parent_graph(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    _migration(root, "0001.py", "0001", "None")
    file = _migration(root, "0038.py", "0038", '"missing"')
    before = file.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-parent-graph", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["collision_free"] is True
    assert report["parent_graph_consistent"] is False
    assert report["parent_graphs"][str(root)]["missing_parent_revisions"] == ["missing"]
    assert file.read_bytes() == before


@pytest.mark.parametrize(
    "hidden_source",
    ["nested/0037.py", "nested/deeper/0037.py", ".#0037.py", "__init__0037.py"],
)
def test_strict_graph_refuses_sources_not_discovered_by_packaged_alembic(
    tmp_path: Path, hidden_source: str
) -> None:
    root = tmp_path / "versions"
    parent = _migration(root / Path(hidden_source).parent, Path(hidden_source).name, "0037", "None")
    child = _migration(root, "0038.py", "0038", '"0037"')
    before = {path: path.read_bytes() for path in (parent, child)}

    legacy = _module().audit([root])
    assert legacy["revision_count"] == 2
    assert legacy["collision_free"] is True
    assert legacy["safe_to_reconcile_automatically"] is False

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-parent-graph", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unsupported strict graph migration source location or name" in result.stderr
    assert not result.stdout
    assert {path: path.read_bytes() for path in before} == before


def test_strict_flat_graph_permits_package_marker_and_bytecode_cache(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    paths = [
        _migration(root, "0037.py", "0037", "None"),
        _migration(root, "0038.py", "0038", '"0037"'),
    ]
    marker = root / "__init__.py"
    marker.write_bytes(b"")
    cache = root / "__pycache__"
    cache.mkdir()
    bytecode = cache / "0037.pyc"
    bytecode.write_bytes(b"ignored cache")
    before = {path: path.read_bytes() for path in [*paths, marker, bytecode]}
    report = _module().audit([root], verify_parent_graph=True)
    assert report["revision_count"] == 2
    assert report["parent_graph_consistent"] is True
    assert report["parent_graphs"][str(root)]["head_revisions"] == ["0038"]
    assert report["safe_to_reconcile_automatically"] is False
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    ("field", "literal", "extra"),
    [
        ("down_revision", '["0037"]', 'down_revision.append("missing")'),
        ("down_revision", '["0037"]', 'down_revision[0] = "missing"'),
        ("down_revision", '["0037"]', "del down_revision[0]"),
        ("down_revision", '["0037"]', 'alias = down_revision\nalias[:] = ["missing"]'),
        (
            "down_revision",
            '["0037"]',
            'def mutate(links):\n    links.append("missing")\nmutate(down_revision)',
        ),
        ("down_revision", '["0037"]', 'down_revision.extend(["missing"])'),
        ("depends_on", "None", "alias = depends_on"),
        ("branch_labels", "None", "alias = branch_labels"),
    ],
)
def test_strict_graph_refuses_executable_metadata_references(
    tmp_path: Path, field: str, literal: str, extra: str
) -> None:
    root = tmp_path / "versions"
    parent = _migration(root, "0037.py", "0037", "None")
    parent_literal = literal if field == "down_revision" else '"0037"'
    child = _migration(root, "0038.py", "0038", parent_literal)
    declaration = "" if field == "down_revision" else f"{field} = {literal}\n"
    child.write_text(
        child.read_text(encoding="utf-8") + declaration + extra + "\n", encoding="utf-8"
    )
    before = {path: path.read_bytes() for path in (parent, child)}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-parent-graph", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert field in result.stderr
    assert not result.stdout
    assert _module().audit([root])["collision_free"] is True
    assert {path: path.read_bytes() for path in before} == before


def test_strict_graph_accepts_unmodified_literal_parent_list(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    _migration(root, "0037.py", "0037", "None")
    _migration(root, "0038.py", "0038", '["0037"]')
    report = _module().audit([root], verify_parent_graph=True)
    assert report["parent_graph_consistent"] is True
    assert report["safe_to_reconcile_automatically"] is False


def test_packaged_16_graph_matches_current_lineage() -> None:
    """Exercise strict verification against the actual isolated migration sources."""
    root = SCRIPT.parents[1] / "apps" / "api" / "migrations" / "versions"
    before = {path: path.read_bytes() for path in root.glob("*.py")}
    report = _module().audit([root], verify_parent_graph=True)

    assert report["revision_count"] == 42
    assert report["collision_free"] is True
    assert report["parent_graph_consistent"] is True
    assert report["safe_to_reconcile_automatically"] is False
    graph = report["parent_graphs"][str(root)]
    assert graph["root_revisions"] == ["0001"]
    assert graph["head_revisions"] == ["0041"]
    assert graph["missing_parent_revisions"] == []
    assert graph["cycle_revisions"] == []
    assert graph["duplicate_revision_ids"] == []

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-parent-graph", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert json.loads(result.stdout) == report
    assert {path: path.read_bytes() for path in root.glob("*.py")} == before
