"""Project monitoring, immutable assessments, and attributed review decisions."""

from typing import TypeVar

from pydantic import ValidationError as InvalidStoredValue
from sqlalchemy import Select, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.monitoring import (
    MonitoringAlert,
    MonitoringAlertReview,
    MonitoringAssessment,
    MonitoringRule,
)
from reefvision.db.models.project import Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.monitoring import (
    MONITORING_RULE,
    MONITORING_RULE_READ,
    BiologicalMonitoringRule,
    MonitoringAlertPage,
    MonitoringAlertRead,
    MonitoringAlertReviewCreate,
    MonitoringAlertReviewPage,
    MonitoringAlertReviewRead,
    MonitoringAssessmentCreate,
    MonitoringAssessmentPage,
    MonitoringAssessmentRead,
    MonitoringAssessmentResult,
    MonitoringFinding,
    MonitoringRuleCreate,
    MonitoringRulePage,
    MonitoringRuleRead,
    MonitoringWindow,
)
from reefvision.services.ecology_event_summary import EcologyEventSummaryService
from reefvision.services.monitoring_evidence import monitoring_result, monitoring_utc
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.identity import get_local_user_identity

_Record = TypeVar(
    "_Record", MonitoringRule, MonitoringAssessment, MonitoringAlert, MonitoringAlertReview
)


def _definition(row: MonitoringRule) -> dict[str, object]:
    return {
        "kind": row.kind,
        "label": row.label,
        "protocol": row.protocol,
        "metric": row.metric,
        "unit": row.unit,
        "parameters": row.parameters_json,
    }


