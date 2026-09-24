"""Read-only GIS serialization of canonical persisted geographic observations."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from reefvision.schemas.georeferenced_observation import GeoReferencedObservation


class GeographicGISExportError(ValueError):
    """A persisted observation cannot safely be represented in the export."""


@dataclass(frozen=True)
class GeographicExportEnrichment:
    """Authoritative non-geographic metadata linked to one observation."""

    label_class_id: str | None = None
    class_name: str | None = None
    confidence: float | None = None
    confidence_status: str = "not_available"


CSV_COLUMNS = (
    "observation_id",
    "project_id",
    "video_asset_id",
    "track_id",
    "detection_id",
    "frame_index",
    "frame_time_s",
    "timestamp_utc",
    "timestamp_source",
    "longitude_deg",
    "latitude_deg",
    "crs",
    "label_class_id",
    "class_name",
    "confidence",
    "confidence_status",
    "classification_status",
    "calibration_id",
    "calibration_version",
    "calibration_checksum_sha256",
    "telemetry_source_id",
    "telemetry_source_type",
    "telemetry_sync_method",
    "telemetry_absolute_time_error_ms",
    "uncertainty_available",
    "uncertainty_method",
    "horizontal_95_m",
    "method_name",
    "method_version",
    "created_at",
    "source_observation_json",
)


def _ordered(
    observations: Sequence[GeoReferencedObservation],
) -> list[GeoReferencedObservation]:
    """Validate all locations before generating any export content."""
    ordered = sorted(
        observations,
        key=lambda item: (
            str(item.video_asset_id),
            item.frame_index,
            item.timestamp.frame_time_s,
            str(item.id),
        ),
    )

    seen: set[str] = set()

    for item in ordered:
        identifier = str(item.id)

        if identifier in seen:
            raise GeographicGISExportError("Duplicate geographic observation identifier")

        seen.add(identifier)

        location = item.location

        if location.crs != "EPSG:4326":
            raise GeographicGISExportError("Only persisted EPSG:4326 locations can be exported")

        if (
            not isfinite(location.latitude_deg)
            or not isfinite(location.longitude_deg)
            or not -90 <= location.latitude_deg <= 90
            or not -180 <= location.longitude_deg <= 180
            or not isfinite(item.timestamp.frame_time_s)
            or item.timestamp.frame_time_s < 0
        ):
            raise GeographicGISExportError(
                "Persisted observation contains invalid coordinates or time"
            )

    return ordered


def _properties(
    item: GeoReferencedObservation,
    enrichment: GeographicExportEnrichment | None = None,
) -> dict[str, object]:
    payload = item.model_dump(mode="json")

    # The canonical geographic observation has no class or confidence.
    # Do not infer either value from an ID or a neighboring observation.
    return {
        "observation_id": str(item.id),
        "project_id": str(item.project_id),
        "video_asset_id": str(item.video_asset_id),
        "track_id": str(item.track_id) if item.track_id else None,
        "detection_id": str(item.detection_id) if item.detection_id else None,
        "frame_index": item.frame_index,
        "frame_time_s": item.timestamp.frame_time_s,
        "timestamp_utc": payload["timestamp"]["utc"],
        "timestamp_source": item.timestamp.source,
        "longitude_deg": item.location.longitude_deg,
        "latitude_deg": item.location.latitude_deg,
        "crs": item.location.crs,
        "label_class_id": (enrichment.label_class_id if enrichment is not None else None),
        "class_name": (enrichment.class_name if enrichment is not None else None),
        "confidence": (enrichment.confidence if enrichment is not None else None),
        "confidence_status": (
            enrichment.confidence_status
            if enrichment is not None
            else ("untracked_observation" if item.track_id is None else "not_enriched")
        ),
        "classification_status": (
            "not_in_geographic_observation"
            if enrichment is None
            else (
                "linked_track_class"
                if enrichment.label_class_id is not None
                else (
                    "untracked_observation" if item.track_id is None else "track_class_unavailable"
                )
            )
        ),
        "calibration_id": str(item.calibration.calibration_id),
        "calibration_version": item.calibration.calibration_version,
        "calibration_checksum_sha256": item.calibration.checksum_sha256,
        "telemetry_source_id": str(item.telemetry.source_id),
        "telemetry_source_type": item.telemetry.source_type,
        "telemetry_sync_method": item.telemetry.synchronization_method,
        "telemetry_absolute_time_error_ms": (item.telemetry.absolute_time_error_ms),
        "uncertainty_available": item.uncertainty.available,
        "uncertainty_method": item.uncertainty.method,
        "horizontal_95_m": (
            item.uncertainty.horizontal_95_m if item.uncertainty.available else None
        ),
        "method_name": item.method.name,
        "method_version": item.method.version,
        "created_at": payload["created_at"],
        "source_observation": payload,
    }


def build_geojson(
    observations: Sequence[GeoReferencedObservation],
    enrichments: Mapping[str, GeographicExportEnrichment] | None = None,
) -> dict[str, object]:
    """Produce point features and chronologically ordered track LineStrings."""
    ordered = _ordered(observations)
    features: list[dict[str, object]] = []
    tracks: dict[str, list[GeoReferencedObservation]] = defaultdict(list)

    for item in ordered:
        properties = _properties(
            item,
            enrichments.get(str(item.id)) if enrichments else None,
        )

        features.append(
            {
                "type": "Feature",
                "id": str(item.id),
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        item.location.longitude_deg,
                        item.location.latitude_deg,
                    ],
                },
                "properties": {
                    **properties,
                    "feature_kind": "observation",
                },
            }
        )

        if item.track_id is not None:
            tracks[str(item.track_id)].append(item)

    for track_id, samples in sorted(tracks.items()):
        # A single point cannot form a genuine LineString.
        if len(samples) < 2:
            continue

        if (
            len({str(item.video_asset_id) for item in samples}) != 1
            or len({str(item.project_id) for item in samples}) != 1
        ):
            raise GeographicGISExportError(
                "One track contains observations from different videos or projects"
            )

        features.append(
            {
                "type": "Feature",
                "id": f"track:{track_id}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [
                            item.location.longitude_deg,
                            item.location.latitude_deg,
                        ]
                        for item in samples
                    ],
                },
                "properties": {
                    "feature_kind": "track",
                    "track_id": track_id,
                    "project_id": str(samples[0].project_id),
                    "video_asset_id": str(samples[0].video_asset_id),
                    "crs": "EPSG:4326",
                    "observation_count": len(samples),
                    "observation_ids": [str(item.id) for item in samples],
                    "frame_indices": [item.frame_index for item in samples],
                    "frame_times_s": [item.timestamp.frame_time_s for item in samples],
                    "timestamp_utc": [
                        item.timestamp.utc.isoformat() if item.timestamp.utc is not None else None
                        for item in samples
                    ],
                    "label_class_id": next(
                        (
                            enrichments[str(item.id)].label_class_id
                            for item in samples
                            if enrichments
                            and str(item.id) in enrichments
                            and enrichments[str(item.id)].label_class_id is not None
                        ),
                        None,
                    ),
                    "class_name": next(
                        (
                            enrichments[str(item.id)].class_name
                            for item in samples
                            if enrichments
                            and str(item.id) in enrichments
                            and enrichments[str(item.id)].class_name is not None
                        ),
                        None,
                    ),
                    "confidence": None,
                    "confidence_status": (
                        "per_observation_values" if enrichments else "not_enriched"
                    ),
                    "observation_confidences": [
                        (
                            enrichments[str(item.id)].confidence
                            if enrichments and str(item.id) in enrichments
                            else None
                        )
                        for item in samples
                    ],
                    "classification_status": (
                        "linked_track_class"
                        if enrichments
                        and any(
                            str(item.id) in enrichments
                            and enrichments[str(item.id)].label_class_id is not None
                            for item in samples
                        )
                        else (
                            "track_class_unavailable"
                            if enrichments
                            else "not_in_geographic_observation"
                        )
                    ),
                    "geometry_interpretation": (
                        "straight_segments_between_persisted_samples;"
                        " no intermediate coordinates inferred"
                    ),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def geojson_bytes(
    observations: Sequence[GeoReferencedObservation],
    enrichments: Mapping[str, GeographicExportEnrichment] | None = None,
) -> bytes:
    """Serialize validated GeoJSON without nonstandard NaN/Infinity tokens."""
    return (
        json.dumps(
            build_geojson(observations, enrichments),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def csv_bytes(
    observations: Sequence[GeoReferencedObservation],
    enrichments: Mapping[str, GeographicExportEnrichment] | None = None,
) -> bytes:
    """Export one observation per row with full provenance in JSON form."""
    ordered = _ordered(observations)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for item in ordered:
        properties = _properties(
            item,
            enrichments.get(str(item.id)) if enrichments else None,
        )
        original = properties.pop("source_observation")

        writer.writerow(
            {
                **properties,
                "source_observation_json": json.dumps(
                    original,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ),
            }
        )

    return output.getvalue().encode("utf-8")
