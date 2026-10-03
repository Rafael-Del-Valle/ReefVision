from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 6,
        "fps": 10.0,
        "duration_seconds": 0.6,
    }


def _setup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "Behavior dynamics",
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    project = create_project(client, name)
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    video_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("behavior.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    classes = cast(list[dict[str, object]], project["label_classes"])
    track_response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [0, 0, 20, 20]},
                {"frame": 5, "bbox": [20, 0, 20, 20]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track_response.status_code == 201, track_response.text
    return project, video, track_response.json()


def _ethogram(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/behavior-ethograms",
        json={
            "name": "Jellyfish ethogram",
            "description": "Independent locomotion and feeding channels.",
            "states": [
                {"code": "rest", "label": "Rest", "channel": "locomotion"},
                {"code": "swim", "label": "Swimming", "channel": "locomotion"},
                {"code": "feed", "label": "Feeding", "channel": "feeding"},
                {"code": "not_feed", "label": "Not feeding", "channel": "feeding"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_behavior_ethogram_bouts_and_transition_summary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, track = _setup(client, monkeypatch)
    ethogram = _ethogram(client, str(project["id"]))
    states = {item["code"]: item for item in ethogram["states"]}

    for code, start, end in (
        ("rest", 0, 1),
        ("swim", 2, 3),
        ("rest", 4, 5),
        ("feed", 1, 4),
    ):
        response = client.post(
            f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
            json={
                "ethogram_revision_id": ethogram["id"],
                "behavior_state_id": states[code]["id"],
                "start_frame": start,
                "end_frame": end,
                "source": "manual",
            },
        )
        assert response.status_code == 201, response.text
        created_bout = response.json()
        assert created_bout["stale_against_track"] is False
        assert created_bout["duration_seconds"] == pytest.approx(
            (end - start + 1) / 10.0
        )
        assert created_bout["end_time_seconds"] == pytest.approx(
            (end + 1) / 10.0
        )

    listed = client.get(
        f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
        params={"ethogram_revision_id": ethogram["id"]},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 4

    summary = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-dynamics",
        json={"ethogram_revision_id": ethogram["id"]},
    )
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["schema_version"] == "behavior-dynamics-0001"
    assert payload["transition_policy"] == "adjacent-labeled-bouts-only"
    assert payload["interval_policy"] == "inclusive-frame-intervals"
    assert payload["provenance_status"] == "current"

    channels = {item["channel"]: item for item in payload["channels"]}
    locomotion = channels["locomotion"]
    assert locomotion["coverage_fraction"] == pytest.approx(1.0)
    locomotion_states = {
        item["behavior_code"]: item for item in locomotion["states"]
    }
    assert locomotion_states["rest"]["bout_count"] == 2
    assert locomotion_states["rest"]["dwell_seconds"] == pytest.approx(0.4)
    assert locomotion_states["rest"]["fraction_of_evaluated_time"] == pytest.approx(
        4 / 6
    )
    assert locomotion_states["swim"]["dwell_seconds"] == pytest.approx(0.2)
    transitions = {
        (item["from_behavior_code"], item["to_behavior_code"]): item
        for item in locomotion["transitions"]
    }
    assert transitions[("rest", "swim")]["count"] == 1
    assert transitions[("swim", "rest")]["count"] == 1
    assert transitions[("rest", "swim")]["probability_from_state"] == pytest.approx(1.0)

    feeding = channels["feeding"]
    assert feeding["labeled_frames"] == 4
    assert feeding["unlabeled_frames"] == 2
    assert feeding["coverage_fraction"] == pytest.approx(4 / 6)


def test_behavior_bouts_allow_parallel_channels_but_reject_same_channel_overlap(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, track = _setup(client, monkeypatch, "Behavior overlap")
    ethogram = _ethogram(client, str(project["id"]))
    states = {item["code"]: item for item in ethogram["states"]}

    first = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
        json={
            "ethogram_revision_id": ethogram["id"],
            "behavior_state_id": states["rest"]["id"],
            "start_frame": 0,
            "end_frame": 3,
        },
    )
    assert first.status_code == 201, first.text

    parallel = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
        json={
            "ethogram_revision_id": ethogram["id"],
            "behavior_state_id": states["feed"]["id"],
            "start_frame": 1,
            "end_frame": 4,
        },
    )
    assert parallel.status_code == 201, parallel.text

    overlap = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
        json={
            "ethogram_revision_id": ethogram["id"],
            "behavior_state_id": states["swim"]["id"],
            "start_frame": 3,
            "end_frame": 5,
        },
    )
    assert overlap.status_code == 400, overlap.text
    assert "cannot overlap" in overlap.json()["detail"]


def test_behavior_bouts_detect_stale_track_revision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, track = _setup(client, monkeypatch, "Behavior provenance")
    ethogram = _ethogram(client, str(project["id"]))
    state = next(item for item in ethogram["states"] if item["code"] == "rest")

    created = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-bouts",
        json={
            "ethogram_revision_id": ethogram["id"],
            "behavior_state_id": state["id"],
            "start_frame": 0,
            "end_frame": 1,
        },
    )
    assert created.status_code == 201, created.text

    updated = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": track["revision"],
            "label_class_id": track["label_class_id"],
            "keyframes": [
                {"frame": 0, "bbox": [1, 0, 20, 20]},
                {"frame": 5, "bbox": [20, 0, 20, 20]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text

    listed = client.get(f"/api/v1/video-tracks/{track['id']}/behavior-bouts")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["stale_against_track"] is True

    summary = client.post(
        f"/api/v1/video-tracks/{track['id']}/behavior-dynamics",
        json={"ethogram_revision_id": ethogram["id"]},
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["provenance_status"] == "stale"
    assert summary.json()["stale_bout_count"] == 1
    assert "older video-track revision" in summary.json()["provenance_warning"]


def test_behavior_ethogram_is_project_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_one, _video_one, _track_one = _setup(
        client,
        monkeypatch,
        "Behavior project one",
    )
    project_two, _video_two, track_two = _setup(
        client,
        monkeypatch,
        "Behavior project two",
    )
    ethogram = _ethogram(client, str(project_one["id"]))
    state = ethogram["states"][0]

    cross_project = client.post(
        f"/api/v1/video-tracks/{track_two['id']}/behavior-bouts",
        json={
            "ethogram_revision_id": ethogram["id"],
            "behavior_state_id": state["id"],
            "start_frame": 0,
            "end_frame": 1,
        },
    )
    assert cross_project.status_code == 400, cross_project.text
    assert "different project" in cross_project.json()["detail"]

    listed = client.get(
        f"/api/v1/projects/{project_two['id']}/behavior-ethograms"
    )
    assert listed.status_code == 200
    assert listed.json() == []



def test_behavior_ethogram_revisions_are_immutable_and_latest_listing_wins(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _video, _track = _setup(
        client,
        monkeypatch,
        "Behavior ethogram revisions",
    )
    original = _ethogram(client, str(project["id"]))

    no_op = client.post(
        f"/api/v1/behavior-ethograms/{original['ethogram_series_id']}/revisions",
        json={
            "name": "Jellyfish ethogram",
            "description": "Independent locomotion and feeding channels.",
            "states": [
                {"code": "rest", "label": "Rest", "channel": "locomotion"},
                {"code": "swim", "label": "Swimming", "channel": "locomotion"},
                {"code": "feed", "label": "Feeding", "channel": "feeding"},
                {"code": "not_feed", "label": "Not feeding", "channel": "feeding"},
            ],
        },
    )
    assert no_op.status_code == 400, no_op.text

    revised = client.post(
        f"/api/v1/behavior-ethograms/{original['ethogram_series_id']}/revisions",
        json={
            "name": "Jellyfish ethogram",
            "description": "Revised locomotion and feeding vocabulary.",
            "states": [
                {"code": "rest", "label": "Rest", "channel": "locomotion"},
                {"code": "swim", "label": "Swimming", "channel": "locomotion"},
                {"code": "burst", "label": "Burst swimming", "channel": "locomotion"},
                {"code": "feed", "label": "Feeding", "channel": "feeding"},
                {"code": "not_feed", "label": "Not feeding", "channel": "feeding"},
            ],
        },
    )
    assert revised.status_code == 201, revised.text
    revised_payload = revised.json()
    assert revised_payload["revision"] == 2
    assert revised_payload["supersedes_revision_id"] == original["id"]
    assert revised_payload["ethogram_series_id"] == original["ethogram_series_id"]
    assert revised_payload["definition_sha256"] != original["definition_sha256"]

    listed = client.get(
        f"/api/v1/projects/{project['id']}/behavior-ethograms"
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == revised_payload["id"]
    assert listed.json()[0]["revision"] == 2
