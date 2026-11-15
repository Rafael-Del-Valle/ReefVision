"""Non-destructive, source-projection preservation checks for 1.1/1.6 convergence."""

import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

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

    assert code == 0
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

    monkeypatch.setitem(
        compare.__globals__, "_asset_inventory", mutate_after_candidate_scan
    )
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
        ValueError, match="asset_(symlink_not_allowed|changed_during_inspection)"
    ) as error:
        scan(root)
    assert swapped
    assert "external-research.raw" not in str(error.value)
    assert external.read_bytes() == b"private unrelated research"
