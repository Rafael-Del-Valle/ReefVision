"""CLI regression tests for the read-only Alembic collision audit."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "audit-alembic-revision-collisions.py"


def _run(*roots: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(root) for root in roots)],
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
