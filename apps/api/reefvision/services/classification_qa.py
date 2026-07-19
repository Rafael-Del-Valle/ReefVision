"""Classification crop QA and reproducible augmentation preset validation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, ClassificationCrop, ImageAsset, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification_qa import (
    ClassificationAugmentationValidationRequest,
    ClassificationAugmentationValidationResponse,
    ClassificationCropQAIssue,
    ClassificationCropQAMetrics,
    ClassificationCropQARequest,
    ClassificationCropQAResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


def _sharpness(gray: np.ndarray) -> float:
    try:
        import cv2

        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        horizontal = np.diff(gray.astype(np.float32), axis=1)
        vertical = np.diff(gray.astype(np.float32), axis=0)
        values = []
        if horizontal.size:
            values.append(float(np.var(horizontal)))
        if vertical.size:
            values.append(float(np.var(vertical)))
        return float(sum(values) / len(values)) if values else 0.0


class ClassificationQAService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def run_crop_qa(
        self,
        project_id: str,
        request: ClassificationCropQARequest,
    ) -> ClassificationCropQAResponse:
        self._project(project_id)
        query = select(ClassificationCrop).where(
            ClassificationCrop.project_id == project_id
        )
        if request.crop_ids:
            query = query.where(ClassificationCrop.id.in_(request.crop_ids))
        crops = list(
            self.session.scalars(
                query.order_by(
                    ClassificationCrop.label_class_id,
                    ClassificationCrop.created_at,
                    ClassificationCrop.id,
                )
            )
        )
        if request.crop_ids and len(crops) != len(set(request.crop_ids)):
            raise ValidationError("One or more requested crop IDs are missing")
        if not crops:
            raise ValidationError("No classification crops match the request")
        image_ids = {crop.image_id for crop in crops}
        source_images = {
            image.id: image
            for image in self.session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(image_ids))
            )
        }
        issues: list[ClassificationCropQAIssue] = []
        metrics: list[ClassificationCropQAMetrics] = []
        sha_groups: dict[str, list[ClassificationCrop]] = defaultdict(list)
        per_class_counts = Counter(crop.label_class_id for crop in crops)

        for crop in crops:
            path = resolve_managed_project_path(self.settings, crop.managed_path)
            sha_groups[crop.sha256].append(crop)
            if not path.is_file():
                metrics.append(
                    ClassificationCropQAMetrics(
                        crop_id=crop.id,
                        label_class_id=crop.label_class_id,
                        managed_path=crop.managed_path,
                        exists=False,
                        width_px=None,
                        height_px=None,
                        area_px=None,
                        aspect_ratio=None,
                        mean_brightness=None,
                        contrast_std=None,
                        sharpness=None,
                        dark_fraction=None,
                        bright_fraction=None,
                        sha256=crop.sha256,
                    )
                )
                issues.append(
                    ClassificationCropQAIssue(
                        crop_id=crop.id,
                        severity="error",
                        code="managed_crop_missing",
                        message="The managed classification crop file is missing.",
                        measured_value=crop.managed_path,
                    )
                )
                continue
            with Image.open(path) as source:
                gray = np.asarray(source.convert("L"), dtype=np.uint8)
                width, height = source.size
            area = width * height
            aspect_ratio = max(width / max(height, 1), height / max(width, 1))
            mean_brightness = float(gray.mean())
            contrast_std = float(gray.std())
            sharpness = _sharpness(gray)
            dark_fraction = float(np.mean(gray <= 8))
            bright_fraction = float(np.mean(gray >= 247))
            metrics.append(
                ClassificationCropQAMetrics(
                    crop_id=crop.id,
                    label_class_id=crop.label_class_id,
                    managed_path=crop.managed_path,
                    exists=True,
                    width_px=width,
                    height_px=height,
                    area_px=area,
                    aspect_ratio=aspect_ratio,
                    mean_brightness=mean_brightness,
                    contrast_std=contrast_std,
                    sharpness=sharpness,
                    dark_fraction=dark_fraction,
                    bright_fraction=bright_fraction,
                    sha256=crop.sha256,
                )
            )
            checks = [
                (
                    width < request.minimum_width_px,
                    "crop_too_narrow",
                    f"Crop width is below {request.minimum_width_px} pixels.",
                    width,
                    request.minimum_width_px,
                ),
                (
                    height < request.minimum_height_px,
                    "crop_too_short",
                    f"Crop height is below {request.minimum_height_px} pixels.",
                    height,
                    request.minimum_height_px,
                ),
                (
                    area < request.minimum_area_px,
                    "crop_area_too_small",
                    f"Crop area is below {request.minimum_area_px} pixels.",
                    area,
                    request.minimum_area_px,
                ),
                (
                    aspect_ratio > request.maximum_aspect_ratio,
                    "extreme_aspect_ratio",
                    "Crop aspect ratio exceeds the configured maximum.",
                    round(aspect_ratio, 4),
                    request.maximum_aspect_ratio,
                ),
                (
                    mean_brightness < request.minimum_brightness,
                    "crop_too_dark",
                    "Mean crop brightness is below the configured threshold.",
                    round(mean_brightness, 4),
                    request.minimum_brightness,
                ),
                (
                    mean_brightness > request.maximum_brightness,
                    "crop_too_bright",
                    "Mean crop brightness is above the configured threshold.",
                    round(mean_brightness, 4),
                    request.maximum_brightness,
                ),
                (
                    contrast_std < request.minimum_contrast_std,
                    "low_contrast",
                    "Crop contrast is below the configured threshold.",
                    round(contrast_std, 4),
                    request.minimum_contrast_std,
                ),
                (
                    sharpness < request.minimum_sharpness,
                    "possible_blur",
                    "Crop sharpness is below the configured threshold.",
                    round(sharpness, 4),
                    request.minimum_sharpness,
                ),
                (
                    dark_fraction > request.maximum_dark_fraction,
                    "excessive_dark_pixels",
                    "The fraction of near-black pixels exceeds the configured threshold.",
                    round(dark_fraction, 6),
                    request.maximum_dark_fraction,
                ),
                (
                    bright_fraction > request.maximum_bright_fraction,
                    "excessive_bright_pixels",
                    "The fraction of near-white pixels exceeds the configured threshold.",
                    round(bright_fraction, 6),
                    request.maximum_bright_fraction,
                ),
            ]
            for failed, code, message, measured, threshold in checks:
                if failed:
                    issues.append(
                        ClassificationCropQAIssue(
                            crop_id=crop.id,
                            severity="warning",
                            code=code,
                            message=message,
                            measured_value=measured,
                            threshold=threshold,
                        )
                    )
            source_image = source_images.get(crop.image_id)
            box = crop.source_box_json or {}
            if source_image and box:
                touches_boundary = any(
                    (
                        float(box.get("x_min", 1)) <= 0,
                        float(box.get("y_min", 1)) <= 0,
                        float(box.get("x_max", source_image.width_px - 1))
                        >= source_image.width_px,
                        float(box.get("y_max", source_image.height_px - 1))
                        >= source_image.height_px,
                    )
                )
                if touches_boundary:
                    issues.append(
                        ClassificationCropQAIssue(
                            crop_id=crop.id,
                            severity="info",
                            code="source_geometry_touches_boundary",
                            message="The source geometry touches an image boundary; context padding may be clipped.",
                        )
                    )

        duplicate_groups = [items for items in sha_groups.values() if len(items) > 1]
        if request.duplicate_policy != "ignore":
            severity = "error" if request.duplicate_policy == "error" else "warning"
            for group in duplicate_groups:
                for crop in group:
                    issues.append(
                        ClassificationCropQAIssue(
                            crop_id=crop.id,
                            severity=severity,
                            code="duplicate_crop_checksum",
                            message=f"This crop shares its SHA-256 with {len(group) - 1} other crop(s).",
                            measured_value=crop.sha256,
                        )
                    )

        error_crop_ids = {issue.crop_id for issue in issues if issue.severity == "error"}
        checked_at = datetime.now(UTC).isoformat()
        input_payload = {
            "project_id": project_id,
            "request": request.model_dump(mode="json"),
            "crops": [
                {
                    "id": crop.id,
                    "sha256": crop.sha256,
                    "label_class_id": crop.label_class_id,
                    "image_id": crop.image_id,
                    "annotation_id": crop.annotation_id,
                }
                for crop in crops
            ],
        }
        input_checksum = canonical_json_sha256(input_payload)
        report_payload: dict[str, Any] = {
            "format": "reefvision-classification-crop-qa",
            "format_version": "1.0",
            "checked_at": checked_at,
            "input_checksum": input_checksum,
            "crop_count": len(crops),
            "valid_crop_count": len(crops) - len(error_crop_ids),
            "per_class_counts": dict(per_class_counts),
            "metrics": [item.model_dump(mode="json") for item in metrics],
            "issues": [item.model_dump(mode="json") for item in issues],
        }
        report_checksum = canonical_json_sha256(report_payload)
        artifact_id: str | None = None
        if request.persist_report:
            artifact = ArtifactRecord(
                project_id=project_id,
                artifact_type="classification_crop_qa",
                created_by="classification_qa",
                reefvision_version=__version__,
                source_kind="classification_crops",
                source_id=project_id,
                source_checksum=input_checksum,
                parameters_json=request.model_dump(mode="json"),
                postprocessing_json={},
                review_status="unreviewed",
                managed_path=None,
                checksum=report_checksum,
                size_bytes=None,
                metadata_json={"payload": report_payload},
            )
            self.session.add(artifact)
            self.session.commit()
            artifact_id = artifact.id

        warning_messages: list[str] = []
        class_counts = sorted(per_class_counts.values())
        if class_counts and class_counts[0] > 0 and class_counts[-1] / class_counts[0] >= 5:
            warning_messages.append(
                "The crop dataset has at least a 5:1 class imbalance; consider weighted sampling or targeted collection."
            )
        if duplicate_groups:
            warning_messages.append(
                f"Found {len(duplicate_groups)} duplicate checksum groups; keep duplicates in one data split to avoid leakage."
            )
        return ClassificationCropQAResponse(
            project_id=project_id,
            checked_at=checked_at,
            crop_count=len(crops),
            valid_crop_count=len(crops) - len(error_crop_ids),
            error_count=sum(issue.severity == "error" for issue in issues),
            warning_count=sum(issue.severity == "warning" for issue in issues),
            duplicate_group_count=len(duplicate_groups),
            per_class_counts=dict(per_class_counts),
            input_checksum=input_checksum,
            report_checksum=report_checksum,
            artifact_id=artifact_id,
            metrics=metrics,
            issues=issues,
            warnings=warning_messages,
        )

    def validate_augmentation(
        self,
        project_id: str,
        request: ClassificationAugmentationValidationRequest,
    ) -> ClassificationAugmentationValidationResponse:
        self._project(project_id)
        config = request.config
        warnings: list[str] = []
        blockers: list[str] = []
        if config.vertical_flip_probability > 0:
            warnings.append(
                "Vertical flips can create biologically implausible orientations; confirm that orientation is not meaningful for this classifier."
            )
        if config.rotation_degrees > 45:
            warnings.append(
                "Large rotations may expose padding artifacts and unrealistic specimen orientation."
            )
        if config.hue_jitter > 0.08:
            warnings.append(
                "Strong hue jitter may obscure pigmentation or polyp-state cues used by marine classifiers."
            )
        if config.random_erasing_probability > 0.25:
            warnings.append(
                "Frequent random erasing may remove small coral branches or diagnostic polyps."
            )
        if config.mixup_probability + config.cutmix_probability > 0.75:
            blockers.append(
                "Combined MixUp and CutMix probability cannot exceed 0.75 for the ReefVision classifier workflow."
            )
        if config.scale_min < 0.5 or config.scale_max > 2.0:
            warnings.append(
                "The scale range is unusually broad and may create unrealistic specimen sizes."
            )
        payload = {
            "format": "reefvision-classification-augmentation",
            "format_version": "1.0",
            "project_id": project_id,
            "name": request.name,
            "task": request.task,
            "config": config.model_dump(mode="json"),
            "warnings": warnings,
            "blockers": blockers,
        }
        checksum = canonical_json_sha256(payload)
        artifact_id: str | None = None
        if request.save_as_artifact and not blockers:
            artifact = ArtifactRecord(
                project_id=project_id,
                artifact_type="classification_augmentation_preset",
                created_by="classification_qa",
                reefvision_version=__version__,
                source_kind="project",
                source_id=project_id,
                source_checksum=None,
                parameters_json={"task": request.task},
                postprocessing_json={},
                review_status="unreviewed",
                managed_path=None,
                checksum=checksum,
                size_bytes=None,
                metadata_json={"payload": payload},
            )
            self.session.add(artifact)
            self.session.commit()
            artifact_id = artifact.id
        return ClassificationAugmentationValidationResponse(
            project_id=project_id,
            name=request.name,
            task=request.task,
            valid=not blockers,
            normalized_config=config,
            config_checksum=checksum,
            warnings=warnings,
            blockers=blockers,
            artifact_id=artifact_id,
        )
