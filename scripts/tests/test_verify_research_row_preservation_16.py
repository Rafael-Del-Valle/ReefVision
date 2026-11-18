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
    expected = "changed_records" if candidate == "changed_expression" else "removed_columns"
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
    assert report["status"] == (
        "PASS_PRESERVATION_ONLY" if expected == "preserved" else "HOLD"
    )
    assert next(
        entry["status"]
        for entry in report["tables"]
        if entry["table"] == "scientific_records"
    ) == expected
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
        entry["status"]
        for entry in report["tables"]
        if entry["table"] == "scientific_records"
    ) == ("preserved" if valid else "changed_foreign_key_contract")
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert "private-coral" not in json.dumps(report)
    assert "private-project" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate
