"""Reproducible held-out evaluation for registered native ReefPose models."""

from __future__ import annotations

import csv
import io
import json
import platform
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ModelRegistration,
    PoseEvaluationRun,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    Project,
    VideoAsset,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.pose_evaluation import (
    PoseEvaluationInstance,
    PoseLandmarkEstimate,
    PoseLandmarkReference,
    evaluate_pose_instances,
)
from reefvision.ml.reefpose.inference import ReefPosePredictor
from reefvision.schemas.pose_evaluation import (
    PoseEvaluationCreateRequest,
    PoseEvaluationRunResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def load_exact_video_frames(
    video_path: Path,
    video: VideoAsset,
    frame_indices: list[int],
) -> dict[int, Image.Image]:
    targets = sorted(set(frame_indices))
    if not targets or targets[0] < 0 or targets[-1] >= video.frame_count:
        raise ValidationError("Evaluation contains an invalid source video frame")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValidationError("Could not open the managed evaluation source video")
    frames: dict[int, Image.Image] = {}
    target_set = set(targets)
    try:
        for frame_index in range(targets[-1] + 1):
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValidationError(f"Evaluation video ended before frozen frame {targets[-1]}")
            if frame_index in target_set:
                height, width = frame.shape[:2]
                if (width, height) != (video.width_px, video.height_px):
                    raise ValidationError(
                        "Decoded evaluation frame dimensions differ from frozen video metadata"
                    )
                frames[frame_index] = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    return frames


def _synchronize_cuda(device: str) -> None:
    if not device.casefold().startswith("cuda"):
        return
    try:
        import torch

        torch.cuda.synchronize()
    except Exception as exc:
        raise ValidationError("CUDA synchronization failed during pose evaluation") from exc


class PoseEvaluationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _run(self, run_id: str) -> PoseEvaluationRun:
        run = self.session.get(PoseEvaluationRun, run_id)
        if run is None:
            raise NotFoundError("Pose evaluation run not found")
        return run

    @staticmethod
    def _schema_identity(model: ModelRegistration) -> tuple[str, int, str]:
        metadata = dict(model.metadata_json or {})
        try:
            return (
                str(metadata["source_pose_schema_id"]),
                int(metadata["source_pose_schema_revision"]),
                str(metadata["source_pose_schema_content_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                "Registered ReefPose model lacks immutable anatomy schema provenance"
            ) from exc

    @staticmethod
    def _check_leakage(model: ModelRegistration, dataset: PoseTrainingDataset) -> None:
        metadata = dict(model.metadata_json or {})
        forbidden_ids = {
            str(value)
            for value in (
                metadata.get("source_pose_training_dataset_id"),
                metadata.get("source_pose_validation_dataset_id"),
            )
            if value
        }
        forbidden_hashes = {
            str(value)
            for value in (
                metadata.get("source_pose_training_dataset_manifest_sha256"),
                metadata.get("source_pose_validation_dataset_manifest_sha256"),
            )
            if value
        }
        if dataset.id in forbidden_ids or dataset.manifest_sha256 in forbidden_hashes:
            raise ValidationError(
                "Evaluation leakage detected: choose a dataset that was not used for "
                "training or validation/model selection"
            )

    @staticmethod
    def _reference_instance(
        item: PoseTrainingDatasetItem,
        estimates: tuple[PoseLandmarkEstimate, ...],
        oks_sigmas: dict[str, float] | None,
    ) -> PoseEvaluationInstance:
        payload = dict(item.canonical_pose_json or {})
        raw_observations = payload.get("pose_observations")
        raw_bbox = payload.get("bbox")
        if not isinstance(raw_observations, list) or not isinstance(raw_bbox, list):
            raise ValidationError("Frozen evaluation pose is missing observations or bbox")
        if len(raw_bbox) != 4:
            raise ValidationError("Frozen evaluation pose bbox is invalid")
        width = float(raw_bbox[2])
        height = float(raw_bbox[3])
        normalization_length = (width**2 + height**2) ** 0.5
        if normalization_length <= 0:
            raise ValidationError("Evaluation pose bbox diagonal must be positive")
        references: list[PoseLandmarkReference] = []
        for raw in raw_observations:
            if not isinstance(raw, dict) or not raw.get("landmark_id"):
                raise ValidationError("Evaluation truth requires stable landmark IDs")
            try:
                references.append(
                    PoseLandmarkReference(
                        landmark_id=str(raw["landmark_id"]),
                        name=str(raw.get("semantic_label") or raw["landmark_id"]),
                        x=float(raw.get("x", 0.0)),
                        y=float(raw.get("y", 0.0)),
                        visibility=str(raw.get("status", "uncertain")),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValidationError("Evaluation truth landmark is invalid") from exc
        return PoseEvaluationInstance(
            instance_id=item.id,
            references=tuple(references),
            estimates=estimates,
            normalization_length=normalization_length,
            reference_area=width * height if width > 0 and height > 0 else None,
            oks_sigmas=oks_sigmas,
        )

    def create(
        self,
        project_id: str,
        payload: PoseEvaluationCreateRequest,
    ) -> PoseEvaluationRunResponse:
        project = self.session.get(Project, project_id)
        model = self.session.get(ModelRegistration, payload.model_id)
        dataset = self.session.get(PoseTrainingDataset, payload.evaluation_dataset_id)
        if project is None:
            raise NotFoundError("Project not found")
        if model is None or dataset is None:
            raise NotFoundError("Pose model or evaluation dataset not found")
        if model.project_id != project_id or dataset.project_id != project_id:
            raise ValidationError("Pose evaluation inputs must belong to the selected project")
        if model.provider_name != "reefpose" or model.task != "pose":
            raise ValidationError("This evaluator currently requires a native ReefPose model")
        if dataset.status != "complete" or dataset.item_count < 1:
            raise ValidationError("Pose evaluation requires a completed immutable dataset")
        self._check_leakage(model, dataset)
        if self._schema_identity(model) != (
            dataset.pose_schema_id,
            dataset.pose_schema_revision,
            dataset.pose_schema_content_hash,
        ):
            raise ValidationError("Model and evaluation dataset anatomy schema identities differ")

        checkpoint_path = resolve_managed_project_path(self.settings, model.managed_path)
        checkpoint_sha, checkpoint_size = hash_model_file(checkpoint_path)
        if checkpoint_sha != model.sha256 or checkpoint_size != model.file_size_bytes:
            raise ValidationError("Registered ReefPose checkpoint integrity check failed")
        items = list(
            self.session.scalars(
                select(PoseTrainingDatasetItem)
                .where(PoseTrainingDatasetItem.dataset_id == dataset.id)
                .order_by(PoseTrainingDatasetItem.video_id, PoseTrainingDatasetItem.frame_index)
            )
        )
        if len(items) != dataset.item_count:
            raise ValidationError("Frozen evaluation dataset item count has changed")

        predictor = ReefPosePredictor.from_checkpoint(checkpoint_path, device=payload.device)
        frame_requests: dict[str, list[int]] = {}
        videos: dict[str, VideoAsset] = {}
        for item in items:
            video = videos.get(item.video_id)
            if video is None:
                video = self.session.get(VideoAsset, item.video_id)
            if video is None or video.project_id != project_id:
                raise ValidationError("Frozen evaluation source video is unavailable")
            videos[item.video_id] = video
            if video.sha256 != item.video_sha256 or video.revision != item.video_revision:
                raise ValidationError("Frozen evaluation source video provenance has changed")
            frame_requests.setdefault(item.video_id, []).append(item.frame_index)
        frames: dict[tuple[str, int], Image.Image] = {}
        for video_id, indices in frame_requests.items():
            video = videos[video_id]
            video_path = resolve_managed_project_path(self.settings, video.managed_path)
            for frame_index, image in load_exact_video_frames(video_path, video, indices).items():
                frames[(video_id, frame_index)] = image

        instances: list[PoseEvaluationInstance] = []
        predictions: list[dict[str, Any]] = []
        inference_seconds = 0.0
        try:
            for item in items:
                image = frames[(item.video_id, item.frame_index)]
                _synchronize_cuda(payload.device)
                started = perf_counter()
                prediction = predictor.predict(image, confidence_threshold=0.0)
                _synchronize_cuda(payload.device)
                inference_seconds += max(perf_counter() - started, 1e-12)
                if (
                    prediction.anatomy_schema_id,
                    prediction.anatomy_schema_revision,
                    prediction.anatomy_integrity_hash,
                ) != self._schema_identity(model):
                    raise ValidationError(
                        "ReefPose prediction anatomy differs from registered model provenance"
                    )
                estimates = tuple(
                    PoseLandmarkEstimate(
                        landmark_id=item_prediction.landmark_id,
                        x=item_prediction.x,
                        y=item_prediction.y,
                        confidence=item_prediction.confidence,
                        visible=item_prediction.visibility_state == "visible",
                    )
                    for item_prediction in prediction.landmarks
                )
                instances.append(
                    self._reference_instance(
                        item,
                        estimates,
                        (
                            {key: float(value) for key, value in payload.oks_sigmas.items()}
                            if payload.oks_sigmas is not None
                            else None
                        ),
                    )
                )
                predictions.append(
                    {
                        "item_id": item.id,
                        "video_id": item.video_id,
                        "frame_index": item.frame_index,
                        "landmarks": [asdict(landmark) for landmark in prediction.landmarks],
                        "confidence": prediction.confidence,
                        "bbox": list(prediction.bbox) if prediction.bbox is not None else None,
                    }
                )
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError("ReefPose evaluation inference failed") from exc

        metrics = evaluate_pose_instances(
            instances,
            pck_thresholds=tuple(float(value) for value in payload.pck_thresholds),
            calibration_threshold=float(payload.calibration_threshold),
            calibration_bins=payload.calibration_bins,
            confidence_thresholds=tuple(float(value) for value in payload.confidence_thresholds),
        )
        metrics_json = asdict(metrics)
        configuration = payload.model_dump(mode="json")
        provenance = {
            "project_id": project_id,
            "model_id": model.id,
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_size_bytes": checkpoint_size,
            "dataset_id": dataset.id,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "pose_schema_id": dataset.pose_schema_id,
            "pose_schema_revision": dataset.pose_schema_revision,
            "pose_schema_content_hash": dataset.pose_schema_content_hash,
            "truth_policy": "scientist_verified_only",
            "normalization_policy": "verified_bbox_diagonal",
            "software": {"python": platform.python_version()},
            "device_request": payload.device,
        }
        result_payload = {
            "schema_version": "reefpose-evaluation-run-0001",
            "configuration": configuration,
            "metrics": metrics_json,
            "predictions": predictions,
            "provenance": provenance,
        }
        run = PoseEvaluationRun(
            project_id=project_id,
            model_id=model.id,
            evaluation_dataset_id=dataset.id,
            schema_version="reefpose-evaluation-run-0001",
            status="completed",
            configuration_json=configuration,
            metrics_json=metrics_json,
            predictions_json=predictions,
            provenance_json=provenance,
            warnings_json=list(metrics.warnings),
            result_sha256=canonical_json_sha256(result_payload),
            inference_latency_ms=(inference_seconds / len(items)) * 1000.0,
            images_per_second=len(items) / inference_seconds,
        )
        try:
            self.session.add(run)
            self.session.commit()
            self.session.refresh(run)
        except Exception:
            self.session.rollback()
            raise
        return PoseEvaluationRunResponse.model_validate(run)

    def list_for_project(
        self, project_id: str, *, limit: int, offset: int
    ) -> list[PoseEvaluationRunResponse]:
        rows = self.session.scalars(
            select(PoseEvaluationRun)
            .where(PoseEvaluationRun.project_id == project_id)
            .order_by(PoseEvaluationRun.created_at.desc(), PoseEvaluationRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [PoseEvaluationRunResponse.model_validate(row) for row in rows]

    def get(self, run_id: str) -> PoseEvaluationRunResponse:
        return PoseEvaluationRunResponse.model_validate(self._run(run_id))

    def export_json(self, run_id: str) -> dict[str, Any]:
        return self.get(run_id).model_dump(mode="json")

    def export_csv(self, run_id: str) -> str:
        run = self._run(run_id)
        per_landmark = dict(run.metrics_json.get("per_landmark") or {})
        stream = io.StringIO(newline="")
        fieldnames = [
            "landmark_id",
            "name",
            "visible_reference_count",
            "matched_visible_count",
            "localization_coverage",
            "mean_euclidean_error",
            "median_euclidean_error",
            "nme",
            "pck_json",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for landmark_id, metrics in sorted(per_landmark.items()):
            writer.writerow(
                {
                    **{key: metrics.get(key) for key in fieldnames if key != "pck_json"},
                    "landmark_id": landmark_id,
                    "pck_json": json.dumps(
                        metrics.get("pck", {}),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        return stream.getvalue()
