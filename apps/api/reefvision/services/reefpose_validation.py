"""Freeze and read independent reference datasets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import PoseLandmarkSchema, PoseLandmarkSchemaRevision, Project, VideoAsset
from reefvision.db.models.reefpose_validation import ReefPoseReference
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.reefpose_validation import FreezeReferenceRequest
from reefvision.services.pose_schemas import definition_for_revision
from reefvision.storage.datasets import canonical_json_sha256


class ReferenceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, project_id: str, reference_id: str) -> ReefPoseReference:
        row = self.session.get(ReefPoseReference, reference_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Independent reference dataset was not found")
        if canonical_json_sha256(row.manifest) != row.manifest_sha256:
            raise ValidationError("Frozen reference dataset integrity check failed")
        return row

    def list(self, project_id: str, limit: int, offset: int) -> list[ReefPoseReference]:
        return list(
            self.session.scalars(
                select(ReefPoseReference)
                .where(ReefPoseReference.project_id == project_id)
                .order_by(ReefPoseReference.created_at.desc(), ReefPoseReference.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def freeze(self, project_id: str, payload: FreezeReferenceRequest) -> ReefPoseReference:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project was not found")
        parent = self.get(project_id, str(payload.parent_id)) if payload.parent_id else None
        if parent and parent.data_kind != payload.data_kind:
            raise ValidationError("A reference revision cannot change its data kind")
        revisions = self.session.scalars(
            select(ReefPoseReference).where(ReefPoseReference.project_id == project_id)
        )
        prior_partitions: dict[tuple[str, str], str] = {}
        for revision in revisions:
            if revision.data_kind == payload.data_kind:
                for record in revision.manifest["recordings"]:
                    for field in ("video_sha256", "group_id"):
                        prior_partitions[(field, record[field])] = record["split"]
        records: list[dict[str, Any]] = []
        for record in payload.recordings:
            video = self.session.get(VideoAsset, str(record.video_id))
            if (
                video is None
                or video.project_id != project_id
                or video.sha256 != record.video_sha256
            ):
                raise ValidationError("Reference source video or content hash does not match")
            if payload.data_kind == "biological" and (video.metadata_json or {}).get("fixture"):
                raise ValidationError("Engineering fixture video cannot be declared biological")
            for field in ("video_sha256", "group_id"):
                if (
                    prior_partitions.get((field, getattr(record, field)), record.split)
                    != record.split
                ):
                    raise ValidationError(
                        "Source video or recording group already belongs to another split"
                    )
            schema = self.session.get(PoseLandmarkSchema, str(record.schema_id))
            revision_row = self.session.scalar(
                select(PoseLandmarkSchemaRevision).where(
                    PoseLandmarkSchemaRevision.schema_id == str(record.schema_id),
                    PoseLandmarkSchemaRevision.revision == record.schema_revision,
                )
            )
            if (
                schema is None
                or schema.project_id != project_id
                or revision_row is None
                or revision_row.content_hash != record.schema_sha256
            ):
                raise ValidationError("Reference anatomy schema revision or hash does not match")
            definition = definition_for_revision(revision_row)
            landmark_ids = {item["id"] for item in definition["landmarks"]}
            for annotation in record.annotations:
                for pose in annotation.poses:
                    if pose.frame >= video.frame_count:
                        raise ValidationError("Reference pose frame is outside the video")
                    ids = [point.id for point in pose.landmarks]
                    if len(set(ids)) != len(ids) or not set(ids) <= landmark_ids:
                        raise ValidationError(
                            "Reference pose landmarks do not match the frozen schema"
                        )
                    if pose.bbox is not None:
                        x, y, width, height = pose.bbox
                        if x + width > video.width_px or y + height > video.height_px:
                            raise ValidationError(
                                "Reference bounding box exceeds source dimensions"
                            )
                    if any(
                        point.x is not None
                        and point.y is not None
                        and point.visibility in {"visible", "occluded"}
                        and not (0 <= point.x < video.width_px and 0 <= point.y < video.height_px)
                        for point in pose.landmarks
                    ):
                        raise ValidationError("Reference landmark exceeds source dimensions")
                if any(sample.frame >= video.frame_count for sample in annotation.measurements):
                    raise ValidationError("Reference measurement frame is outside the video")
            if any(window.end_s > video.duration_seconds + 1e-6 for window in record.event_windows):
                raise ValidationError("Reference scoring window exceeds source duration")
            frozen = record.model_dump(mode="json")
            frozen.update(
                schema=definition,
                annotation_sha256={
                    item["rater_id"]: canonical_json_sha256(item) for item in frozen["annotations"]
                },
                video_revision=video.revision,
                video_geometry={
                    "width": video.width_px,
                    "height": video.height_px,
                    "frames": video.frame_count,
                    "fps": video.fps,
                    "duration_s": video.duration_seconds,
                },
            )
            records.append(frozen)
        manifest = {
            "schema_version": "reefpose-reference-1",
            "name": payload.name,
            "data_kind": payload.data_kind,
            "revision": parent.revision + 1 if parent else 1,
            "parent_sha256": parent.manifest_sha256 if parent else None,
            "recordings": records,
        }
        row = ReefPoseReference(
            project_id=project_id,
            name=payload.name,
            data_kind=payload.data_kind,
            revision=manifest["revision"],
            parent_id=parent.id if parent else None,
            manifest=manifest,
            manifest_sha256=canonical_json_sha256(manifest),
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("A newer reference revision already exists") from exc
        self.session.refresh(row)
        return row
