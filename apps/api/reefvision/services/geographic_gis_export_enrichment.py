"""Authoritative track metadata enrichment for GIS exports."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite

from sqlalchemy.orm import Session

from reefvision.db.models import LabelClass, VideoTrack
from reefvision.schemas.georeferenced_observation import GeoReferencedObservation
from reefvision.services.geographic_gis_export import (
    GeographicExportEnrichment,
)


def _frame_confidence(
    track: VideoTrack,
    frame_index: int,
) -> tuple[float | None, str]:
    matches = [
        item
        for item in (track.keyframes_json or [])
        if isinstance(item, dict) and item.get("frame") == frame_index
    ]

    if not matches:
        return None, "not_persisted_for_frame"

    if len(matches) != 1:
        return None, "ambiguous_duplicate_keyframe"

    value = matches[0].get("confidence")

    if value is None:
        return None, "exact_keyframe_without_confidence"

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "invalid_persisted_confidence"

    numeric = float(value)

    if not isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        return None, "invalid_persisted_confidence"

    return numeric, "exact_keyframe"


def build_geographic_export_enrichments(
    session: Session,
    observations: Sequence[GeoReferencedObservation],
) -> dict[str, GeographicExportEnrichment]:
    """Link only authoritative persisted track/class/keyframe metadata."""
    tracks: dict[str, VideoTrack | None] = {}
    classes: dict[str, LabelClass | None] = {}

    result: dict[str, GeographicExportEnrichment] = {}

    for observation in observations:
        observation_id = str(observation.id)

        if observation.track_id is None:
            result[observation_id] = GeographicExportEnrichment(
                confidence_status="untracked_observation",
            )
            continue

        track_id = str(observation.track_id)

        if track_id not in tracks:
            tracks[track_id] = session.get(VideoTrack, track_id)

        track = tracks[track_id]

        if track is None:
            result[observation_id] = GeographicExportEnrichment(
                confidence_status="track_not_found",
            )
            continue

        label_class_id = str(track.label_class_id)

        if label_class_id not in classes:
            classes[label_class_id] = session.get(
                LabelClass,
                label_class_id,
            )

        label_class = classes[label_class_id]

        confidence, confidence_status = _frame_confidence(
            track,
            observation.frame_index,
        )

        result[observation_id] = GeographicExportEnrichment(
            label_class_id=label_class_id,
            class_name=(str(label_class.name) if label_class is not None else None),
            confidence=confidence,
            confidence_status=confidence_status,
        )

    return result
