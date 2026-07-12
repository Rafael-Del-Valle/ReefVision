"""Project and label-class persistence operations."""

from __future__ import annotations

import builtins
from typing import NamedTuple

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from reefvision.db.models import LabelClass, Project


class ProjectSummaryRow(NamedTuple):
    project: Project
    label_class_count: int
    active_label_class_count: int


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, include_archived: bool = False) -> builtins.list[Project]:
        statement = (
            select(Project).options(selectinload(Project.label_classes)).order_by(Project.name)
        )
        if not include_archived:
            statement = statement.where(Project.archived_at.is_(None))
        return builtins.list(self.session.scalars(statement).unique())

    def list_summaries(self, *, include_archived: bool = False) -> builtins.list[ProjectSummaryRow]:
        active_count = func.sum(case((LabelClass.is_active.is_(True), 1), else_=0))
        statement = (
            select(
                Project,
                func.count(LabelClass.id),
                func.coalesce(active_count, 0),
            )
            .outerjoin(LabelClass, LabelClass.project_id == Project.id)
            .group_by(Project.id)
            .order_by(Project.name)
        )
        if not include_archived:
            statement = statement.where(Project.archived_at.is_(None))
        rows = self.session.execute(statement).all()
        return [
            ProjectSummaryRow(
                project=project,
                label_class_count=int(label_class_count or 0),
                active_label_class_count=int(active_label_class_count or 0),
            )
            for project, label_class_count, active_label_class_count in rows
        ]

    def get(self, project_id: str) -> Project | None:
        statement = (
            select(Project)
            .options(selectinload(Project.label_classes))
            .where(Project.id == project_id)
        )
        return self.session.scalar(statement)

    def slug_exists(self, slug: str, *, exclude_project_id: str | None = None) -> bool:
        statement = select(Project.id).where(Project.slug == slug)
        if exclude_project_id:
            statement = statement.where(Project.id != exclude_project_id)
        return self.session.scalar(statement) is not None

    def add(self, project: Project) -> None:
        self.session.add(project)


class LabelClassRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_project(self, project_id: str) -> list[LabelClass]:
        statement = (
            select(LabelClass)
            .where(LabelClass.project_id == project_id)
            .order_by(LabelClass.display_order, LabelClass.class_index)
        )
        return list(self.session.scalars(statement))

    def get(self, class_id: str) -> LabelClass | None:
        return self.session.get(LabelClass, class_id)

    def add(self, label_class: LabelClass) -> None:
        self.session.add(label_class)

    def name_exists(
        self, project_id: str, name: str, *, exclude_class_id: str | None = None
    ) -> bool:
        statement = select(LabelClass.id).where(
            LabelClass.project_id == project_id, LabelClass.name == name
        )
        if exclude_class_id:
            statement = statement.where(LabelClass.id != exclude_class_id)
        return self.session.scalar(statement) is not None

    def index_exists(self, project_id: str, class_index: int) -> bool:
        statement = select(LabelClass.id).where(
            LabelClass.project_id == project_id, LabelClass.class_index == class_index
        )
        return self.session.scalar(statement) is not None

    def next_display_order(self, project_id: str) -> int:
        classes = self.list_for_project(project_id)
        return max((item.display_order for item in classes), default=-1) + 1
