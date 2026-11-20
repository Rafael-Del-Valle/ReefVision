"""Independent Reviewer Lab decisions and immutable, typed agreement reports."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import cached_property
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.image import ImageAsset
from reefvision.db.models.project_exchange_package import ProjectExchangePackage
from reefvision.db.models.review_queue_item import ReviewQueueItem
from reefvision.db.models.reviewer_lab_v15 import (
    ReviewerLabDecisionRecord,
    ReviewerLabReportRecord,
    ReviewerLabRoundRecord,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.reviewer_lab_v15 import (
    VALUES,
    ReviewerLabAdjudication,
    ReviewerLabAgreement,
    ReviewerLabDecision,
    ReviewerLabJudgement,
    ReviewerLabPlan,
    ReviewerLabReport,
    ReviewerLabReportBody,
    ReviewerLabReportSubject,
    ReviewerLabReportSummary,
    ReviewerLabRole,
    ReviewerLabRound,
    ReviewerLabRoundCreate,
    ReviewerLabSource,
    ReviewerLabSubject,
    ReviewerLabSubjectView,
    ReviewSlot,
)
from reefvision.services.review_queue_exchange_checksums import (
    matches_pinned_queue_item,
    queue_item_snapshot,
)
from reefvision.services.reviewer_lab_roles_v15 import ReviewerLabRoles
from reefvision.storage.datasets import canonical_json_sha256


def reviewer_lab_report_sha256(body: Mapping[str, Any]) -> str:
    """A portable digest of the exact original report body, excluding its digest field."""
    return canonical_json_sha256({key: val for key, val in body.items() if key != "content_sha256"})


def reviewer_lab_agreement(subjects: list[ReviewerLabReportSubject]) -> ReviewerLabAgreement:
    matrix = {first: dict.fromkeys(VALUES, 0) for first in VALUES}
    for item in subjects:
        matrix[item.first.value][item.second.value] += 1
    paired = len(subjects)
    agreements = sum(matrix[value][value] for value in VALUES)
    # Use integer marginals so a degenerate one-category denominator is exactly zero.
    expected_count = sum(
        sum(matrix[value].values()) * sum(matrix[row][value] for row in VALUES) for value in VALUES
    )
    denominator = paired * paired - expected_count
    return ReviewerLabAgreement(
        planned_subjects=paired,
        paired_subjects=paired,
        agreements=agreements,
        disagreements=paired - agreements,
        adjudicated_disagreements=sum(item.resolution is not None for item in subjects),
        matrix=matrix,
        observed_agreement=agreements / paired,
        cohens_kappa=(agreements * paired - expected_count) / denominator if denominator else None,
    )


class ReviewerLabService:
    def __init__(self, session: Session, project_id: str) -> None:
        self.session = session
        self.project_id = project_id
        self.roles = ReviewerLabRoles(session, project_id)

    @cached_property
    def _origin_ids(self) -> dict[str, str]:
        package = self.session.scalar(
            select(ProjectExchangePackage)
            .where(
                ProjectExchangePackage.project_id == self.project_id,
                ProjectExchangePackage.direction == "import",
                ProjectExchangePackage.status == "complete",
            )
            .order_by(ProjectExchangePackage.created_at.desc(), ProjectExchangePackage.id)
            .limit(1)
        )
        if package is None:
            return {}
        values = (package.options_json or {}).get("origin_id_map", {})
        return dict(values) if isinstance(values, dict) else {}

    def _live_id(self, identifier: str) -> str:
        return self._origin_ids.get(identifier, identifier)

    def _image(self, image_id: str) -> ImageAsset:
        row = self.session.get(ImageAsset, image_id)
        if row is None or row.project_id != self.project_id:
            raise NotFoundError("Review source image does not belong to this project")
        return row

    def _queue_item(self, item_id: str) -> ReviewQueueItem:
        item = self.session.get(ReviewQueueItem, item_id)
        if item is None or item.project_id != self.project_id:
            raise NotFoundError("Review queue item does not belong to this project")
        return item

    def _snapshot(self, source: ReviewerLabSource) -> ReviewerLabSubject:
        item = self._queue_item(str(source.id)) if source.type == "queue_item" else None
        image = self._image(item.image_id if item else str(source.id))
        return ReviewerLabSubject(
            id=str(uuid4()),
            image_id=image.id,
            filename=image.original_filename,
            source_sha256=image.sha256,
            annotation_revision=image.annotation_revision,
            queue_id=item.review_queue_id if item else None,
            queue_item_id=item.id if item else None,
            queue_input_sha256=item.input_checksum if item else None,
        )

    def _current_source(self, subject: ReviewerLabSubject) -> ImageAsset:
        try:
            image = self._image(self._live_id(subject.image_id))
            item = (
                self._queue_item(self._live_id(subject.queue_item_id))
                if subject.queue_item_id
                else None
            )
        except NotFoundError as exc:
            raise ConflictError("A pinned review source is unavailable") from exc
        if (
            image.sha256 != subject.source_sha256
            or image.annotation_revision != subject.annotation_revision
        ):
            raise ConflictError("A pinned source changed. Start a new independent review round.")
        if item and (
            item.review_queue_id != self._live_id(subject.queue_id or "")
            or item.image_id != image.id
            or not matches_pinned_queue_item(
                item.review_queue.configuration_json,
                queue_item_snapshot(item),
                subject.queue_input_sha256,
            )
        ):
            raise ConflictError("A pinned review queue item changed. Start a new review round.")
        return image

    def _plan(self, record: ReviewerLabRoundRecord) -> ReviewerLabPlan:
        if canonical_json_sha256(record.plan_json) != record.plan_sha256:
            raise ConflictError("Stored Reviewer Lab plan checksum does not match")
        return ReviewerLabPlan.model_validate(record.plan_json)

    def _round(self, round_id: str) -> ReviewerLabRoundRecord:
        row = self.session.get(ReviewerLabRoundRecord, round_id)
        if row is None or row.project_id != self.project_id:
            raise NotFoundError("Independent review round not found")
        return row

    def _report_for_round(self, round_id: str) -> ReviewerLabReportRecord | None:
        return self.session.scalar(
            select(ReviewerLabReportRecord).where(
                ReviewerLabReportRecord.round_id == round_id,
                ReviewerLabReportRecord.project_id == self.project_id,
            )
        )

    def _slot(self, plan: ReviewerLabPlan, actor: ReviewerLabRole) -> ReviewSlot | None:
        if actor.role == "manager":
            return None
        for role, slot in zip(plan.reviewers, ("first", "second"), strict=True):
            if actor.role == "reviewer" and actor.member_id == self._live_id(role.member_id):
                return "first" if slot == "first" else "second"
        if actor.role == "adjudicator" and actor.member_id == self._live_id(
            plan.adjudicator.member_id
        ):
            return "adjudication"
        raise NotFoundError("Independent review round not found")

    def _subject(self, plan: ReviewerLabPlan, subject_id: str) -> ReviewerLabSubject:
        subject = next(
            (item for item in plan.subjects if self._live_id(item.id) == subject_id), None
        )
        if subject is None:
            raise NotFoundError("Independent review subject not found")
        return subject

    def _decisions(self, round_id: str) -> dict[str, dict[str, ReviewerLabDecisionRecord]]:
        decisions: dict[str, dict[str, ReviewerLabDecisionRecord]] = defaultdict(dict)
        for row in self.session.scalars(
            select(ReviewerLabDecisionRecord).where(ReviewerLabDecisionRecord.round_id == round_id)
        ):
            decisions[row.subject_id][row.slot] = row
        return decisions

    def create_round(
        self, actor: ReviewerLabRole, payload: ReviewerLabRoundCreate
    ) -> ReviewerLabRound:
        request_sha256 = canonical_json_sha256(payload.model_dump(mode="json"))
        prior = self.session.scalar(
            select(ReviewerLabRoundRecord).where(
                ReviewerLabRoundRecord.project_id == self.project_id,
                ReviewerLabRoundRecord.operation_id == str(payload.operation_id),
            )
        )
        if prior:
            if prior.request_sha256 != request_sha256:
                raise ConflictError("This round operation was already used with different inputs")
            return self.view(prior.id, actor)

        first, second = (self.roles.current(str(member)) for member in payload.reviewer_member_ids)
        adjudicator = self.roles.current(str(payload.adjudicator_member_id))
        if any(
            role.role != "reviewer" or not self.roles.has_access(role) for role in (first, second)
        ):
            raise ValidationError("Both assigned reviewers must hold active local reviewer roles")
        if adjudicator.role != "adjudicator" or not self.roles.has_access(adjudicator):
            raise ValidationError("Assign a separate active local adjudicator")
        targets = [self._snapshot(item) for item in payload.sources]
        if len({item.image_id for item in targets}) != len(targets):
            raise ValidationError("Select each original source image once per round")
        plan = ReviewerLabPlan(
            title=payload.title,
            criterion=payload.criterion,
            manager=actor,
            reviewers=(first, second),
            adjudicator=adjudicator,
            subjects=targets,
        ).model_dump(mode="json")
        row = ReviewerLabRoundRecord(
            id=str(uuid4()),
            project_id=self.project_id,
            operation_id=str(payload.operation_id),
            request_sha256=request_sha256,
            plan_json=plan,
            plan_sha256=canonical_json_sha256(plan),
        )
        self.session.add(row)
        self.session.commit()
        return self.view(row.id, actor)

    def _view_record(
        self,
        record: ReviewerLabRoundRecord,
        actor: ReviewerLabRole,
        *,
        include_subjects: bool = True,
    ) -> ReviewerLabRound:
        plan = self._plan(record)
        slot = self._slot(plan, actor)
        report = self._report_for_round(record.id)
        subjects: list[ReviewerLabSubjectView] = []
        if include_subjects:
            decisions = self._decisions(record.id)
            for subject in plan.subjects:
                live_subject_id = self._live_id(subject.id)
                rows = decisions.get(live_subject_id, {})
                first, second, resolution = (
                    rows.get(key) for key in ("first", "second", "adjudication")
                )
                complete = bool(first and second and (first.value == second.value or resolution))
                view = ReviewerLabSubjectView(
                    **{
                        **subject.model_dump(),
                        "id": live_subject_id,
                        "image_id": self._live_id(subject.image_id),
                        "queue_id": self._live_id(subject.queue_id) if subject.queue_id else None,
                        "queue_item_id": self._live_id(subject.queue_item_id)
                        if subject.queue_item_id
                        else None,
                    }
                )
                if slot in ("first", "second") and (decision := rows.get(slot)):
                    view.own_decision = ReviewerLabDecision.model_validate(decision)
                if slot == "adjudication" and first and second:
                    view.paired_decisions = (
                        ReviewerLabDecision.model_validate(first),
                        ReviewerLabDecision.model_validate(second),
                    )
                    if resolution:
                        view.resolution = ReviewerLabDecision.model_validate(resolution)
                if slot in (None, "adjudication"):
                    view.complete = complete
                subjects.append(view)
        return ReviewerLabRound(
            id=record.id,
            title=plan.title,
            criterion=plan.criterion,
            plan_sha256=record.plan_sha256,
            report_id=report.id if report else None,
            subjects=subjects,
        )

    def view(self, round_id: str, actor: ReviewerLabRole) -> ReviewerLabRound:
        return self._view_record(self._round(round_id), actor)

    def rounds(self, actor: ReviewerLabRole) -> list[ReviewerLabRound]:
        rows = self.session.scalars(
            select(ReviewerLabRoundRecord)
            .where(ReviewerLabRoundRecord.project_id == self.project_id)
            .order_by(ReviewerLabRoundRecord.created_at.desc(), ReviewerLabRoundRecord.id)
        )
        views = []
        for row in rows:
            try:
                views.append(self._view_record(row, actor, include_subjects=False))
            except NotFoundError:
                continue
        return views

    def image(self, round_id: str, subject_id: str, actor: ReviewerLabRole) -> ImageAsset:
        plan = self._plan(self._round(round_id))
        self._slot(plan, actor)
        return self._current_source(self._subject(plan, subject_id))

    def submit(
        self,
        round_id: str,
        subject_id: str,
        actor: ReviewerLabRole,
        payload: ReviewerLabJudgement | ReviewerLabAdjudication,
    ) -> ReviewerLabDecision:
        row = self._round(round_id)
        plan = self._plan(row)
        slot = self._slot(plan, actor)
        subject = self._subject(plan, subject_id)
        if slot is None or isinstance(payload, ReviewerLabAdjudication) != (slot == "adjudication"):
            raise ValidationError("The local role cannot make a decision in this slot")
        if payload.plan_sha256 != row.plan_sha256:
            raise ConflictError("The review plan changed. Reopen it before submitting a decision.")
        request_sha256 = canonical_json_sha256(payload.model_dump(mode="json"))
        operation_id = str(payload.operation_id)
        prior = self.session.scalar(
            select(ReviewerLabDecisionRecord).where(
                ReviewerLabDecisionRecord.round_id == round_id,
                ReviewerLabDecisionRecord.operation_id == operation_id,
            )
        )
        if prior:
            if (prior.role_revision_id, prior.subject_id, prior.slot, prior.request_sha256) == (
                actor.id,
                subject_id,
                slot,
                request_sha256,
            ):
                return ReviewerLabDecision.model_validate(prior)
            raise ConflictError("This decision operation is already in use")
        if self._report_for_round(round_id):
            raise ConflictError("This review round is sealed")
        rows = self._decisions(round_id).get(subject_id, {})
        if slot in rows:
            raise ConflictError("This independent review slot has already been committed")
        self._current_source(subject)
        decision_ids = None
        if isinstance(payload, ReviewerLabAdjudication):
            first, second = rows.get("first"), rows.get("second")
            if not first or not second or first.value == second.value:
                raise ConflictError("Adjudication requires two committed, disagreeing reviews")
            decision_ids = [str(id_) for id_ in payload.decision_ids]
            if decision_ids != [first.id, second.id]:
                raise ConflictError(
                    "Adjudication must refer to the displayed independent decisions"
                )
        decision = ReviewerLabDecisionRecord(
            id=str(uuid4()),
            round_id=round_id,
            subject_id=subject_id,
            role_revision_id=actor.id,
            operation_id=operation_id,
            request_sha256=request_sha256,
            slot=slot,
            value=payload.value,
            reason=payload.reason,
            decision_ids_json=decision_ids,
        )
        self.session.add(decision)
        self.session.commit()
        return ReviewerLabDecision.model_validate(decision)

    def seal(self, round_id: str, actor: ReviewerLabRole) -> ReviewerLabReport:
        row = self._round(round_id)
        if prior := self._report_for_round(round_id):
            return self._read_report(prior)
        plan = self._plan(row)
        per_subject = self._decisions(row.id)
        subjects: list[ReviewerLabReportSubject] = []
        role_ids = set()
        for source in plan.subjects:
            self._current_source(source)
            entries = per_subject.get(self._live_id(source.id), {})
            first, second, resolution = (
                entries.get(slot) for slot in ("first", "second", "adjudication")
            )
            if not first or not second or (first.value != second.value and not resolution):
                raise ConflictError(
                    "Complete all paired reviews and resolve each disagreement before sealing"
                )
            for decision in entries.values():
                role_ids.add(decision.role_revision_id)
            subjects.append(
                ReviewerLabReportSubject(
                    source=source,
                    first=ReviewerLabDecision.model_validate(first),
                    second=ReviewerLabDecision.model_validate(second),
                    resolution=ReviewerLabDecision.model_validate(resolution)
                    if resolution
                    else None,
                )
            )
        body = ReviewerLabReportBody(
            id=str(uuid4()),
            project_id=self.project_id,
            round_id=row.id,
            plan_sha256=row.plan_sha256,
            plan=plan,
            sealed_at=datetime.now(UTC),
            sealed_by_role_revision_id=actor.id,
            role_revisions=[self.roles.version(item) for item in sorted(role_ids | {actor.id})],
            agreement=reviewer_lab_agreement(subjects),
            subjects=subjects,
        ).model_dump(mode="json")
        report = ReviewerLabReportRecord(
            id=body["id"],
            project_id=self.project_id,
            round_id=row.id,
            content_json=body,
            content_sha256=reviewer_lab_report_sha256(body),
        )
        self.session.add(report)
        self.session.commit()
        return self._read_report(report)

    @staticmethod
    def _read_report(report: ReviewerLabReportRecord) -> ReviewerLabReport:
        if reviewer_lab_report_sha256(report.content_json) != report.content_sha256:
            raise ConflictError("Stored Reviewer Lab report checksum does not match")
        return ReviewerLabReport.model_validate(
            {**report.content_json, "content_sha256": report.content_sha256}
        )

    def report(self, report_id: str) -> ReviewerLabReport:
        report = self.session.get(ReviewerLabReportRecord, report_id)
        if report is None or report.project_id != self.project_id:
            raise NotFoundError("Sealed Reviewer Lab report not found")
        return self._read_report(report)

    def reports(self) -> list[ReviewerLabReportSummary]:
        rows = self.session.scalars(
            select(ReviewerLabReportRecord)
            .where(ReviewerLabReportRecord.project_id == self.project_id)
            .order_by(ReviewerLabReportRecord.id)
        )
        return [
            ReviewerLabReportSummary(id=row.id, title=self._read_report(row).plan.title)
            for row in rows
        ]