def verify_monitoring_rule(
    session: Session, project_id: str, rule_id: str, rule_sha256: str | None = None
) -> MonitoringRuleRead:
    """Return the verified rule pin used by both standalone and saved workflows."""
    row = session.get(MonitoringRule, rule_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Monitoring rule not found in this project")
    body = _definition(row)
    try:
        definition = MONITORING_RULE.validate_python(body)
    except InvalidStoredValue as exc:
        raise ConflictError("Saved monitoring rule could not be verified") from exc
    if (
        canonical_json_sha256(definition.model_dump(mode="json")) != row.rule_sha256
        or canonical_json_sha256(body) != row.rule_sha256
        or (rule_sha256 is not None and row.rule_sha256 != rule_sha256)
    ):
        raise ConflictError("The monitoring rule does not match its saved SHA-256")
    return MONITORING_RULE_READ.validate_python(
        {
            **body,
            "id": row.id,
            "project_id": row.project_id,
            "rule_sha256": row.rule_sha256,
            "created_at": monitoring_utc(row.created_at),
        }
    )


class MonitoringService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str, *, write: bool = False) -> None:
        query = select(Project.id).where(Project.id == project_id)
        if write:
            connection = self.session.connection()
            if connection.dialect.name == "sqlite":
                # Reserve the writer before checking live evidence and revision. A workflow
                # node may already own this transaction, but its artifact has not been written.
                if not getattr(connection.connection.driver_connection, "in_transaction", False):
                    try:
                        connection.exec_driver_sql("BEGIN IMMEDIATE")
                    except OperationalError as exc:
                        raise ConflictError(
                            "Monitoring database is busy. Reload and retry."
                        ) from exc
            else:
                query = query.with_for_update()
        if self.session.scalar(query) is None:
            raise NotFoundError("Project not found")

    def _owned(self, table: type[_Record], project_id: str, row_id: str, name: str) -> _Record:
        row = self.session.get(table, row_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError(f"Monitoring {name} not found in this project")
        return row

    def _page(
        self, query: Select[_Record], *, limit: int, offset: int
    ) -> tuple[list[_Record], int]:
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        return list(self.session.scalars(query.limit(limit).offset(offset))), total

    def get_rule(self, project_id: str, rule_id: str) -> MonitoringRuleRead:
        return verify_monitoring_rule(self.session, project_id, rule_id)

    def create_rule(self, project_id: str, definition: MonitoringRuleCreate) -> MonitoringRuleRead:
        self._project(project_id, write=True)
        digest = canonical_json_sha256(definition.model_dump(mode="json"))
        previous = self.session.scalar(
            select(MonitoringRule).where(
                MonitoringRule.project_id == project_id, MonitoringRule.rule_sha256 == digest
            )
        )
        if previous is not None:
            return self.get_rule(project_id, previous.id)

        if isinstance(definition, BiologicalMonitoringRule):
            events = EcologyEventSummaryService(self.session)
            for summary_id in definition.parameters.summary_ids:
                summary = events.get(project_id, str(summary_id))
                if summary.stale_reasons:
                    raise ConflictError("Review changed biological evidence and save a new summary")
                if summary.snapshot.protocol_sha256 != definition.protocol:
                    raise ValidationError("Choose reviewed summaries that match the rule protocol")

        rule = MonitoringRule(
            project_id=project_id,
            kind=definition.kind,
            label=definition.label,
            protocol=definition.protocol,
            metric=definition.metric,
            unit=definition.unit,
            parameters_json=definition.parameters.model_dump(mode="json"),
            rule_sha256=digest,
        )
        self.session.add(rule)
        self.session.flush()
        return self.get_rule(project_id, rule.id)

    def list_rules(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> MonitoringRulePage:
        self._project(project_id)
        rows, total = self._page(
            select(MonitoringRule)
            .where(MonitoringRule.project_id == project_id)
            .order_by(MonitoringRule.created_at.desc(), MonitoringRule.id),
            limit=limit,
            offset=offset,
        )
        return MonitoringRulePage(
            items=[self.get_rule(project_id, row.id) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def _assessment_result(self, row: MonitoringAssessment) -> MonitoringAssessmentResult:
        if canonical_json_sha256(row.result_json) != row.result_sha256:
            raise ConflictError("Saved monitoring result failed its evidence checksum")
        try:
            result = MonitoringAssessmentResult.model_validate(row.result_json)
        except InvalidStoredValue as exc:
            raise ConflictError("Saved monitoring result is invalid") from exc
        if (
            str(result.project_id) != row.project_id
            or str(result.rule_id) != row.rule_id
            or result.window_start != monitoring_utc(row.window_start)
            or result.window_end != monitoring_utc(row.window_end)
            or result.evidence_sha256 != row.evidence_sha256
        ):
            raise ConflictError("Saved monitoring result does not match its project or time window")
        return result

    def _read_assessment(
        self, row: MonitoringAssessment, *, check_current: bool = True
    ) -> MonitoringAssessmentRead:
        result = self._assessment_result(row)
        stale_reasons: list[str] = []
        if check_current:
            try:
                rule = verify_monitoring_rule(
                    self.session, row.project_id, row.rule_id, result.rule_sha256
                )
                current = monitoring_result(self.session, rule, result)
            except (ConflictError, NotFoundError, ValidationError) as exc:
                stale_reasons.append(str(exc))
            else:
                if current.evidence_sha256 != result.evidence_sha256:
                    stale_reasons.append(
                        "Source observations or reviewed event evidence changed in this window"
                    )
        return MonitoringAssessmentRead(
            id=row.id,
            project_id=row.project_id,
            rule_id=row.rule_id,
            window_start=monitoring_utc(row.window_start),
            window_end=monitoring_utc(row.window_end),
            evidence_sha256=row.evidence_sha256,
            result_sha256=row.result_sha256,
            result=result,
            created_at=monitoring_utc(row.created_at),
            source_status="stale" if stale_reasons else "current",
            stale_reasons=stale_reasons,
        )

    def get_assessment(self, project_id: str, assessment_id: str) -> MonitoringAssessmentRead:
        return self._read_assessment(
            self._owned(MonitoringAssessment, project_id, assessment_id, "assessment")
        )

    def list_assessments(
        self, project_id: str, *, rule_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> MonitoringAssessmentPage:
        self._project(project_id)
        query = select(MonitoringAssessment).where(MonitoringAssessment.project_id == project_id)
        if rule_id is not None:
            self.get_rule(project_id, rule_id)
            query = query.where(MonitoringAssessment.rule_id == rule_id)
        rows, total = self._page(
            query.order_by(MonitoringAssessment.created_at.desc(), MonitoringAssessment.id),
            limit=limit,
            offset=offset,
        )
        return MonitoringAssessmentPage(
            items=[self._read_assessment(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def create_assessment(
        self, project_id: str, payload: MonitoringAssessmentCreate
    ) -> MonitoringAssessmentRead:
        """Stage one assessment and its proposed alerts in the caller's transaction."""
        self._project(project_id, write=True)
        rule = verify_monitoring_rule(
            self.session, project_id, str(payload.rule_id), payload.rule_sha256
        )
        window = MonitoringWindow(window_start=payload.window_start, window_end=payload.window_end)
        result = monitoring_result(self.session, rule, window)
        previous = self.session.scalar(
            select(MonitoringAssessment).where(
                MonitoringAssessment.rule_id == str(rule.id),
                MonitoringAssessment.window_start == window.window_start,
                MonitoringAssessment.window_end == window.window_end,
                MonitoringAssessment.evidence_sha256 == result.evidence_sha256,
            )
        )
        if previous is not None:
            return self._read_assessment(previous, check_current=False)
        result_json = result.model_dump(mode="json")
        record = MonitoringAssessment(
            project_id=project_id,
            rule_id=str(rule.id),
            window_start=window.window_start,
            window_end=window.window_end,
            evidence_sha256=result.evidence_sha256,
            result_sha256=canonical_json_sha256(result_json),
            result_json=result_json,
        )
        self.session.add(record)
        self.session.flush()
        for finding in result.findings:
            body = finding.model_dump(mode="json")
            self.session.add(
                MonitoringAlert(
                    project_id=project_id,
                    assessment_id=record.id,
                    kind=finding.kind,
                    finding_key=finding.finding_key,
                    proposal_json=body,
                    proposal_sha256=canonical_json_sha256(body),
                )
            )
        self.session.flush()
        return self._read_assessment(record, check_current=False)

    @staticmethod
    def _read_review(row: MonitoringAlertReview) -> MonitoringAlertReviewRead:
        return MonitoringAlertReviewRead.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "alert_id": row.alert_id,
                "reviewer": row.reviewer,
                "decision": row.decision,
                "reason": row.reason,
                "revision": row.revision,
                "reviewed_at": monitoring_utc(row.reviewed_at),
            }
        )

    def _review_query(self, row: MonitoringAlert) -> Select[MonitoringAlertReview]:
        return (
            select(MonitoringAlertReview)
            .where(
                MonitoringAlertReview.project_id == row.project_id,
                MonitoringAlertReview.alert_id == row.id,
            )
            .order_by(MonitoringAlertReview.revision.desc())
        )

    def _read_alert(
        self, row: MonitoringAlert, assessment: MonitoringAssessmentRead
    ) -> MonitoringAlertRead:
        if canonical_json_sha256(row.proposal_json) != row.proposal_sha256:
            raise ConflictError("Saved monitoring alert failed its proposal checksum")
        try:
            proposal = MonitoringFinding.model_validate(row.proposal_json)
        except InvalidStoredValue as exc:
            raise ConflictError("Saved monitoring alert is invalid") from exc
        if (
            row.kind != proposal.kind
            or row.finding_key != proposal.finding_key
            or proposal not in assessment.result.findings
        ):
            raise ConflictError("Saved alert differs from its immutable assessment")
        latest = self.session.scalar(self._review_query(row).limit(1))
        review = None if latest is None else self._read_review(latest)
        return MonitoringAlertRead(
            id=row.id,
            project_id=row.project_id,
            assessment_id=row.assessment_id,
            kind=proposal.kind,
            finding_key=proposal.finding_key,
            proposal=proposal,
            proposal_sha256=row.proposal_sha256,
            created_at=monitoring_utc(row.created_at),
            status=review.decision if review else "proposed",
            review_revision=review.revision if review else 0,
            latest_review=review,
            source_status=assessment.source_status,
        )

    def get_alert(self, project_id: str, alert_id: str) -> MonitoringAlertRead:
        row = self._owned(MonitoringAlert, project_id, alert_id, "alert")
        return self._read_alert(row, self.get_assessment(project_id, row.assessment_id))

    def list_alerts(
        self, project_id: str, *, assessment_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> MonitoringAlertPage:
        self._project(project_id)
        query = select(MonitoringAlert).where(MonitoringAlert.project_id == project_id)
        assessments: dict[str, MonitoringAssessmentRead] = {}
        if assessment_id is not None:
            assessments[assessment_id] = self.get_assessment(project_id, assessment_id)
            query = query.where(MonitoringAlert.assessment_id == assessment_id)
        rows, total = self._page(
            query.order_by(MonitoringAlert.created_at.desc(), MonitoringAlert.id),
            limit=limit,
            offset=offset,
        )
        items: list[MonitoringAlertRead] = []
        for row in rows:
            assessment = assessments.get(row.assessment_id)
            if assessment is None:
                assessment = self.get_assessment(project_id, row.assessment_id)
                assessments[row.assessment_id] = assessment
            items.append(self._read_alert(row, assessment))
        return MonitoringAlertPage(items=items, total=total, limit=limit, offset=offset)

    def list_reviews(
        self, project_id: str, alert_id: str, *, limit: int = 50, offset: int = 0
    ) -> MonitoringAlertReviewPage:
        alert = self._owned(MonitoringAlert, project_id, alert_id, "alert")
        rows, total = self._page(self._review_query(alert), limit=limit, offset=offset)
        return MonitoringAlertReviewPage(
            items=[self._read_review(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def review_alert(
        self, project_id: str, alert_id: str, payload: MonitoringAlertReviewCreate
    ) -> MonitoringAlertReviewRead:
        self._project(project_id, write=True)
        alert = self.get_alert(project_id, alert_id)
        if alert.source_status == "stale":
            raise ConflictError(
                "Monitoring evidence changed. Assess the current sources before review."
            )
        if payload.expected_revision != alert.review_revision:
            raise ConflictError("An alert review already changed. Reload the review history.")
        review = MonitoringAlertReview(
            project_id=project_id,
            alert_id=alert_id,
            reviewer=get_local_user_identity(self.settings),
            reason=payload.reason,
            decision=payload.decision,
            revision=alert.review_revision + 1,
        )
        self.session.add(review)
        self.session.flush()
        return self._read_review(review)
