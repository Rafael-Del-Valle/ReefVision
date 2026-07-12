"""Persistence helpers for quality-control runs and issues."""

from __future__ import annotations

from math import ceil

from sqlalchemy import desc, exists, func, select
from sqlalchemy.orm import Session

from reefvision.db.models import QualityControlIssue, QualityControlRun


class QualityControlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_run(self, run: QualityControlRun) -> None:
        self.session.add(run)

    def add_issue(self, issue: QualityControlIssue) -> None:
        self.session.add(issue)

    def add_issues(self, issues: list[QualityControlIssue]) -> None:
        self.session.add_all(issues)

    def get_run(self, run_id: str) -> QualityControlRun | None:
        return self.session.get(QualityControlRun, run_id)

    def get_run_by_job_id(self, job_id: str) -> QualityControlRun | None:
        statement = select(QualityControlRun).where(QualityControlRun.job_id == job_id)
        return self.session.scalar(statement)

    def list_runs(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None = None,
    ) -> list[QualityControlRun]:
        filters = [QualityControlRun.project_id == project_id]
        if dataset_version_id is None:
            filters.append(QualityControlRun.dataset_version_id.is_(None))
        else:
            filters.append(QualityControlRun.dataset_version_id == dataset_version_id)
        statement = (
            select(QualityControlRun)
            .where(*filters)
            .order_by(desc(QualityControlRun.created_at), desc(QualityControlRun.id))
        )
        return list(self.session.scalars(statement))

    def latest_complete_run(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None,
        exclude_run_id: str | None = None,
    ) -> QualityControlRun | None:
        filters = [
            QualityControlRun.project_id == project_id,
            QualityControlRun.status == "succeeded",
        ]
        if dataset_version_id is None:
            filters.append(QualityControlRun.dataset_version_id.is_(None))
        else:
            filters.append(QualityControlRun.dataset_version_id == dataset_version_id)
        if exclude_run_id is not None:
            filters.append(QualityControlRun.id != exclude_run_id)
        statement = (
            select(QualityControlRun)
            .where(*filters)
            .order_by(desc(QualityControlRun.completed_at), desc(QualityControlRun.created_at))
            .limit(1)
        )
        return self.session.scalar(statement)

    def issues_for_run(self, run_id: str) -> list[QualityControlIssue]:
        statement = (
            select(QualityControlIssue)
            .where(QualityControlIssue.quality_control_run_id == run_id)
            .order_by(
                QualityControlIssue.severity,
                QualityControlIssue.rule_id,
                QualityControlIssue.created_at,
                QualityControlIssue.id,
            )
        )
        return list(self.session.scalars(statement))

    def get_issue(self, issue_id: str) -> QualityControlIssue | None:
        return self.session.get(QualityControlIssue, issue_id)

    def latest_openish_issues_for_scope(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None,
    ) -> list[QualityControlIssue]:
        statement = (
            select(QualityControlIssue)
            .join(
                QualityControlRun,
                QualityControlRun.id == QualityControlIssue.quality_control_run_id,
            )
            .where(
                QualityControlRun.project_id == project_id,
                QualityControlRun.status == "succeeded",
                QualityControlIssue.status.in_(("open", "acknowledged")),
            )
            .order_by(desc(QualityControlRun.completed_at), QualityControlIssue.created_at)
        )
        if dataset_version_id is None:
            statement = statement.where(QualityControlRun.dataset_version_id.is_(None))
        else:
            statement = statement.where(QualityControlRun.dataset_version_id == dataset_version_id)
        return list(self.session.scalars(statement))

    def paged_issues(
        self,
        run_id: str,
        *,
        page: int,
        page_size: int,
        severity: str | None,
        rule_id: str | None,
        class_id: str | None,
        image_id: str | None,
        status: str | None,
    ) -> tuple[list[QualityControlIssue], int, int]:
        filters = [QualityControlIssue.quality_control_run_id == run_id]
        if severity is not None:
            filters.append(QualityControlIssue.severity == severity)
        if rule_id is not None:
            filters.append(QualityControlIssue.rule_id == rule_id)
        if image_id is not None:
            filters.append(QualityControlIssue.image_id == image_id)
        if status is not None:
            filters.append(QualityControlIssue.status == status)
        if class_id is not None:
            class_values = func.json_each(QualityControlIssue.class_ids_json).table_valued(
                "value"
            )
            filters.append(
                exists(
                    select(1)
                    .select_from(class_values)
                    .where(class_values.c.value == class_id)
                )
            )
        base_statement = select(QualityControlIssue).where(*filters)
        total = int(
            self.session.scalar(
                select(func.count()).select_from(base_statement.subquery())
            )
            or 0
        )
        pages = max(1, ceil(total / page_size)) if total else 1
        start = (page - 1) * page_size
        end = start + page_size
        page_statement = (
            base_statement.order_by(
                QualityControlIssue.severity,
                QualityControlIssue.rule_id,
                QualityControlIssue.created_at,
                QualityControlIssue.id,
            )
            .offset(start)
            .limit(max(end - start, 0))
        )
        return list(self.session.scalars(page_statement)), total, pages
