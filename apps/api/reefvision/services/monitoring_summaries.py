"""Compare local monitoring assessments without pooling observations or review authority."""

from collections import Counter
from datetime import UTC
from uuid import UUID

from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import MonitoringProjectSummary, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.monitoring_summary import (
    AssessmentSelection,
    ComparedAlert,
    ComparisonReview,
    ComparisonRow,
    ComparisonSnapshot,
    ComparisonUnit,
    ComparisonValues,
    MonitoringSummaryCreate,
    MonitoringSummaryPage,
    MonitoringSummaryRead,
)
from reefvision.services.monitoring import MonitoringService
from reefvision.storage.datasets import canonical_json_sha256


def _shared_signatures(row: ComparisonRow) -> set[str]:
    return {source.sha256 for source in row.values.source_refs} | {
        unit.video_sha256 for unit in row.values.independent_units
    }


def _compare(reference: ComparisonRow, peer: ComparisonRow) -> list[str]:
    reasons = []
    for field in ("kind", "protocol", "metric", "unit"):
        if getattr(reference, field) != getattr(peer, field):
            reasons.append(f"Different {field} from the reference project.")
    if (reference.window_start, reference.window_end) != (peer.window_start, peer.window_end):
        reasons.append("The UTC observation windows differ.")
    if reference.values.method != peer.values.method:
        reasons.append("The assessment methods differ.")
    if reference.values.rule_parameters != peer.values.rule_parameters:
        reasons.append("The rule parameters for sampling or alerts differ.")
    return reasons


