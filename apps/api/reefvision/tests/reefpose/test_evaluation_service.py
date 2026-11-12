from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from reefvision.db.models import (
    ModelRegistration,
    PoseEvaluationRun,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    Project,
    VideoAsset,
)
from reefvision.ml.reefpose.inference import LandmarkPrediction, PosePrediction

PROJECT_ID = "10000000-0000-0000-0000-000000000001"
MODEL_ID = "20000000-0000-0000-0000-000000000001"
DATASET_ID = "30000000-0000-0000-0000-000000000001"
VIDEO_ID = "40000000-0000-0000-0000-000000000001"
SCHEMA_ID = "50000000-0000-0000-0000-000000000001"
SCHEMA_HASH = "a" * 64
DATASET_HASH = "b" * 64


class _FakePredictor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def predict(self, _image: Image.Image, *, confidence_threshold: float = 0.0) -> PosePrediction:
        del confidence_threshold
        if self.fail:
            raise RuntimeError("synthetic inference failure")
        return PosePrediction(
            landmarks=(
                LandmarkPrediction(
                    landmark_id="snout",
                    name="Snout",
                    occurrence_index=0,
                    x=3.0,
                    y=4.0,
                    confidence=0.8,
                    heatmap_confidence=0.9,
                    visibility_probability=0.9,
                    visibility_state="visible",
                ),
                LandmarkPrediction(
                    landmark_id="tail",
                    name="Tail",
                    occurrence_index=0,
                    x=10.0,
                    y=0.0,
                    confidence=0.9,
                    heatmap_confidence=0.95,
                    visibility_probability=0.95,
                    visibility_state="visible",
                ),
            ),
            confidence=0.85,
            bbox=(2.0, 0.0, 11.0, 5.0),
            anatomy_schema_id=SCHEMA_ID,
            anatomy_schema_revision=2,
            anatomy_integrity_hash=SCHEMA_HASH,
        )


def _seed(client: TestClient) -> None:
    settings = client.app.state.settings
    managed_checkpoint = settings.resolved_data_dir / "projects/p1/models/reefpose.pt"
    managed_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    managed_checkpoint.write_bytes(b"synthetic-checkpoint")
    checkpoint_sha = hashlib.sha256(managed_checkpoint.read_bytes()).hexdigest()

    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id=PROJECT_ID,
                name="Evaluation project",
                slug="evaluation-project",
                storage_root="projects/p1",
            )
        )
        session.add(
            VideoAsset(
                id=VIDEO_ID,
                project_id=PROJECT_ID,
                original_filename="fish.avi",
                managed_path="projects/p1/videos/fish.avi",
                sha256="c" * 64,
                media_type="video/x-msvideo",
                width_px=20,
                height_px=10,
                frame_count=1,
                fps=30.0,
                duration_seconds=1 / 30,
            )
        )
        session.add(
            ModelRegistration(
                id=MODEL_ID,
                project_id=PROJECT_ID,
                purpose="detector",
                display_name="Synthetic ReefPose",
                source_filename="reefpose.pt",
                managed_path="projects/p1/models/reefpose.pt",
                sha256=checkpoint_sha,
                file_size_bytes=len(b"synthetic-checkpoint"),
                framework="reefpose",
                task="pose",
                provider_name="reefpose",
                provider_version="1",
                class_map_json={},
                metadata_json={
                    "source_pose_training_dataset_id": "different-dataset",
                    "source_pose_training_dataset_manifest_sha256": "d" * 64,
                    "source_pose_validation_dataset_id": "different-validation",
                    "source_pose_validation_dataset_manifest_sha256": "e" * 64,
                    "source_pose_schema_id": SCHEMA_ID,
                    "source_pose_schema_revision": 2,
                    "source_pose_schema_content_hash": SCHEMA_HASH,
                    "pose_landmark_schema": {
                        "schema_id": SCHEMA_ID,
                        "schema_revision": 2,
                        "content_hash": SCHEMA_HASH,
                        "landmarks": [
                            {"id": "snout", "name": "Snout"},
                            {"id": "tail", "name": "Tail"},
                        ],
                    },
                },
            )
        )
        session.add(
            PoseTrainingDataset(
                id=DATASET_ID,
                project_id=PROJECT_ID,
                source_round_id="60000000-0000-0000-0000-000000000001",
                name="Held-out fish",
                status="complete",
                pose_schema_id=SCHEMA_ID,
                pose_schema_revision=2,
                pose_schema_content_hash=SCHEMA_HASH,
                source_selection_sha256="f" * 64,
                source_retraining_manifest_sha256="1" * 64,
                manifest_json={"schema_version": "pose-training-dataset-manifest-0001"},
                manifest_sha256=DATASET_HASH,
                item_count=1,
            )
        )
        session.add(
            PoseTrainingDatasetItem(
                id="70000000-0000-0000-0000-000000000001",
                dataset_id=DATASET_ID,
                candidate_id="80000000-0000-0000-0000-000000000001",
                video_id=VIDEO_ID,
                video_sha256="c" * 64,
                video_revision=1,
                video_track_id="90000000-0000-0000-0000-000000000001",
                label_class_id="class-1",
                frame_index=0,
                verified_track_revision=1,
                pose_schema_id=SCHEMA_ID,
                pose_schema_revision=2,
                pose_schema_content_hash=SCHEMA_HASH,
                verified_pose_sha256="2" * 64,
                canonical_pose_json={
                    "schema_version": "reefvision-canonical-pose-frame-0001",
                    "frame_index": 0,
                    "bbox": [0.0, 0.0, 10.0, 0.0],
                    "pose_observations": [
                        {
                            "landmark_id": "snout",
                            "semantic_label": "Snout",
                            "x": 0.0,
                            "y": 0.0,
                            "status": "visible",
                        },
                        {
                            "landmark_id": "tail",
                            "semantic_label": "Tail",
                            "x": 10.0,
                            "y": 0.0,
                            "status": "visible",
                        },
                    ],
                },
                item_sha256="3" * 64,
            )
        )
        session.commit()


