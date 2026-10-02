"""Self-verifying export package for one persisted skeleton analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from reefvision.schemas.skeletonization import SkeletonAnalysisRevisionResponse

EXPORT_SCHEMA_VERSION = "skeleton-export-0001"
CHUNK_SIZE = 1024 * 1024


def skeleton_export_stem(analysis_id: str) -> str:
    return f"skeleton-{_token(analysis_id)}"


def _token(value: str) -> str:
    import base64

    raw = UUID(value).bytes
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(rows)
    headers = list(dict.fromkeys(key for row in materialized for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(materialized)


def _pixel_rows(points: list[Any]) -> list[dict[str, int]]:
    return [{"x": point.x, "y": point.y} for point in points]


def _edge_rows(edges: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "branch_id": edge.id,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "path_pixel_count": edge.path_pixel_count,
            "boundary_to_boundary_length_pixels": (edge.boundary_to_boundary_length_pixels),
            "node_to_node_length_pixels": edge.node_to_node_length_pixels,
            "length_physical": edge.length_physical,
            "is_cycle": edge.is_cycle,
        }
        for edge in edges
    ]


def _angle_rows(angles: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "junction_id": angle.junction_id,
            "first_branch_id": angle.first_branch_id,
            "second_branch_id": angle.second_branch_id,
            "angle_degrees": angle.angle_degrees,
        }
        for angle in angles
    ]


def verify_skeleton_export(package: Path) -> dict[str, Any]:
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "checked_files": 0,
            "errors": [f"Manifest unavailable: {exc}"],
        }

    errors: list[str] = []
    if manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
        errors.append("Unsupported skeleton export schema version")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        return {
            "valid": False,
            "checked_files": 0,
            "errors": ["Manifest files must be a list"],
        }

    package_root = package.resolve()
    expected: set[str] = set()
    checked = 0
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("Manifest file entry must be an object")
            continue
        relative = str(entry.get("relative_path", ""))
        path = (package / relative).resolve()
        if not relative or Path(relative).is_absolute() or not path.is_relative_to(package_root):
            errors.append(f"Unsafe manifest path: {relative}")
            continue
        expected.add(Path(relative).as_posix())
        if not path.is_file():
            errors.append(f"Missing file: {relative}")
            continue
        checked += 1
        if path.stat().st_size != entry.get("size_bytes"):
            errors.append(f"Size mismatch: {relative}")
        if _sha256(path) != entry.get("sha256"):
            errors.append(f"Checksum mismatch: {relative}")

    actual = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "checksums.sha256"}
    }
    for relative in sorted(actual - expected):
        errors.append(f"Unlisted file: {relative}")

    return {
        "valid": not errors,
        "checked_files": checked,
        "errors": errors,
    }


def build_skeleton_export(
    *,
    export_root: Path,
    record: SkeletonAnalysisRevisionResponse,
) -> dict[str, Any]:
    """Create an atomic directory + ZIP with reproducibility metadata."""

    export_root.mkdir(parents=True, exist_ok=True)
    stem = skeleton_export_stem(record.id)
    final_dir = export_root / stem
    archive = export_root / f"{stem}.zip"
    shutil.rmtree(final_dir, ignore_errors=True)
    archive.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="rv-skeleton-",
        dir=export_root,
    ) as temporary:
        package = Path(temporary) / stem
        package.mkdir()
        data = package / "data"
        data.mkdir()

        analysis_path = data / "analysis.json"
        provenance_path = data / "provenance.json"
        summary_path = data / "summary.csv"
        raw_pixels_path = data / "raw_skeleton_pixels.csv"
        pruned_pixels_path = data / "pruned_skeleton_pixels.csv"
        final_pixels_path = data / "final_skeleton_pixels.csv"
        raw_edges_path = data / "raw_branches.csv"
        pruned_edges_path = data / "pruned_branches.csv"
        final_edges_path = data / "final_branches.csv"
        raw_angles_path = data / "raw_branch_angles.csv"
        pruned_angles_path = data / "pruned_branch_angles.csv"
        final_angles_path = data / "final_branch_angles.csv"

        _write_json(analysis_path, record.model_dump(mode="json"))
        _write_json(
            provenance_path,
            {
                "schema_version": EXPORT_SCHEMA_VERSION,
                "analysis_id": record.id,
                "analysis_series_id": record.analysis_series_id,
                "analysis_revision": record.analysis_revision,
                "supersedes_analysis_id": record.supersedes_analysis_id,
                "source_kind": record.source_kind,
                "mask_annotation_id": record.mask_annotation_id,
                "mask_revision": record.mask_revision,
                "input_mask_sha256": record.input_mask_sha256,
                "calibration_sha256": record.calibration_sha256,
                "parameters_sha256": record.parameters_sha256,
                "result_sha256": record.result_sha256,
                "algorithm": record.algorithm,
                "algorithm_version": record.algorithm_version,
                "terminal_spur_max_length_pixels": (record.terminal_spur_max_length_pixels),
                "review_status": record.review_status,
                "reviewed_by": record.reviewed_by,
                "reviewed_at": (
                    record.reviewed_at.isoformat() if record.reviewed_at is not None else None
                ),
                "review_note": record.review_note,
                "correction": record.correction,
                "stale": record.stale,
            },
        )
        result = record.result
        _write_csv(
            summary_path,
            [
                {
                    "analysis_id": record.id,
                    "analysis_revision": record.analysis_revision,
                    "source_kind": record.source_kind,
                    "final_skeleton_source": result.final_skeleton_source,
                    "physical_unit": result.physical_unit,
                    "raw_branch_count": result.raw_branch_count,
                    "pruned_branch_count": result.pruned_branch_count,
                    "final_branch_count": result.final_branch_count,
                    "raw_tle_pixels": result.raw_total_linear_extension_pixels,
                    "pruned_tle_pixels": (result.pruned_total_linear_extension_pixels),
                    "final_tle_pixels": (result.final_total_linear_extension_pixels),
                    "raw_tle_physical": (result.raw_total_linear_extension_physical),
                    "pruned_tle_physical": (result.pruned_total_linear_extension_physical),
                    "final_tle_physical": (result.final_total_linear_extension_physical),
                    "raw_longest_path_pixels": result.raw_longest_path_pixels,
                    "pruned_longest_path_pixels": (result.pruned_longest_path_pixels),
                    "final_longest_path_pixels": (result.final_longest_path_pixels),
                    "length_calibration_method": (result.length_calibration_method),
                    "branch_angle_space": result.branch_angle_space,
                }
            ],
        )
        _write_csv(raw_pixels_path, _pixel_rows(result.raw_skeleton_pixels))
        _write_csv(
            pruned_pixels_path,
            _pixel_rows(result.pruned_skeleton_pixels),
        )
        _write_csv(
            final_pixels_path,
            _pixel_rows(result.final_skeleton_pixels),
        )
        _write_csv(raw_edges_path, _edge_rows(result.graph_edges))
        _write_csv(
            pruned_edges_path,
            _edge_rows(result.pruned_graph_edges),
        )
        _write_csv(
            final_edges_path,
            _edge_rows(result.final_graph_edges),
        )
        _write_csv(
            raw_angles_path,
            _angle_rows(result.raw_branch_angles),
        )
        _write_csv(
            pruned_angles_path,
            _angle_rows(result.pruned_branch_angles),
        )
        _write_csv(
            final_angles_path,
            _angle_rows(result.final_branch_angles),
        )

        files = sorted(path for path in package.rglob("*") if path.is_file())
        entries = [
            {
                "relative_path": path.relative_to(package).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ]
        manifest = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "analysis_id": record.id,
            "analysis_series_id": record.analysis_series_id,
            "analysis_revision": record.analysis_revision,
            "result_sha256": record.result_sha256,
            "files": entries,
            "excluded_from_manifest": [
                "manifest.json",
                "checksums.sha256",
            ],
        }
        manifest_path = package / "manifest.json"
        _write_json(manifest_path, manifest)

        checksum_rows = [f"{entry['sha256']}  {entry['relative_path']}" for entry in entries]
        checksum_rows.append(f"{_sha256(manifest_path)}  manifest.json")
        (package / "checksums.sha256").write_text(
            "\n".join(checksum_rows) + "\n",
            encoding="utf-8",
        )
        verification = verify_skeleton_export(package)
        if not verification["valid"]:
            raise RuntimeError(
                "Skeleton export verification failed: " + "; ".join(verification["errors"])
            )
        package.rename(final_dir)

    archive_path = Path(
        shutil.make_archive(
            str(final_dir),
            "zip",
            root_dir=final_dir.parent,
            base_dir=final_dir.name,
        )
    )
    return {
        "package_dir": final_dir,
        "archive_path": archive_path,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": _sha256(archive_path),
        "manifest_sha256": _sha256(final_dir / "manifest.json"),
    }
