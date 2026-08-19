"""Strict structural validation for ReefVision video-track CSV imports."""

from __future__ import annotations

import csv
import io

from reefvision.domain.errors import ValidationError

REEFVISION_TRACK_CSV_COLUMNS = (
    "track_number",
    "frame",
    "label_class_id",
    "label_class_name",
    "x",
    "y",
    "width",
    "height",
    "confidence",
    "interpolation",
    "status",
    "source_track_id",
    "source_model_id",
    "source_job_id",
)


def validate_reefvision_track_csv_shape(content: str) -> None:
    """Reject ambiguous CSV structure before semantic track parsing begins.

    ``csv.DictReader`` otherwise silently collapses duplicate headers and places
    overflow cells under a ``None`` key. Both behaviors are dangerous for a
    scientific interchange format because the imported value may no longer be
    traceable to a unique source column.
    """

    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationError("ReefVision track CSV is empty") from exc

    normalized_header = [value.strip() for value in header]
    if any(not value for value in normalized_header):
        raise ValidationError("ReefVision track CSV headers must not be blank")
    duplicates = sorted({name for name in normalized_header if normalized_header.count(name) > 1})
    if duplicates:
        raise ValidationError(
            "ReefVision track CSV contains duplicate headers: " + ", ".join(duplicates)
        )

    expected = list(REEFVISION_TRACK_CSV_COLUMNS)
    missing = sorted(set(expected) - set(normalized_header))
    unexpected = sorted(set(normalized_header) - set(expected))
    if missing:
        raise ValidationError(
            "ReefVision track CSV is missing required columns: " + ", ".join(missing)
        )
    if unexpected:
        raise ValidationError(
            "ReefVision track CSV contains unsupported columns: " + ", ".join(unexpected)
        )
    if normalized_header != expected:
        raise ValidationError("ReefVision track CSV columns must use the canonical export order")

    expected_width = len(expected)
    for row_number, row in enumerate(reader, start=2):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != expected_width:
            raise ValidationError(
                f"ReefVision track CSV row {row_number} has {len(row)} columns; "
                f"expected {expected_width}"
            )
