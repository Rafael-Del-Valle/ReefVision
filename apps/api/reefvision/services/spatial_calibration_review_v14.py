"""Append-only, source-bound spatial calibration review receipts.

Review attribution is self-declared in the current offline API; it must never
be represented as authenticated verification of scale or specimen identity.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import SpatialCalibrationReviewRecord
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_calibration_review_v14 import (
    SpatialCalibrationReviewResponse,
)
from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services.spatial_source_assets_v14 import SpatialSourceAssetService


class SpatialCalibrationReviewService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.sources = SpatialSourceAssetService(session, settings)

    def _source_digest(self, project_id: str, asset_id: str) -> str:
        source = self.sources.get(project_id, asset_id)
        self.sources.read_verified(project_id, asset_id)
        return source.sha256

    @staticmethod
    def _canonical(evidence: MeshCalibrationReviewEvidence) -> tuple[dict[str, Any], str]:
        payload = evidence.model_dump(mode="json")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return payload, sha256(encoded).hexdigest()

    def _response(
        self, project_id: str, asset_id: str, record: SpatialCalibrationReviewRecord
    ) -> SpatialCalibrationReviewResponse:
        digest = self._source_digest(project_id, asset_id)
        if (
            record.project_id != project_id
            or record.spatial_source_asset_id != asset_id
            or record.source_sha256 != digest
        ):
            raise ValidationError("Spatial review source binding is inconsistent")
        try:
            evidence = MeshCalibrationReviewEvidence.model_validate(record.evidence_json)
        except PydanticValidationError as exc:
            raise ValidationError("Stored spatial review evidence is invalid") from exc
        _, evidence_digest = self._canonical(evidence)
        if (
            evidence_digest != record.evidence_sha256
            or evidence.reviewed_spatial_source_asset_id != asset_id
            or evidence.reviewed_source_payload_sha256 != digest
        ):
            raise ValidationError("Stored spatial review evidence failed integrity validation")
        return SpatialCalibrationReviewResponse(
            id=record.id,
            project_id=project_id,
            spatial_source_asset_id=asset_id,
            source_sha256=digest,
            evidence_sha256=evidence_digest,
            evidence=evidence,
            created_at=record.created_at,
        )

    def create(
        self, project_id: str, asset_id: str, evidence: MeshCalibrationReviewEvidence
    ) -> SpatialCalibrationReviewResponse:
        digest = self._source_digest(project_id, asset_id)
        if evidence.reviewed_spatial_source_asset_id != asset_id:
            raise ValidationError("Persisted review must bind the project-owned spatial asset ID")
        if evidence.reviewed_source_payload_sha256 != digest:
            raise ValidationError("Persisted review must bind the verified original SHA-256")
        payload, evidence_digest = self._canonical(evidence)
        condition = (
            SpatialCalibrationReviewRecord.project_id == project_id,
            SpatialCalibrationReviewRecord.spatial_source_asset_id == asset_id,
            SpatialCalibrationReviewRecord.evidence_sha256 == evidence_digest,
        )
        existing = self.session.scalar(select(SpatialCalibrationReviewRecord).where(*condition))
        if existing is not None:
            return self._response(project_id, asset_id, existing)
        record = SpatialCalibrationReviewRecord(
            project_id=project_id,
            spatial_source_asset_id=asset_id,
            source_sha256=digest,
            evidence_sha256=evidence_digest,
            evidence_json=payload,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            # A concurrent identical submission can win the unique constraint.
            self.session.rollback()
            existing = self.session.scalar(select(SpatialCalibrationReviewRecord).where(*condition))
            if existing is None:
                raise
            return self._response(project_id, asset_id, existing)
        self.session.refresh(record)
        return self._response(project_id, asset_id, record)

    def get(
        self, project_id: str, asset_id: str, review_id: str
    ) -> SpatialCalibrationReviewResponse:
        self.sources.get(project_id, asset_id)
        record = self.session.get(SpatialCalibrationReviewRecord, review_id)
        if (
            record is None
            or record.project_id != project_id
            or record.spatial_source_asset_id != asset_id
        ):
            raise NotFoundError("Spatial calibration review not found for project asset")
        return self._response(project_id, asset_id, record)

    def list(
        self,
        project_id: str,
        asset_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        after_review_id: str | None = None,
    ) -> list[SpatialCalibrationReviewResponse]:
        self.sources.get(project_id, asset_id)
        query = select(SpatialCalibrationReviewRecord).where(
            SpatialCalibrationReviewRecord.project_id == project_id,
            SpatialCalibrationReviewRecord.spatial_source_asset_id == asset_id,
        )
        if after_review_id is not None:
            if offset:
                raise ValidationError("Cursor pagination cannot be combined with offset")
            anchor = self.session.get(SpatialCalibrationReviewRecord, after_review_id)
            if (
                anchor is None
                or anchor.project_id != project_id
                or anchor.spatial_source_asset_id != asset_id
            ):
                raise NotFoundError("Spatial calibration review cursor not found for project asset")
            # Never trust an altered receipt as a reproducibility cursor.
            self._response(project_id, asset_id, anchor)
            query = query.where(
                or_(
                    SpatialCalibrationReviewRecord.created_at > anchor.created_at,
                    and_(
                        SpatialCalibrationReviewRecord.created_at == anchor.created_at,
                        SpatialCalibrationReviewRecord.id > anchor.id,
                    ),
                )
            )
        records = self.session.scalars(
            query.order_by(SpatialCalibrationReviewRecord.created_at, SpatialCalibrationReviewRecord.id)
            .limit(limit)
            .offset(offset)
        )
        return [self._response(project_id, asset_id, record) for record in records]
