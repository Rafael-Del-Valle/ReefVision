from __future__ import annotations

import csv
import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 120,
        "frame_count": 20,
        "fps": 10.0,
        "duration_seconds": 2.0,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("jellyfish.mp4", io.BytesIO(b"pose-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _first_class(project: dict[str, object]) -> str:
    classes = cast(list[dict[str, object]], project["label_classes"])
    return str(classes[0]["id"])


def _observation(
    observation_id: str,
    occurrence: int,
    x: float,
    y: float,
    confidence: float,
    *,
    status: str = "visible",
) -> dict[str, object]:
    return {
        "id": observation_id,
        "semantic_label": "tentacle",
        "occurrence_index": occurrence,
        "x": x,
        "y": y,
        "confidence": confidence,
        "status": status,
        "source": "model",
    }


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
                {
                    "frame": 0,
                    "bbox": [0, 0, 100, 100],
                    "confidence": 0.95,
                    "pose_observations": [
                        _observation("f0-t0", 0, 20, 50, 0.95),
                        _observation("f0-t1", 1, 80, 50, 0.93),
                    ],
                },
                {
                    "frame": 1,
                    "bbox": [1, 0, 100, 100],
                    "confidence": 0.94,
                    "pose_observations": [
                        _observation("f1-t0", 0, 22, 50, 0.94),
                        _observation("f1-t1", 1, 82, 50, 0.91, status="occluded"),
                    ],
                },
                {
                    "frame": 2,
                    "bbox": [2, 0, 100, 100],
                    "confidence": 0.93,
                    "pose_observations": [
                        _observation("f2-t0", 0, 24, 50, 0.92),
                        _observation("f2-t1", 1, 84, 50, 0.90),
                    ],
                },
            ],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_temporal_pose_build_persists_repeated_landmark_identity_and_occlusion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Temporal pose persistence")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))

    built = client.post(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal-associations",
        json={
            "max_gap_frames": 2,
            "max_normalized_displacement": 0.35,
            "ambiguity_margin": 0.02,
            "confirm_after_observations": 3,
        },
    )
    assert built.status_code == 200, built.text
    result = built.json()
    assert result["created_landmark_tracks"] == 2
    assert result["created_observations"] == 6
    assert result["created_association_decisions"] == 6
    assert result["unresolved_associations"] == 0

    summary_response = client.get(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal"
    )
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    assert len(summary["landmark_tracks"]) == 2
    assert all(item["semantic_label"] == "tentacle" for item in summary["landmark_tracks"])
    assert all(item["lifecycle_state"] == "confirmed" for item in summary["landmark_tracks"])

    occluded = next(
        item
        for item in summary["observations"]
        if item["frame_index"] == 1 and item["occurrence_index"] == 1
    )
    assert occluded["visibility_state"] == "occluded"
    assert occluded["observed_x_px"] is None
    assert occluded["observed_y_px"] is None
    assert occluded["predicted_x_px"] == 82.0
    assert occluded["predicted_y_px"] == 50.0

    decisions_by_observation = {
        item["observation_id"]: item for item in summary["association_decisions"]
    }
    occurrence_zero = [
        item
        for item in summary["observations"]
        if item["occurrence_index"] == 0
    ]
    occurrence_zero_ids = {
        decisions_by_observation[item["id"]]["selected_landmark_track_id"]
        for item in occurrence_zero
    }
    assert len(occurrence_zero_ids) == 1


def test_temporal_pose_ambiguous_crossing_is_not_forced(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Temporal pose ambiguity")
    video = _video(client, str(project["id"]), monkeypatch)
    response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": _first_class(project),
            "keyframes": [
                {
                    "frame": 0,
                    "bbox": [0, 0, 100, 100],
                    "pose_observations": [
                        _observation("a0", 0, 40, 50, 0.9),
                        _observation("b0", 1, 60, 50, 0.9),
                    ],
                },
                {
                    "frame": 1,
                    "bbox": [0, 0, 100, 100],
                    "pose_observations": [
                        _observation("a1", 0, 50, 50, 0.9),
                        _observation("b1", 1, 50, 50, 0.9),
                    ],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    track = response.json()

    built = client.post(
        f"/api/v1/video-tracks/{track['id']}/pose-temporal-associations",
        json={
            "max_gap_frames": 2,
            "max_normalized_displacement": 0.35,
            "ambiguity_margin": 0.05,
        },
    )
    assert built.status_code == 200, built.text
    assert built.json()["unresolved_associations"] == 2

    summary = client.get(
        f"/api/v1/video-tracks/{track['id']}/pose-temporal"
    ).json()
    frame_one_ids = {
        item["id"] for item in summary["observations"] if item["frame_index"] == 1
    }
    frame_one_decisions = [
        item
        for item in summary["association_decisions"]
        if item["observation_id"] in frame_one_ids
    ]
    assert len(frame_one_decisions) == 2
    assert all(item["association_state"] == "unresolved" for item in frame_one_decisions)
    assert all(item["selected_landmark_track_id"] is None for item in frame_one_decisions)


def test_human_association_correction_identity_break_and_exports_are_auditable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Temporal pose human review")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))
    build = client.post(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal-associations",
        json={},
    )
    assert build.status_code == 200, build.text

    summary = client.get(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal"
    ).json()
    observation = next(
        item
        for item in summary["observations"]
        if item["frame_index"] == 1 and item["occurrence_index"] == 0
    )
    decision = next(
        item
        for item in summary["association_decisions"]
        if item["observation_id"] == observation["id"]
    )
    landmark_track_id = decision["selected_landmark_track_id"]
    assert landmark_track_id is not None

    corrected = client.post(
        f"/api/v1/pose-landmark-observations/{observation['id']}/association-corrections",
        json={
            "selected_landmark_track_id": None,
            "association_state": "unresolved",
            "reason_code": "crossing_identity_ambiguous",
            "note": "Reviewer could not defend identity through the crossing.",
        },
    )
    assert corrected.status_code == 200, corrected.text
    corrected_payload = corrected.json()
    assert corrected_payload["decision_revision"] == 2
    assert corrected_payload["association_source"] == "human"
    assert corrected_payload["verification_state"] == "human_corrected"
    assert corrected_payload["association_state"] == "unresolved"
    assert corrected_payload["selected_landmark_track_id"] is None

    identity_break = client.post(
        f"/api/v1/pose-landmark-tracks/{landmark_track_id}/identity-breaks",
        json={
            "break_after_frame": 1,
            "reason": "ambiguous_crossing",
            "decision_confidence": 0.95,
            "note": "Continuity is intentionally not asserted beyond this frame.",
        },
    )
    assert identity_break.status_code == 201, identity_break.text
    assert identity_break.json()["human_verified"] is True
    assert identity_break.json()["source"] == "human"

    audited = client.get(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal"
    ).json()
    assert len(audited["corrections"]) == 2
    assert len(audited["identity_breaks"]) == 1

    csv_export = client.get(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal/export?format=csv"
    )
    assert csv_export.status_code == 200, csv_export.text
    rows = list(csv.DictReader(io.StringIO(csv_export.text)))
    assert len(rows) == 6
    corrected_row = next(
        row
        for row in rows
        if row["frame_index"] == "1" and row["occurrence_index"] == "0"
    )
    assert corrected_row["association_state"] == "unresolved"
    assert corrected_row["landmark_track_id"] == ""
    assert corrected_row["human_corrected"] == "True"

    json_export = client.get(
        f"/api/v1/video-tracks/{source['id']}/pose-temporal/export?format=json"
    )
    assert json_export.status_code == 200, json_export.text
    document = json_export.json()
    assert document["schema_version"] == "reefvision-pose-tracks-0001"
    assert len(document["human_corrections"]) == 2
    assert len(document["identity_breaks"]) == 1


def test_temporal_pose_rebuild_requires_explicit_replace(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Temporal pose replacement")
    video = _video(client, str(project["id"]), monkeypatch)
    source = _track(client, str(video["id"]), _first_class(project))
    url = f"/api/v1/video-tracks/{source['id']}/pose-temporal-associations"

    first = client.post(url, json={})
    assert first.status_code == 200, first.text

    conflict = client.post(url, json={})
    assert conflict.status_code == 409, conflict.text

    replaced = client.post(url, json={"replace_existing": True})
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["created_observations"] == 6
