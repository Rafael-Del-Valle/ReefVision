"""Transactional, project-scoped scientific observations with content integrity."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ImageAsset,
    Job,
    MaskAnnotation,
    PredictionProposal,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.scientific_units import normalize_quantity
from reefvision.schemas.scientific_data import (
    ScientificPixel,
    ScientificRecordCreate,
    ScientificRecordPage,
    ScientificRecordResponse,
    ScientificSubject,
    SourceKind,
)


def content_hash(payload: Any) -> str:
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Scientific metadata must be finite JSON") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ScientificDataService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def require_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def validate_subject(
        self, project_id: str, subject: ScientificSubject, pixel: ScientificPixel | None = None
    ) -> ImageAsset | None:
        object_run_id: str | None = None
        image = self.session.get(ImageAsset, str(subject.image_id)) if subject.image_id else None
        video = self.session.get(VideoAsset, str(subject.video_id)) if subject.video_id else None
        for identifier, asset in ((subject.image_id, image), (subject.video_id, video)):
            if identifier and (asset is None or asset.project_id != project_id):
                raise ValidationError("Scientific source media must belong to this project")
        if (
            video is not None
            and subject.frame_index is not None
            and subject.frame_index >= video.frame_count
        ):
            raise ValidationError("Frame index exceeds the source video")
        if subject.track_id:
            track = self.session.get(VideoTrack, str(subject.track_id))
            if track is None or track.video_id != str(subject.video_id) or track.deleted_at:
                raise ValidationError("Track must belong to the source video and be active")
            object_run_id = track.source_job_id
        for identifier, model in (
            (subject.annotation_id, Annotation),
            (subject.mask_id, MaskAnnotation),
            (subject.prediction_id, PredictionProposal),
        ):
            if identifier:
                obj = self.session.get(model, str(identifier))
                if (
                    not isinstance(obj, (Annotation, MaskAnnotation, PredictionProposal))
                    or obj.image_id != str(subject.image_id)
                    or getattr(obj, "deleted_at", None)
                ):
                    raise ValidationError("Object must belong to the source image and be active")
                if isinstance(obj, PredictionProposal):
                    object_run_id = obj.inference_job_id
                else:
                    object_run_id = (obj.provenance_json or {}).get("inference_job_id")
        if subject.model_run_id:
            job = self.session.get(Job, str(subject.model_run_id))
            if job is None or job.project_id != project_id:
                raise ValidationError("Model run must belong to this project")
            if job.job_type not in {
                "inference",
                "classification_inference",
                "sam_image_proposals",
                "advanced_depth",
                "video_tracking",
                "video_metric_depth_3d",
            }:
                raise ValidationError(
                    "Model run must identify a supported inference or tracking job"
                )
            if object_run_id is not None and object_run_id != job.id:
                raise ValidationError("Model run must match the canonical object's source run")
            if (
                any((subject.track_id, subject.annotation_id, subject.mask_id))
                and object_run_id is None
            ):
                raise ValidationError("The canonical object has no recorded model source run")
            if image is not None:
                image_ids = job.request_json.get("image_ids", [])
                if not isinstance(image_ids, list) or (
                    image.id not in image_ids and job.request_json.get("image_id") != image.id
                ):
                    raise ValidationError("Model run does not include the source image")
            if video is not None and job.request_json.get("video_id") != video.id:
                raise ValidationError("Model run does not include the source video")
        if pixel is not None:
            media = image if pixel.frame == "image_pixels" else video
            if media is None or pixel.x >= media.width_px or pixel.y >= media.height_px:
                raise ValidationError(
                    "Pixel location must lie inside the original source dimensions"
                )
        return image

    def add_records(
        self,
        project_id: str,
        items: list[ScientificRecordCreate],
        *,
        environmental_cache_key: str | None = None,
    ) -> list[ScientificRecord]:
        """Stage a validated batch; the caller owns the transaction/commit."""
        self.require_project(project_id)
        rows = []
        for item in items:
            image = self.validate_subject(project_id, item.subject, item.pixel)
            payload = item.model_dump(mode="json")
            try:
                value, unit = normalize_quantity(item.value, item.unit)
                uncertainty = (
                    normalize_quantity(item.uncertainty.value, item.unit, difference=True)[0]
                    if item.uncertainty
                    else None
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            calibration = (
                deepcopy((image.metadata_json or {}).get("measurement_calibration"))
                if image
                else None
            )
            payload.update(
                normalized_value=value,
                normalized_unit=unit,
                normalized_uncertainty=uncertainty,
                calibration_snapshot=calibration,
                calibration_sha256=content_hash(calibration) if calibration else None,
                environmental_cache_key=environmental_cache_key,
            )
            rows.append(
                ScientificRecord(
                    id=str(uuid4()),
                    project_id=project_id,
                    variable=item.variable,
                    source_kind=item.source_kind,
                    observed_at=item.observed_at,
                    image_id=str(item.subject.image_id) if item.subject.image_id else None,
                    video_id=str(item.subject.video_id) if item.subject.video_id else None,
                    track_id=str(item.subject.track_id) if item.subject.track_id else None,
                    model_run_id=str(item.subject.model_run_id)
                    if item.subject.model_run_id
                    else None,
                    payload_json=payload,
                    content_sha256=content_hash(payload),
                )
            )
        self.session.add_all(rows)
        self.session.flush()
        return rows

    def response(self, row: ScientificRecord) -> ScientificRecordResponse:
        if content_hash(row.payload_json) != row.content_sha256:
            raise ConflictError("Scientific record checksum mismatch; do not use this record")
        current = None
        snapshot_current = None
        cache_key = row.payload_json.get("environmental_cache_key")
        if cache_key is not None:
            cache = self.session.scalar(
                select(EnvironmentalCacheEntry).where(
                    EnvironmentalCacheEntry.project_id == row.project_id,
                    EnvironmentalCacheEntry.cache_key == cache_key,
                )
            )
            if cache is None or content_hash(cache.payload_json) != cache.content_sha256:
                raise ConflictError("Environmental snapshot cache is missing or corrupt")
            snapshot_current = row.id in cache.payload_json["record_ids"]
        if row.payload_json.get("calibration_sha256"):
            image = self.session.get(ImageAsset, row.image_id) if row.image_id else None
            calibration = (
                (image.metadata_json or {}).get("measurement_calibration") if image else None
            )
            current = content_hash(calibration) == row.payload_json["calibration_sha256"]
        return ScientificRecordResponse.model_validate(
            {
                **row.payload_json,
                "id": row.id,
                "project_id": row.project_id,
                "content_sha256": row.content_sha256,
                "calibration_current": current,
                "environmental_snapshot_current": snapshot_current,
            }
        )

    def list_records(
        self,
        project_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        variable: str | None = None,
        source_kind: SourceKind | None = None,
    ) -> ScientificRecordPage:
        self.require_project(project_id)
        query = select(ScientificRecord).where(ScientificRecord.project_id == project_id)
        if variable is not None:
            query = query.where(ScientificRecord.variable == variable)
        if source_kind is not None:
            query = query.where(ScientificRecord.source_kind == source_kind)
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ScientificRecord.created_at, ScientificRecord.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ScientificRecordPage(items=[self.response(row) for row in rows], total=total)
