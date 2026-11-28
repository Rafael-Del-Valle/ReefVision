"""Append-only integrity-checked metadata revisions for immutable 3D originals."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import SpatialAssetMetadataRevision
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_asset_metadata_revision_v14 import (
    SpatialAssetMetadataRevisionCreate,
    SpatialAssetMetadataRevisionResponse,
)
from reefvision.services.spatial_source_assets_v14 import SpatialSourceAssetService
from reefvision.storage.datasets import canonical_json_sha256


def spatial_asset_metadata_content(
    *,
    project_id: str,
    asset_id: str,
    source_sha256: str,
    revision: int,
    previous_revision_id: str | None,
    payload: SpatialAssetMetadataRevisionCreate,
) -> dict[str, Any]:
    return {
        "schema_version": "spatial-asset-metadata-0001",
        "project_id": project_id,
        "spatial_source_asset_id": asset_id,
        "source_sha256": source_sha256,
        "revision": revision,
        "previous_revision_id": previous_revision_id,
        **payload.model_dump(mode="json"),
    }


class SpatialAssetMetadataRevisionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.sources = SpatialSourceAssetService(session, settings)

    def _response(
        self,
        project_id: str,
        asset_id: str,
        row: SpatialAssetMetadataRevision,
    ) -> SpatialAssetMetadataRevisionResponse:
        source = self.sources.get(project_id, asset_id)
        self.sources.read_verified(project_id, asset_id)
        return self._validated_response(project_id, asset_id, source.sha256, row)

    def _validated_response(
        self,
        project_id: str,
        asset_id: str,
        source_sha256: str,
        row: SpatialAssetMetadataRevision,
    ) -> SpatialAssetMetadataRevisionResponse:
        if (
            row.project_id != project_id
            or row.spatial_source_asset_id != asset_id
            or row.source_sha256 != source_sha256
            or row.revision <= 0
        ):
            raise ValidationError("Spatial asset metadata source binding is inconsistent")
        # A self-consistent content hash alone does not prove revision ancestry.
        # Check the immediate predecessor before exposing a purported history.
        if row.revision == 1:
            if row.previous_revision_id is not None:
                raise ValidationError("Spatial asset metadata revision ancestry is inconsistent")
        else:
            if row.previous_revision_id is None:
                raise ValidationError("Spatial asset metadata revision ancestry is inconsistent")
            predecessor = self.session.get(SpatialAssetMetadataRevision, row.previous_revision_id)
            if (
                predecessor is None
                or predecessor.project_id != project_id
                or predecessor.spatial_source_asset_id != asset_id
                or predecessor.source_sha256 != source_sha256
                or predecessor.revision != row.revision - 1
            ):
                raise ValidationError("Spatial asset metadata revision ancestry is inconsistent")
        try:
            payload = SpatialAssetMetadataRevisionCreate.model_validate(
                {
                    "coordinate_unit": row.coordinate_unit,
                    "meters_per_unit": row.meters_per_unit,
                    "coordinate_frame_id": row.coordinate_frame_id,
                    "transform_to_project_frame": row.transform_to_project_frame_json,
                    "calibration_evidence": row.calibration_evidence,
                    "review_state": row.review_state,
                    "reviewed_by_identity": row.reviewed_by_identity,
                    "review_note": row.review_note,
                    "created_by_identity": row.created_by_identity,
                }
            )
        except ValueError as exc:
            raise ValidationError("Stored spatial asset metadata is invalid") from exc
        content = spatial_asset_metadata_content(
            project_id=project_id,
            asset_id=asset_id,
            source_sha256=source_sha256,
            revision=row.revision,
            previous_revision_id=row.previous_revision_id,
            payload=payload,
        )
        if canonical_json_sha256(content) != row.content_sha256:
            raise ValidationError("Stored spatial asset metadata failed integrity validation")
        return SpatialAssetMetadataRevisionResponse(
            **payload.model_dump(mode="python"),
            id=row.id,
            project_id=project_id,
            spatial_source_asset_id=asset_id,
            previous_revision_id=row.previous_revision_id,
            revision=row.revision,
            source_sha256=source_sha256,
            content_sha256=row.content_sha256,
            created_at=row.created_at,
        )

    def create(
        self,
        project_id: str,
        asset_id: str,
        payload: SpatialAssetMetadataRevisionCreate,
    ) -> SpatialAssetMetadataRevisionResponse:
        source = self.sources.get(project_id, asset_id)
        self.sources.read_verified(project_id, asset_id)
        history = self.session.scalars(
            select(SpatialAssetMetadataRevision)
            .where(
                SpatialAssetMetadataRevision.project_id == project_id,
                SpatialAssetMetadataRevision.spatial_source_asset_id == asset_id,
            )
            .order_by(SpatialAssetMetadataRevision.revision, SpatialAssetMetadataRevision.id)
        ).all()
        # Validate the entire history, not just the current head. The source
        # bytes were checked above; avoid reading them again for every revision.
        for expected_revision, ancestor in enumerate(history, start=1):
            if ancestor.revision != expected_revision:
                raise ValidationError("Spatial asset metadata revision ancestry is inconsistent")
            self._validated_response(project_id, asset_id, source.sha256, ancestor)
        previous = history[-1] if history else None
        revision = 1 if previous is None else previous.revision + 1
        previous_id = None if previous is None else previous.id
        content_sha256 = canonical_json_sha256(
            spatial_asset_metadata_content(
                project_id=project_id,
                asset_id=asset_id,
                source_sha256=source.sha256,
                revision=revision,
                previous_revision_id=previous_id,
                payload=payload,
            )
        )
        row = SpatialAssetMetadataRevision(
            project_id=project_id,
            spatial_source_asset_id=asset_id,
            previous_revision_id=previous_id,
            revision=revision,
            source_sha256=source.sha256,
            coordinate_unit=payload.coordinate_unit,
            meters_per_unit=payload.meters_per_unit,
            coordinate_frame_id=payload.coordinate_frame_id,
            transform_to_project_frame_json=payload.transform_to_project_frame,
            calibration_evidence=payload.calibration_evidence,
            review_state=payload.review_state,
            reviewed_by_identity=payload.reviewed_by_identity,
            review_note=payload.review_note,
            created_by_identity=payload.created_by_identity,
            content_sha256=content_sha256,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError(
                "Spatial asset metadata revision conflicts with stored history"
            ) from exc
        self.session.refresh(row)
        return self._response(project_id, asset_id, row)

    def get(
        self,
        project_id: str,
        asset_id: str,
        revision_id: str,
    ) -> SpatialAssetMetadataRevisionResponse:
        self.sources.get(project_id, asset_id)
        row = self.session.get(SpatialAssetMetadataRevision, revision_id)
        if row is None or row.project_id != project_id or row.spatial_source_asset_id != asset_id:
            raise NotFoundError("Spatial asset metadata revision not found")
        return self._response(project_id, asset_id, row)

    def list(
        self,
        project_id: str,
        asset_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[SpatialAssetMetadataRevisionResponse]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationError("Spatial asset metadata pagination is invalid")
        self.sources.get(project_id, asset_id)
        rows = self.session.scalars(
            select(SpatialAssetMetadataRevision)
            .where(
                SpatialAssetMetadataRevision.project_id == project_id,
                SpatialAssetMetadataRevision.spatial_source_asset_id == asset_id,
            )
            .order_by(SpatialAssetMetadataRevision.revision, SpatialAssetMetadataRevision.id)
            .limit(limit)
            .offset(offset)
        )
        return [self._response(project_id, asset_id, row) for row in rows]
