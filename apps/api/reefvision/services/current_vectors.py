"""Pair validated current components without interpolation or invented values."""

import math
from collections import defaultdict

from reefvision.domain.errors import ValidationError
from reefvision.schemas.environmental_context import (
    CurrentVector,
    CurrentVectorExclusions,
    CurrentVectorPage,
)
from reefvision.schemas.scientific_data import ScientificRecordResponse


def build_current_vectors(records: list[ScientificRecordResponse]) -> CurrentVectorPage:
    groups: dict[tuple[object, ...], dict[str, list[ScientificRecordResponse]]] = defaultdict(
        lambda: {"east": [], "north": []}
    )
    excluded = CurrentVectorExclusions()
    for record in records:
        if record.variable not in {
            "current_eastward_velocity",
            "current_northward_velocity",
        }:
            excluded.unsupported_record += 1
            continue
        if (
            record.location is None
            or record.depth_m is None
            or record.depth_reference is None
            or record.normalized_unit != "m/s"
            or record.provenance.dataset_id is None
            or record.provenance.model_version is None
        ):
            excluded.invalid_metadata_or_unit += 1
            continue
        if record.qc in {"suspect", "rejected"}:
            excluded.qc_rejected += 1
            continue
        if record.environmental_snapshot_current is False:
            excluded.superseded_snapshot += 1
            continue
        key = (
            record.location.latitude,
            record.location.longitude,
            record.observed_at,
            record.depth_m,
            record.depth_reference,
            record.source_kind,
            record.provenance.source,
            record.provenance.dataset_id,
            record.provenance.model_version,
            record.environmental_cache_key,
        )
        component = "east" if record.variable == "current_eastward_velocity" else "north"
        groups[key][component].append(record)
    vectors = []
    for components in groups.values():
        if not components["east"] or not components["north"]:
            excluded.incomplete_pair += 1
            continue
        if len(components["east"]) != 1 or len(components["north"]) != 1:
            excluded.duplicate_component += 1
            continue
        east_record, north_record = components["east"][0], components["north"][0]
        east, north = east_record.normalized_value, north_record.normalized_value
        speed = math.hypot(east, north)
        direction = None if speed == 0 else math.degrees(math.atan2(east, north)) % 360
        if (
            east_record.provenance.dataset_id is None
            or east_record.provenance.model_version is None
        ):
            raise ValidationError("Current vectors require a pinned dataset identity and version")
        assert east_record.location is not None and east_record.depth_m is not None
        vectors.append(
            CurrentVector(
                eastward_velocity_m_s=east,
                northward_velocity_m_s=north,
                speed_m_s=speed,
                direction_deg_true=direction,
                observed_at=east_record.observed_at,
                depth_m=east_record.depth_m,
                depth_reference=east_record.depth_reference or "",
                location=east_record.location,
                source_kind=east_record.source_kind,
                source=east_record.provenance.source,
                dataset_id=east_record.provenance.dataset_id,
                dataset_version=east_record.provenance.model_version,
                component_record_ids=[east_record.id, north_record.id],
            )
        )
    vectors.sort(
        key=lambda item: (
            item.observed_at,
            item.depth_m,
            item.location.latitude,
            item.location.longitude,
        )
    )
    return CurrentVectorPage(
        items=vectors,
        input_record_count=len(records),
        exclusions=excluded,
    )
