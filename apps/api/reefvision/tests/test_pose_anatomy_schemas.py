from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import PoseLandmarkSchema, PoseLandmarkSchemaRevision
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_video_tracking_phase6 import _import_video


def _jellyfish_definition() -> dict[str, object]:
    return {
        "name": "Moon jelly anatomy",
        "landmarks": [
            {
                "id": "bell_center",
                "name": "Bell center",
                "description": "Geometric center of the bell",
                "group": "bell",
            },
            {
                "id": "tentacle_1",
                "name": "Tentacle",
                "group": "appendages",
                "repeat_group": "tentacle",
                "repeat_index": 0,
                "symmetric_with": "tentacle_2",
            },
            {
                "id": "tentacle_2",
                "name": "Tentacle",
                "group": "appendages",
                "repeat_group": "tentacle",
                "repeat_index": 1,
                "symmetric_with": "tentacle_1",
            },
        ],
        "edges": [
            {"from_id": "bell_center", "to_id": "tentacle_1"},
            {"from_id": "bell_center", "to_id": "tentacle_2"},
        ],
    }


def test_create_and_list_arbitrary_anatomy_schema(client: TestClient) -> None:
    project = create_project(client, "Invertebrate anatomy")

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-schemas",
        json=_jellyfish_definition(),
    )

    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["name"] == "Moon jelly anatomy"
    assert payload["revision"] == 1
    assert payload["keypoint_count"] == 3
    assert payload["expanded_labels"] == ["Bell center", "Tentacle", "Tentacle"]
    assert payload["groups"] == [
        {"name": "Bell center", "count": 1},
        {"name": "Tentacle", "count": 2},
    ]
    assert payload["allows_repeated_labels"] is True
    assert len(payload["content_hash"]) == 64
    assert payload["landmarks"][1]["id"] == "tentacle_1"
    assert payload["edges"][0] == {
        "from_id": "bell_center",
        "to_id": "tentacle_1",
    }

    listed = client.get(f"/api/v1/projects/{project['id']}/pose-schemas")
    assert listed.status_code == 200, listed.text
    assert [(item["id"], item["revision"]) for item in listed.json()] == [(payload["id"], 1)]


def test_reorder_and_rename_create_revision_without_mutating_identity(
    client: TestClient,
) -> None:
    project = create_project(client, "Revisioned anatomy")
    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-schemas",
        json=_jellyfish_definition(),
    ).json()
    revised_definition = _jellyfish_definition()
    revised_definition.pop("name")
    landmarks = cast(list[dict[str, object]], revised_definition["landmarks"])
    landmarks[0]["name"] = "Bell centroid"
    revised_definition["landmarks"] = [landmarks[2], landmarks[0], landmarks[1]]

    revised = client.post(
        f"/api/v1/pose-schemas/{created['id']}/revisions",
        json=revised_definition,
    )

    assert revised.status_code == 201, revised.text
    assert revised.json()["revision"] == 2
    assert [item["id"] for item in revised.json()["landmarks"]] == [
        "tentacle_2",
        "bell_center",
        "tentacle_1",
    ]
    assert revised.json()["landmarks"][1]["name"] == "Bell centroid"
    assert revised.json()["content_hash"] != created["content_hash"]

    history = client.get(f"/api/v1/pose-schemas/{created['id']}")
    assert history.status_code == 200, history.text
    assert [item["revision"] for item in history.json()["revisions"]] == [2, 1]
    assert history.json()["revisions"][1]["landmarks"][0]["name"] == "Bell center"


def test_schema_rejects_dangling_edges_and_asymmetric_relationships(
    client: TestClient,
) -> None:
    project = create_project(client, "Invalid anatomy")
    dangling = _jellyfish_definition()
    cast(list[dict[str, object]], dangling["edges"])[0]["to_id"] = "missing"

    edge_response = client.post(
        f"/api/v1/projects/{project['id']}/pose-schemas",
        json=dangling,
    )
    assert edge_response.status_code == 422
    assert "edge" in edge_response.text.lower()

    asymmetric = _jellyfish_definition()
    cast(list[dict[str, object]], asymmetric["landmarks"])[2].pop("symmetric_with")
    symmetry_response = client.post(
        f"/api/v1/projects/{project['id']}/pose-schemas",
        json=asymmetric,
    )
    assert symmetry_response.status_code == 422
    assert "symmetr" in symmetry_response.text.lower()


def test_legacy_schema_revision_is_serialized_with_deterministic_stable_ids(
    client: TestClient,
) -> None:
    project = create_project(client, "Legacy schema")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        schema = PoseLandmarkSchema(project_id=project["id"], name="Legacy fish")
        session.add(schema)
        session.flush()
        session.add(
            PoseLandmarkSchemaRevision(
                schema_id=schema.id,
                revision=1,
                groups_json=[
                    {"name": "snout", "count": 1},
                    {"name": "fin", "count": 2},
                ],
                expanded_labels_json=["snout", "fin", "fin"],
                keypoint_count=3,
                allows_repeated_labels=True,
                content_hash="a" * 64,
            )
        )
        session.commit()
        schema_id = schema.id

    response = client.get(f"/api/v1/pose-schemas/{schema_id}")

    assert response.status_code == 200, response.text
    revision = response.json()["revisions"][0]
    assert [item["id"] for item in revision["landmarks"]] == [
        "snout",
        "fin_1",
        "fin_2",
    ]
    assert revision["legacy_projection"] is True


def test_manual_video_track_binds_exact_custom_anatomy_revision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Manual custom anatomy")
    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-schemas",
        json=_jellyfish_definition(),
    ).json()
    video = _import_video(client, str(project["id"]), monkeypatch)
    label_class_id = str(project["label_classes"][0]["id"])
    track = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [{"frame": 0, "bbox": [5, 5, 40, 40]}],
            "status": "draft",
        },
    ).json()

    updated = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": track["revision"],
            "label_class_id": label_class_id,
            "keyframes": [
                {
                    "frame": 0,
                    "bbox": [5, 5, 40, 40],
                    "pose_observations": [
                        {
                            "id": "manual-bell",
                            "landmark_id": "bell_center",
                            "semantic_label": "Bell center",
                            "occurrence_index": 0,
                            "x": 20,
                            "y": 20,
                            "status": "visible",
                            "source": "manual",
                        }
                    ],
                }
            ],
            "status": "draft",
            "pose_schema_binding": {
                "schema_id": created["id"],
                "schema_revision": created["revision"],
                "content_hash": created["content_hash"],
            },
        },
    )

    assert updated.status_code == 200, updated.text
    stored = updated.json()["metadata_json"]["pose_landmark_schema"]
    assert stored["schema_id"] == created["id"]
    assert stored["schema_revision"] == 1
    assert stored["content_hash"] == created["content_hash"]
    assert stored["landmarks"][1]["id"] == "tentacle_1"
    assert (
        updated.json()["keyframes_json"][0]["pose_observations"][0]["landmark_id"] == "bell_center"
    )

    mismatch = client.put(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "base_revision": updated.json()["revision"],
            "label_class_id": label_class_id,
            "keyframes": [{"frame": 0, "bbox": [5, 5, 40, 40]}],
            "status": "draft",
            "pose_schema_binding": {
                "schema_id": created["id"],
                "schema_revision": 1,
                "content_hash": "f" * 64,
            },
        },
    )
    assert mismatch.status_code == 400
    assert "hash" in mismatch.text.lower()
