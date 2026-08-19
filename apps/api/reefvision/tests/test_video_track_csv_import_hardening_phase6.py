from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.services.video_track_csv_validation import REEFVISION_TRACK_CSV_COLUMNS
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 10,
        "fps": 10.0,
        "duration_seconds": 1.0,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _valid_row(label_class_id: str, label_class_name: str) -> list[str]:
    return [
        "1",
        "0",
        label_class_id,
        label_class_name,
        "10",
        "10",
        "20",
        "10",
        "0.9",
        "linear",
        "verified",
        "source-track",
        "",
        "",
    ]


def test_duplicate_header_csv_is_rejected_before_any_track_is_created(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Malformed CSV")
    video = _video(client, str(project["id"]), monkeypatch)
    label_class = project["label_classes"][0]
    header = list(REEFVISION_TRACK_CSV_COLUMNS)
    header[-1] = "source_model_id"
    content = (
        ",".join(header)
        + "\n"
        + ",".join(_valid_row(str(label_class["id"]), str(label_class["name"])))
        + "\n"
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=reefvision_csv",
        files={"file": ("bad.csv", io.BytesIO(content.encode()), "text/csv")},
    )
    assert response.status_code == 400, response.text
    assert "duplicate headers" in response.text

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200
    assert tracks.json() == []


def test_overflow_csv_row_is_rejected_before_semantic_parser(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Overflow CSV")
    video = _video(client, str(project["id"]), monkeypatch)
    label_class = project["label_classes"][0]
    content = (
        ",".join(REEFVISION_TRACK_CSV_COLUMNS)
        + "\n"
        + ",".join(
            [
                *_valid_row(str(label_class["id"]), str(label_class["name"])),
                "unexpected-overflow-cell",
            ]
        )
        + "\n"
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=reefvision_csv",
        files={"file": ("overflow.csv", io.BytesIO(content.encode()), "text/csv")},
    )
    assert response.status_code == 400, response.text
    assert "expected 14" in response.text
    assert client.get(f"/api/v1/videos/{video['id']}/tracks").json() == []
