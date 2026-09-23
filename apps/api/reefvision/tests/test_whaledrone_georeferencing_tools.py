import csv

import pytest
from openpyxl import Workbook

from reefvision.domain.errors import ValidationError
from reefvision.tests.whaledrone_georeferencing import (
    load_validation_points,
    select_validation_clip,
)


def _dataset(tmp_path, *, ambiguous=False):
    for name in ("videos", "telemetry", "annotations"):
        (tmp_path / name).mkdir()
    book = Workbook()
    sheet = book.active
    sheet.title = "filelist"
    sheet.append(["video_ID", "flight_ID", "DVM_video_name", "annotated"])
    sheet.append(["synthetic.mp4", "flight.csv", "internal.mp4", "yes"])
    if ambiguous:
        sheet.append(["second.mp4", "flight.csv", "internal.mp4", "yes"])
    book.save(tmp_path / "dataset_index.xlsx")
    book.close()
    (tmp_path / "videos" / "synthetic.mp4").write_bytes(b"synthetic placeholder")
    (tmp_path / "telemetry" / "synthetic.SRT").write_text("synthetic placeholder")
    annotation = tmp_path / "annotations" / "annotations_flight.csv"
    with annotation.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "name",
                "frame",
                "video",
                "length",
                "image_x",
                "image_y",
                "lat",
                "lon",
                "height",
                "pitch",
            ],
        )
        writer.writeheader()
        writer.writerow(
            dict(
                name="point",
                frame=31,
                video="/app/data/internal.mp4",
                length="NA",
                image_x=500,
                image_y=400,
                lat=0,
                lon=0,
                height=100,
                pitch=-90,
            )
        )
        writer.writerow(
            dict(
                name="vector",
                frame=31,
                video="/app/data/internal.mp4",
                length=5,
                image_x=500,
                image_y=400,
                lat=0,
                lon=0,
            )
        )
    return annotation


def test_documented_index_mapping_and_frame_base(tmp_path):
    _dataset(tmp_path)
    clip = select_validation_clip(tmp_path)
    assert clip.video_path.name == "synthetic.mp4"
    assert clip.srt_path.name == "synthetic.SRT"
    points = load_validation_points(clip, frame_base=1, max_samples=10)
    assert len(points) == 1
    assert points[0].frame_index == 30 and points[0].reference_height_m == 100


def test_published_flight_subdirectory_layout(tmp_path):
    _dataset(tmp_path)
    flight_directory = tmp_path / "videos" / "flight"
    flight_directory.mkdir()
    (tmp_path / "videos" / "synthetic.mp4").rename(flight_directory / "synthetic.mp4")
    clip = select_validation_clip(tmp_path, video_name="synthetic.mp4")
    assert clip.video_path == flight_directory / "synthetic.mp4"
    assert clip.srt_path == tmp_path / "telemetry" / "synthetic.SRT"


def test_ambiguous_index_mapping_is_never_guessed(tmp_path):
    _dataset(tmp_path, ambiguous=True)
    with pytest.raises(ValidationError, match="unambiguous"):
        select_validation_clip(tmp_path)


def test_malformed_annotation_is_not_silently_dropped(tmp_path):
    annotation = _dataset(tmp_path)
    text = annotation.read_text().replace("500", "not-a-number")
    annotation.write_text(text)
    clip = select_validation_clip(tmp_path)
    with pytest.raises(ValidationError, match="annotation"):
        load_validation_points(clip, frame_base=1, max_samples=10)


@pytest.mark.parametrize("field_count", [2, 3, 8, 9])
def test_truncated_annotation_row_reports_validation_error(tmp_path, field_count):
    annotation = _dataset(tmp_path)
    lines = annotation.read_text().splitlines()
    annotation.write_text(lines[0] + "\n" + ",".join(lines[1].split(",")[:field_count]) + "\n")
    clip = select_validation_clip(tmp_path)
    with pytest.raises(ValidationError, match="annotation"):
        load_validation_points(clip, frame_base=1)
