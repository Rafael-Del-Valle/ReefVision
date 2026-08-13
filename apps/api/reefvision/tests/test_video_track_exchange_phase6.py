from __future__ import annotations

import io
import json
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
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
    filename: str = "fish.mp4",
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": (filename, io.BytesIO(b"same-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [0, 0, 20, 10], "confidence": 0.9},
                {"frame": 3, "bbox": [12.5, 5, 20, 10], "confidence": 0.8},
            ],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _first_class(project: dict[str, object]) -> str:
    classes = cast(list[dict[str, object]], project["label_classes"])
    return str(classes[0]["id"])


def test_reefvision_json_export_import_preserves_track_semantics_and_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "JSON track exchange")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))

    exported = client.get(
        f"/api/v1/videos/{video['id']}/tracks/export?format=reefvision_json"
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/json")
    assert exported.headers["x-reefvision-track-format"] == "reefvision_json"
    assert "attachment;" in exported.headers["content-disposition"]
    document = exported.json()
    assert document["schema_version"] == "reefvision-video-tracks-0001"
    assert document["source_video_sha256"] == video["sha256"]
    assert document["frame_index_base"] == 0
    assert document["coordinate_base"] == 0
    assert document["observation_policy"] == "persisted_keyframes"
    assert len(document["tracks"]) == 1
    assert document["tracks"][0]["original_track_id"] == source["id"]
    assert document["tracks"][0]["keyframes"] == source["keyframes_json"]

    imported = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=reefvision_json",
        files={
            "file": (
                "tracks.json",
                io.BytesIO(exported.content),
                "application/json",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["schema_version"] == "video-track-import-0001"
    assert result["format"] == "reefvision_json"
    assert result["track_count"] == 1
    assert result["observation_count"] == 2
    assert result["warnings"] == []

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200, tracks.text
    assert len(tracks.json()) == 2
    restored = next(item for item in tracks.json() if item["id"] != source["id"])
    assert restored["label_class_id"] == source["label_class_id"]
    assert restored["interpolation"] == "hold"
    assert restored["status"] == "verified"
    assert restored["keyframes_json"] == source["keyframes_json"]
    assert restored["source_model_id"] is None
    assert restored["source_job_id"] is None
    provenance = restored["metadata_json"]["exchange_import"]
    assert provenance["format"] == "reefvision_json"
    assert provenance["original_track_id"] == source["id"]
    assert provenance["original_track_number"] == source["track_number"]


def test_reefvision_csv_export_import_round_trip(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "CSV track exchange")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))

    exported = client.get(
        f"/api/v1/videos/{video['id']}/tracks/export?format=reefvision_csv"
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    lines = exported.text.strip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("track_number,frame,label_class_id,label_class_name,")

    imported = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=reefvision_csv",
        files={"file": ("tracks.csv", io.BytesIO(exported.content), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["track_count"] == 1
    assert imported.json()["observation_count"] == 2

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks").json()
    restored = next(item for item in tracks if item["id"] != source["id"])
    assert restored["label_class_id"] == source["label_class_id"]
    assert restored["keyframes_json"] == source["keyframes_json"]
    assert restored["interpolation"] == source["interpolation"]
    assert restored["status"] == source["status"]
    assert restored["metadata_json"]["exchange_import"]["format"] == "reefvision_csv"
    assert restored["metadata_json"]["exchange_import"]["original_track_id"] == source["id"]


def test_mot_export_import_converts_one_based_coordinates_and_requires_class(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "MOT track exchange")
    video = _video(client, str(project["id"]), monkeypatch)
    label_class_id = _first_class(project)
    source = _track(client, str(video["id"]), label_class_id)

    exported = client.get(f"/api/v1/videos/{video['id']}/tracks/export?format=mot_csv")
    assert exported.status_code == 200, exported.text
    rows = exported.text.strip().splitlines()
    assert rows[0].split(",")[:7] == [
        "1",
        str(source["track_number"]),
        "1",
        "1",
        "20",
        "10",
        "0.9",
    ]
    assert rows[1].split(",")[:2] == ["4", str(source["track_number"])]

    missing_class = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=mot_csv",
        files={"file": ("gt.txt", io.BytesIO(exported.content), "text/plain")},
    )
    assert missing_class.status_code == 422

    imported = client.post(
        (
            f"/api/v1/videos/{video['id']}/tracks/import?format=mot_csv"
            f"&mot_label_class_id={label_class_id}"
        ),
        files={"file": ("gt.txt", io.BytesIO(exported.content), "text/plain")},
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["track_count"] == 1
    assert result["observation_count"] == 2
    assert len(result["warnings"]) == 3

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks").json()
    restored = next(item for item in tracks if item["id"] != source["id"])
    assert restored["label_class_id"] == label_class_id
    assert restored["status"] == "draft"
    assert restored["interpolation"] == "linear"
    assert restored["keyframes_json"] == source["keyframes_json"]
    assert restored["metadata_json"]["exchange_import"]["original_track_number"] == source[
        "track_number"
    ]


def test_json_import_is_transactional_when_later_track_is_invalid(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Transactional track exchange")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))
    exported = client.get(
        f"/api/v1/videos/{video['id']}/tracks/export?format=reefvision_json"
    )
    document = exported.json()
    invalid = json.loads(json.dumps(document["tracks"][0]))
    invalid["original_track_id"] = "invalid-second-track"
    invalid["keyframes"][0]["frame"] = int(video["frame_count"])
    document["tracks"].append(invalid)

    imported = client.post(
        f"/api/v1/videos/{video['id']}/tracks/import?format=reefvision_json",
        files={
            "file": (
                "invalid.json",
                io.BytesIO(json.dumps(document).encode("utf-8")),
                "application/json",
            )
        },
    )
    assert imported.status_code == 422

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200
    assert [item["id"] for item in tracks.json()] == [source["id"]]
