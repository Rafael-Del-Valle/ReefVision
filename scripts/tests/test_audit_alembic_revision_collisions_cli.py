"""CLI regression tests for the read-only Alembic collision audit."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "audit-alembic-revision-collisions.py"


def _run(*roots: Path, verify_parent_graph: bool = False) -> subprocess.CompletedProcess[str]:
    flags = ["--verify-parent-graph"] if verify_parent_graph else []
    return subprocess.run(
        [sys.executable, str(SCRIPT), *flags, *(str(root) for root in roots)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_rejects_conflicting_revisions_without_touching_sources(tmp_path: Path) -> None:
    first, second = tmp_path / "science", tmp_path / "review"
    first.mkdir()
    second.mkdir()
    source_a = first / "0038_science.py"
    source_b = second / "0038_review.py"
    source_a.write_text('revision = "0038"\n', encoding="utf-8")
    source_b.write_text('revision = "0038"\n', encoding="utf-8")
    before = (source_a.read_bytes(), source_b.read_bytes())

    result = _run(first, second)

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["collision_free"] is False
    assert report["safe_to_reconcile_automatically"] is False
    assert report["collisions"]["0038"] == [str(source_a), str(source_b)]
    assert (source_a.read_bytes(), source_b.read_bytes()) == before


def test_cli_unique_revisions_still_do_not_authorize_reconciliation(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    (root / "0037.py").write_text('revision = "0037"\n', encoding="utf-8")
    (root / "0038.py").write_text('revision = "0038"\n', encoding="utf-8")

    result = _run(root)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["revision_count"] == 2
    assert report["collision_free"] is True
    assert report["safe_to_reconcile_automatically"] is False


def test_cli_malformed_revision_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    source = root / "bad.py"
    source.write_text("revision = compute_revision()\n", encoding="utf-8")
    before = source.read_bytes()

    result = _run(root)

    assert result.returncode != 0
    assert "literal string" in result.stderr
    assert source.read_bytes() == before


def test_cli_missing_directory_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing")
    assert result.returncode != 0
    assert "Migration directory missing" in result.stderr


def test_cli_missing_revision_in_python_migration_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    source = root / "0038_unversioned.py"
    source.write_text("down_revision = '0037'\n", encoding="utf-8")
    before = source.read_bytes()

    result = _run(root)

    assert result.returncode != 0
    assert "missing literal revision assignment" in result.stderr
    assert source.read_bytes() == before


def test_cli_empty_migration_directory_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()

    result = _run(root)

    assert result.returncode != 0
    assert "No migration revision files found" in result.stderr


def test_cli_rejects_symlinked_migration_file_without_reading_target(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    external = tmp_path / "external_scientific_record.py"
    external.write_text('revision = "external"\n', encoding="utf-8")
    linked = root / "0038_link.py"
    linked.symlink_to(external)
    before = external.read_bytes()

    result = _run(root)

    assert result.returncode != 0
    assert "Migration tree contains a symbolic link" in result.stderr
    assert external.read_bytes() == before


def test_cli_rejects_symlinked_migration_directory(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    source = external / "0038.py"
    source.write_text('revision = "0038"\n', encoding="utf-8")
    linked = tmp_path / "versions"
    linked.symlink_to(external, target_is_directory=True)
    before = source.read_bytes()

    result = _run(linked)

    assert result.returncode != 0
    assert "Migration directory has a symbolic-link ancestor" in result.stderr
    assert source.read_bytes() == before


def test_cli_distinguishes_shared_and_divergent_source_without_authorizing_merge(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("science", "review", "third")]
    files = {}
    for root in roots:
        root.mkdir()
        for revision in ("0037", "0038", "0039", "0040", "0041"):
            source = root / f"{revision}.py"
            body = f'revision = "{revision}"\n'
            if revision != "0037":
                body += "# science\n" if root == roots[0] else "# QC\n"
            source.write_text(body, encoding="utf-8")
            files[source] = source.read_bytes()
    only_science = roots[0] / "0042.py"
    only_science.write_text('revision = "0042"\n', encoding="utf-8")
    files[only_science] = only_science.read_bytes()

    for order in (roots, list(reversed(roots))):
        result = _run(*order)
        assert result.returncode == 2
        report = json.loads(result.stdout)
        assert report["collision_source_relationship"] == {
            "0037": "byte_identical",
            "0038": "source_differs",
            "0039": "source_differs",
            "0040": "source_differs",
            "0041": "source_differs",
        }
        assert report["collision_free"] is False
        assert report["safe_to_reconcile_automatically"] is False
        assert set(report["collisions"]) == {"0037", "0038", "0039", "0040", "0041"}
        assert report["revision_count"] == 6
        assert {path: path.read_bytes() for path in files} == files


def test_cli_identical_duplicate_within_one_lineage_remains_a_collision(
    tmp_path: Path,
) -> None:
    first = tmp_path / "0038_a.py"
    second = tmp_path / "0038_b.py"
    for path in (first, second):
        path.write_text('revision = "0038"\n', encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["collision_source_relationship"] == {"0038": "byte_identical"}
    assert report["collision_free"] is False
    assert report["safe_to_reconcile_automatically"] is False


def test_cli_identical_descendants_do_not_hide_divergent_ancestry(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("science", "review")]
    files = {}
    for root in roots:
        root.mkdir()
        for revision, parent in (
            ("0037", None),
            ("0038", "0037"),
            ("0039", "0038"),
            ("0040", "0039"),
        ):
            source = root / f"{revision}.py"
            body = f"revision = {revision!r}\ndown_revision = {parent!r}\n"
            if revision == "0038":
                body += f"# {root.name}\n"
            source.write_text(body, encoding="utf-8")
            files[source] = source.read_bytes()

    expected = {
        "0037": "identical_history",
        "0038": "divergent_history",
        "0039": "divergent_history",
        "0040": "divergent_history",
    }
    for order in (roots, list(reversed(roots))):
        result = _run(*order, verify_parent_graph=True)
        assert result.returncode == 2
        report = json.loads(result.stdout)
        assert report["parent_graph_consistent"] is True
        assert report["collision_source_relationship"]["0039"] == "byte_identical"
        assert report["collision_source_relationship"]["0040"] == "byte_identical"
        assert report["collision_ancestry_relationship"] == expected
        for revision, relationship in expected.items():
            hashes = report["collision_ancestry_sha256"][revision].values()
            assert all(len(digest) == 64 for digest in hashes)
            assert len(set(hashes)) == (1 if relationship == "identical_history" else 2)
        assert report["safe_to_reconcile_automatically"] is False
        assert {path: path.read_bytes() for path in files} == files

    default = json.loads(_run(*roots).stdout)
    assert "collision_ancestry_relationship" not in default


def test_cli_invalid_parent_graph_withholds_ancestry_evidence(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("valid", "invalid")]
    files = {}
    for root in roots:
        root.mkdir()
        source = root / "0037.py"
        source.write_text("revision = '0037'\ndown_revision = None\n", encoding="utf-8")
        files[source] = source.read_bytes()
        source = root / "0038.py"
        parent = "0037" if root == roots[0] else "missing"
        source.write_text(f"revision = '0038'\ndown_revision = {parent!r}\n", encoding="utf-8")
        files[source] = source.read_bytes()

    result = _run(*roots, verify_parent_graph=True)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["parent_graph_consistent"] is False
    assert report["collision_source_relationship"]["0037"] == "byte_identical"
    assert report["collision_ancestry_relationship"] == {
        "0037": "unverified_graph",
        "0038": "unverified_graph",
    }
    for revision, hashes in report["collision_ancestry_sha256"].items():
        assert hashes[str(roots[1] / f"{revision}.py")] is None
        assert len(hashes[str(roots[0] / f"{revision}.py")]) == 64
    assert report["safe_to_reconcile_automatically"] is False
    assert {path: path.read_bytes() for path in files} == files


def test_cli_parent_graph_refuses_unverified_dependency_edges(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    parent = root / "0037.py"
    parent.write_text("revision = '0037'\ndown_revision = None\n", encoding="utf-8")
    child = root / "0038.py"
    base = "revision = '0038'\ndown_revision = '0037'\n"
    invalid = (
        "depends_on = 'missing'\n",
        "depends_on = ('0037', 'missing')\n",
        "depends_on = ['0037']\n",
        "depends_on = '0037'\n",
        "depends_on = compute_dependencies()\n",
        "depends_on = None\ndepends_on = 'missing'\n",
        "depends_on = None\nif True:\n    depends_on = 'missing'\n",
        "depends_on = None\ndel depends_on\n",
        "from somewhere import value as depends_on\n",
        "for depends_on in ['missing']:\n    pass\n",
        "def depends_on():\n    return 'missing'\n",
        "depends_on = ('0037', 4)\n",
    )
    parent_before = parent.read_bytes()
    for suffix in invalid:
        child.write_text(base + suffix, encoding="utf-8")
        before = child.read_bytes()
        default = _run(root)
        assert default.returncode == 0, default.stderr
        assert "parent_graph_consistent" not in json.loads(default.stdout)

        strict = _run(root, verify_parent_graph=True)
        assert strict.returncode == 2
        assert "depends_on" in strict.stderr
        assert not strict.stdout
        assert child.read_bytes() == before
        assert parent.read_bytes() == parent_before


def test_cli_parent_graph_accepts_dependency_free_sources(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    parent = root / "0037.py"
    parent.write_text("revision = '0037'\ndown_revision = None\n", encoding="utf-8")
    child = root / "0038.py"
    base = "revision = '0038'\ndown_revision = '0037'\n"
    for suffix in ("", "depends_on = None\n", "depends_on: str | None = None\n"):
        child.write_text(base + suffix, encoding="utf-8")
        before = child.read_bytes()
        strict = _run(root, verify_parent_graph=True)
        assert strict.returncode == 0, strict.stderr
        report = json.loads(strict.stdout)
        assert report["parent_graph_consistent"] is True
        assert report["safe_to_reconcile_automatically"] is False
        assert child.read_bytes() == before


def test_cli_parent_graph_refuses_unverified_branch_labels(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    parent = root / "0037.py"
    parent.write_text("revision = '0037'\ndown_revision = None\n", encoding="utf-8")
    child = root / "0038.py"
    base = "revision = '0038'\ndown_revision = '0037'\n"
    invalid = (
        "branch_labels = 'qc'\n",
        "branch_labels = '0037'\n",
        "branch_labels = ('qc', 'science')\n",
        "branch_labels = ['qc']\n",
        "branch_labels = compute_labels()\n",
        "branch_labels = None\nbranch_labels = 'qc'\n",
        "branch_labels = None\nif True:\n    branch_labels = 'qc'\n",
        "branch_labels = None\ndel branch_labels\n",
        "from somewhere import labels as branch_labels\n",
        "branch_labels = ('qc', 4)\n",
    )
    parent_before = parent.read_bytes()
    for suffix in invalid:
        child.write_text(base + suffix, encoding="utf-8")
        before = child.read_bytes()
        default = _run(root)
        assert default.returncode == 0, default.stderr
        assert "parent_graph_consistent" not in json.loads(default.stdout)

        strict = _run(root, verify_parent_graph=True)
        assert strict.returncode == 2
        assert "branch_labels" in strict.stderr
        assert not strict.stdout
        assert child.read_bytes() == before
        assert parent.read_bytes() == parent_before


def test_cli_parent_graph_accepts_unlabeled_sources(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    parent = root / "0037.py"
    parent.write_text("revision = '0037'\ndown_revision = None\n", encoding="utf-8")
    child = root / "0038.py"
    base = "revision = '0038'\ndown_revision = '0037'\ndepends_on = None\n"
    for suffix in ("", "branch_labels = None\n", "branch_labels: str | None = None\n"):
        child.write_text(base + suffix, encoding="utf-8")
        before = child.read_bytes()
        strict = _run(root, verify_parent_graph=True)
        assert strict.returncode == 0, strict.stderr
        report = json.loads(strict.stdout)
        assert report["parent_graph_consistent"] is True
        assert report["safe_to_reconcile_automatically"] is False
        assert child.read_bytes() == before


def test_cli_strict_graph_rejects_unsafe_revision_and_parent_identifiers(
    tmp_path: Path,
) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    source = root / "migration.py"
    invalid = (
        "a-b",
        "a+b",
        "a@b",
        "a b",
        "a\tb",
        "a\u200bb",
        "\uff10\uff10\uff13\uff18",
        "x" * 33,
        "base",
        "head",
        "heads",
        "a/b",
        "a.b",
    )
    for token in invalid:
        for field in ("revision", "parent"):
            revision = token if field == "revision" else "0038"
            parent = None if field == "revision" else token
            source.write_text(
                f"revision = {revision!r}\ndown_revision = {parent!r}\n",
                encoding="utf-8",
            )
            before = source.read_bytes()
            default = _run(root)
            assert default.returncode == 0, default.stderr
            assert "parent_graph_consistent" not in json.loads(default.stdout)
            strict = _run(root, verify_parent_graph=True)
            assert strict.returncode == 2
            assert f"unsupported strict graph {field} identifier" in strict.stderr
            assert not strict.stdout
            assert source.read_bytes() == before


def test_cli_strict_graph_accepts_numeric_and_namespaced_revision_ids(
    tmp_path: Path,
) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    revisions = ("0037", "0038", "b12_identity_0005", "reefpose_0044", "x" * 32)
    files = {}
    for index, revision in enumerate(revisions):
        parent = revisions[index - 1] if index else None
        source = root / f"{index}.py"
        source.write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\n",
            encoding="utf-8",
        )
        files[source] = source.read_bytes()

    result = _run(root, verify_parent_graph=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["parent_graph_consistent"] is True
    assert report["parent_graphs"][str(root)]["head_revisions"] == [revisions[-1]]
    assert report["safe_to_reconcile_automatically"] is False
    assert {path: path.read_bytes() for path in files} == files
