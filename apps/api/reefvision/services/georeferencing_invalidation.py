"""Lifecycle invalidation for persisted derived geographic observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from reefvision.db.models import (
    GeoReferencedObservation as GeoReferencedObservationRecord,
)
from reefvision.domain.errors import ValidationError

STALE_REASON_PROJECT_SURFACE_REFERENCE_CHANGED = "project_surface_reference_changed"
STALE_REASON_CALIBRATION_CHANGED = "georeferencing_calibration_changed"
STALE_REASON_TELEMETRY_CONFIGURATION_CHANGED = "telemetry_configuration_changed"
STALE_REASON_CONFIGURATION_HASH_MISMATCH = "configuration_hash_mismatch"


class GeoreferencingInvalidationService:
    """Mark derived coordinates stale inside the caller transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _reason(value: str) -> str:
        rendered = str(value).strip()

        if not rendered:
            raise ValidationError("Georeferencing stale reason cannot be blank")

        if len(rendered) > 100:
            raise ValidationError("Georeferencing stale reason cannot exceed 100 characters")

        return rendered

    @staticmethod
    def _configuration_hash(value: str) -> str:
        rendered = str(value).strip().lower()

        if len(rendered) != 64 or any(
            character not in "0123456789abcdef" for character in rendered
        ):
            raise ValidationError(
                "Georeferencing configuration hash must be a 64-character SHA-256 value"
            )

        return rendered

    def mark_video_stale(
        self,
        video_id: str,
        *,
        reason: str,
    ) -> int:
        stale_reason = self._reason(reason)

        result = self.session.execute(
            update(GeoReferencedObservationRecord)
            .where(
                GeoReferencedObservationRecord.video_id == str(video_id),
                GeoReferencedObservationRecord.is_stale.is_(False),
            )
            .values(
                is_stale=True,
                stale_reason=stale_reason,
                stale_at=datetime.now(UTC),
            )
        )

        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount or 0)

    def mark_project_stale(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> int:
        stale_reason = self._reason(reason)

        result = self.session.execute(
            update(GeoReferencedObservationRecord)
            .where(
                GeoReferencedObservationRecord.project_id == str(project_id),
                GeoReferencedObservationRecord.is_stale.is_(False),
            )
            .values(
                is_stale=True,
                stale_reason=stale_reason,
                stale_at=datetime.now(UTC),
            )
        )

        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount or 0)

    def mark_hash_mismatch_stale(
        self,
        video_id: str,
        *,
        current_configuration_hash: str,
    ) -> int:
        current_hash = self._configuration_hash(current_configuration_hash)

        result = self.session.execute(
            update(GeoReferencedObservationRecord)
            .where(
                GeoReferencedObservationRecord.video_id == str(video_id),
                GeoReferencedObservationRecord.is_stale.is_(False),
                or_(
                    GeoReferencedObservationRecord.configuration_hash.is_(None),
                    GeoReferencedObservationRecord.configuration_hash != current_hash,
                ),
            )
            .values(
                is_stale=True,
                stale_reason=(STALE_REASON_CONFIGURATION_HASH_MISMATCH),
                stale_at=datetime.now(UTC),
            )
        )

        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount or 0)
