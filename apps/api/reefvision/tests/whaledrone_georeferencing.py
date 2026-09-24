"""Read-only developer tooling for the published WhaleDrone layout (not shipped)."""

import csv
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.validation import GeoreferenceValidationPoint
from reefvision.tests.whaledrone import find_whaledrone_srt


@dataclass(frozen=True)
class WhaleDroneValidationClip:
    video_path: Path
    srt_path: Path
    annotation_path: Path
    dvm_video_name: str
    project: str


def _basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def select_validation_clip(
    root: Path, *, video_name: str | None = None
) -> WhaleDroneValidationClip:
    """Resolve the authoritative index; reject duplicate internal-name mappings.

    Source paths in Directory_file are intentionally ignored. Only documented
    filenames under this external root are read. No filenames are guessed from
    drone timestamps or annotation coordinates.
    """
    index = root / "dataset_index.xlsx"
    if not index.is_file():
        raise FileNotFoundError("External dataset_index.xlsx is unavailable")
    try:
        book = load_workbook(index, read_only=True, data_only=True)
        try:
            sheet = book["filelist"]
            rows = sheet.iter_rows(values_only=True)
            headers = [str(value) for value in next(rows)]
            required = {"video_ID", "flight_ID", "DVM_video_name", "annotated"}
            if not required.issubset(headers):
                raise ValidationError("WhaleDrone index is missing required mapping columns")
            entries = [dict(zip(headers, row, strict=False)) for row in rows]
        finally:
            book.close()
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        raise ValidationError("Malformed WhaleDrone dataset index") from exc
    candidates: list[tuple[str, str, str]] = []
    mappings: dict[tuple[str, str], set[str]] = {}
    for entry in entries:
        original = str(entry.get("video_ID") or "")
        internal = _basename(str(entry.get("DVM_video_name") or ""))
        flight = _basename(str(entry.get("flight_ID") or ""))
        if not internal or not original.lower().endswith(".mp4") or not flight:
            continue
        if original != _basename(original):
            raise ValidationError("WhaleDrone video_ID must be a filename, not an external path")
        mappings.setdefault((flight, internal), set()).add(original)
        if str(entry.get("annotated", "")).casefold() == "yes":
            candidates.append((original, internal, flight))
    ambiguity = False
    for original, internal, flight in sorted(set(candidates)):
        if video_name is not None and original.casefold() != video_name.casefold():
            continue
        if video_name is None and len(mappings[(flight, internal)]) != 1:
            ambiguity = True
            continue
        locations = [
            path
            for path in (
                root / "videos" / Path(flight).stem / original,
                root / "videos" / original,
            )
            if path.is_file()
        ]
        if len(locations) > 1:
            raise ValidationError("Ambiguous external video locations for the selected mapping")
        if not locations:
            continue
        video = locations[0]
        sidecar = find_whaledrone_srt(root, video)
        annotation = root / "annotations" / f"annotations_{Path(flight).stem}.csv"
        if sidecar is not None and annotation.is_file():
            return WhaleDroneValidationClip(video, sidecar, annotation, internal, Path(flight).stem)
    if ambiguity:
        raise ValidationError(
            "No unambiguous annotated video mapping is available; review dataset index"
        )
    raise FileNotFoundError("No complete annotated video/SRT/annotation resources found")


def load_validation_points(
    clip: WhaleDroneValidationClip, *, frame_base: int, max_samples: int = 100
) -> list[GeoreferenceValidationPoint]:
    if frame_base not in {0, 1} or isinstance(frame_base, bool):
        raise ValidationError("Annotation frame base must be explicitly 0 or 1")
    if not isinstance(max_samples, int) or isinstance(max_samples, bool) or max_samples < 1:
        raise ValidationError("Validation sample limit must be a positive integer")
    points = []
    try:
        with clip.annotation_path.open(encoding="utf-8-sig", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream), start=2):
                if None in row or any(value is None for value in row.values()):
                    raise ValidationError(f"Malformed annotation row {index}: wrong column count")
                if _basename(row.get("video", "")) != clip.dvm_video_name:
                    continue
                # Use points, not vector-centroid geography, for direct pixel validation.
                if row.get("length", "").strip().casefold() not in {"", "na", "nan"}:
                    continue
                frame = int(row["frame"])
                values: dict[str, object] = {
                    "point_id": f"{index}:{row.get('name', '')}",
                    "frame_index": frame - frame_base,
                    "pixel_x": float(row["image_x"]),
                    "pixel_y": float(row["image_y"]),
                    "latitude": float(row["lat"]),
                    "longitude": float(row["lon"]),
                }
                for column, field in (
                    ("height", "reference_height_m"),
                    ("pitch", "reference_pitch_deg"),
                ):
                    if row.get(column, "").strip().casefold() not in {"", "na", "nan"}:
                        values[field] = float(row[column])
                points.append(GeoreferenceValidationPoint.model_validate(values))
    except (OSError, KeyError, TypeError, ValueError, SchemaError) as exc:
        raise ValidationError("Malformed WhaleDrone point annotation or frame convention") from exc
    if not points:
        raise ValidationError("No native point annotations match the selected clip")
    points.sort(key=lambda point: (point.frame_index, point.point_id))
    if len(points) <= max_samples:
        return points
    if max_samples == 1:
        return [points[0]]
    # Span the clip deterministically; do not select points by observed residual.
    return [points[round(i * (len(points) - 1) / (max_samples - 1))] for i in range(max_samples)]