class MonitoringSummaryService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.monitoring = MonitoringService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Monitoring project not found")
        return project

    def _review(self, project_id: str, assessment_id: str) -> ComparisonReview:
        alerts: list[ComparedAlert] = []
        while True:
            page = self.monitoring.list_alerts(
                project_id, assessment_id=assessment_id, limit=100, offset=len(alerts)
            )
            alerts.extend(
                ComparedAlert(
                    alert_id=a.id,
                    kind=a.kind,
                    proposal_sha256=a.proposal_sha256,
                    status=a.status,
                    review_revision=a.review_revision,
                    latest_review=a.latest_review,
                )
                for a in page.items
            )
            if len(alerts) >= page.total or not page.items:
                break
        alerts.sort(key=lambda alert: str(alert.alert_id))
        return ComparisonReview(
            alerts=alerts,
            proposed=sum(a.status == "proposed" for a in alerts),
            confirmed=sum(a.status == "confirmed" for a in alerts),
            dismissed=sum(a.status == "dismissed" for a in alerts),
        )

    def _row(self, selection: AssessmentSelection) -> ComparisonRow:
        project_id, assessment_id = str(selection.project_id), str(selection.assessment_id)
        project = self._project(project_id)
        assessment = self.monitoring.get_assessment(project_id, assessment_id)
        result = assessment.result
        review = self._review(project_id, assessment_id)
        reasons: list[str] = []
        if assessment.source_status == "stale":
            reasons.extend(["Source evidence changed.", *assessment.stale_reasons])
        if result.estimate is None:
            reasons.append("The observation window has no supported estimate.")
        if review.proposed:
            reasons.append("Researcher review is pending for one or more alerts.")
        units = [
            ComparisonUnit.model_validate(s.model_dump(include=set(ComparisonUnit.model_fields)))
            for s in result.biological_sessions
        ]
        if result.kind == "biological" and any(
            not unit.unit_id or not unit.unit_type for unit in units
        ):
            reasons.append("A reviewed session has no declared independent sampling unit.")
        # Source selectors identify different sites and specimens. Cadence, QC and alert criteria
        # are still part of comparability, even when two projects use the same protocol label.
        try:
            rule = self.monitoring.get_rule(project_id, str(assessment.rule_id))
            settings = rule.parameters.model_dump(mode="json", exclude={"source", "summary_ids"})
        except (ConflictError, NotFoundError) as exc:
            reasons.append(str(exc))
            settings = {}
        return ComparisonRow(
            project_id=selection.project_id,
            project_name=project.name,
            assessment_id=assessment.id,
            rule_id=assessment.rule_id,
            rule_sha256=result.rule_sha256,
            kind=result.kind,
            protocol=result.protocol,
            metric=result.metric,
            unit=result.unit,
            window_start=assessment.window_start,
            window_end=assessment.window_end,
            result_sha256=assessment.result_sha256,
            evidence_sha256=assessment.evidence_sha256,
            effort=result.effort,
            review=review,
            reasons=reasons,
            status="excluded" if reasons else "included",
            values=ComparisonValues(
                estimate=result.estimate,
                method=result.method,
                source_refs=result.source_refs,
                independent_units=units,
                exclusions=result.exclusions,
                rule_parameters=settings,
            ),
        )

    def create(self, project_id: str, payload: MonitoringSummaryCreate) -> MonitoringSummaryRead:
        reference_id = payload.selections[0].project_id
        if str(reference_id) != project_id:
            raise ValidationError("Choose an assessment from the open project as the reference")
        # Acquire the local SQLite write transaction before collecting decisions across projects.
        # Two concurrent reviews or retries cannot combine different generations of evidence.
        self.session.execute(
            update(Project).where(Project.id == project_id).values(updated_at=Project.updated_at)
        )
        rows = [self._row(entry) for entry in payload.selections]
        reference = rows[0]
        signatures = [_shared_signatures(row) for row in rows]
        counts = Counter(digest for project_sources in signatures for digest in project_sources)
        for row, project_sources in zip(rows, signatures, strict=True):
            if any(counts[digest] > 1 for digest in project_sources):
                row.reasons.append(
                    "Source evidence or a recording also appears in another selected project."
                )
                row.status = "excluded"
        for peer in rows[1:]:
            peer.reasons.extend(_compare(reference, peer))
            if reference.reasons:
                peer.reasons.append("The reference project is excluded from this comparison.")
            if peer.reasons:
                peer.status = "excluded"
        snapshot = ComparisonSnapshot(reference_project_id=reference_id, rows=rows).model_dump(
            mode="json"
        )
        digest = canonical_json_sha256(snapshot)
        record = self.session.scalar(
            select(MonitoringProjectSummary).where(
                MonitoringProjectSummary.project_id == project_id,
                MonitoringProjectSummary.content_sha256 == digest,
            )
        )
        if record is None:
            record = MonitoringProjectSummary(
                project_id=project_id, snapshot_json=snapshot, content_sha256=digest
            )
            self.session.add(record)
        self.session.commit()
        return self._read(record)

    @staticmethod
    def _read(record: MonitoringProjectSummary) -> MonitoringSummaryRead:
        if canonical_json_sha256(record.snapshot_json) != record.content_sha256:
            raise ConflictError("The saved monitoring comparison checksum has changed")
        try:
            snapshot = ComparisonSnapshot.model_validate(record.snapshot_json)
        except SchemaError as exc:
            raise ConflictError("The saved monitoring comparison is invalid") from exc
        # Restored comparisons retain their original project identities inside the frozen snapshot.
        stamp = record.created_at
        return MonitoringSummaryRead(
            id=UUID(record.id),
            project_id=UUID(record.project_id),
            created_at=stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp,
            content_sha256=record.content_sha256,
            snapshot=snapshot,
        )

    def get(self, project_id: str, summary_id: str) -> MonitoringSummaryRead:
        record = self.session.get(MonitoringProjectSummary, summary_id)
        if record is None or record.project_id != project_id:
            raise NotFoundError("Monitoring comparison not found in this project")
        return self._read(record)

    def list(self, project_id: str, limit: int, offset: int) -> MonitoringSummaryPage:
        self._project(project_id)
        scope = MonitoringProjectSummary.project_id == project_id
        rows = self.session.scalars(
            select(MonitoringProjectSummary)
            .where(scope)
            .order_by(MonitoringProjectSummary.created_at.desc(), MonitoringProjectSummary.id)
            .limit(limit)
            .offset(offset)
        )
        total = self.session.scalar(
            select(func.count()).select_from(MonitoringProjectSummary).where(scope)
        )
        return MonitoringSummaryPage(items=[self._read(row) for row in rows], total=total or 0)
