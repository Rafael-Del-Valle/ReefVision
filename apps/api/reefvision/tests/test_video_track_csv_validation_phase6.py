from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.video_track_csv_validation import (
    REEFVISION_TRACK_CSV_COLUMNS,
    validate_reefvision_track_csv_shape,
)


def _row() -> list[str]:
    return [
        "1",
        "0",
        "class-id",
        "Fish",
        "10",
        "20",
        "30",
        "15",
        "0.9",
        "linear",
        "verified",
        "source-track",
        "source-model",
        "source-job",
    ]


def _csv(header: list[str], rows: list[list[str]]) -> str:
    return ",".join(header) + "\n" + "\n".join(",".join(row) for row in rows) + "\n"


def test_track_csv_shape_accepts_only_canonical_export_shape() -> None:
    validate_reefvision_track_csv_shape(
        [].__class__ and _csv(list(REEFVISION_TRACK_CSV_COLUMNS), [_row()])
    )


@pytest.mark.parametrize(
    ("header", "row", "message"),
    [
        (
            [*REEFVISION_TRACK_CSV_COLUMNS[:-1], "source_model_id"],
            _row(),
            "duplicate headers",
        ),
        (
            [*REEFVISION_TRACK_CSV_COLUMNS, "unexpected"],
            [*_row(), "extra"],
            "unsupported columns",
        ),
        (
            [
                REEFVISION_TRACK_CSV_COLUMNS[1],
                REEFVISION_TRACK_CSV_COLUMNS[0],
                *REEFVISION_TRACK_CSV_COLUMNS[2:],
            ],
            _row(),
            "canonical export order",
        ),
        (
            list(REEFVISION_TRACK_CSV_COLUMNS),
            [*_row(), "overflow"],
            "expected 14",
        ),
        (
            list(REEFVISION_TRACK_CSV_COLUMNS),
            _row()[:-1],
            "expected 14",
        ),
    ],
)
def test_track_csv_shape_rejects_ambiguous_or_noncanonical_rows(
    header: list[str],
    row: list[str],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_reefvision_track_csv_shape(_csv(header, [row]))


def test_track_csv_shape_rejects_empty_and_blank_headers() -> None:
    with pytest.raises(ValidationError, match="empty"):
        validate_reefvision_track_csv_shape("")
    header = list(REEFVISION_TRACK_CSV_COLUMNS)
    header[3] = ""
    with pytest.raises(ValidationError, match="must not be blank"):
        validate_reefvision_track_csv_shape(_csv(header, [_row()]))
