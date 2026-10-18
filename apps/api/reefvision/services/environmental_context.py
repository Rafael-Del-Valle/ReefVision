"""Project environmental acquisition, bounded lookup and persistent offline reuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.environmental_context import (
    EnvironmentalImportResponse,
    EnvironmentalLookup,
    EnvironmentalLookupResponse,
    EnvironmentalMatch,
    NOAAImportRequest,
)
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
        if entry is not None and content_hash(raw) == content_hash(
            entry.payload_json["provider_response"]
        ):
            entry.fetched_at = self.now
            entry.expires_at = self.now + timedelta(days=1)
        else:
            rows = self.science.add_records(project_id, items)
            payload = {
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
            if record.location is None or record.qc in ("rejected", "suspect"):
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
            matches.append(
                EnvironmentalMatch(
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
