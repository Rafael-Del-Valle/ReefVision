"""Non-destructive, source-projection preservation checks for 1.1/1.6 convergence."""

import json
import os
import runpy
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"


def _seed(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        for table in (
            "scientific_records",
            "review_queue_item_events",
            "class_visibility_preferences",
            "workflow_graph_records",
            "annotations",
        ):
            connection.execute(
                f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, payload BLOB NOT NULL, note TEXT)'
            )
            connection.execute(
                f'INSERT INTO "{table}" VALUES (?, ?, ?)',
                ("z", b"\x00\xff", "coral \u03b1; private record"),
            )
            connection.execute(
                f'INSERT INTO "{table}" VALUES (?, ?, ?)',
                ("a", b"\x10\x11", None),
            )


def _run(
    before: Path,
    after: Path,
    before_assets: Path | None = None,
    after_assets: Path | None = None,
) -> tuple[int, dict]:
    command = [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)]
    if before_assets is not None:
        command.extend(["--before-assets", str(before_assets)])
    if after_assets is not None:
        command.extend(["--after-assets", str(after_assets)])
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("table", "mutation", "expected"),
    [
        (
            "scientific_records",
            "UPDATE scientific_records SET note = 'forged' WHERE id = 'z'",
            "changed_records",
        ),
        (
            "review_queue_item_events",
            "DELETE FROM review_queue_item_events WHERE id = 'a'",
            "changed_records",
        ),
        (
            "workflow_graph_records",
            "INSERT INTO workflow_graph_records VALUES ('new', X'00', NULL)",
            "changed_records",
        ),
        (
            "class_visibility_preferences",
            "ALTER TABLE class_visibility_preferences DROP COLUMN note",
            "removed_columns",
        ),
        ("annotations", "DROP TABLE annotations", "removed_table"),
    ],
)
def test_detects_modified_science_qc_class_and_workflow_evidence(
    tmp_path: Path, table: str, mutation: str, expected: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = before.read_bytes()
    with sqlite3.connect(after) as connection:
        connection.execute(mutation)
    modified = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert any(item["table"] == table and item["status"] == expected for item in report["tables"])
    assert "coral \u03b1; private record" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == modified


@pytest.mark.parametrize(
    "table",
    [
        "scientific_records",
        "review_queue_item_events",
        "class_visibility_preferences",
        "workflow_graph_records",
    ],
)
def test_removed_scientific_column_names_remain_private(tmp_path: Path, table: str) -> None:
    """Schema-drift diagnostics must not disclose researcher-defined identifiers."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    private_column = "private_researcher_donor_identifier_0123"
    with sqlite3.connect(before) as connection:
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{private_column}" TEXT')
        connection.execute(
            f'UPDATE "{table}" SET "{private_column}" = ?',
            ("nonpublic-biological-identification",),
        )
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(f'ALTER TABLE "{table}" DROP COLUMN "{private_column}"')

    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    entry = next(item for item in report["tables"] if item["table"] == table)
    assert entry["status"] == "removed_columns"
    assert entry["removed_column_count"] == 1
    assert "removed_columns" not in entry
    public_report = json.dumps(report, ensure_ascii=False)
    assert private_column not in public_report
    assert "nonpublic-biological-identification" not in public_report
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


def test_rebuilt_qc_history_cannot_silently_reorder_review_actions(tmp_path: Path) -> None:
    """Identical UUID-keyed rows may have different SQLite append chronology."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    baseline_code, baseline_report = _run(before, after)
    assert baseline_code == 0
    assert baseline_report["status"] == "PASS_PRESERVATION_ONLY"

    with sqlite3.connect(after) as connection:
        rows = connection.execute(
            "SELECT id, payload, note FROM review_queue_item_events ORDER BY id"
        ).fetchall()
        connection.execute("DELETE FROM review_queue_item_events")
        connection.executemany(
            "INSERT INTO review_queue_item_events (id, payload, note) VALUES (?, ?, ?)", rows
        )
        assert connection.execute(
            "SELECT id FROM review_queue_item_events ORDER BY rowid"
        ).fetchall() == [("a",), ("z",)]
    old_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert any(
        item["table"] == "review_queue_item_events"
        and item["status"] == "changed_review_event_append_order"
        and item["baseline_sha256"] == item["candidate_sha256"]
        for item in report["tables"]
    )
    assert "coral \u03b1; private record" not in json.dumps(report)
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == candidate_bytes


def test_qc_history_rowid_alias_shadowing_requires_review(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("ALTER TABLE review_queue_item_events ADD COLUMN rowid INTEGER")
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert any(
        item["table"] == "review_queue_item_events"
        and item["status"] == "ambiguous_review_event_rowid"
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


def test_additive_schema_and_new_qc_table_preserve_original_record_projection(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    old_bytes = before.read_bytes()
    with sqlite3.connect(after) as connection:
        connection.execute("ALTER TABLE scientific_records ADD COLUMN new_science TEXT")
        connection.execute("CREATE TABLE review_queue_bulk_requests (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO review_queue_bulk_requests VALUES ('new')")
        connection.execute("UPDATE alembic_version SET version_num = '0041'")
    new_bytes = after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["protected_tables_examined"] == 5
    assert report["requires_researcher_approval"] is True
    assert report["upgrade_authorized"] is False
    assert not report["problems"]
    assert all(entry["status"] in {"preserved", "not_in_baseline"} for entry in report["tables"])
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


@pytest.mark.parametrize("storage", ["VIRTUAL", "STORED"])
@pytest.mark.parametrize("candidate", ["changed_expression", "removed_column"])
def test_generated_scientific_column_preserved(
    tmp_path: Path, storage: str, candidate: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"

    def create(path: Path, expression: str | None) -> None:
        generated = (
            f", length_mm REAL GENERATED ALWAYS AS ({expression}) {storage}"
            if expression is not None
            else ""
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records "
                f"(id TEXT PRIMARY KEY, raw_length_mm REAL NOT NULL{generated})"
            )
            connection.execute(
                "INSERT INTO scientific_records (id, raw_length_mm) VALUES (?, ?)",
                ("coral-1", 3.5),
            )

    create(before, "raw_length_mm * 2.0")
    create(
        after,
        "raw_length_mm * 3.0" if candidate == "changed_expression" else None,
    )
    original = before.read_bytes()
    upgraded = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    expected = (
        "changed_generated_column_contract"
        if candidate == "changed_expression"
        else "removed_columns"
    )
    assert any(
        item["table"] == "scientific_records" and item["status"] == expected
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False
    assert "coral-1" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == upgraded


@pytest.mark.parametrize("storage", ["VIRTUAL", "STORED"])
def test_new_generated_column_does_not_modify_original_science(
    tmp_path: Path, storage: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, raw_length_mm REAL)"
        )
        connection.execute("INSERT INTO scientific_records VALUES (1, 3.5)")
    with sqlite3.connect(after) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, raw_length_mm REAL, "
            f"length_mm REAL GENERATED ALWAYS AS (raw_length_mm * 2.0) {storage})"
        )
        connection.execute("INSERT INTO scientific_records (id, raw_length_mm) VALUES (1, 3.5)")
    original, upgraded = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["protected_tables_examined"] == 1
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == upgraded


def test_no_pk_uses_canonical_column_order_for_record_preservation(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute("CREATE TABLE annotations (note TEXT, measurement REAL, blob BLOB)")
        connection.executemany(
            "INSERT INTO annotations VALUES (?, ?, ?)",
            [("b", -0.0, b"\x01"), ("a", 2.5, b"\x02")],
        )
    with sqlite3.connect(after) as connection:
        connection.execute("CREATE TABLE annotations (note TEXT, measurement REAL, blob BLOB)")
        connection.executemany(
            "INSERT INTO annotations VALUES (?, ?, ?)",
            [("a", 2.5, b"\x02"), ("b", -0.0, b"\x01")],
        )
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"


@pytest.mark.parametrize("mode", ["same_path", "missing", "corrupt", "no_covered_table"])
def test_fails_closed_on_unsafe_inputs(tmp_path: Path, mode: str) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    if mode == "same_path":
        after = before
    elif mode == "missing":
        after.unlink()
    elif mode == "corrupt":
        after.write_bytes(b"not-a-database")
    elif mode == "no_covered_table":
        with sqlite3.connect(before) as connection:
            for name in (
                "scientific_records",
                "review_queue_item_events",
                "class_visibility_preferences",
                "workflow_graph_records",
                "annotations",
            ):
                connection.execute(f'DROP TABLE "{name}"')
    baseline_bytes = before.read_bytes()
    if after.is_file():
        candidate_bytes = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert before.read_bytes() == baseline_bytes
    if after.is_file():
        assert after.read_bytes() == candidate_bytes


def test_wal_sidecar_blocks_preservation_claim(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    writer = sqlite3.connect(after)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("UPDATE scientific_records SET note = note WHERE id = 'z'")
        writer.commit()
        assert Path(str(after) + "-wal").exists()
        code, report = _run(before, after)
        assert code == 2
        assert report["status"] == "HOLD"
        assert "mutable_sqlite_sidecar_detected" in report["problems"]
    finally:
        writer.close()


def test_upgrade_asset_inventory_preserves_original_media_and_allows_additions(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    before_assets = tmp_path / "original-assets"
    after_assets = tmp_path / "candidate-assets"
    (before_assets / "study-1").mkdir(parents=True)
    (after_assets / "study-1").mkdir(parents=True)
    (before_assets / "study-1" / "video.mov").write_bytes(b"frame" * 10_000)
    (before_assets / "study-1" / "mask.png").write_bytes(b"\x00\xff\x01")
    shutil.copytree(before_assets, after_assets, dirs_exist_ok=True)
    (after_assets / "study-1" / "new-image.jpg").write_bytes(b"new observation")
    original = before.read_bytes()
    candidate = after.read_bytes()
    baseline_assets = {
        path.relative_to(before_assets): path.read_bytes()
        for path in before_assets.rglob("*")
        if path.is_file()
    }

    code, report = _run(before, after, before_assets, after_assets)

    assert code == 0, report["problems"]
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["research_assets"] == {
        "checked": True,
        "baseline_files": 2,
        "candidate_files": 3,
        "missing_files": 0,
        "changed_files": 0,
        "added_files": 1,
        "baseline_directories": 1,
        "candidate_directories": 1,
        "missing_directories": 0,
        "added_directories": 0,
    }
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "video.mov" not in json.dumps(report)
    assert "mask.png" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate
    assert all(
        (before_assets / relative).read_bytes() == content
        for relative, content in baseline_assets.items()
    )


@pytest.mark.parametrize("mutation", ["removed", "changed", "symlink"])
def test_upgrade_asset_inventory_fails_closed_without_changing_evidence(
    tmp_path: Path, mutation: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    before_assets = tmp_path / "original"
    after_assets = tmp_path / "candidate"
    before_assets.mkdir()
    after_assets.mkdir()
    (before_assets / "original.mp4").write_bytes(b"archival coral video\x00")
    candidate_file = after_assets / "original.mp4"
    candidate_file.write_bytes(b"archival coral video\x00")
    if mutation == "removed":
        candidate_file.unlink()
    elif mutation == "changed":
        candidate_file.write_bytes(b"archival coral video\x01")
    else:
        candidate_file.unlink()
        try:
            candidate_file.symlink_to(before_assets / "original.mp4")
        except (NotImplementedError, OSError):
            pytest.skip("platform does not permit symlinks")
    baseline_before, baseline_after = before.read_bytes(), after.read_bytes()
    original_asset_bytes = (before_assets / "original.mp4").read_bytes()
    code, report = _run(before, after, before_assets, after_assets)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    if mutation == "removed":
        assert "research_assets_missing" in report["problems"]
        assert report["research_assets"]["missing_files"] == 1
    elif mutation == "changed":
        assert "research_assets_changed" in report["problems"]
        assert report["research_assets"]["changed_files"] == 1
    else:
        assert "asset_symlink_not_allowed" in report["problems"]
    assert "original.mp4" not in json.dumps(report)
    assert before.read_bytes() == baseline_before
    assert after.read_bytes() == baseline_after
    assert (before_assets / "original.mp4").read_bytes() == original_asset_bytes


@pytest.mark.parametrize("aliased_scope", ["baseline", "candidate"])
@pytest.mark.parametrize("nested", [False, True])
def test_asset_preservation_rejects_symlinked_ancestor_outside_scoped_root(
    tmp_path: Path, aliased_scope: str, nested: bool
) -> None:
    """A non-link media root must not hide a symlink in its parent path."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    real_parent = tmp_path / "real-research-parent"
    real_root = real_parent / ("nested" if nested else "study") / "media"
    real_root.mkdir(parents=True)
    alias = tmp_path / "alias-to-parent"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("filesystem does not permit directory symlinks")
    aliased_root = alias / ("nested" if nested else "study") / "media"
    assert not aliased_root.is_symlink()
    other_root = tmp_path / "independent-media"
    other_root.mkdir()
    for root in (real_root, other_root):
        (root / "private-coral-image.raw").write_bytes(b"preserved coral observation")
    baseline = aliased_root if aliased_scope == "baseline" else other_root
    candidate = aliased_root if aliased_scope == "candidate" else other_root
    before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
    code, evidence = _run(before, after, baseline, candidate)
    assert code == 2
    assert evidence["status"] == "HOLD"
    assert evidence["upgrade_authorized"] is False
    assert evidence["requires_researcher_approval"] is True
    assert "asset_symlink_not_allowed" in evidence["problems"]
    assert "private-coral-image.raw" not in json.dumps(evidence)
    assert "real-research-parent" not in json.dumps(evidence)
    assert before.read_bytes() == before_bytes
    assert after.read_bytes() == after_bytes
    assert (real_root / "private-coral-image.raw").read_bytes() == b"preserved coral observation"


def test_asset_copies_must_not_share_hardlinked_original_storage(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    source = original / "camera.raw"
    source.write_bytes(b"source pixels")
    try:
        (candidate / "camera.raw").hardlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("filesystem does not permit hardlinks")
    if source.stat().st_ino == 0:
        pytest.skip("filesystem does not expose stable inodes")
    baseline_bytes = source.read_bytes()
    code, report = _run(before, after, original, candidate)
    assert code == 2
    assert report["status"] == "HOLD"
    assert "asset_copies_share_hardlinks" in report["problems"]
    assert "camera.raw" not in json.dumps(report)
    assert source.read_bytes() == baseline_bytes


@pytest.mark.parametrize("linked_copy", ["baseline", "candidate"])
def test_asset_preservation_rejects_unscanned_external_hardlink(
    tmp_path: Path, linked_copy: str
) -> None:
    """Independent directory roots are insufficient if a third alias can edit media."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    original = baseline / "private-field-video.raw"
    upgraded = candidate / original.name
    original.write_bytes(b"preserved biological observation")
    upgraded.write_bytes(original.read_bytes())
    linked = original if linked_copy == "baseline" else upgraded
    outside = tmp_path / "unscanned-hardlink.raw"
    try:
        outside.hardlink_to(linked)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support hardlinks")
    if linked.stat().st_nlink < 2:
        pytest.skip("filesystem does not expose reliable link counts")
    before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after, baseline, candidate)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "asset_hardlinks_not_independent" in report["problems"], report["problems"]
    assert "private-field-video.raw" not in json.dumps(report)
    assert "unscanned-hardlink.raw" not in json.dumps(report)
    assert before.read_bytes() == before_bytes
    assert after.read_bytes() == after_bytes
    assert outside.read_bytes() == original.read_bytes() == upgraded.read_bytes()


def test_asset_scan_detects_hardlink_added_after_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late alias changes link count even if no file data or name changes."""
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    original = baseline / "observation.raw"
    upgraded = candidate / "observation.raw"
    original.write_bytes(b"original observation")
    upgraded.write_bytes(b"original observation")
    outside = tmp_path / "late-unscanned-alias.raw"
    compare = runpy.run_path(str(SCRIPT))["_compare_assets"]
    inventory = compare.__globals__["_asset_inventory"]

    def create_alias_after_candidate_scan(root: Path) -> object:
        snapshot = inventory(root)
        if root == candidate:
            try:
                outside.hardlink_to(original)
            except (OSError, NotImplementedError):
                pytest.skip("filesystem does not support hardlinks")
            if original.stat().st_nlink < 2:
                pytest.skip("filesystem does not expose reliable link counts")
        return snapshot

    monkeypatch.setitem(compare.__globals__, "_asset_inventory", create_alias_after_candidate_scan)
    with pytest.raises(ValueError, match="asset_changed_after_inventory") as error:
        compare(baseline, candidate)
    assert "observation.raw" not in str(error.value)
    assert outside.read_bytes() == original.read_bytes() == upgraded.read_bytes()


def test_empty_asset_baseline_cannot_claim_preservation(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    before_assets = tmp_path / "empty-original"
    after_assets = tmp_path / "candidate"
    before_assets.mkdir()
    after_assets.mkdir()
    (after_assets / "new-video.mp4").write_bytes(b"new")
    code, report = _run(before, after, before_assets, after_assets)
    assert code == 2
    assert report["status"] == "HOLD"
    assert "no_research_assets_in_baseline" in report["problems"]
    assert "new-video.mp4" not in json.dumps(report)


@pytest.mark.parametrize("case", ["unpaired", "same_root", "nested_root"])
def test_upgrade_asset_inventory_rejects_unsafe_scope(tmp_path: Path, case: str) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    original.mkdir()
    (original / "one.jpg").write_bytes(b"original")
    if case == "unpaired":
        before_assets, after_assets = original, None
    elif case == "same_root":
        before_assets, after_assets = original, original
    else:
        candidate = original / "nested"
        candidate.mkdir()
        before_assets, after_assets = original, candidate
    code, report = _run(before, after, before_assets, after_assets)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert "one.jpg" not in json.dumps(report)
    assert (original / "one.jpg").read_bytes() == b"original"


def test_database_only_preservation_does_not_claim_research_assets(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    code, report = _run(before, after)
    assert code == 0
    assert report["research_assets"] == {"checked": False}
    assert report["upgrade_authorized"] is False


@pytest.mark.parametrize(
    "mutation",
    ["baseline_rewritten", "baseline_removed", "candidate_rewritten", "candidate_added"],
)
def test_asset_comparison_rejects_changes_between_inventory_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """A scanner must not PASS against a baseline edited during candidate hashing."""
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    baseline_file = original / "private-coral-sample.raw"
    candidate_file = candidate / baseline_file.name
    baseline_file.write_bytes(b"original measured observation")
    candidate_file.write_bytes(b"original measured observation")
    compare = runpy.run_path(str(SCRIPT))["_compare_assets"]
    inventory = compare.__globals__["_asset_inventory"]

    def mutate_after_candidate_scan(root: Path) -> object:
        result = inventory(root)
        if root == candidate:
            if mutation == "baseline_rewritten":
                baseline_file.write_bytes(b"rewritten measured observation")
            elif mutation == "baseline_removed":
                baseline_file.unlink()
            elif mutation == "candidate_rewritten":
                candidate_file.write_bytes(b"rewritten measured observation")
            else:
                (candidate / "late-added.jpg").write_bytes(b"new unverified image")
        return result

    monkeypatch.setitem(compare.__globals__, "_asset_inventory", mutate_after_candidate_scan)
    with pytest.raises(ValueError, match="asset_changed_after_inventory") as error:
        compare(original, candidate)
    assert "private-coral-sample.raw" not in str(error.value)


def test_asset_scan_rejects_symlink_swap_between_lstat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On platforms without O_NOFOLLOW, descriptor identity still detects swaps."""
    root = tmp_path / "original"
    root.mkdir()
    asset = root / "recording.raw"
    asset.write_bytes(b"reviewed biological pixels")
    external = tmp_path / "external-research.raw"
    external.write_bytes(b"private unrelated research")
    scan = runpy.run_path(str(SCRIPT))["_asset_inventory"]
    actual_open = os.open
    swapped = False

    def swap_on_open(
        path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        if not swapped and Path(path) == asset:
            swapped = True
            asset.unlink()
            try:
                asset.symlink_to(external)
            except (OSError, NotImplementedError):
                pytest.skip("filesystem does not permit symlink race fixture")
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_on_open)
    with pytest.raises(
        ValueError, match=r"asset_(symlink_not_allowed|changed_during_inspection)"
    ) as error:
        scan(root)
    assert swapped
    assert "external-research.raw" not in str(error.value)
    assert external.read_bytes() == b"private unrelated research"


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE sqlite_sequence SET seq = 2 WHERE name = 'scientific_records'",
        "DELETE FROM sqlite_sequence WHERE name = 'scientific_records'",
        "INSERT INTO sqlite_sequence (name, seq) VALUES ('scientific_records', 3)",
    ],
)
def test_autoincrement_allocation_history_is_preserved(tmp_path: Path, mutation: str) -> None:
    """A migration must not reuse an old scientific identifier after deletion."""
    before = tmp_path / "original.sqlite"
    after = tmp_path / "migrated.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, species TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO scientific_records (species) VALUES (?)",
            [("Swiftia",), ("Thesea",), ("Muricea",)],
        )
        connection.execute("DELETE FROM scientific_records WHERE id = 3")
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(mutation)
    original_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "scientific_records:changed_autoincrement_sequence" in report["problems"]
    assert (
        next(item for item in report["tables"] if item["table"] == "scientific_records")["status"]
        == "changed_autoincrement_sequence"
    )
    assert "Swiftia" not in json.dumps(report)
    assert before.read_bytes() == original_bytes
    assert after.read_bytes() == candidate_bytes


def test_additive_science_schema_preserves_autoincrement_counter(tmp_path: Path) -> None:
    """An allowed additive migration leaves historical allocation intact."""
    before = tmp_path / "original.sqlite"
    after = tmp_path / "migrated.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, species TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO scientific_records (species) VALUES ('Swiftia')")
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("ALTER TABLE scientific_records ADD COLUMN verified_note TEXT")
    original_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert report["protected_tables_examined"] == 1
    assert report["problems"] == []
    assert before.read_bytes() == original_bytes
    assert after.read_bytes() == candidate_bytes


def test_windows_reparse_metadata_is_not_confused_with_regular_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows junctions and non-symlink reparse files must never pass as originals."""
    is_link = runpy.run_path(str(SCRIPT))["_is_unsafe_asset_link"]
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    for mode in (stat.S_IFDIR, stat.S_IFREG):
        metadata = SimpleNamespace(st_mode=mode, st_file_attributes=0x400)
        assert is_link(tmp_path / "private-redirect", metadata)


def test_asset_verifier_detects_empty_directory_swap_after_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Swapping an empty subtree must not escape the second-pass inventory."""
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    for root in (original, candidate):
        (root / "coral.raw").write_bytes(b"preserved study image")
        (root / "empty-study-folder").mkdir()
    replaced = original / "empty-study-folder"
    compare = runpy.run_path(str(SCRIPT))["_compare_assets"]
    inventory = compare.__globals__["_asset_inventory"]

    def replace_after_candidate_scan(root: Path) -> object:
        snapshot = inventory(root)
        if root == candidate:
            replaced.rename(tmp_path / "original-folder-before-swap")
            replaced.mkdir()
        return snapshot

    monkeypatch.setitem(compare.__globals__, "_asset_inventory", replace_after_candidate_scan)
    with pytest.raises(ValueError, match="asset_changed_after_inventory") as error:
        compare(original, candidate)
    assert "empty-study-folder" not in str(error.value)
    assert (original / "coral.raw").read_bytes() == b"preserved study image"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction acceptance")
@pytest.mark.parametrize(
    "placement",
    ["original_root", "candidate_root", "original_child", "candidate_child"],
)
def test_windows_native_junctions_block_research_asset_preservation(
    tmp_path: Path, placement: str
) -> None:
    """A real NTFS junction must not redirect the verifier outside its scope."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original-assets"
    candidate = tmp_path / "candidate-assets"
    outside = tmp_path / "external-science"
    outside.mkdir()
    (outside / "private.raw").write_bytes(b"unrelated field observation")
    victim = original if placement.startswith("original") else candidate

    if placement.endswith("root"):
        other = candidate if victim == original else original
        other.mkdir()
        (other / "original.raw").write_bytes(b"preserved coral")
        junction = victim
    else:
        original.mkdir()
        candidate.mkdir()
        (original / "original.raw").write_bytes(b"preserved coral")
        (candidate / "original.raw").write_bytes(b"preserved coral")
        junction = victim / "redirected"

    try:
        command = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:RV_JUNCTION "
                "-Target $env:RV_TARGET | Out-Null",
            ],
            env={**os.environ, "RV_JUNCTION": str(junction), "RV_TARGET": str(outside)},
            capture_output=True,
            text=True,
            check=False,
        )
        if command.returncode:
            raise AssertionError(
                "Windows NTFS junction fixture creation failed: " + command.stderr.strip()[:300]
            )
        before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
        code, report = _run(before, after, original, candidate)
        assert code == 2
        assert report["status"] == "HOLD"
        assert report["upgrade_authorized"] is False
        assert report["requires_researcher_approval"] is True
        assert "asset_symlink_not_allowed" in report["problems"]
        assert "private.raw" not in json.dumps(report)
        assert before.read_bytes() == before_bytes
        assert after.read_bytes() == after_bytes
        assert (outside / "private.raw").read_bytes() == b"unrelated field observation"
    finally:
        if junction.exists():
            junction.rmdir()


def test_windows_ctime_handle_normalization_keeps_all_other_identity_checks() -> None:
    """A Windows lstat/fstat creation-time mismatch must not become a false HOLD."""
    scope = runpy.run_path(str(SCRIPT))
    identity = scope["_asset_handle_state"]
    full_identity = scope["_asset_state"]
    fields = {
        "st_dev": 1,
        "st_ino": 42,
        "st_size": 1024,
        "st_mtime_ns": 2000,
        "st_ctime_ns": 3000,
        "st_mode": stat.S_IFREG,
        "st_nlink": 1,
    }
    first = SimpleNamespace(**fields)
    opened = SimpleNamespace(**{**fields, "st_ctime_ns": 3500})
    assert identity(first) == identity(opened)
    assert full_identity(first) != full_identity(opened)
    for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink"):
        changed_value = stat.S_IFDIR if key == "st_mode" else fields[key] + 1
        changed = SimpleNamespace(**{**fields, key: changed_value})
        assert identity(first) != identity(changed), key


@pytest.mark.parametrize(
    ("candidate_definition", "expected"),
    [
        ("measurement REAL DEFAULT 1", "changed_column_contract"),
        ("measurement NUMERIC NOT NULL DEFAULT 1", "changed_column_contract"),
        ("measurement REAL NOT NULL DEFAULT 2", "changed_column_contract"),
        ("measurement REAL NOT NULL DEFAULT 1", "preserved"),
    ],
)
def test_upgrade_preserves_original_scientific_column_contracts(
    tmp_path: Path, candidate_definition: str, expected: str
) -> None:
    """Unchanged coral measurements cannot justify weakened future write rules."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    for path, definition in (
        (before, "measurement REAL NOT NULL DEFAULT 1"),
        (after, candidate_definition),
    ):
        with sqlite3.connect(path) as connection:
            connection.execute(
                f"CREATE TABLE scientific_records (id TEXT PRIMARY KEY, {definition})"
            )
            connection.execute(
                "INSERT INTO scientific_records (id, measurement) VALUES (?, ?)",
                ("private-coral-1", 3.5),
            )
    before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == (0 if expected == "preserved" else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if expected == "preserved" else "HOLD")
    assert (
        next(
            entry["status"] for entry in report["tables"] if entry["table"] == "scientific_records"
        )
        == expected
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral-1" not in json.dumps(report)
    assert before.read_bytes() == before_bytes
    assert after.read_bytes() == after_bytes


@pytest.mark.parametrize("candidate_delete", ["RESTRICT", "CASCADE", "SET NULL"])
def test_upgrade_preserves_scientific_foreign_key_delete_policy(
    tmp_path: Path, candidate_delete: str
) -> None:
    """Equal present rows cannot authorize orphaning or cascading later observations."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    for path, delete_action in ((before, "RESTRICT"), (after, candidate_delete)):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE scientific_records "
                "(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                f"FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE {delete_action})"
            )
            connection.execute("INSERT INTO projects (id) VALUES ('private-project')")
            connection.execute(
                "INSERT INTO scientific_records (id, project_id) VALUES (?, ?)",
                ("private-coral", "private-project"),
            )
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    valid = candidate_delete == "RESTRICT"
    assert code == (0 if valid else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if valid else "HOLD")
    assert next(
        entry["status"] for entry in report["tables"] if entry["table"] == "scientific_records"
    ) == ("preserved" if valid else "changed_foreign_key_contract")
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral" not in json.dumps(report)
    assert "private-project" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


@pytest.mark.parametrize(
    ("baseline_index", "candidate_index", "expected"),
    [
        (
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            "preserved",
        ),
        (
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            None,
            "changed_unique_index_contract",
        ),
        (
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            "INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            "changed_unique_index_contract",
        ),
        (
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)",
            "UNIQUE INDEX uq_species ON scientific_records(species COLLATE BINARY)",
            "changed_unique_index_contract",
        ),
        (
            "UNIQUE INDEX uq_species ON scientific_records(species) WHERE status = 'verified'",
            "UNIQUE INDEX uq_species ON scientific_records(species) WHERE status = 'draft'",
            "changed_unique_index_contract",
        ),
        (
            "UNIQUE INDEX uq_species ON scientific_records(lower(species))",
            "UNIQUE INDEX uq_species ON scientific_records(substr(species, 1, 1))",
            "changed_unique_index_contract",
        ),
    ],
)
def test_scientific_uniqueness_survives_migration(
    tmp_path: Path,
    baseline_index: str,
    candidate_index: str | None,
    expected: str,
) -> None:
    """Preserved old rows do not prove later duplicate observations are rejected."""
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    for path, definition in ((before, baseline_index), (after, candidate_index)):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records "
                "(id TEXT PRIMARY KEY, species TEXT, status TEXT NOT NULL)"
            )
            if definition is not None:
                connection.execute("CREATE " + definition)
            connection.executemany(
                "INSERT INTO scientific_records (id, species, status) VALUES (?, ?, ?)",
                [("private-1", "Swiftia", "verified"), ("private-2", "Thesea", "verified")],
            )
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == (0 if expected == "preserved" else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if expected == "preserved" else "HOLD")
    assert (
        next(
            entry["status"] for entry in report["tables"] if entry["table"] == "scientific_records"
        )
        == expected
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-1" not in json.dumps(report)
    assert "verified" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


def test_additional_unique_constraint_is_preservation_compatible(tmp_path: Path) -> None:
    """New science-specific uniqueness may be additive without deleting old guarantees."""
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id TEXT PRIMARY KEY, species TEXT, status TEXT)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX uq_species ON scientific_records(species COLLATE NOCASE)"
        )
        connection.execute(
            "INSERT INTO scientific_records VALUES ('private-science', 'Swiftia', 'verified')"
        )
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("CREATE UNIQUE INDEX uq_status ON scientific_records(status)")
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


@pytest.mark.parametrize(
    ("candidate_check", "expected"),
    [
        ("", "changed_check_constraint_contract"),
        ("CHECK (measurement >= -100)", "changed_check_constraint_contract"),
        ("CHECK (measurement > -100)", "changed_check_constraint_contract"),
        ("CHECK (measurement >= 0)", "preserved"),
        ("CHECK (measurement >= 0) CHECK (measurement < 100)", "preserved"),
    ],
)
def test_scientific_check_constraints_survive_migration(
    tmp_path: Path, candidate_check: str, expected: str
) -> None:
    """Identical measured data cannot excuse relaxed future CHECK enforcement."""
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    for path, check_sql in (
        (before, "CHECK (measurement >= 0)"),
        (after, candidate_check),
    ):
        with sqlite3.connect(path) as connection:
            # The default literal contains CHECK( but is not a DDL constraint.
            connection.execute(
                "CREATE TABLE scientific_records "
                "(id TEXT PRIMARY KEY, measurement REAL "
                + check_sql
                + ", note TEXT DEFAULT 'CHECK(not_a_constraint)')"
            )
            connection.execute(
                "INSERT INTO scientific_records (id, measurement) VALUES (?, ?)",
                ("private-coral", 3.5),
            )
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    valid = expected == "preserved"
    assert code == (0 if valid else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if valid else "HOLD")
    assert (
        next(
            entry["status"] for entry in report["tables"] if entry["table"] == "scientific_records"
        )
        == expected
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral" not in json.dumps(report)
    assert "not_a_constraint" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


def test_additive_column_preserves_existing_scientific_check(tmp_path: Path) -> None:
    """Extra columns do not invalidate unchanged CHECK predicates."""
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records "
            "(id TEXT PRIMARY KEY, measurement REAL CHECK (measurement >= 0))"
        )
        connection.execute("INSERT INTO scientific_records VALUES ('private-coral', 3.5)")
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("ALTER TABLE scientific_records ADD COLUMN note TEXT")
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 0, report["problems"]
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


@pytest.mark.parametrize(
    ("baseline_suffix", "candidate_suffix", "expected"),
    [
        (" STRICT", "", "changed_table_storage_contract"),
        (" WITHOUT ROWID", "", "changed_table_storage_contract"),
        (" STRICT", " STRICT", "preserved"),
        (" WITHOUT ROWID", " WITHOUT ROWID", "preserved"),
    ],
)
def test_scientific_storage_rules_survive_migration(
    tmp_path: Path, baseline_suffix: str, candidate_suffix: str, expected: str
) -> None:
    """Retain SQLite strict typing and rowid allocation behavior."""
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    for path, suffix in ((before, baseline_suffix), (after, candidate_suffix)):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records (id TEXT PRIMARY KEY, measurement REAL)" + suffix
            )
            connection.execute("INSERT INTO scientific_records VALUES ('private-coral', 3.5)")
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    valid = expected == "preserved"
    assert code == (0 if valid else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if valid else "HOLD")
    assert (
        next(
            entry["status"] for entry in report["tables"] if entry["table"] == "scientific_records"
        )
        == expected
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate


@pytest.mark.parametrize("table", ["scientific_records", "review_queue_item_events"])
@pytest.mark.parametrize(
    "mode",
    [
        "same",
        "formatted",
        "removed",
        "changed_event",
        "conditional",
        "inert_body",
        "additional_guard",
    ],
)
def test_protected_scientific_and_reviewer_triggers_survive_upgrade(
    tmp_path: Path, table: str, mode: str
) -> None:
    """Identical current rows must not conceal removal of future write safeguards."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    baseline = (
        f"CREATE TRIGGER preserve_original BEFORE UPDATE ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'private review and science rule'); END"
    )
    for path, candidate in ((before, False), (after, True)):
        with sqlite3.connect(path) as connection:
            connection.execute(
                f"CREATE TABLE {table} (id TEXT PRIMARY KEY, measurement_mm REAL NOT NULL)"
            )
            connection.execute(f"INSERT INTO {table} VALUES (?, ?)", ("private-coral-source", 3.5))
            statement: str | None = baseline
            if candidate:
                if mode == "removed":
                    statement = None
                elif mode == "changed_event":
                    statement = baseline.replace("BEFORE UPDATE", "BEFORE DELETE")
                elif mode == "conditional":
                    statement = baseline.replace(" BEGIN ", " WHEN NEW.measurement_mm < 0 BEGIN ")
                elif mode == "inert_body":
                    statement = baseline.replace(
                        "SELECT RAISE(ABORT, 'private review and science rule')",
                        "SELECT 1",
                    )
                elif mode == "formatted":
                    statement = baseline.replace(" BEFORE UPDATE ", "   before   update   ")
            if statement is not None:
                connection.execute(statement)
            if candidate and mode == "additional_guard":
                connection.execute(
                    f"CREATE TRIGGER preserve_new_delete BEFORE DELETE ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'new guard'); END"
                )
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    valid = mode in {"same", "formatted", "additional_guard"}
    assert code == (0 if valid else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if valid else "HOLD")
    assert next(entry["status"] for entry in report["tables"] if entry["table"] == table) == (
        "preserved" if valid else "changed_trigger_contract"
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral-source" not in json.dumps(report)
    assert "private review and science rule" not in json.dumps(report)
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize("storage", ["VIRTUAL", "STORED"])
@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("changed_factor", "changed_generated_column_contract"),
        ("changed_conditional_formula", "changed_generated_column_contract"),
        ("formatted_same_formula", "preserved"),
        ("additional_generated_column", "preserved"),
        ("unchanged", "preserved"),
    ],
)
def test_generated_scientific_formula_not_silently_changed_when_values_match(
    tmp_path: Path, storage: str, variant: str, expected: str
) -> None:
    """Zero/NULL historical data must not mask a changed future measurement formula."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    original_sql = (
        "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, "
        "raw_length REAL, derived_length REAL "
        f"GENERATED ALWAYS AS (raw_length * 2) {storage})"
    )
    candidate_sql = original_sql
    if variant == "changed_factor":
        candidate_sql = candidate_sql.replace("raw_length * 2", "raw_length * 3")
    elif variant == "changed_conditional_formula":
        candidate_sql = candidate_sql.replace(
            "raw_length * 2",
            "CASE WHEN raw_length IS NULL THEN NULL ELSE raw_length * 3 END",
        )
    elif variant == "formatted_same_formula":
        candidate_sql = candidate_sql.replace(
            "GENERATED ALWAYS AS (raw_length * 2)",
            "generated always as( raw_length  *   2 )",
        )
    elif variant == "additional_generated_column":
        candidate_sql = candidate_sql.replace(
            f" {storage})",
            f" {storage}, other_length REAL GENERATED ALWAYS AS (raw_length * 4) VIRTUAL)",
        )

    for path, sql in ((before, original_sql), (after, candidate_sql)):
        with sqlite3.connect(path) as connection:
            connection.execute(sql)
            connection.executemany(
                "INSERT INTO scientific_records (id, raw_length) VALUES (?, ?)",
                [(1, 0.0), (2, None)],
            )

    with sqlite3.connect(before) as original, sqlite3.connect(after) as candidate:
        projection = "SELECT id, raw_length, derived_length FROM scientific_records ORDER BY id"
        # Existing values can be identical even when future computations differ.
        assert original.execute(projection).fetchall() == candidate.execute(projection).fetchall()
    before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == (2 if expected != "preserved" else 0)
    assert report["status"] == ("HOLD" if expected != "preserved" else "PASS_PRESERVATION_ONLY")
    assert any(
        item["table"] == "scientific_records" and item["status"] == expected
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == before_bytes
    assert after.read_bytes() == after_bytes


def test_generated_scientific_formula_parsing_supports_quoted_column_name(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    for path, multiplier in ((before, 2), (after, 3)):
        with sqlite3.connect(path) as connection:
            connection.execute(
                'CREATE TABLE scientific_records ("raw length" REAL, '
                f'"derived length" REAL AS ("raw length" * {multiplier}) VIRTUAL)'
            )
            connection.execute('INSERT INTO scientific_records ("raw length") VALUES (0)')
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert any(
        item["table"] == "scientific_records"
        and item["status"] == "changed_generated_column_contract"
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False


@pytest.mark.parametrize(
    ("original", "candidate", "expected"),
    [
        ("TEXT COLLATE NOCASE", "TEXT COLLATE BINARY", "changed_column_collation_contract"),
        ("TEXT COLLATE NOCASE", "TEXT COLLATE RTRIM", "changed_column_collation_contract"),
        ("TEXT", "TEXT COLLATE NOCASE", "changed_column_collation_contract"),
        ("TEXT", "TEXT COLLATE BINARY", "preserved"),
        ("TEXT COLLATE NOCASE", 'TEXT COLLATE "nocase"', "preserved"),
        ("TEXT COLLATE NOCASE", "TEXT COLLATE NOCASE", "preserved"),
    ],
)
def test_protected_label_column_collation_preserved_for_future_observations(
    tmp_path: Path, original: str, candidate: str, expected: str
) -> None:
    """Existing equal observations cannot certify the next label comparison semantics."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    for path, declaration in ((before, original), (after, candidate)):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records "
                f"(id INTEGER PRIMARY KEY, label {declaration}, measurement REAL)"
            )
            connection.execute("INSERT INTO scientific_records VALUES (1, 'Coral-A', 3.5)")
    with sqlite3.connect(before) as a, sqlite3.connect(after) as b:
        assert (
            a.execute("SELECT * FROM scientific_records").fetchall()
            == b.execute("SELECT * FROM scientific_records").fetchall()
        )
        if expected != "preserved":
            original_matches = a.execute(
                "SELECT COUNT(*) FROM scientific_records WHERE label = 'coral-a'"
            ).fetchone()[0]
            candidate_matches = b.execute(
                "SELECT COUNT(*) FROM scientific_records WHERE label = 'coral-a'"
            ).fetchone()[0]
            if (original, candidate) != ("TEXT COLLATE NOCASE", "TEXT COLLATE RTRIM"):
                assert original_matches != candidate_matches
    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == (0 if expected == "preserved" else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if expected == "preserved" else "HOLD")
    assert any(
        item["table"] == "scientific_records" and item["status"] == expected
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "Coral-A" not in json.dumps(report)
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


def test_column_collation_does_not_confuse_nested_check_expression(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    statement = (
        "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, "
        "label TEXT CHECK (label COLLATE NOCASE <> ''), measurement REAL)"
    )
    for path in (before, after):
        with sqlite3.connect(path) as connection:
            connection.execute(statement)
            connection.execute("INSERT INTO scientific_records VALUES (1, 'Coral-A', 3.5)")
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True


@pytest.mark.parametrize(
    ("removed_level", "expected_missing"),
    [("none", 0), ("leaf", 1), ("tree", 2)],
)
def test_research_asset_empty_directory_preservation(
    tmp_path: Path, removed_level: str, expected_missing: int
) -> None:
    """Offline upgrade copies must retain empty scientific collection folders."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    private_collection = original / "study" / "unscored" / "future-observations"
    private_collection.mkdir(parents=True)
    (original / "study" / "coral.raw").write_bytes(b"unaltered observation")
    shutil.copytree(original, candidate)
    # Additional collections are allowed; dropping existing empty directories
    # should not masquerade as a successful full research-asset preservation.
    (candidate / "new-study").mkdir()
    if removed_level in ("leaf", "tree"):
        (candidate / "study" / "unscored" / "future-observations").rmdir()
    if removed_level == "tree":
        (candidate / "study" / "unscored").rmdir()
    old_db, new_db = before.read_bytes(), after.read_bytes()
    old_asset = (original / "study" / "coral.raw").read_bytes()

    code, report = _run(before, after, original, candidate)

    assert code == (0 if expected_missing == 0 else 2)
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if expected_missing == 0 else "HOLD")
    evidence = report["research_assets"]
    assert evidence["baseline_files"] == evidence["candidate_files"] == 1
    assert evidence["missing_files"] == evidence["changed_files"] == 0
    assert evidence["baseline_directories"] == 3
    assert evidence["candidate_directories"] == 4 - expected_missing
    assert evidence["missing_directories"] == expected_missing
    assert evidence["added_directories"] == 1
    assert ("research_directories_missing" in report["problems"]) == (expected_missing > 0)
    assert report["requires_researcher_approval"] is True
    assert report["upgrade_authorized"] is False
    for private_name in ("future-observations", "unscored", "coral.raw"):
        assert private_name not in json.dumps(report)
    assert before.read_bytes() == old_db
    assert after.read_bytes() == new_db
    assert (original / "study" / "coral.raw").read_bytes() == old_asset
    assert (candidate / "study" / "coral.raw").read_bytes() == old_asset


@pytest.mark.parametrize("scope", ["both", "candidate"])
@pytest.mark.parametrize("kind", ["file_case", "directory_case", "file_unicode"])
def test_research_asset_portable_name_collisions_fail_closed(
    tmp_path: Path, scope: str, kind: str
) -> None:
    """A portable upgrade must never collapse separate field-study assets."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    (original / "original-observation.bin").write_bytes(b"private baseline observation")
    shutil.copytree(original, candidate)
    names = {
        "file_case": ("Frame.JPG", "frame.jpg"),
        "directory_case": ("Study", "study"),
        "file_unicode": ("caf\u00e9.raw", "cafe\u0301.raw"),
    }
    first_name, second_name = names[kind]
    roots = (original, candidate) if scope == "both" else (candidate,)
    for root in roots:
        first, second = root / first_name, root / second_name
        if kind == "directory_case":
            first.mkdir()
        else:
            first.write_bytes(b"first independent image")
        # Case-insensitive/normalizing hosts cannot construct this synthetic
        # collision; the portable-name guard is exercised on capable hosts.
        if second.exists():
            pytest.skip("filesystem already aliases these names")
        if kind == "directory_case":
            second.mkdir()
        else:
            second.write_bytes(b"second independent image")
        assert first != second

    before_db, after_db = before.read_bytes(), after.read_bytes()
    original_bytes = (original / "original-observation.bin").read_bytes()
    code, report = _run(before, after, original, candidate)

    assert code == 2
    assert report["status"] == "HOLD"
    assert "asset_portable_path_collision" in report["problems"]
    assert report["requires_researcher_approval"] is True
    assert report["upgrade_authorized"] is False
    report_text = json.dumps(report)
    for private_name in ("original-observation", first_name, second_name):
        assert private_name not in report_text
    assert before.read_bytes() == before_db
    assert after.read_bytes() == after_db
    assert (original / "original-observation.bin").read_bytes() == original_bytes
    assert (candidate / "original-observation.bin").read_bytes() == original_bytes


def test_research_asset_similarly_named_folders_are_not_ambiguous(tmp_path: Path) -> None:
    """Distinct portable names and additive directories remain compatible."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    (original / "Study_A").mkdir(parents=True)
    (original / "Study_B").mkdir()
    (original / "Study_A" / "frame_1.raw").write_bytes(b"first")
    (original / "Study_B" / "frame_2.raw").write_bytes(b"second")
    candidate = tmp_path / "candidate"
    shutil.copytree(original, candidate)
    (candidate / "new-study").mkdir()
    code, report = _run(before, after, original, candidate)

    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["research_assets"]["missing_files"] == 0
    assert report["research_assets"]["missing_directories"] == 0


@pytest.mark.skipif(os.name == "nt", reason="Win32 cannot create invalid asset names")
@pytest.mark.parametrize("scope", ["both", "candidate"])
@pytest.mark.parametrize(
    "relative_path",
    [
        "CON.raw",
        "com1.dat",
        "LPT¹.log",
        "sample.raw.",
        "sample.raw ",
        "sample:raw",
        "bad?.raw",
        "NUL/field.raw",
        "study /frame.raw",
        "\\x01field.raw",
    ],
)
def test_windows_unrepresentable_research_asset_paths_fail_closed(
    tmp_path: Path, scope: str, relative_path: str
) -> None:
    """Equal hashes cannot approve a copy whose field-study names Windows cannot preserve."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    baseline_file = original / "original-observation.bin"
    baseline_file.write_bytes(b"unchanged private biological observation")
    shutil.copytree(original, candidate)
    for root in (original, candidate) if scope == "both" else (candidate,):
        invalid = root / relative_path
        invalid.parent.mkdir(parents=True, exist_ok=True)
        invalid.write_bytes(b"additional private field data")

    before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
    original_bytes = baseline_file.read_bytes()
    code, report = _run(before, after, original, candidate)

    assert code == 2
    assert report["status"] == "HOLD"
    assert "asset_windows_incompatible_name" in report["problems"]
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert relative_path not in json.dumps(report)
    assert "original-observation.bin" not in json.dumps(report)
    assert before.read_bytes() == before_bytes
    assert after.read_bytes() == after_bytes
    assert baseline_file.read_bytes() == original_bytes
    assert (candidate / "original-observation.bin").read_bytes() == original_bytes


def test_portable_windows_research_asset_names_remain_supported(tmp_path: Path) -> None:
    """Do not reject legitimate multi-dot filenames or COM10/LPT10 observations."""
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = tmp_path / "original"
    (original / "Study_A").mkdir(parents=True)
    (original / "Study_A" / "reef.v1.6.raw").write_bytes(b"original")
    (original / "COM10.raw").write_bytes(b"ordinary specimen name")
    candidate = tmp_path / "candidate"
    shutil.copytree(original, candidate)
    (candidate / "LPT10.raw").write_bytes(b"new field image")
    (candidate / "new-study").mkdir()

    code, report = _run(before, after, original, candidate)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["research_assets"]["missing_files"] == 0
    assert report["research_assets"]["added_files"] == 1
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True


@pytest.mark.parametrize(
    ("baseline_autoincrement", "candidate_autoincrement", "expected_hold"),
    [
        (True, False, True),
        (False, True, True),
        (True, True, False),
        (False, False, False),
    ],
)
@pytest.mark.parametrize("populated", [False, True])
def test_empty_and_populated_scientific_autoincrement_contract(
    tmp_path: Path,
    baseline_autoincrement: bool,
    candidate_autoincrement: bool,
    expected_hold: bool,
    populated: bool,
) -> None:
    """Matching current rows do not prove future biological IDs cannot be reused.

    Empty tables have no sqlite_sequence entry even when they were declared
    AUTOINCREMENT. A default literal and quoted name containing the keyword
    must not produce false positives when the actual contract is unchanged.
    """
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    for path, use_autoincrement in (
        (before, baseline_autoincrement),
        (after, candidate_autoincrement),
    ):
        modifier = " AUTOINCREMENT" if use_autoincrement else ""
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records ("
                f"id INTEGER PRIMARY KEY{modifier}, "
                "\"autoincrement\" TEXT DEFAULT 'AUTOINCREMENT', "
                "measurement_mm REAL)"
            )
            if populated:
                connection.execute(
                    'INSERT INTO scientific_records (id, "autoincrement", measurement_mm) '
                    "VALUES (7, 'private-coral', 0.0)"
                )

    with sqlite3.connect(before) as old, sqlite3.connect(after) as new:
        assert list(old.execute("PRAGMA table_xinfo(scientific_records)")) == list(
            new.execute("PRAGMA table_xinfo(scientific_records)")
        )
        assert (
            old.execute("SELECT * FROM scientific_records").fetchall()
            == new.execute("SELECT * FROM scientific_records").fetchall()
        )
        if not populated:
            # The existing sequence-counter guard alone cannot distinguish
            # the two declarations before any biological observation exists.
            for connection in (old, new):
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'"
                ).fetchone():
                    assert connection.execute("SELECT * FROM sqlite_sequence").fetchall() == []

    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    expected_status = "HOLD" if expected_hold else "PASS_PRESERVATION_ONLY"
    assert code == (2 if expected_hold else 0)
    assert report["status"] == expected_status
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    item = next(row for row in report["tables"] if row["table"] == "scientific_records")
    assert item["status"] == ("changed_autoincrement_contract" if expected_hold else "preserved")
    if expected_hold:
        assert "scientific_records:changed_autoincrement_contract" in report["problems"]
    else:
        assert not report["problems"]
    public = json.dumps(report)
    assert "private-coral" not in public
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


# Source tables implemented in earlier versions must survive the offline
# upgrade even when saved reviewed QC workflows remain byte-for-byte intact.
_MEDIA_SOURCE_TABLES = (
    "images",
    "videos",
    "video_tracks",
    "model_registrations",
    "prediction_proposals",
    "image_labels",
    "quality_control_issues",
    "geo_referenced_observations",
    "active_learning_rounds",
)


@pytest.mark.parametrize("table", _MEDIA_SOURCE_TABLES)
def test_biological_media_source_lineage_protected(tmp_path: Path, table: str) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    with sqlite3.connect(before) as connection:
        connection.execute(
            f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, source_evidence BLOB NOT NULL)'
        )
        connection.execute(
            f'INSERT INTO "{table}" VALUES (?, ?)',
            ("private-coral-site-001", b"\x00original-digest\xff"),
        )
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(
            f'UPDATE "{table}" SET source_evidence = ? WHERE id = ?',
            (b"\x00modified-digest\xff", "private-coral-site-001"),
        )
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 2
    assert report["status"] == "HOLD"
    assert report["protected_tables_examined"] == 6
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    statuses = {item["table"]: item["status"] for item in report["tables"]}
    assert statuses[table] == "changed_records"
    assert statuses["workflow_graph_records"] == "preserved"
    assert statuses["review_queue_item_events"] == "preserved"
    public_report = json.dumps(report)
    assert "private-coral-site-001" not in public_report
    assert "original-digest" not in public_report
    assert "modified-digest" not in public_report
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize("table", ("images", "videos"))
def test_removed_biological_media_source_table_requires_hold(tmp_path: Path, table: str) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    with sqlite3.connect(before) as connection:
        connection.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')
        connection.execute(f'INSERT INTO "{table}" VALUES (?)', ("coral-source",))
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(f'DROP TABLE "{table}"')
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    statuses = {item["table"]: item["status"] for item in report["tables"]}
    assert statuses[table] == "removed_table"
    assert "coral-source" not in json.dumps(report)
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


