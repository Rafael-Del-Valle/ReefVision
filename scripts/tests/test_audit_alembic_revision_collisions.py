"""Regression coverage for non-destructive Alembic revision collision auditing."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "audit-alembic-revision-collisions.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("revision_collision_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit


def migration(root: Path, filename: str, revision: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(f'revision: str = "{revision}"\n', encoding="utf-8")
    return path


def test_conflicting_revision_ids_are_reported_without_modification(tmp_path: Path) -> None:
    first, second = tmp_path / "scientific", tmp_path / "qc"
    files = [
        migration(first, "0038_scientific_data.py", "0038"),
        migration(second, "0038_review_queue_item_events.py", "0038"),
    ]
    before = [path.read_bytes() for path in files]
    report = load_audit()([first, second])
    assert report["collision_free"] is False
    assert report["safe_to_reconcile_automatically"] is False
    assert report["collisions"]["0038"] == [str(files[0]), str(files[1])]
    assert report["collision_source_sha256"]["0038"] == {
        str(path): hashlib.sha256(contents).hexdigest()
        for path, contents in zip(files, before, strict=True)
    }
    assert len(set(report["collision_source_sha256"]["0038"].values())) == 1
    assert [path.read_bytes() for path in files] == before


def test_unique_revision_ids_do_not_authorize_migration(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    migration(root, "0037.py", "0037")
    migration(root, "0038.py", "0038")
    report = load_audit()([root])
    assert report["collision_free"] is True
    assert report["safe_to_reconcile_automatically"] is False
    assert report["revision_count"] == 2
    assert report["collision_source_sha256"] == {}


def test_nonliteral_revision_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    (root / "bad.py").write_text("revision = get_revision()\n", encoding="utf-8")
    with pytest.raises(ValueError, match="literal string"):
        load_audit()([root])


@pytest.mark.parametrize("link_is_directory", [False, True])
def test_nested_symlink_is_rejected_without_reading_external_content(
    tmp_path: Path, link_is_directory: bool
) -> None:
    root = tmp_path / "versions"
    migration(root, "0037.py", "0037")
    outside = tmp_path / "external"
    outside.mkdir()
    external_file = migration(outside, "0038.py", "0038")
    original = external_file.read_bytes()
    target = outside if link_is_directory else external_file
    link = root / ("linked_dir" if link_is_directory else "linked.py")
    try:
        link.symlink_to(target, target_is_directory=link_is_directory)
    except (NotImplementedError, OSError):
        pytest.skip("Filesystem does not permit symbolic links")
    with pytest.raises(ValueError, match="symbolic link"):
        load_audit()([root])
    assert external_file.read_bytes() == original


def test_duplicate_directory_alias_does_not_invent_collision(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    file = migration(root, "0038.py", "0038")
    before = file.read_bytes()
    with pytest.raises(ValueError, match="specified more than once"):
        load_audit()([root, root / ".." / "versions"])
    assert file.read_bytes() == before


def test_symlinked_parent_is_rejected_without_external_reads(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    file = migration(outside / "versions", "0038.py", "0038")
    before = file.read_bytes()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Filesystem does not permit symbolic links")
    with pytest.raises(ValueError, match="symbolic-link ancestor"):
        load_audit()([alias / "versions"])
    assert file.read_bytes() == before


@pytest.mark.parametrize("parent_first", [True, False])
def test_overlapping_roots_rejected_without_double_counting(
    tmp_path: Path, parent_first: bool
) -> None:
    parent = tmp_path / "migrations"
    child = parent / "versions"
    file = migration(child, "0038.py", "0038")
    before = file.read_bytes()
    roots = [parent, child] if parent_first else [child, parent]
    with pytest.raises(ValueError, match="directories overlap"):
        load_audit()(roots)
    assert file.read_bytes() == before


def test_divergent_collision_fingerprints_remain_read_only(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    files = [migration(first, "0038_a.py", "0038"), migration(second, "0038_b.py", "0038")]
    files[1].write_text(files[1].read_text(encoding="utf-8") + "# distinct schema\n", encoding="utf-8")
    before = [path.read_bytes() for path in files]
    report = load_audit()([first, second])
    hashes = report["collision_source_sha256"]["0038"]
    assert set(hashes) == {str(path) for path in files}
    assert len(set(hashes.values())) == 2
    assert report["safe_to_reconcile_automatically"] is False
    assert [path.read_bytes() for path in files] == before