def _patch_runtime(monkeypatch, *, fail: bool = False) -> None:
    from reefvision.services import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation.ReefPosePredictor,
        "from_checkpoint",
        lambda _path, *, device: _FakePredictor(fail=fail),
    )
    monkeypatch.setattr(
        pose_evaluation,
        "load_exact_video_frames",
        lambda _video_path, _video, frame_indices: {
            index: Image.new("RGB", (20, 10), "black") for index in frame_indices
        },
    )


def test_create_persist_list_and_export_scientific_pose_evaluation(
    client: TestClient,
    monkeypatch,
) -> None:
    _seed(client)
    _patch_runtime(monkeypatch)

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={
            "model_id": MODEL_ID,
            "evaluation_dataset_id": DATASET_ID,
            "device": "cpu",
            "pck_thresholds": [0.1, 0.5],
            "calibration_threshold": 0.1,
            "calibration_bins": 2,
            "confidence_thresholds": [0.0, 0.85],
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert run["model_id"] == MODEL_ID
    assert run["evaluation_dataset_id"] == DATASET_ID
    assert run["metrics_json"]["mean_euclidean_error"] == 2.5
    assert run["metrics_json"]["pck"] == {"0.1": 0.5, "0.5": 1.0}
    assert run["provenance_json"]["dataset_manifest_sha256"] == DATASET_HASH
    assert run["provenance_json"]["checkpoint_sha256"]
    assert run["result_sha256"]
    assert run["images_per_second"] > 0

    listed = client.get(f"/api/v1/projects/{PROJECT_ID}/pose-evaluations")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run["id"]]

    detail = client.get(f"/api/v1/pose-evaluations/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["predictions_json"][0]["item_id"].startswith("7000")

    exported_json = client.get(f"/api/v1/pose-evaluations/{run['id']}/export?format=json")
    assert exported_json.status_code == 200
    assert exported_json.json()["result_sha256"] == run["result_sha256"]

    exported_csv = client.get(f"/api/v1/pose-evaluations/{run['id']}/export?format=csv")
    assert exported_csv.status_code == 200
    assert "landmark_id,name,visible_reference_count" in exported_csv.text
    assert "snout" in exported_csv.text


def test_evaluation_rejects_training_leakage_and_schema_mismatch(
    client: TestClient,
    monkeypatch,
) -> None:
    _seed(client)
    _patch_runtime(monkeypatch)

    with client.app.state.session_factory() as session:
        model = session.get(ModelRegistration, MODEL_ID)
        assert model is not None
        metadata = dict(model.metadata_json)
        metadata["source_pose_training_dataset_id"] = DATASET_ID
        model.metadata_json = metadata
        session.commit()

    leaked = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert leaked.status_code == 400
    assert "leakage" in leaked.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        model = session.get(ModelRegistration, MODEL_ID)
        assert model is not None
        metadata = dict(model.metadata_json)
        metadata["source_pose_training_dataset_id"] = "different-dataset"
        metadata["source_pose_schema_content_hash"] = "9" * 64
        model.metadata_json = metadata
        session.commit()

    mismatch = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert mismatch.status_code == 400
    assert "schema" in mismatch.json()["detail"].lower()


def test_failed_inference_does_not_persist_completed_evaluation(
    client: TestClient,
    monkeypatch,
) -> None:
    _seed(client)
    _patch_runtime(monkeypatch, fail=True)

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert response.status_code == 400
    assert "inference" in response.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(PoseEvaluationRun))
        assert count == 0