def test_new_candidate_only_media_source_table_remains_additive(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("CREATE TABLE videos (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
        connection.execute("INSERT INTO videos VALUES (?, ?)", ("new-video", "synthetic-sha"))
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["protected_tables_examined"] == 5
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    statuses = {item["table"]: item["status"] for item in report["tables"]}
    assert statuses["videos"] == "not_in_baseline"
    assert not report["problems"]
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


# Independent inventory from the existing pose, skeleton, and behavior SQLAlchemy
# models; intentionally NOT imported from the verifier's protected-table list.
POSE_BEHAVIOR_LINEAGE_TABLES = (
    "pose_landmark_schemas",
    "pose_landmark_schema_revisions",
    "pose_model_schema_bindings",
    "pose_landmark_tracks",
    "pose_landmark_observations",
    "pose_landmark_association_decisions",
    "pose_landmark_association_candidates",
    "pose_landmark_corrections",
    "pose_landmark_identity_breaks",
    "pose_training_datasets",
    "pose_training_dataset_items",
    "pose_active_learning_rounds",
    "pose_active_learning_candidates",
    "skeleton_analysis_revisions",
    "behavior_ethogram_revisions",
    "behavior_state_definitions",
    "behavior_bout_revisions",
    "behavior_classifier_models",
    "behavior_predictions",
)


def _seed_pose_behavior_lineage(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for table in POSE_BEHAVIOR_LINEAGE_TABLES:
            connection.execute(
                f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, evidence BLOB NOT NULL)'
            )
            connection.execute(
                f'INSERT INTO "{table}" (id, evidence) VALUES (?, ?)',
                ("private-field-observation", b"reviewed biological evidence"),
            )


@pytest.mark.parametrize("changed_table", POSE_BEHAVIOR_LINEAGE_TABLES)
def test_existing_pose_behavior_evidence_cannot_change_unnoticed(
    tmp_path: Path, changed_table: str
) -> None:
    """A saved pose/behavior measurement must not disappear behind a clean QC graph."""
    before = tmp_path / "original.sqlite"
    after = tmp_path / "upgraded.sqlite"
    _seed_pose_behavior_lineage(before)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(
            f'UPDATE "{changed_table}" SET evidence = ?',
            (b"altered biological measurement",),
        )
    original_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert report["protected_tables_examined"] == len(POSE_BEHAVIOR_LINEAGE_TABLES)
    assert changed_table + ":changed_records" in report["problems"]
    assert (
        next(item["status"] for item in report["tables"] if item["table"] == changed_table)
        == "changed_records"
    )
    assert "private-field-observation" not in json.dumps(report)
    assert "reviewed biological evidence" not in json.dumps(report)
    assert "altered biological measurement" not in json.dumps(report)
    assert before.read_bytes() == original_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize(
    ("changed_table", "mutation", "expected"),
    [
        ("pose_landmark_observations", "DROP TABLE pose_landmark_observations", "removed_table"),
        (
            "behavior_bout_revisions",
            "ALTER TABLE behavior_bout_revisions ADD COLUMN temporary_note TEXT",
            "preserved",
        ),
    ],
)
def test_pose_and_behavior_lineage_structure_or_addition(
    tmp_path: Path, changed_table: str, mutation: str, expected: str
) -> None:
    before = tmp_path / "original.sqlite"
    after = tmp_path / "upgraded.sqlite"
    _seed_pose_behavior_lineage(before)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute(mutation)
    original_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    entry = next(item for item in report["tables"] if item["table"] == changed_table)
    assert entry["status"] == expected
    assert report["status"] == ("PASS_PRESERVATION_ONLY" if expected == "preserved" else "HOLD")
    assert code == (0 if expected == "preserved" else 2)
    assert report["requires_researcher_approval"] is True
    assert report["upgrade_authorized"] is False
    assert before.read_bytes() == original_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize("aliased_copy", ["baseline", "candidate"])
def test_database_copy_rejects_symlinked_parent_before_resolve(
    tmp_path: Path, aliased_copy: str
) -> None:
    """Two identical databases are not independent when either path uses an alias."""
    baseline = tmp_path / "before.sqlite"
    candidate = tmp_path / "after.sqlite"
    _seed(baseline)
    shutil.copyfile(baseline, candidate)
    private_parent = tmp_path / "private-research-directory"
    private_parent.mkdir()
    real_copy = private_parent / "private-scientific-data.sqlite"
    shutil.copyfile(baseline, real_copy)
    alias = tmp_path / "external-parent-alias"
    try:
        alias.symlink_to(private_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("host does not permit directory symlinks")
    hidden_copy = alias / real_copy.name
    assert not hidden_copy.is_symlink()
    if aliased_copy == "baseline":
        baseline = hidden_copy
    else:
        candidate = hidden_copy
    old_bytes, new_bytes = baseline.read_bytes(), candidate.read_bytes()
    code, evidence = _run(baseline, candidate)
    assert code == 2
    assert evidence["status"] == "HOLD"
    assert evidence["problems"] == ["database_copy_symlink_not_allowed"]
    assert evidence["requires_researcher_approval"] is True
    assert evidence["upgrade_authorized"] is False
    assert "private-scientific-data" not in json.dumps(evidence)
    assert "private-research-directory" not in json.dumps(evidence)
    assert baseline.read_bytes() == old_bytes
    assert candidate.read_bytes() == new_bytes


@pytest.mark.parametrize("aliased_copy", ["baseline", "candidate"])
def test_database_copy_rejects_unscanned_external_hardlink(
    tmp_path: Path, aliased_copy: str
) -> None:
    """An unrelated third hardlink can still modify supposedly offline science."""
    baseline = tmp_path / "before.sqlite"
    candidate = tmp_path / "after.sqlite"
    _seed(baseline)
    shutil.copyfile(baseline, candidate)
    target = baseline if aliased_copy == "baseline" else candidate
    outside = tmp_path / "private-external-backup.sqlite"
    try:
        outside.hardlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("host does not permit hardlinks")
    if target.stat().st_nlink < 2:
        pytest.skip("host does not report hardlink counts")
    old_bytes, new_bytes = baseline.read_bytes(), candidate.read_bytes()
    code, evidence = _run(baseline, candidate)
    assert code == 2
    assert evidence["status"] == "HOLD"
    assert evidence["problems"] == ["database_copy_hardlinks_not_independent"]
    assert evidence["requires_researcher_approval"] is True
    assert evidence["upgrade_authorized"] is False
    assert "private-external-backup" not in json.dumps(evidence)
    assert baseline.read_bytes() == old_bytes
    assert candidate.read_bytes() == new_bytes
    assert outside.read_bytes() == target.read_bytes()


def test_database_copy_rejects_direct_symlink_and_noncanonical_path(tmp_path: Path) -> None:
    baseline = tmp_path / "before.sqlite"
    candidate = tmp_path / "after.sqlite"
    _seed(baseline)
    shutil.copyfile(baseline, candidate)
    alias = tmp_path / "private-link.sqlite"
    try:
        alias.symlink_to(candidate)
    except (OSError, NotImplementedError):
        pytest.skip("host does not permit file symlinks")
    code, evidence = _run(baseline, alias)
    assert code == 2
    assert evidence["problems"] == ["database_copy_symlink_not_allowed"]

    intermediate = tmp_path / "existing"
    intermediate.mkdir()
    noncanonical = intermediate / ".." / "before.sqlite"
    code, evidence = _run(noncanonical, candidate)
    assert code == 2
    assert evidence["status"] == "HOLD"
    assert evidence["problems"] == ["database_copy_noncanonical_path"]
    assert evidence["upgrade_authorized"] is False

