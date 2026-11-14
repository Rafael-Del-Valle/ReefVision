"""Project study reports assembled from immutable, explicitly reviewed results."""

from collections import defaultdict
from datetime import UTC, datetime
from statistics import stdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.db.models import Job, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_analysis import AbundanceResult, GrowthResult
from reefvision.schemas.longitudinal_monitoring import PopulationUnitSummary
from reefvision.schemas.research_reports import (
    FigurePoint,
    FigureRecord,
    FigureRequest,
    FigureSeries,
    FigureSnapshot,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService
from reefvision.services.ecology_event_summary import EcologyEventSummaryService
from reefvision.services.scientific_comparison import read_comparison
from reefvision.storage.datasets import canonical_json_sha256

REPORT_JOB = "research_publication_figure"


def _earth_day(value: datetime) -> float:
    return value.timestamp() / 86400


def _group_point(result: GrowthResult, row: PopulationUnitSummary, index: int) -> FigurePoint:
    units = set(row.experimental_unit_ids)
    values = [
        unit.mean_absolute_change
        for unit in result.unit_summaries
        if unit.experimental_unit_id in units
        and unit.metric_name == row.metric_name
        and unit.unit == row.unit
        and unit.baseline_at.astimezone(UTC).date() == row.baseline_date
        and unit.final_at.astimezone(UTC).date() == row.final_date
    ]
    spread = (
        stdev(values) if len(values) == row.independent_unit_count and len(values) >= 2 else None
    )
    return FigurePoint(
        x=index,
        y=row.mean_unit_absolute_change,
        label=f"{row.baseline_date} to {row.final_date}",
        denominator=row.independent_unit_count,
        lower=row.mean_unit_absolute_change - spread if spread is not None else None,
        upper=row.mean_unit_absolute_change + spread if spread is not None else None,
    )


def _ecology_series(source: Any, options: FigureRequest) -> dict[str, Any]:
    result = source.snapshot.result
    output: dict[str, Any]
    if isinstance(result, GrowthResult) and options.figure == "trajectory":
        units = {item.unit for item in result.observations}
        if len(units) != 1:
            raise ValidationError("A figure requires one common measurement unit")
        groups: dict[str, list[FigurePoint]] = defaultdict(list)
        for item in sorted(result.observations, key=lambda item: item.observed_at):
            groups[item.organism_key].append(
                FigurePoint(
                    x=_earth_day(item.observed_at),
                    y=item.value,
                    label=item.observed_at.isoformat(),
                    denominator=1,
                )
            )
        output = {
            "x_label": "Observation date (UTC)",
            "x_scale": "utc_day",
            "y_label": f"Measured value ({units.pop()})",
            "geometry": "points",
            "series": [
                FigureSeries(label=key, points=points) for key, points in sorted(groups.items())
            ],
        }
    elif isinstance(result, GrowthResult) and options.figure == "group_summary":
        units = {row.unit for row in result.population_summaries}
        if len(units) != 1:
            raise ValidationError("Group figure requires comparable independent-unit summaries")
        output = {
            "x_label": "UTC comparison window",
            "y_label": f"Mean unit change ({units.pop()})",
            "geometry": "bars",
            "uncertainty": "Error bars show one sample SD across eligible declared units.",
            "series": [
                FigureSeries(
                    label="Comparable windows",
                    points=[
                        _group_point(result, row, index)
                        for index, row in enumerate(result.population_summaries, 1)
                    ],
                )
            ],
        }
    elif isinstance(result, AbundanceResult) and options.figure == "sample_coverage":
        labels = [
            f"{row.experimental_unit_id} · {row.observed_on}" for row in result.unit_summaries
        ]
        output = {
            "x_label": "Declared unit and UTC visit",
            "y_label": "Survey samples (count)",
            "geometry": "bars",
            "series": [
                FigureSeries(
                    label=field,
                    points=[
                        FigurePoint(x=index, y=value, label=label, denominator=total)
                        for index, (label, value, total) in enumerate(
                            (
                                (
                                    label,
                                    getattr(row, attribute),
                                    row.sample_count + row.excluded_sample_count,
                                )
                                for label, row in zip(labels, result.unit_summaries, strict=True)
                            ),
                            1,
                        )
                    ],
                )
                for field, attribute in (
                    ("Included samples", "sample_count"),
                    ("Excluded samples", "excluded_sample_count"),
                )
            ],
        }
    else:
        raise ValidationError("The selected ecological analysis does not support this figure")
    output.update(
        source_method=source.snapshot.method_version,
        source_evidence=source.snapshot.evidence_level,
        exclusions=[f"{row.source}: {row.reason}" for row in result.exclusions],
        limitations=source.snapshot.limitations,
        provenance={
            "reviewed_by": source.snapshot.reviewed_by,
            "review_note": source.snapshot.review_note,
        },
    )
    return output


def _event_series(source: Any, options: FigureRequest) -> dict[str, Any]:
    if options.figure != "event_rate":
        raise ValidationError("Select the event-rate figure for a reviewed event summary")
    snapshot = source.snapshot
    return {
        "source_method": snapshot.method,
        "source_evidence": snapshot.evidence_level,
        "x_label": "Organism",
        "y_label": "Confirmed events per minute of valid observation",
        "geometry": "bars",
        "series": [
            FigureSeries(
                label="Confirmed event rate",
                points=[
                    FigurePoint(
                        x=index,
                        y=row.confirmed_events_per_minute,
                        label=row.organism_key,
                        denominator=row.session_count,
                    )
                    for index, row in enumerate(snapshot.organisms, 1)
                    if row.confirmed_events_per_minute is not None
                ],
            )
        ],
        "exclusions": [
            f"{row.organism_key}: valid observation duration unavailable"
            for row in snapshot.organisms
            if row.confirmed_events_per_minute is None
        ],
        "limitations": [
            "Valid duration sums contiguous reviewed observations. Only complete events count."
        ],
        "provenance": {
            "protocol_sha256": snapshot.protocol_sha256,
            "reviewer": snapshot.selection.reviewer,
        },
    }


def _comparison_series(source: Any, options: FigureRequest) -> dict[str, Any]:
    if options.figure not in {"identity_scatter", "bland_altman"}:
        raise ValidationError(
            "Select an identity scatter or Bland-Altman figure for model comparison"
        )
    difference = options.figure == "bland_altman"
    source_snapshot = source.snapshot
    unit = source_snapshot.options.unit or "count"
    series: list[FigureSeries] = []
    guidelines: list[tuple[str, float]] = []
    provenance = {
        "reference_sha256": source_snapshot.reference_sha256,
        "scoring_configuration_sha256": source_snapshot.configuration_sha256,
    }
    for model in source_snapshot.models:
        points = [
            FigurePoint(
                x=(pair.reference + pair.estimate) / 2 if difference else pair.reference,
                y=pair.estimate - pair.reference if difference else pair.estimate,
                label=f"{pair.group_id} · {pair.individual_id}",
            )
            for pair in model.pairs
        ]
        series.append(FigureSeries(label=model.model_name, points=points))
        provenance[f"checkpoint {model.model_name}"] = model.checkpoint_sha256
        if difference:
            stats = model.statistics
            guidelines.append((f"{model.model_name} bias", stats.bias))
            if stats.limits_of_agreement:
                low, high = stats.limits_of_agreement
                guidelines.extend(
                    (
                        (f"{model.model_name} lower agreement limit", low),
                        (f"{model.model_name} upper agreement limit", high),
                    )
                )
    return {
        "source_method": source_snapshot.method,
        "source_evidence": source_snapshot.data_kind,
        "geometry": "points",
        "series": series,
        "guidelines": guidelines,
        "zero_identity": not difference,
        "x_label": f"Pair mean ({unit})" if difference else f"Reviewed reference ({unit})",
        "y_label": f"Model minus reference ({unit})" if difference else f"Model estimate ({unit})",
        "uncertainty": "Limits of agreement from the saved method, when available."
        if difference
        else None,
        "exclusions": [
            f"{row.video_id} · {row.individual_id}: {row.reason}"
            for row in source_snapshot.exclusions
        ],
        "limitations": source_snapshot.limitations,
        "provenance": provenance,
    }


def assemble_figure_snapshot(
    source: Any, options: FigureRequest, *, software_version: str
) -> FigureSnapshot:
    """Use the same immutable source projection for saving and archive validation."""
    builders = {
        "ecology": _ecology_series,
        "event_summary": _event_series,
        "comparison": _comparison_series,
    }
    fields = builders[options.source_kind](source, options)
    if not any(row.points for row in fields["series"]):
        raise ValidationError("No comparable numeric observations are available for this figure")
    return FigureSnapshot.model_validate(
        {
            **fields,
            "software_version": software_version,
            "configuration": options,
            "source_sha256": source.content_sha256,
        }
    )


class ResearchReportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _source(self, project_id: str, kind: str, source_id: str) -> Any:
        if kind == "ecology":
            return EcologyAnalysisService(self.session).get(project_id, source_id)
        if kind == "event_summary":
            return EcologyEventSummaryService(self.session).get(project_id, source_id)
        return read_comparison(self.session, project_id, source_id)

    def save(self, project_id: str, options: FigureRequest) -> FigureRecord:
        source = self._source(project_id, options.source_kind, str(options.source_id))
        if getattr(source, "stale", False) or getattr(source, "stale_reasons", []):
            raise ConflictError("Review and recalculate stale evidence before saving a new figure")
        result = assemble_figure_snapshot(source, options, software_version=__version__)
        snapshot = result.model_dump(mode="json")
        now = datetime.now(UTC)
        job = Job(
            project_id=project_id,
            job_type=REPORT_JOB,
            status="succeeded",
            progress_current=1,
            progress_total=1,
            started_at=now,
            completed_at=now,
            request_json=options.model_dump(mode="json"),
            result_json={
                "snapshot": snapshot,
                "content_sha256": canonical_json_sha256(snapshot),
                "local_source_id": str(options.source_id),
            },
        )
        self.session.add(job)
        self.session.commit()
        return self._read(project_id, job)

    def _read(self, project_id: str, job: Job, *, current: bool = True) -> FigureRecord:
        record = job.result_json or {}
        raw = record.get("snapshot")
        if not isinstance(raw, dict) or canonical_json_sha256(raw) != record.get("content_sha256"):
            raise ValidationError("Saved report failed its checksum")
        snapshot = FigureSnapshot.model_validate(raw)
        stale = False
        if current:
            try:
                source = self._source(
                    project_id, snapshot.configuration.source_kind, record["local_source_id"]
                )
                stale = source.content_sha256 != snapshot.source_sha256 or bool(
                    getattr(source, "stale", False) or getattr(source, "stale_reasons", [])
                )
            except (ConflictError, NotFoundError, ValidationError):
                stale = True
        created = job.created_at
        return FigureRecord(
            id=job.id,
            project_id=project_id,
            created_at=created if created.tzinfo else created.replace(tzinfo=UTC),
            content_sha256=record["content_sha256"],
            local_source_id=record["local_source_id"],
            stale=stale,
            snapshot=snapshot,
        )

    def get(self, project_id: str, identifier: str) -> FigureRecord:
        record = self.session.get(Job, identifier)
        if record is None or record.project_id != project_id or record.job_type != REPORT_JOB:
            raise NotFoundError("Saved research report not found")
        return self._read(project_id, record)

    def list(self, project_id: str, offset: int, limit: int) -> list[FigureRecord]:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        records = self.session.scalars(
            select(Job)
            .where(Job.project_id == project_id, Job.job_type == REPORT_JOB)
            .order_by(Job.created_at.desc(), Job.id)
            .offset(offset)
            .limit(limit)
        )
        return [self._read(project_id, record, current=False) for record in records]
