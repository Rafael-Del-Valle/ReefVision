from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    ModelRegistration,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
)
from reefvision.tests.test_annotations import create_project


def _pose_model(client: TestClient, project_id: str) -> str:
    app = cast(FastAPI, client.app)
    model_id = str(uuid4())
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose="detector",
                display_name="Jellyfish pose",
                source_filename="jellyfish-pose.pt",
                managed_path=f"projects/{project_id}/models/{model_id}.pt",
                sha256="a" * 64,
                file_size_bytes=1,
                framework="ultralytics",
                task="pose",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={},
                input_size_json={"width": 640, "height": 640},
                metadata_json={},
                notes=None,
            )
        )
        session.commit()
    return model_id


def test_pose_landmark_schema_revisions_are_canonical_and_immutable(
    client: TestClient,
) -> None:
    project = create_project(client, "Canonical pose schemas")
    model_id = _pose_model(client, str(project["id"]))
    url = f"/api/v1/models/{model_id}/pose-landmark-schema"

    first = client.put(
        url,
        json={
            "groups": [
                {"name": "bell_center", "count": 1},
                {"name": "tentacle", "count": 2},
            ]
        },
    )
    assert first.status_code == 200, first.text
    first_schema = first.json()["metadata_json"]["pose_landmark_schema"]
    assert first_schema["schema_revision"] == 1
    assert first_schema["schema_id"]
    assert first_schema["expanded_labels"] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]

    repeated = client.put(
        url,
        json={
            "groups": [
                {"name": "bell_center", "count": 1},
                {"name": "tentacle", "count": 2},
            ]
        },
    )
    assert repeated.status_code == 200, repeated.text
    repeated_schema = repeated.json()["metadata_json"]["pose_landmark_schema"]
    assert repeated_schema["schema_id"] == first_schema["schema_id"]
    assert repeated_schema["schema_revision"] == 1
    assert repeated_schema["content_hash"] == first_schema["content_hash"]

    changed = client.put(
        url,
        json={
            "groups": [
                {"name": "bell_center", "count": 1},
                {"name": "tentacle", "count": 3},
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    changed_schema = changed.json()["metadata_json"]["pose_landmark_schema"]
    assert changed_schema["schema_id"] == first_schema["schema_id"]
    assert changed_schema["schema_revision"] == 2
    assert changed_schema["content_hash"] != first_schema["content_hash"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        binding = session.get(PoseModelSchemaBinding, model_id)
        assert binding is not None
        assert binding.schema_id == first_schema["schema_id"]
        assert binding.schema_revision == 2

        revisions = list(
            session.scalars(
                select(PoseLandmarkSchemaRevision)
                .where(PoseLandmarkSchemaRevision.schema_id == binding.schema_id)
                .order_by(PoseLandmarkSchemaRevision.revision)
            )
        )
        assert [item.revision for item in revisions] == [1, 2]
        assert revisions[0].expanded_labels_json == [
            "bell_center",
            "tentacle",
            "tentacle",
        ]
        assert revisions[1].expanded_labels_json == [
            "bell_center",
            "tentacle",
            "tentacle",
            "tentacle",
        ]
