from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from reefvision.db.models import (
    ModelRegistration,
    PoseEvaluationRun,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    Project,
    VideoAsset,
)
from reefvision.ml.pose_evaluation import (
    NormalizedLandmarkPrediction,
    NormalizedPosePrediction,
)
from reefvision.ml.reefpose.checkpoints import save_checkpoint
from reefvision.ml.reefpose.inference import LandmarkPrediction, PosePrediction
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition
from reefvision.storage.datasets import canonical_json_sha256

PROJECT_ID = "10000000-0000-0000-0000-000000000001"
MODEL_ID = "20000000-0000-0000-0000-000000000001"
DATASET_ID = "30000000-0000-0000-0000-000000000001"
VIDEO_ID = "40000000-0000-0000-0000-000000000001"
SCHEMA_ID = "50000000-0000-0000-0000-000000000001"
SCHEMA_HASH = "a" * 64
NATIVE_SCHEMA_HASH = "7" * 64
ITEM_ID = "70000000-0000-0000-0000-000000000001"
SOURCE_ROUND_ID = "60000000-0000-0000-0000-000000000001"
CANDIDATE_ID = "80000000-0000-0000-0000-000000000001"
CANDIDATE_PROVENANCE_SHA = "4" * 64
CANONICAL_POSE = {
    "schema_version": "reefvision-canonical-pose-frame-0001",
    "frame_index": 0,
    "bbox": [0.0, 0.0, 6.0, 8.0],
    "confidence": None,
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
    "keypoints": [],
}
VERIFIED_POSE_HASH = canonical_json_sha256(
    {
        "schema_version": "pose-active-learning-verified-pose-0001",
        "video_track_id": "90000000-0000-0000-0000-000000000001",
        "track_revision": 1,
        "focus_frame": 0,
        "pose_schema_id": SCHEMA_ID,
        "pose_schema_revision": 2,
        "pose_observations": CANONICAL_POSE["pose_observations"],
        "keypoints": [],
    }
)
VIDEO_BYTES = b"synthetic-video"
VIDEO_SHA = hashlib.sha256(VIDEO_BYTES).hexdigest()
SCHEMA_SNAPSHOT = {
    "schema_version": "pose-landmarks-0001",
    "schema_id": SCHEMA_ID,
    "schema_revision": 2,
    "name": "Synthetic fish anatomy",
    "groups": [],
    "expanded_labels": ["snout", "tail"],
    "keypoint_count": 2,
    "allows_repeated_labels": False,
    "content_hash": SCHEMA_HASH,
}
REVIEW_PROVENANCE = {"before": {"candidate_provenance_sha256": CANDIDATE_PROVENANCE_SHA}}
ITEM_SHA = canonical_json_sha256(
    {
        "schema_version": "pose-training-dataset-item-0001",
        "dataset_id": DATASET_ID,
        "candidate_id": CANDIDATE_ID,
        "project_id": PROJECT_ID,
        "source_round_id": SOURCE_ROUND_ID,
        "video": {
            "video_id": VIDEO_ID,
            "sha256": VIDEO_SHA,
            "revision": 1,
            "original_filename": "fish.avi",
            "width_px": 20,
            "height_px": 10,
            "frame_count": 1,
            "fps": 30.0,
        },
        "video_track_id": "90000000-0000-0000-0000-000000000001",
        "label_class_id": "class-1",
        "verified_track_revision": 1,
        "pose_schema": SCHEMA_SNAPSHOT,
        "verified_pose_sha256": VERIFIED_POSE_HASH,
        "canonical_pose": CANONICAL_POSE,
        "source_models": [],
        "source_job_ids": [],
        "acquisition_provenance": {},
        "candidate_provenance_sha256": CANDIDATE_PROVENANCE_SHA,
        "review_provenance": REVIEW_PROVENANCE,
    }
)
DATASET_MANIFEST = {
    "schema_version": "pose-training-dataset-manifest-0001",
    "dataset_id": DATASET_ID,
    "items": [
        {
            "item_id": ITEM_ID,
            "item_sha256": ITEM_SHA,
            "candidate_id": CANDIDATE_ID,
            "video_id": VIDEO_ID,
            "video_sha256": VIDEO_SHA,
            "video_track_id": "90000000-0000-0000-0000-000000000001",
            "frame_index": 0,
            "verified_track_revision": 1,
            "verified_pose_sha256": VERIFIED_POSE_HASH,
            "pose_schema_id": SCHEMA_ID,
            "pose_schema_revision": 2,
            "pose_schema_content_hash": SCHEMA_HASH,
        }
    ],
}
DATASET_HASH = canonical_json_sha256(DATASET_MANIFEST)


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
            anatomy_integrity_hash=NATIVE_SCHEMA_HASH,
        )


