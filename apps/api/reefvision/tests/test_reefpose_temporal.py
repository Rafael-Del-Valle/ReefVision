from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import (
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
    ReefPoseReference,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_reefpose_validation import freeze_fixture


def _setup(client: TestClient, monkeypatch: pytest.MonkeyPatch, *, held_out: bool = False):
    url, _, reference = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    recording = reference["manifest"]["recordings"][0]
    with client.app.state.session_factory() as session:
        source = PoseIdentityAssociationRun(
            project_id=project_id,
            video_id=recording["video_id"],
            pose_schema_id=recording["schema_id"],
            pose_schema_revision=1,
            pose_schema_content_hash=recording["schema_sha256"],
            algorithm="fixture",
            algorithm_version="1",
            parameters_json={},
            parameters_sha256="a" * 64,
            input_manifest_sha256="b" * 64,
            source_coordinate_space="source_pixels",
            source_width=320,
            source_height=180,
            status="completed",
            revision=1,
        )
        session.add(source)
        session.flush()
        animal = PoseAnimalIdentity(
            association_run_id=source.id,
            stable_identity_key="fish-1",
            display_name="Synthetic fish",
            origin="synthetic",
            first_frame=0,
            last_frame=4,
        )
        session.add(animal)
        session.flush()
        run = PoseMeasurementRun(
            project_id=project_id,
            video_id=source.video_id,
            source_identity_run_id=source.id,
            source_identity_run_revision=1,
            pose_schema_id=source.pose_schema_id,
            pose_schema_revision=1,
            pose_schema_content_hash=source.pose_schema_content_hash,
            video_sha256=recording["video_sha256"],
            video_revision=recording["video_revision"],
            timebase_json={"fps": 10},
            definitions_json=[
                {
                    "id": name,
                    "name": name,
                    "kind": "distance",
                    "landmark_ids": ["jaw", "head"],
                    "options": {},
                }
                for name in ("jaw", "gill")
            ],
            configuration_json={},
            input_manifest_json={},
            input_manifest_sha256="c" * 64,
            status="completed",
            result_sha256="d" * 64,
        )
        session.add(run)
        session.flush()
        for name in ("jaw", "gill"):
            series = PoseMeasurementSeries(
                measurement_run_id=run.id,
                animal_identity_id=animal.id,
                definition_id=name,
                display_name=name,
                measurement_kind="distance",
                landmark_ids_json=["jaw", "head"],
                formula_version="1",
                unit_dimension="length",
                pixel_unit="px",
                series_sha256="e" * 64,
            )
            session.add(series)
            session.flush()
            for frame in range(5):
                if frame == 3 and name == "jaw":
                    continue
                session.add(
                    PoseMeasurementSample(
                        series_id=series.id,
                        frame_index=frame,
                        time_s=frame / 10,
                        pixel_value=0.0,
                        confidence=0.9,
                        valid=frame != 2 or name == "gill",
                        source_observation_ids_json=[],
                        source_observation_revisions_json=[],
                    )
                )
        row = session.get(ReefPoseReference, reference["id"])
        assert row is not None
        manifest = reference["manifest"]
        if held_out:
            recording["split"] = "test"
        recording["event_windows"][0]["end_s"] = 0.4
        recording["annotations"][1]["events"][0]["end_s"] = 0.4
        recording["annotations"][0]["frame_states"] = [
            {"individual_id": "animal-a", "label": "gape", "frame": 3, "state": "missing"}
        ]
        row.manifest = manifest
        row.manifest_sha256 = canonical_json_sha256(manifest)
        payload = {
            "rater_id": "rater-a",
            "label": "gape",
            "feature_ids": ["jaw", "gill"],
            "clips": [
                {
                    "measurement_run_id": run.id,
                    "animal_identity_id": animal.id,
                    "reference_individual_id": "animal-a",
                }
            ],
        }
        session.commit()
    return f"{url}/{reference['id']}/temporal-training-data", payload, project_id


def test_temporal_export_preserves_zeros_gaps_and_independent_interval_labels(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, _ = _setup(client, monkeypatch)
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == client.post(url, json=payload).json()
    assert result["sha256"] == canonical_json_sha256(result["manifest"])
    clip = result["manifest"]["clips"][0]
    assert clip["group_id"] == "session-a"
    frames = clip["frames"]
    assert [item["frame_index"] for item in frames] == [0, 1, 2, 3]
    assert [item["target"] for item in frames] == [0, 1, 1, None]
    assert frames[0]["values"] == [0.0, 0.0]
    assert frames[2]["values"] == [None, 0.0]
    assert frames[3]["values"] == [None, 0.0]
    assert clip["events"][0]["start_s"] == 0.1


def test_temporal_export_refuses_held_out_recordings_and_wrong_project(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, project_id = _setup(client, monkeypatch, held_out=True)
    response = client.post(url, json=payload)
    assert response.status_code == 400, response.text
    assert "held-out" in response.text.lower()
    other = create_project(client, "Other project")
    assert client.post(url.replace(project_id, str(other["id"])), json=payload).status_code == 404


def test_temporal_export_keeps_reviewed_zero_event_clips(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, _ = _setup(client, monkeypatch)
    reference_id = url.split("/")[-2]
    with client.app.state.session_factory() as session:
        row = session.get(ReefPoseReference, reference_id)
        assert row is not None
        manifest = deepcopy(row.manifest)
        manifest["recordings"][0]["annotations"][0]["events"] = []
        row.manifest_sha256 = canonical_json_sha256(manifest)
        row.manifest = manifest
        session.commit()
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    clip = response.json()["manifest"]["clips"][0]
    assert clip["events"] == []
    assert [frame["target"] for frame in clip["frames"]] == [0, 0, 0, None]
