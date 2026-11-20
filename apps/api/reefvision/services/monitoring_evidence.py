"""Build replayable monitoring results from scoped canonical observations."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil, fsum, isfinite
from typing import Literal
from uuid import UUID

from pydantic import ValidationError as InvalidSource
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_event_summary import EventSessionSummary, EventSummaryRead
from reefvision.schemas.monitoring import (
    BiologicalMonitoringRuleRead,
    EnvironmentalMonitoringRuleRead,
    LevelLimits,
    MonitoringAssessmentResult,
    MonitoringBiologicalSession,
    MonitoringEffort,
    MonitoringExclusion,
    MonitoringFinding,
    MonitoringRuleRead,
    MonitoringSourceReference,
    MonitoringWindow,
)
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.ecology_event_summary import EcologyEventSummaryService
from reefvision.services.scientific_data import ScientificDataService
from reefvision.storage.datasets import canonical_json_sha256

_MAX_OBSERVATIONS = 10_000


def monitoring_utc(value: datetime) -> datetime:
    """SQLite removes the UTC offset from timezone-aware stored columns."""
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def sort_monitoring_evidence(
    sources: list[MonitoringSourceReference],
    exclusions: list[MonitoringExclusion],
    sessions: list[MonitoringBiologicalSession],
) -> None:
    """Give equivalent locally rebound evidence a deterministic order."""
    undated = datetime.min.replace(tzinfo=UTC)
    sources.sort(key=lambda item: (item.observed_at or undated, str(item.id)))
    exclusions.sort(
        key=lambda item: (
            item.observed_at or undated,
            str(item.source_id or ""),
            item.session_id or "",
            item.reason,
        )
    )
    sessions.sort(key=lambda item: (item.observed_at, str(item.summary_id), item.link_revision_id))


def monitoring_evidence_checksum(
    rule_sha256: str,
    window: MonitoringWindow,
    sources: list[MonitoringSourceReference],
    exclusions: list[MonitoringExclusion],
    sessions: list[MonitoringBiologicalSession],
) -> str:
    return canonical_json_sha256(
        {
            "rule_sha256": rule_sha256,
            "window": window.model_dump(mode="json", include={"window_start", "window_end"}),
            "sources": [row.model_dump(mode="json") for row in sources],
            "exclusions": [row.model_dump(mode="json") for row in exclusions],
            "biological_sessions": [row.model_dump(mode="json") for row in sessions],
        }
    )


def biological_session_evidence(
    summary_id: UUID, item: EventSessionSummary, source_id_map: Mapping[str, str]
) -> MonitoringBiologicalSession:
    assert item.observed_at is not None
    return MonitoringBiologicalSession(
        summary_id=summary_id,
        link_revision_id=source_id_map.get(item.link_revision_id, item.link_revision_id),
        link_source_sha256=item.link_source_sha256,
        organism_key=item.organism_key,
        unit_type=item.unit_type,
        unit_id=item.unit_id,
        video_id=source_id_map.get(item.video_id, item.video_id),
        video_sha256=item.video_sha256,
        measurement_sha256=item.measurement_sha256,
        event_revision_digest=item.event_revision_digest,
        event_ids=[source_id_map.get(event.id, event.id) for event in item.events],
        observed_at=item.observed_at,
        frame_start=item.frame_start,
        frame_end=item.frame_end,
        valid_duration_s=item.valid_duration_s,
        confirmed_event_count=item.confirmed_complete_count,
        unreviewed_count=item.unreviewed_count,
        partial_count=item.partial_count,
        excluded_confirmed_count=item.excluded_confirmed_count,
    )


@dataclass
class MonitoringEvidence:
    method: str
    estimate: float | None = None
    effort: MonitoringEffort = field(default_factory=MonitoringEffort)
    source_refs: list[MonitoringSourceReference] = field(default_factory=list)
    exclusions: list[MonitoringExclusion] = field(default_factory=list)
    findings: list[MonitoringFinding] = field(default_factory=list)
    sessions: list[MonitoringBiologicalSession] = field(default_factory=list)

    def exclude(
        self,
        reason: str,
        *,
        kind: Literal["scientific_record", "reviewed_event_summary", "assessment"],
        source: UUID | None = None,
        at: datetime | None = None,
        session_id: str | None = None,
    ) -> None:
        self.exclusions.append(
            MonitoringExclusion(
                kind=kind, source_id=source, observed_at=at, session_id=session_id, reason=reason
            )
        )

    def result(
        self, rule: MonitoringRuleRead, window: MonitoringWindow
    ) -> MonitoringAssessmentResult:
        sort_monitoring_evidence(self.source_refs, self.exclusions, self.sessions)
        evidence_sha256 = monitoring_evidence_checksum(
            rule.rule_sha256, window, self.source_refs, self.exclusions, self.sessions
        )
        return MonitoringAssessmentResult(
            project_id=rule.project_id,
            rule_id=rule.id,
            rule_sha256=rule.rule_sha256,
            window_start=window.window_start,
            window_end=window.window_end,
            evidence_sha256=evidence_sha256,
            kind=rule.kind,
            protocol=rule.protocol,
            metric=rule.metric,
            unit=rule.unit,
            estimate=self.estimate,
            effort=self.effort,
            source_refs=self.source_refs,
            exclusions=self.exclusions,
            findings=self.findings,
            biological_sessions=self.sessions,
            method=self.method,
        )


def _levels(
    value: float,
    limits: LevelLimits,
    *,
    key: str,
    unit: str,
    source_ids: list[UUID],
    at: datetime | None = None,
) -> list[MonitoringFinding]:
    if limits.lower_limit is not None and value < limits.lower_limit:
        kind, threshold = "lower_limit", limits.lower_limit
        detail = "Value below the declared lower limit"
    elif limits.upper_limit is not None and value > limits.upper_limit:
        kind, threshold = "upper_limit", limits.upper_limit
        detail = "Value above the declared upper limit"
    else:
        return []
    return [
        MonitoringFinding(
            kind=kind,
            finding_key=f"{kind}/{key}",
            detail=detail,
            source_ids=source_ids,
            observed_at=at,
            value=value,
            threshold=threshold,
            unit=unit,
        )
    ]


def _record_reference(item: ScientificRecordResponse) -> MonitoringSourceReference:
    return MonitoringSourceReference(
        kind="scientific_record",
        id=item.id,
        sha256=item.content_sha256,
        observed_at=item.observed_at,
        acquired_at=item.provenance.acquired_at,
        source=item.provenance.source,
        original_value=item.value,
        original_unit=item.unit,
        normalized_value=item.normalized_value,
        normalized_unit=item.normalized_unit,
        qc=item.qc,
    )


def _drop_findings(
    start: datetime, cadence: int, observed_slots: list[int], expected: int
) -> list[MonitoringFinding]:
    missing: list[MonitoringFinding] = []
    previous = -1
    for slot in [*observed_slots, expected]:
        count = slot - previous - 1
        if count > 0:
            first_missing = previous + 1
            missing.append(
                MonitoringFinding(
                    kind="drop",
                    finding_key=f"drop/{first_missing}/{count}",
                    detail=f"No matching source observation in {count} expected time slots",
                    observed_at=start + timedelta(seconds=cadence * first_missing),
                    missing_slots=count,
                )
            )
        previous = slot
    return missing


def _source_slots(
    session: Session,
    rule: EnvironmentalMonitoringRuleRead,
    window: MonitoringWindow,
    evidence: MonitoringEvidence,
) -> dict[int, list[ScientificRecordResponse]]:
    params = rule.parameters
    rows = list(
        session.scalars(
            select(ScientificRecord)
            .where(
                ScientificRecord.project_id == str(rule.project_id),
                ScientificRecord.variable == rule.metric,
                ScientificRecord.source_kind == params.source_kind,
                ScientificRecord.observed_at >= window.window_start,
                ScientificRecord.observed_at < window.window_end,
            )
            .order_by(ScientificRecord.observed_at, ScientificRecord.id)
            .limit(_MAX_OBSERVATIONS + 1)
        )
    )
    if len(rows) > _MAX_OBSERVATIONS:
        raise ValidationError("Choose a shorter window for this monitoring record series")

    reader = ScientificDataService(session)
    slots: dict[int, list[ScientificRecordResponse]] = defaultdict(list)
    for row in rows:
        observed_at = monitoring_utc(row.observed_at)
        identifier = UUID(row.id)
        try:
            record = reader.response(row)
            if (
                record.variable != row.variable
                or record.source_kind != row.source_kind
                or record.observed_at != observed_at
                or record.calibration_current is False
                or record.environmental_snapshot_current is False
            ):
                raise ValueError("Scientific record source no longer matches its evidence")
        except (ConflictError, InvalidSource, ValidationError, ValueError):
            evidence.exclude(
                "source_integrity", kind="scientific_record", source=identifier, at=observed_at
            )
            continue
        if params.source is not None and record.provenance.source != params.source:
            continue

        evidence.source_refs.append(_record_reference(record))
        protocol = record.provenance.source_metadata.get("protocol")
        reason = None
        if not isinstance(protocol, str) or not protocol.strip():
            reason = "missing_protocol"
        elif protocol != rule.protocol:
            reason = "incompatible_protocol"
        elif record.normalized_unit != rule.unit:
            reason = "incompatible_unit"
        if reason:
            evidence.exclude(reason, kind="scientific_record", source=identifier, at=observed_at)
            continue
        elapsed = observed_at - window.window_start
        slot = elapsed // timedelta(seconds=params.cadence_seconds)
        slots[slot].append(record)
    return slots


def _accepted_slots(
    slots: dict[int, list[ScientificRecordResponse]],
    evidence: MonitoringEvidence,
) -> list[tuple[int, ScientificRecordResponse]]:
    result: list[tuple[int, ScientificRecordResponse]] = []
    mixed = len({row.provenance.source for items in slots.values() for row in items}) > 1
    for slot, records in sorted(slots.items()):
        for record in records:
            reason = None
            if record.qc != "accepted":
                reason = f"qc_{record.qc}"
            elif mixed:
                reason = "multiple_sources_select_one"
            elif len(records) != 1:
                reason = "duplicate_slot"
            elif record.provenance.acquired_at < record.observed_at:
                reason = "acquisition_clock_precedes_observation"
            if reason:
                evidence.exclude(
                    reason, kind="scientific_record", source=record.id, at=record.observed_at
                )
            else:
                result.append((slot, record))
    return result


def _environmental(
    session: Session, rule: EnvironmentalMonitoringRuleRead, window: MonitoringWindow
) -> MonitoringEvidence:
    params = rule.parameters
    evidence = MonitoringEvidence("qc_accepted_single_source_cadence_slots_v1")
    slots = _source_slots(session, rule, window, evidence)
    expected = ceil(
        (window.window_end - window.window_start).total_seconds() / params.cadence_seconds
    )
    evidence.findings.extend(
        _drop_findings(window.window_start, params.cadence_seconds, sorted(slots), expected)
    )
    accepted = _accepted_slots(slots, evidence)
    evidence.effort = MonitoringEffort(
        expected_slots=expected,
        observed_slots=len(slots),
        accepted_observations=len(accepted),
        coverage_fraction=len(slots) / expected,
        accepted_fraction=len(accepted) / expected,
    )
    if accepted:
        evidence.estimate = fsum(record.normalized_value / len(accepted) for _, record in accepted)
    previous: tuple[int, ScientificRecordResponse] | None = None
    for slot, record in accepted:
        evidence.findings.extend(
            _levels(
                record.normalized_value,
                params,
                key=str(record.id),
                unit=rule.unit,
                source_ids=[record.id],
                at=record.observed_at,
            )
        )
        delay = (record.provenance.acquired_at - record.observed_at).total_seconds()
        if params.max_delay_seconds is not None and delay > params.max_delay_seconds:
            evidence.findings.append(
                MonitoringFinding(
                    kind="delay",
                    finding_key=f"delay/{record.id}",
                    detail="Acquisition arrived after the declared delay limit",
                    observed_at=record.observed_at,
                    source_ids=[record.id],
                    value=delay,
                    threshold=params.max_delay_seconds,
                    unit="s",
                )
            )
        if previous is not None and previous[0] + 1 == slot and params.max_drift is not None:
            difference = abs(record.normalized_value - previous[1].normalized_value)
            if not isfinite(difference):
                raise ValidationError("Observation change exceeds the finite numeric range")
            if difference > params.max_drift:
                evidence.findings.append(
                    MonitoringFinding(
                        kind="drift",
                        finding_key=f"drift/{previous[1].id}/{record.id}",
                        detail="Change between adjacent accepted values exceeds the drift limit",
                        observed_at=record.observed_at,
                        source_ids=[previous[1].id, record.id],
                        value=difference,
                        threshold=params.max_drift,
                        unit=rule.unit,
                    )
                )
        previous = (slot, record)
    return evidence


def _summary_candidates(
    session: Session,
    rule: BiologicalMonitoringRuleRead,
    window: MonitoringWindow,
    evidence: MonitoringEvidence,
) -> list[tuple[EventSummaryRead, EventSessionSummary]]:
    reader = EcologyEventSummaryService(session)
    candidates: list[tuple[EventSummaryRead, EventSessionSummary]] = []
    for summary_id in rule.parameters.summary_ids:
        try:
            record = reader.get(str(rule.project_id), str(summary_id))
        except (NotFoundError, ValidationError, ConflictError, InvalidSource):
            evidence.exclude(
                "missing_or_invalid_summary", kind="reviewed_event_summary", source=summary_id
            )
            continue
        evidence.source_refs.append(
            MonitoringSourceReference(
                kind="reviewed_event_summary", id=record.id, sha256=record.content_sha256
            )
        )
        if record.stale_reasons:
            evidence.exclude("stale_summary", kind="reviewed_event_summary", source=summary_id)
        elif record.snapshot.protocol_sha256 != rule.protocol:
            evidence.exclude(
                "incompatible_protocol", kind="reviewed_event_summary", source=summary_id
            )
        else:
            for item in record.snapshot.sessions:
                at = item.observed_at
                reason = None
                if at is None:
                    reason = "unknown_session_time"
                elif not window.window_start <= at < window.window_end:
                    reason = "outside_window"
                elif item.valid_duration_s <= 0:
                    reason = "zero_valid_effort"
                if reason:
                    evidence.exclude(
                        reason,
                        kind="reviewed_event_summary",
                        source=summary_id,
                        at=at,
                        session_id=record.source_id_map.get(
                            item.link_revision_id, item.link_revision_id
                        ),
                    )
                else:
                    candidates.append((record, item))
    return candidates


def _overlapping_sessions(
    candidates: list[tuple[EventSummaryRead, EventSessionSummary]],
) -> set[int]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, (_, item) in enumerate(candidates):
        groups[(item.video_sha256, item.organism_key)].append(index)
    overlaps: set[int] = set()
    for indexes in groups.values():
        indexes.sort(key=lambda index: candidates[index][1].frame_start)
        latest: int | None = None
        for index in indexes:
            start, end = candidates[index][1].frame_start, candidates[index][1].frame_end
            if latest is not None and start <= candidates[latest][1].frame_end:
                overlaps.update((latest, index))
            if latest is None or end > candidates[latest][1].frame_end:
                latest = index
    return overlaps


def _biological(
    session: Session, rule: BiologicalMonitoringRuleRead, window: MonitoringWindow
) -> MonitoringEvidence:
    evidence = MonitoringEvidence("confirmed_events_per_valid_minute_by_dated_reviewed_session_v1")
    candidates = _summary_candidates(session, rule, window, evidence)
    duplicates = _overlapping_sessions(candidates)
    for index, (record, item) in enumerate(candidates):
        if index in duplicates:
            evidence.exclude(
                "overlapping_session",
                kind="reviewed_event_summary",
                source=record.id,
                at=item.observed_at,
                session_id=record.source_id_map.get(item.link_revision_id, item.link_revision_id),
            )
            continue
        evidence.sessions.append(biological_session_evidence(record.id, item, record.source_id_map))
    duration = fsum(item.valid_duration_s for item in evidence.sessions)
    count = sum(item.confirmed_event_count for item in evidence.sessions)
    evidence.effort = MonitoringEffort(
        valid_duration_s=duration,
        confirmed_event_count=count,
        accepted_sessions=len(evidence.sessions),
    )
    if duration < rule.parameters.minimum_effort_seconds:
        evidence.exclude("insufficient_reviewed_effort", kind="assessment")
    else:
        evidence.estimate = (count / duration) * 60
        evidence.findings.extend(
            _levels(
                evidence.estimate,
                rule.parameters,
                key="event_rate",
                unit=rule.unit,
                source_ids=sorted({item.summary_id for item in evidence.sessions}),
            )
        )
    return evidence


def monitoring_result(
    session: Session, rule: MonitoringRuleRead, window: MonitoringWindow
) -> MonitoringAssessmentResult:
    evidence = (
        _environmental(session, rule, window)
        if isinstance(rule, EnvironmentalMonitoringRuleRead)
        else _biological(session, rule, window)
    )
    return evidence.result(rule, window)