class _FakeRuntime:
    resolved_device = "cpu"
    visibility_metrics_available = True

    def __init__(self, *, fail: bool = False) -> None:
        self.predictor = _FakePredictor(fail=fail)

    def predict(self, image: Image.Image) -> NormalizedPosePrediction:
        prediction = self.predictor.predict(image, confidence_threshold=0.0)
        return NormalizedPosePrediction(
            landmarks=tuple(
                NormalizedLandmarkPrediction(
                    landmark_id=item.landmark_id,
                    name=item.name,
                    occurrence_index=item.occurrence_index,
                    x=item.x,
                    y=item.y,
                    confidence=item.confidence,
                    visibility_state=item.visibility_state,
                )
                for item in prediction.landmarks
            ),
            bbox=prediction.bbox,
            schema_id=prediction.anatomy_schema_id,
            schema_revision=prediction.anatomy_schema_revision,
            native_integrity_hash=prediction.anatomy_integrity_hash,
        )

    def close(self) -> None:
        return


def _seed(client: TestClient) -> None:
    settings = client.app.state.settings
    managed_checkpoint = settings.resolved_data_dir / "projects/p1/models/reefpose.pt"
    managed_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    managed_checkpoint.write_bytes(b"synthetic-checkpoint")
    checkpoint_sha = hashlib.sha256(managed_checkpoint.read_bytes()).hexdigest()
    managed_video = settings.resolved_data_dir / "projects/p1/videos/fish.avi"
    managed_video.parent.mkdir(parents=True, exist_ok=True)
    managed_video.write_bytes(VIDEO_BYTES)

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
            PoseLandmarkSchema(
                id=SCHEMA_ID,
                project_id=PROJECT_ID,
                name=SCHEMA_SNAPSHOT["name"],
            )
        )
        session.add(
            PoseLandmarkSchemaRevision(
                id="51000000-0000-0000-0000-000000000001",
                schema_id=SCHEMA_ID,
                revision=2,
                schema_version=SCHEMA_SNAPSHOT["schema_version"],
                groups_json=[],
                expanded_labels_json=SCHEMA_SNAPSHOT["expanded_labels"],
                keypoint_count=2,
                allows_repeated_labels=False,
                definition_json=None,
                content_hash=SCHEMA_HASH,
            )
        )
        session.add(
            VideoAsset(
                id=VIDEO_ID,
                project_id=PROJECT_ID,
                original_filename="fish.avi",
                managed_path="projects/p1/videos/fish.avi",
                sha256=VIDEO_SHA,
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
                    "reefpose_anatomy_integrity_hash": NATIVE_SCHEMA_HASH,
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
                source_round_id=SOURCE_ROUND_ID,
                name="Held-out fish",
                status="complete",
                pose_schema_id=SCHEMA_ID,
                pose_schema_revision=2,
                pose_schema_content_hash=SCHEMA_HASH,
                source_selection_sha256="f" * 64,
                source_retraining_manifest_sha256="1" * 64,
                manifest_json=DATASET_MANIFEST,
                manifest_sha256=DATASET_HASH,
                item_count=1,
            )
        )
        session.add(
            PoseTrainingDatasetItem(
                id=ITEM_ID,
                dataset_id=DATASET_ID,
                candidate_id=CANDIDATE_ID,
                video_id=VIDEO_ID,
                video_sha256=VIDEO_SHA,
                video_revision=1,
                video_track_id="90000000-0000-0000-0000-000000000001",
                label_class_id="class-1",
                frame_index=0,
                verified_track_revision=1,
                pose_schema_id=SCHEMA_ID,
                pose_schema_revision=2,
                pose_schema_content_hash=SCHEMA_HASH,
                verified_pose_sha256=VERIFIED_POSE_HASH,
                canonical_pose_json=CANONICAL_POSE,
                review_provenance_json=REVIEW_PROVENANCE,
                item_sha256=ITEM_SHA,
            )
        )
        session.commit()


def _patch_runtime(monkeypatch, *, fail: bool = False) -> None:
    from reefvision.services import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation,
        "create_provider_evaluation_runtime",
        lambda _model, _path, _schema, _device: _FakeRuntime(fail=fail),
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


