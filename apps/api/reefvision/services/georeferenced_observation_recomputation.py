"""Atomic recomputation of stale persisted geographic observations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    GeoReferencedObservation as GeoReferencedObservationRecord,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.georeferenced_observation import (
    BoundingBoxPixels,
)
from reefvision.schemas.georeferenced_observation_api import (
    GeoReferencedObservationRecomputeReplacement,
    GeoReferencedObservationRecomputeResponse,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)
from reefvision.services.georeferencing_invalidation import (
    GeoreferencingInvalidationService,
)
from reefvision.services.video_georeferencing import (
    VideoGeoreferencingService,
)


class GeoreferencedObservationRecomputationService:
    """Replace stale derived records under one database transaction."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
    ) -> None:
        self.session = session
        self.persistence = GeoReferencedObservationService(session)
        self.georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )
        self.invalidation = GeoreferencingInvalidationService(session)

    @staticmethod
    def _representative_pixel(
        record: GeoReferencedObservationRecord,
    ) -> tuple[float, float] | None:
        method = getattr(
            record,
            "representative_pixel_method",
            None,
        )

        if method == "bbox_center":
            # Reapply the current versioned bbox-center policy.
            return None

        if method == "explicit":
            return (
                float(record.representative_pixel_x),
                float(record.representative_pixel_y),
            )

        raise ValidationError("Stored representative-pixel method cannot be recomputed")

    @staticmethod
    def _bbox(
        record: GeoReferencedObservationRecord,
    ) -> BoundingBoxPixels:
        return BoundingBoxPixels(
            x_min=float(record.bbox_x_min),
            y_min=float(record.bbox_y_min),
            x_max=float(record.bbox_x_max),
            y_max=float(record.bbox_y_max),
        )

    def recompute_video(
        self,
        video_id: str,
    ) -> GeoReferencedObservationRecomputeResponse:
        """Atomically replace stale/hash-mismatched observations."""
        initial_records = self.persistence.list_for_video(video_id)

        # A video with no derived observations is a valid no-op and
        # should not require calibration/telemetry merely to say so.
        if not initial_records:
            return GeoReferencedObservationRecomputeResponse(
                video_id=video_id,
                configuration_hash=None,
                invalidated_count=0,
                stale_count=0,
                recomputed_count=0,
                unchanged_count=0,
                replacements=[],
            )

        try:
            current_hash = self.georeferencing.configuration_hash(video_id)

            invalidated_count = self.invalidation.mark_hash_mismatch_stale(
                video_id,
                current_configuration_hash=current_hash,
            )

            # Re-read after the UPDATE so the selected lifecycle state
            # is authoritative for this transaction.
            records = self.persistence.list_for_video(video_id)

            stale_records = [record for record in records if record.is_stale]

            unchanged_count = len(records) - len(stale_records)

            replacements: list[GeoReferencedObservationRecomputeReplacement] = []

            # Stage every replacement first. Nothing old is deleted
            # until every projection/persistence operation succeeds.
            for record in stale_records:
                observation = self.georeferencing.georeference_detection(
                    video_id,
                    frame_index=record.frame_index,
                    bbox=self._bbox(record),
                    representative_pixel=(self._representative_pixel(record)),
                    detection_id=record.detection_id,
                    track_id=record.track_id,
                )

                replacement = self.persistence.persist(
                    observation,
                    configuration_hash=current_hash,
                )

                replacements.append(
                    GeoReferencedObservationRecomputeReplacement(
                        old_observation_id=record.id,
                        new_observation_id=replacement.id,
                        frame_index=record.frame_index,
                        track_id=record.track_id,
                    )
                )

            # Persisted geographic observations are immutable derived
            # results. Successful recomputation supersedes old rows
            # with newly identified scientific derivations.
            for record in stale_records:
                self.session.delete(record)

            self.session.commit()

            return GeoReferencedObservationRecomputeResponse(
                video_id=video_id,
                configuration_hash=current_hash,
                invalidated_count=invalidated_count,
                stale_count=len(stale_records),
                recomputed_count=len(replacements),
                unchanged_count=unchanged_count,
                replacements=replacements,
            )

        except Exception:
            self.session.rollback()
            raise
