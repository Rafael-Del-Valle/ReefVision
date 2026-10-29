"""Project environmental acquisition, bounded lookup and persistent offline reuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.scientific_units import UNITS, normalize_quantity
from reefvision.schemas.environmental_context import (
    ENVIRONMENTAL_VARIABLES,
    EnvironmentalDatasetPage,
    EnvironmentalDatasetSummary,
    EnvironmentalImportResponse,
    EnvironmentalLookup,
    EnvironmentalLookupResponse,
    EnvironmentalMatch,
    EnvironmentalSubjectContext,
    EnvironmentalSubjectLookup,
    EnvironmentalThresholdRequest,
    EnvironmentalThresholdResponse,
    NOAAImportRequest,
)
from reefvision.schemas.scientific_data import ScientificRecordCreate
from reefvision.services.geographic_movement_analytics import geographic_distance_m
from reefvision.services.noaa_environment import fetch_noaa, noaa_request_url, parse_noaa
from reefvision.services.scientific_data import ScientificDataService, content_hash


def _utc(value: datetime) -> datetime:
    # SQLite returns timezone-naive datetimes; these columns are always written in UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EnvironmentalContextService:
    def __init__(
        self, session: Session, *, http: httpx.Client | None = None, now: datetime | None = None
    ) -> None:
        self.session = session
        self.http = http
        self.now = _utc(now or datetime.now(UTC))
        self.science = ScientificDataService(session)

    def _cache_response(
        self, entry: EnvironmentalCacheEntry, status: str
    ) -> EnvironmentalImportResponse:
        if content_hash(entry.payload_json) != entry.content_sha256:
            raise ConflictError(
                "Environmental cache checksum mismatch; cached values cannot be trusted"
            )
        items = []
        for record_id in entry.payload_json["record_ids"]:
            row = self.session.get(ScientificRecord, record_id)
            if row is None or row.project_id != entry.project_id:
                raise ConflictError(
                    "Environmental cache refers to missing or foreign scientific records"
                )
            items.append(self.science.response(row))
        return EnvironmentalImportResponse(
            items=items,
            cache_status=status,
            fetched_at=_utc(entry.fetched_at),
            expires_at=_utc(entry.expires_at),
            source_url=entry.source_url,
            skipped_missing=entry.payload_json["skipped_missing"],
        )

    def import_noaa(
        self, project_id: str, request: NOAAImportRequest
    ) -> EnvironmentalImportResponse:
        self.science.require_project(project_id)
        source_url = noaa_request_url(request)
        key = content_hash(
            {"source_url": source_url, "subject": request.subject.model_dump(mode="json")}
        )
        query = select(EnvironmentalCacheEntry).where(
            EnvironmentalCacheEntry.project_id == project_id,
            EnvironmentalCacheEntry.cache_key == key,
        )
        entry = self.session.scalar(query)
        if entry is not None:
            self._cache_response(entry, "integrity_check")
            if request.offline or self.now < _utc(entry.expires_at):
                status = "fresh" if self.now < _utc(entry.expires_at) else "stale_offline"
                return self._cache_response(entry, status)
        elif request.offline:
            raise NotFoundError(
                "No cached NOAA dataset matches this project, station, day and subject"
            )
        if self.http is None:
            with httpx.Client() as http:
                raw = fetch_noaa(http, source_url)
        else:
            raw = fetch_noaa(self.http, source_url)
        items, missing = parse_noaa(raw, request, self.now, source_url)
        return self.store_dataset(
            project_id,
            identity={"source_url": source_url, "subject": request.subject.model_dump(mode="json")},
            source_url=source_url,
            raw=raw,
            items=items,
            missing=missing,
            entry=entry,
        )

    def store_dataset(
        self,
        project_id: str,
        *,
        identity: dict[str, Any],
        source_url: str,
        raw: dict[str, Any],
        items: list[ScientificRecordCreate],
        missing: int,
        entry: EnvironmentalCacheEntry | None,
    ) -> EnvironmentalImportResponse:
        key = content_hash(identity)
        query = select(EnvironmentalCacheEntry).where(
            EnvironmentalCacheEntry.project_id == project_id,
            EnvironmentalCacheEntry.cache_key == key,
        )
        if entry is not None and content_hash(raw) == content_hash(
            entry.payload_json["provider_response"]
        ):
            entry.fetched_at = self.now
            entry.expires_at = self.now + timedelta(days=1)
        else:
            rows = self.science.add_records(project_id, items, environmental_cache_key=key)
            payload = {
                "cache_identity": identity,
                "provider_response": raw,
                "record_ids": [row.id for row in rows],
                "skipped_missing": missing,
            }
            if entry is None:
                entry = EnvironmentalCacheEntry(
                    project_id=project_id, cache_key=key, source_url=source_url
                )
                self.session.add(entry)
            entry.payload_json = payload
            entry.content_sha256 = content_hash(payload)
            entry.fetched_at = self.now
            entry.expires_at = self.now + timedelta(days=1)
        try:
            self.session.commit()
        except IntegrityError:
            # Another request may have populated this exact cache while NOAA was responding.
            self.session.rollback()
            winner = self.session.scalar(query)
            if winner is None:
                raise ConflictError(
                    "Environmental dataset changed concurrently; retry the import"
                ) from None
            return self._cache_response(
                winner, "fresh" if self.now < _utc(winner.expires_at) else "stale_offline"
            )
        return self._cache_response(entry, "downloaded")

    def lookup(self, project_id: str, request: EnvironmentalLookup) -> EnvironmentalLookupResponse:
        self.science.require_project(project_id)
        window = timedelta(seconds=request.max_time_delta_s)
        rows = self.session.scalars(
            select(ScientificRecord)
            .where(
                ScientificRecord.project_id == project_id,
                ScientificRecord.variable == request.variable,
                ScientificRecord.source_kind.in_(request.source_kinds),
                ScientificRecord.observed_at >= request.observed_at - window,
                ScientificRecord.observed_at <= request.observed_at + window,
            )
            .limit(10001)
        ).all()
        if len(rows) > 10000:
            raise ValidationError("Too many environmental candidates; narrow the time interval")
        matches = []
        for row in rows:
            record = self.science.response(row)
            if (
                record.location is None
                or record.qc in ("rejected", "suspect")
                or record.calibration_current is False
                or record.environmental_snapshot_current is False
            ):
                continue
            distance = geographic_distance_m(
                request.location.latitude,
                request.location.longitude,
                record.location.latitude,
                record.location.longitude,
            )
            if distance > request.max_distance_m:
                continue
            depth_delta = None
            if request.depth_m is not None:
                if record.depth_m is None or record.depth_reference != request.depth_reference:
                    continue
                depth_delta = record.depth_m - request.depth_m
                if abs(depth_delta) > request.max_depth_delta_m:
                    continue
            cache = (
                self.session.scalar(
                    select(EnvironmentalCacheEntry).where(
                        EnvironmentalCacheEntry.project_id == project_id,
                        EnvironmentalCacheEntry.cache_key == record.environmental_cache_key,
                    )
                )
                if record.environmental_cache_key
                else None
            )
            matches.append(
                EnvironmentalMatch(
                    cache_fetched_at=_utc(cache.fetched_at) if cache else None,
                    cache_expires_at=_utc(cache.expires_at) if cache else None,
                    cache_age_s=max(0, (self.now - _utc(cache.fetched_at)).total_seconds())
                    if cache
                    else None,
                    record=record,
                    distance_m=distance,
                    time_delta_s=(record.observed_at - request.observed_at).total_seconds(),
                    depth_delta_m=depth_delta,
                )
            )
        matches.sort(
            key=lambda item: (abs(item.time_delta_s), item.distance_m, str(item.record.id))
        )
        return EnvironmentalLookupResponse(matches=matches)

    def threshold_samples(
        self, project_id: str, request: EnvironmentalThresholdRequest
    ) -> EnvironmentalThresholdResponse:
        """Return qualifying samples, not inferred temporal events or event durations."""
        try:
            threshold, unit = normalize_quantity(
                request.threshold_value, request.threshold_unit
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        expected_dimensions = {
            "water_temperature": "temperature",
            "water_potential_temperature": "temperature",
            "practical_salinity": "practical_salinity",
            "current_eastward_velocity": "speed",
            "current_northward_velocity": "speed",
            "current_speed": "speed",
        }
        expected = expected_dimensions.get(request.variable)
        if expected is not None and UNITS[request.threshold_unit][0] != expected:
            raise ValidationError("Threshold unit must match the environmental variable")
        lookup = EnvironmentalLookup.model_validate(
            request.model_dump(exclude={"threshold_value", "threshold_unit", "direction"})
        )
        candidates = self.lookup(project_id, lookup).matches
        if any(match.record.normalized_unit != unit for match in candidates):
            raise ValidationError("Threshold unit must match the normalized observation unit")
        matches = [
            match
            for match in candidates
            if (
                match.record.normalized_value > threshold
                if request.direction == "above"
                else match.record.normalized_value < threshold
            )
        ]
        matches.sort(key=lambda item: (item.record.observed_at, str(item.record.id)))
        return EnvironmentalThresholdResponse(
            matches=matches,
            normalized_threshold=threshold,
            normalized_unit=unit,
            direction=request.direction,
        )

    def subject_context(
        self, project_id: str, request: EnvironmentalSubjectLookup
    ) -> EnvironmentalSubjectContext:
        self.science.require_project(project_id)
        self.science.validate_subject(project_id, request.subject)
        subject = request.subject.model_dump(mode="json")
        rows = self.session.scalars(
            select(ScientificRecord)
            .where(
                ScientificRecord.project_id == project_id,
                ScientificRecord.variable == "geographic_position",
                ScientificRecord.image_id == subject["image_id"],
                ScientificRecord.video_id == subject["video_id"],
                ScientificRecord.track_id == subject["track_id"],
                ScientificRecord.model_run_id == subject["model_run_id"],
                # Match the complete scientific subject *before* the bounded query.
                # Otherwise positions from other video frames or image objects
                # can exhaust the 1,000-row cap and hide the requested evidence.
                ScientificRecord.payload_json["subject"]["frame_index"].as_integer()
                == subject["frame_index"],
                ScientificRecord.payload_json["subject"]["annotation_id"].as_string()
                == subject["annotation_id"],
                ScientificRecord.payload_json["subject"]["mask_id"].as_string()
                == subject["mask_id"],
                ScientificRecord.payload_json["subject"]["prediction_id"].as_string()
                == subject["prediction_id"],
            )
            .order_by(ScientificRecord.created_at, ScientificRecord.id)
            .limit(1001)
        ).all()
        if len(rows) > 1000:
            raise ValidationError("Too many subject positions; use a narrower subject")
        positions = []
        for row in rows:
            record = self.science.response(row)
            if (
                record.subject == request.subject
                and record.location is not None
                and record.qc not in ("rejected", "suspect")
                and record.calibration_current is not False
                and record.environmental_snapshot_current is not False
            ):
                positions.append(record)
        result = EnvironmentalSubjectContext(
            status="unavailable", subject=request.subject, positions=positions
        )
        if request.position_record_id is not None:
            chosen = next(
                (item for item in positions if item.id == request.position_record_id), None
            )
            if chosen is None:
                raise ValidationError("Position record must match this exact subject and pass QC")
        elif len(positions) > 1:
            result.status = "ambiguous"
            result.reason = (
                "Multiple position/time references exist. Select the intended scientific record."
            )
            return result
        elif not positions:
            result.reason = (
                "No valid subject position and UTC timestamp. "
                "Station locations and video-relative times cannot establish "
                "organism location/time."
            )
            return result
        else:
            chosen = positions[0]
        result.position = chosen
        assert chosen.location is not None
        for variable in ENVIRONMENTAL_VARIABLES:
            result.matches[variable] = self.lookup(
                project_id,
                EnvironmentalLookup(
                    variable=variable,
                    location=chosen.location,
                    observed_at=chosen.observed_at,
                    depth_m=chosen.depth_m,
                    depth_reference=chosen.depth_reference,
                    max_distance_m=request.max_distance_m,
                    max_time_delta_s=request.max_time_delta_s,
                    max_depth_delta_m=request.max_depth_delta_m,
                ),
            ).matches
        if any(result.matches.values()):
            result.status = "available"
        else:
            result.reason = (
                "No defensible environmental observations within the selected "
                "space, time and depth bounds."
            )
        return result

    def datasets(
        self, project_id: str, limit: int = 100, offset: int = 0
    ) -> EnvironmentalDatasetPage:
        self.science.require_project(project_id)
        query = select(EnvironmentalCacheEntry).where(
            EnvironmentalCacheEntry.project_id == project_id
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(EnvironmentalCacheEntry.fetched_at.desc(), EnvironmentalCacheEntry.id)
            .limit(limit)
            .offset(offset)
        )
        items = []
        for entry in rows:
            if content_hash(entry.payload_json) != entry.content_sha256:
                raise ConflictError("Environmental cache checksum mismatch")
            identity = entry.payload_json.get("cache_identity", {})
            items.append(
                EnvironmentalDatasetSummary(
                    cache_key=entry.cache_key,
                    provider=identity.get("provider", "noaa_co_ops"),
                    source_url=entry.source_url,
                    record_count=len(entry.payload_json["record_ids"]),
                    fetched_at=_utc(entry.fetched_at),
                    expires_at=_utc(entry.expires_at),
                )
            )
        return EnvironmentalDatasetPage(items=items, total=total)

    def cached_dataset(self, project_id: str, cache_key: str) -> EnvironmentalImportResponse:
        self.science.require_project(project_id)
        entry = self.session.scalar(
            select(EnvironmentalCacheEntry).where(
                EnvironmentalCacheEntry.project_id == project_id,
                EnvironmentalCacheEntry.cache_key == cache_key,
            )
        )
        if entry is None:
            raise NotFoundError("No matching cached dataset in this project")
        return self._cache_response(
            entry, "fresh" if self.now < _utc(entry.expires_at) else "stale_offline"
        )