def test_evaluation_rejects_tampered_frozen_dataset_and_video(
    client: TestClient,
    monkeypatch,
) -> None:
    _seed(client)
    _patch_runtime(monkeypatch)

    with client.app.state.session_factory() as session:
        dataset = session.get(PoseTrainingDataset, DATASET_ID)
        assert dataset is not None
        dataset.manifest_json = {**dict(dataset.manifest_json), "tampered": True}
        session.commit()
    manifest_response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert manifest_response.status_code == 400
    assert "manifest" in manifest_response.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        dataset = session.get(PoseTrainingDataset, DATASET_ID)
        item = session.get(PoseTrainingDatasetItem, ITEM_ID)
        assert dataset is not None and item is not None
        dataset.manifest_json = DATASET_MANIFEST
        changed = dict(item.canonical_pose_json)
        changed["pose_observations"] = [
            {**observation, "x": 99.0} for observation in changed["pose_observations"]
        ]
        item.canonical_pose_json = changed
        session.commit()
    item_response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert item_response.status_code == 400
    assert "verified pose" in item_response.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        item = session.get(PoseTrainingDatasetItem, ITEM_ID)
        assert item is not None
        item.canonical_pose_json = CANONICAL_POSE
        session.commit()
    with client.app.state.session_factory() as session:
        item = session.get(PoseTrainingDatasetItem, ITEM_ID)
        assert item is not None
        item.canonical_pose_json = {**CANONICAL_POSE, "bbox": [0.0, 0.0, 20.0, 10.0]}
        session.commit()
    item_hash_response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert item_hash_response.status_code == 400
    assert "item integrity" in item_hash_response.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        item = session.get(PoseTrainingDatasetItem, ITEM_ID)
        assert item is not None
        item.canonical_pose_json = CANONICAL_POSE
        session.commit()
    video_path = client.app.state.settings.resolved_data_dir / "projects/p1/videos/fish.avi"
    video_path.write_bytes(b"same-dimensions-replacement")
    video_response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={"model_id": MODEL_ID, "evaluation_dataset_id": DATASET_ID},
    )
    assert video_response.status_code == 400
    assert "video checksum" in video_response.json()["detail"].lower()


def test_pose_evaluation_service_import_does_not_require_torch() -> None:
    environment = os.environ.copy()
    api_root = str(Path(__file__).resolve().parents[3])
    environment["PYTHONPATH"] = api_root
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import sys; sys.modules['torch'] = None; import reefvision.services.pose_evaluation"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("REEFPOSE_RUN_GPU_TESTS") != "1",
    reason="Set REEFPOSE_RUN_GPU_TESTS=1 for explicit RTX evaluation validation",
)
def test_native_reefpose_cuda_scientific_evaluation(
    client: TestClient,
    monkeypatch,
) -> None:
    import torch

    assert torch.cuda.is_available()
    _seed(client)
    schema = AnatomySchema(
        schema_id=SCHEMA_ID,
        name="Synthetic GPU fish",
        revision=2,
        landmarks=(
            LandmarkDefinition(landmark_id="snout", name="Snout"),
            LandmarkDefinition(landmark_id="tail", name="Tail"),
        ),
    )
    model = ReefPoseS(
        ReefPoseConfig(
            num_keypoints=2,
            input_height=64,
            input_width=64,
            base_channels=4,
            fpn_channels=8,
        )
    )
    checkpoint = client.app.state.settings.resolved_data_dir / "projects/p1/models/reefpose.pt"
    save_checkpoint(checkpoint, model=model, schema=schema, epoch=0, global_step=0)
    checkpoint_bytes = checkpoint.read_bytes()
    with client.app.state.session_factory() as session:
        registered = session.get(ModelRegistration, MODEL_ID)
        dataset = session.get(PoseTrainingDataset, DATASET_ID)
        item = session.get(
            PoseTrainingDatasetItem,
            ITEM_ID,
        )
        assert registered is not None and dataset is not None and item is not None
        registered.sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
        registered.file_size_bytes = len(checkpoint_bytes)
        registered.metadata_json = {
            **dict(registered.metadata_json),
            "reefpose_anatomy_integrity_hash": schema.integrity_hash,
        }
        session.commit()

    from reefvision.services import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation,
        "load_exact_video_frames",
        lambda _path, _video, indices: {
            index: Image.new("RGB", (20, 10), "black") for index in indices
        },
    )
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluations",
        json={
            "model_id": MODEL_ID,
            "evaluation_dataset_id": DATASET_ID,
            "device": "cuda",
        },
    )
    torch.cuda.synchronize()
    assert response.status_code == 201, response.text
    result = response.json()
    evidence = {
        "schema_version": "reefpose-phase3-evaluation-gpu-0001",
        "scientific_accuracy_validated": False,
        "fixture": "synthetic-engineering-only",
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "evaluation_run_id": result["id"],
        "result_sha256": result["result_sha256"],
        "inference_latency_ms": result["inference_latency_ms"],
        "images_per_second": result["images_per_second"],
        "peak_gpu_memory_bytes": torch.cuda.max_memory_allocated(),
        "visible_reference_count": result["metrics_json"]["visible_reference_count"],
        "matched_visible_count": result["metrics_json"]["matched_visible_count"],
    }
    print("REEFPOSE_PHASE3_GPU_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
