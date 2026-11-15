"""Build immutable event summaries from reviewed scoped ReefPose evidence."""

import csv
from collections import defaultdict
from datetime import UTC, datetime
from io import StringIO
from itertools import pairwise
from math import fsum, isfinite
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    EcologyIdentityRevision,
    EcologyPoseLinkRevision,
    Job,
    PoseEventDetectionRun,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
    Project,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_event_summary import (
    EventOrganismSummary,
    EventRate,
    EventSessionSelection,
    EventSessionSummary,
    EventSummaryCreate,
    EventSummaryPage,
    EventSummaryRead,
    EventSummarySnapshot,
    EventUnitSummary,
    ReviewedEventValue,
    ValidEventInterval,
)
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.ecology_pose_links import EcologyPoseLinkService
from reefvision.services.pose_biological_measurement import PoseBiologicalMeasurementService
from reefvision.storage.datasets import canonical_json_sha256

EVENT_SUMMARY_JOB = "ecology_event_summary"


def rates(count: int, seconds: float) -> EventRate:
    return EventRate(
        confirmed_complete_count=count,
        valid_duration_s=seconds,
        confirmed_events_per_minute=60 * count / seconds if seconds > 0 else None,
    )


def summarize(
    sessions: list[EventSessionSummary],
) -> tuple[list[EventOrganismSummary], list[EventUnitSummary]]:
    grouped: dict[str, list[EventSessionSummary]] = defaultdict(list)
    for row in sessions:
        grouped[row.organism_key].append(row)
    organisms = [
        EventOrganismSummary(
            organism_key=key,
            session_count=len(rows),
            unit_type=rows[0].unit_type,
            unit_id=rows[0].unit_id,
            **rates(
                sum(row.confirmed_complete_count for row in rows),
                fsum(row.valid_duration_s for row in rows),
            ).model_dump(),
        )
        for key, rows in sorted(grouped.items())
    ]
    units: dict[tuple[str, str], list[EventOrganismSummary]] = defaultdict(list)
    has_comparable_units = (
        all(row.unit_type and row.unit_id for row in organisms)
        and len({row.unit_type for row in organisms}) == 1
    )
    if has_comparable_units:
        for organism in organisms:
            assert organism.unit_type and organism.unit_id
            units[(organism.unit_type, organism.unit_id)].append(organism)
    return organisms, [
        EventUnitSummary(
            unit_type=unit_type,
            unit_id=unit_id,
            organism_count=len(rows),
            **rates(
                sum(row.confirmed_complete_count for row in rows),
                fsum(row.valid_duration_s for row in rows),
            ).model_dump(),
        )
        for (unit_type, unit_id), rows in sorted(units.items())
    ]


def _valid_intervals(
    samples: list[PoseMeasurementSample],
    reviewed_frames: set[int],
    physical: bool,
    maximum_gap: float,
    minimum_confidence: float,
) -> tuple[list[ValidEventInterval], int]:
    valid = []
    for sample in samples:
        value = sample.physical_value if physical else sample.pixel_value
        if (
            sample.frame_index in reviewed_frames
            and sample.valid
            and value is not None
            and isfinite(value)
            and isfinite(sample.time_s)
            and (sample.confidence or 0) >= minimum_confidence
        ):
            valid.append(sample)
    intervals: list[ValidEventInterval] = []
    for first, second in pairwise(valid):
        if second.frame_index != first.frame_index + 1:
            continue
        if not 0 < second.time_s - first.time_s <= maximum_gap:
            continue
        if intervals and intervals[-1].end_frame == first.frame_index:
            intervals[-1].end_frame = second.frame_index
            intervals[-1].end_time_s = second.time_s
        else:
            intervals.append(
                ValidEventInterval(
                    start_frame=first.frame_index,
                    end_frame=second.frame_index,
                    start_time_s=first.time_s,
                    end_time_s=second.time_s,
                )
            )
    return intervals, len(valid)


class EcologyEventSummaryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.links = EcologyPoseLinkService(session)
        self.movement = PoseBiologicalMeasurementService(session)
        self.ecology = EcologyIdentityService(session)

    def _session(
        self,
        project_id: str,
        picked: EventSessionSelection,
        identities: dict[str, EcologyIdentityRevision],
    ) -> tuple[EventSessionSummary, str]:
        row = self.session.get(EcologyPoseLinkRevision, str(picked.link_revision_id))
        if row is None or row.project_id != project_id:
            raise NotFoundError("Reviewed pose link not found")
        link = self.links.history(project_id, row.link_id)[-1]
        if link.id != picked.link_revision_id or link.status != "current":
            raise ConflictError("Select a current reviewed pose link")
        identity = identities.get(link.organism_key)
        if identity is None or identity.id != row.organism_revision_id:
            raise ConflictError("Review the pose link against the current organism assignment")
        series_id = str(picked.measurement_series_id)
        pinned_series = next(
            (entry for entry in link.source.measurements if entry.id == series_id), None
        )
        if pinned_series is None:
            raise ValidationError(
                "The measurement series must be included in the reviewed pose link"
            )
        series = self.session.get(PoseMeasurementSeries, series_id)
        run = self.session.get(PoseEventDetectionRun, str(picked.event_run_id))
        measurement = self.session.get(PoseMeasurementRun, pinned_series.run_id)
        if (
            series is None
            or run is None
            or measurement is None
            or run.measurement_run_id != measurement.id
            or series.measurement_run_id != measurement.id
            or series.animal_identity_id != row.animal_identity_id
            or canonical_json_sha256(run.configuration_json) != run.configuration_sha256
        ):
            raise ValidationError("Event detector does not match the linked scientific measurement")
        self.movement._validate_event_source(run)
        cycle = next(
            (
                item
                for item in run.configuration_json["cycles"]
                if item["measurement_series_id"] == series_id
            ),
            None,
        )
        definitions = [
            item for item in measurement.definitions_json if item["id"] == series.definition_id
        ]
        if cycle is None or len(definitions) != 1:
            raise ValidationError(
                "The selected run must contain exactly one compatible cycle definition"
            )
        amplitude_unit = series.physical_unit or series.pixel_unit
        protocol = canonical_json_sha256(
            {
                "anatomy": link.source.pose_schema_sha256,
                "formula_version": series.formula_version,
                "definition": definitions[0],
                "amplitude_unit": amplitude_unit,
                "cycle": {
                    key: value for key, value in cycle.items() if key != "measurement_series_id"
                },
            }
        )
        samples = list(
            self.session.scalars(
                select(PoseMeasurementSample)
                .where(
                    PoseMeasurementSample.series_id == series_id,
                    PoseMeasurementSample.frame_index.between(link.frame_start, link.frame_end),
                )
                .order_by(PoseMeasurementSample.frame_index)
            )
        )
        intervals, valid_frames = _valid_intervals(
            samples,
            {item.frame_index for item in link.source.observations},
            series.physical_unit is not None,
            cycle["maximum_gap_s"],
            cycle["minimum_confidence"],
        )
        elapsed = fsum(span.end_time_s - span.start_time_s for span in intervals)
        selected = {entry.id for entry in link.source.events if entry.run_id == run.id}
        current = [
            event
            for event in self.movement.events(run.id)
            if event.measurement_series_id == series_id
            and link.frame_start <= event.start_frame <= link.frame_end
            and event.review_state not in {"removed", "rejected"}
        ]
        events: list[ReviewedEventValue] = []
        excluded_confirmed = 0
        for event in current:
            if event.review_state != "confirmed" or event.cycle_state != "complete":
                continue
            if (
                event.id not in selected
                or event.end_frame is None
                or event.end_time_s is None
                or event.duration_s is None
                or not any(
                    span.start_frame <= event.start_frame <= event.end_frame <= span.end_frame
                    for span in intervals
                )
            ):
                excluded_confirmed += 1
                continue
            events.append(
                ReviewedEventValue(
                    id=event.id,
                    event_series_id=event.event_series_id,
                    after_sha256=event.after_sha256,
                    start_frame=event.start_frame,
                    end_frame=event.end_frame,
                    start_time_s=event.start_time_s,
                    end_time_s=event.end_time_s,
                    duration_s=event.duration_s,
                    amplitude=event.amplitude,
                )
            )
        for first, second in pairwise(events):
            if second.start_frame < first.end_frame:
                raise ValidationError(
                    "Resolve overlapping confirmed events before summarizing a session"
                )
        event_rate = rates(len(events), elapsed)
        return EventSessionSummary(
            link_revision_id=row.id,
            link_source_sha256=link.source_sha256,
            identity_revision_id=identity.id,
            organism_key=link.organism_key,
            unit_type=identity.experimental_unit_type,
            unit_id=identity.experimental_unit_id,
            video_id=link.source.video_id,
            video_sha256=link.source.video_sha256,
            identity_run_id=row.association_run_id,
            animal_identity_id=row.animal_identity_id,
            measurement_run_id=measurement.id,
            measurement_series_id=series_id,
            measurement_sha256=series.series_sha256,
            event_run_id=run.id,
            event_revision_digest=self.movement.review_state_sha256(run.id),
            observed_at=picked.observed_at.astimezone(UTC) if picked.observed_at else None,
            frame_start=link.frame_start,
            frame_end=link.frame_end,
            valid_intervals=intervals,
            invalid_frame_count=link.frame_end - link.frame_start + 1 - valid_frames,
            partial_count=sum(event.cycle_state != "complete" for event in current),
            unreviewed_count=sum(
                event.cycle_state == "complete" and event.review_state == "unreviewed"
                for event in current
            ),
            excluded_confirmed_count=excluded_confirmed,
            amplitude_unit=amplitude_unit,
            events=events,
            **event_rate.model_dump(),
        ), protocol

    def calculate(self, project_id: str, payload: EventSummaryCreate) -> EventSummarySnapshot:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        identities = self.ecology._latest(project_id)
        captured = [self._session(project_id, picked, identities) for picked in payload.sessions]
        if len({protocol for _, protocol in captured}) != 1:
            raise ValidationError(
                "All sessions must use the same anatomy, measurement and cycle protocol"
            )
        sessions = sorted(
            (row for row, _ in captured),
            key=lambda row: (row.organism_key, row.video_sha256, row.frame_start),
        )
        for previous, current in pairwise(sessions):
            if (previous.organism_key, previous.video_sha256) == (
                current.organism_key,
                current.video_sha256,
            ) and current.frame_start <= previous.frame_end:
                raise ValidationError(
                    "Selected sessions overlap for the same organism and recording"
                )
        event_ids = [event.event_series_id for row in sessions for event in row.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValidationError("A confirmed event can only contribute once")
        organisms, units = summarize(sessions)
        return EventSummarySnapshot(
            selection=payload,
            protocol_sha256=captured[0][1],
            sessions=sessions,
            organisms=organisms,
            units=units,
        )

    def save(self, project_id: str, payload: EventSummaryCreate) -> EventSummaryRead:
        result = self.calculate(project_id, payload)
        snapshot = result.model_dump(mode="json")
        now = datetime.now(UTC)
        row = Job(
            project_id=project_id,
            job_type=EVENT_SUMMARY_JOB,
            status="succeeded",
            progress_total=len(result.sessions),
            progress_current=len(result.sessions),
            request_json=payload.model_dump(mode="json"),
            result_json={
                "snapshot": snapshot,
                "content_sha256": canonical_json_sha256(snapshot),
                "source_id_map": {},
            },
            started_at=now,
            completed_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return self._read(row, check_current=False)

    def _read(self, row: Job, *, check_current: bool = True) -> EventSummaryRead:
        stored = row.result_json or {}
        raw = stored.get("snapshot")
        if (
            row.project_id is None
            or raw is None
            or canonical_json_sha256(raw) != stored.get("content_sha256")
        ):
            raise ValidationError("Saved event summary failed its evidence checksum")
        snapshot = EventSummarySnapshot.model_validate(raw)
        stale: list[str] = []
        mapping: dict[str, str] = stored.get("source_id_map", {})
        if check_current:
            original = {session.link_revision_id: session for session in snapshot.sessions}
            identities = self.ecology._latest(row.project_id)
            for pick in snapshot.selection.sessions:
                local = EventSessionSelection.model_validate(
                    _map_selection(pick.model_dump(mode="json"), mapping)
                )
                try:
                    current, protocol = self._session(row.project_id, local, identities)
                except (ConflictError, NotFoundError, ValidationError) as exc:
                    stale.append(str(exc))
                    continue
                old = original[str(pick.link_revision_id)]
                if protocol != snapshot.protocol_sha256 or _scientific_values(
                    old
                ) != _scientific_values(current):
                    stale.append(f"Reviewed source or valid effort changed for {old.organism_key}")
        timestamp = row.created_at
        return EventSummaryRead(
            id=row.id,
            project_id=row.project_id,
            created_at=timestamp.astimezone(UTC)
            if timestamp.tzinfo
            else timestamp.replace(tzinfo=UTC),
            content_sha256=stored["content_sha256"],
            snapshot=snapshot,
            source_id_map=mapping,
            stale_reasons=sorted(set(stale)),
        )

    def get(self, project_id: str, summary_id: str) -> EventSummaryRead:
        row = self.session.get(Job, summary_id)
        if row is None or row.project_id != project_id or row.job_type != EVENT_SUMMARY_JOB:
            raise NotFoundError("Reviewed event summary not found")
        return self._read(row)

    def list(self, project_id: str, limit: int, offset: int) -> EventSummaryPage:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        where = (Job.project_id == project_id, Job.job_type == EVENT_SUMMARY_JOB)
        total = self.session.scalar(select(func.count()).select_from(Job).where(*where)) or 0
        rows = self.session.scalars(
            select(Job)
            .where(*where)
            .order_by(Job.created_at.desc(), Job.id)
            .limit(limit)
            .offset(offset)
        )
        return EventSummaryPage(
            items=[self._read(row, check_current=False) for row in rows], total=total
        )


def _map_selection(value: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {
        **value,
        **{
            key: mapping.get(value[key], value[key])
            for key in ("link_revision_id", "event_run_id", "measurement_series_id")
        },
    }


def _scientific_values(row: EventSessionSummary) -> dict[str, Any]:
    return {
        "effort": row.valid_intervals,
        "counts": (
            row.confirmed_complete_count,
            row.unreviewed_count,
            row.partial_count,
            row.excluded_confirmed_count,
        ),
        "invalid_frame_count": row.invalid_frame_count,
        "event_values": [
            event.model_dump(exclude={"id", "event_series_id", "after_sha256"})
            for event in row.events
        ],
        "identity": (row.organism_key, row.unit_type, row.unit_id, row.video_sha256),
        "amplitude_unit": row.amplitude_unit,
    }


def export_event_csv(snapshot: EventSummarySnapshot) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "level",
            "organism",
            "unit_type",
            "unit_id",
            "video_id",
            "observation_time_utc",
            "confirmed_complete_count",
            "valid_seconds",
            "confirmed_events_per_minute",
            "partial_count",
            "unreviewed_count",
            "excluded_confirmed_count",
            "event_id",
            "start_seconds",
            "end_seconds",
            "duration_seconds",
            "amplitude",
            "amplitude_unit",
        )
    )
    for row in snapshot.sessions:
        timestamp = row.observed_at.isoformat() if row.observed_at else None
        keys = (
            row.organism_key,
            _csv_text(row.unit_type),
            _csv_text(row.unit_id),
            row.video_id,
            timestamp,
        )
        writer.writerow(
            (
                "session",
                *keys,
                row.confirmed_complete_count,
                row.valid_duration_s,
                row.confirmed_events_per_minute,
                row.partial_count,
                row.unreviewed_count,
                row.excluded_confirmed_count,
            )
        )
        for event in row.events:
            writer.writerow(
                (
                    "confirmed_event",
                    *keys,
                    *(None,) * 6,
                    event.id,
                    event.start_time_s,
                    event.end_time_s,
                    event.duration_s,
                    event.amplitude,
                    _csv_text(row.amplitude_unit),
                )
            )
    for organism in snapshot.organisms:
        writer.writerow(
            (
                "organism",
                organism.organism_key,
                _csv_text(organism.unit_type),
                _csv_text(organism.unit_id),
                None,
                None,
                organism.confirmed_complete_count,
                organism.valid_duration_s,
                organism.confirmed_events_per_minute,
            )
        )
    for unit in snapshot.units:
        writer.writerow(
            (
                "unit",
                None,
                _csv_text(unit.unit_type),
                _csv_text(unit.unit_id),
                None,
                None,
                unit.confirmed_complete_count,
                unit.valid_duration_s,
                unit.confirmed_events_per_minute,
            )
        )
    return output.getvalue()


def _csv_text(value: str | None) -> str | None:
    if value and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
