"""Access control for local, project-scoped Reviewer Lab roles."""

import re
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.project import Project
from reefvision.db.models.reviewer_lab_v15 import (
    ReviewerLabCredential,
    ReviewerLabMember,
    ReviewerLabRoleRevision,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabRole, ReviewerLabRoleChange, ReviewRole


class ReviewerLabRoles:
    def __init__(self, session: Session, project_id: str) -> None:
        self.session = session
        self.project_id = project_id

    def _manager_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"reefvision:reviewer-lab:{self.project_id}"))

    def ensure_project(self, *, write: bool = False) -> None:
        query = select(Project.id).where(Project.id == self.project_id)
        if write:
            connection = self.session.connection()
            if connection.dialect.name == "sqlite":
                # Acquire the writer reservation before reading authorization or source revisions.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                query = query.with_for_update()
        if self.session.scalar(query) is None:
            raise NotFoundError("Project not found")

    def initialized(self) -> bool:
        self.ensure_project()
        return self.session.get(ReviewerLabMember, self._manager_id()) is not None

    @staticmethod
    def _fingerprint(key: str | None) -> str | None:
        if key is None or re.fullmatch("[a-f0-9]{64}", key) is None:
            return None
        return sha256(key.encode("ascii")).hexdigest()

    @classmethod
    def _new_fingerprint(cls, key: str | None) -> str:
        fingerprint = cls._fingerprint(key)
        if fingerprint is None:
            raise ValidationError("A new 32-byte local role key is required")
        return fingerprint

    @staticmethod
    def _public(member: ReviewerLabMember, revision: ReviewerLabRoleRevision) -> ReviewerLabRole:
        return ReviewerLabRole.model_validate(
            {
                "id": revision.id,
                "member_id": member.id,
                "name": member.name,
                "role": member.role,
                "revision": revision.revision,
                "active": revision.active,
                "previous_revision_id": revision.previous_revision_id,
                "granted_by_role_revision_id": revision.granted_by_role_revision_id,
                "created_at": revision.created_at,
            }
        )

    def _member(self, member_id: str) -> ReviewerLabMember:
        member = self.session.get(ReviewerLabMember, member_id)
        if member is None or member.project_id != self.project_id:
            raise NotFoundError("Local reviewer role not found")
        return member

    def _latest(self, member_id: str) -> ReviewerLabRoleRevision:
        revision = self.session.scalar(
            select(ReviewerLabRoleRevision)
            .where(ReviewerLabRoleRevision.member_id == member_id)
            .order_by(ReviewerLabRoleRevision.revision.desc())
            .limit(1)
        )
        if revision is None:
            raise ConflictError("Local reviewer role history is incomplete")
        return revision

    def authenticate(self, key: str | None) -> ReviewerLabRole | None:
        fingerprint = self._fingerprint(key)
        if fingerprint is None:
            return None
        row = self.session.execute(
            select(ReviewerLabMember, ReviewerLabRoleRevision)
            .join(
                ReviewerLabRoleRevision, ReviewerLabRoleRevision.member_id == ReviewerLabMember.id
            )
            .join(ReviewerLabCredential)
            .where(
                ReviewerLabMember.project_id == self.project_id,
                ReviewerLabCredential.credential_sha256 == fingerprint,
                ReviewerLabRoleRevision.active.is_(True),
            )
        ).one_or_none()
        if row is None:
            return None
        member, revision = row
        return self._public(member, revision) if self._latest(member.id).id == revision.id else None

    def current(self, member_id: str) -> ReviewerLabRole:
        return self._public(self._member(member_id), self._latest(member_id))

    def version(self, revision_id: str) -> ReviewerLabRole:
        revision = self.session.get(ReviewerLabRoleRevision, revision_id)
        if revision is None:
            raise NotFoundError("Local reviewer role revision not found")
        return self._public(self._member(revision.member_id), revision)

    def list(self) -> list[ReviewerLabRole]:
        members = self.session.scalars(
            select(ReviewerLabMember)
            .where(ReviewerLabMember.project_id == self.project_id)
            .order_by(ReviewerLabMember.name_key)
        )
        return [self._public(member, self._latest(member.id)) for member in members]

    def _append(
        self,
        member: ReviewerLabMember,
        fingerprint: str | None,
        *,
        previous: ReviewerLabRoleRevision | None,
        granted_by: str | None,
    ) -> ReviewerLabRole:
        if fingerprint and self.session.scalar(
            select(ReviewerLabCredential).where(
                ReviewerLabCredential.credential_sha256 == fingerprint
            )
        ):
            raise ConflictError("Use a fresh key for this role revision")
        revision = ReviewerLabRoleRevision(
            id=str(uuid4()),
            member_id=member.id,
            revision=previous.revision + 1 if previous else 1,
            active=fingerprint is not None,
            previous_revision_id=previous.id if previous else None,
            granted_by_role_revision_id=granted_by,
        )
        try:
            self.session.flush()
            self.session.add(revision)
            self.session.flush()
            if fingerprint:
                self.session.add(
                    ReviewerLabCredential(
                        role_revision_id=revision.id, credential_sha256=fingerprint
                    )
                )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "Local reviewer role changed concurrently or the key is already registered"
            ) from exc
        return self._public(member, revision)

    def initialize(self, name: str, key: str | None) -> ReviewerLabRole:
        self.ensure_project(write=True)
        fingerprint = self._new_fingerprint(key)
        manager = self.session.get(ReviewerLabMember, self._manager_id())
        if manager is not None:
            actor = self.authenticate(key)
            if actor and actor.member_id == manager.id and manager.name == name:
                return actor
            raise ConflictError("A local manager has already been established")
        manager = ReviewerLabMember(
            id=self._manager_id(),
            project_id=self.project_id,
            name=name,
            name_key=name.casefold(),
            role="manager",
        )
        self.session.add(manager)
        return self._append(manager, fingerprint, previous=None, granted_by=None)

    def add(
        self, name: str, role: ReviewRole, key: str | None, manager: ReviewerLabRole
    ) -> ReviewerLabRole:
        fingerprint = self._new_fingerprint(key)
        name_key = name.casefold()
        existing = self.session.scalar(
            select(ReviewerLabMember).where(
                ReviewerLabMember.project_id == self.project_id,
                ReviewerLabMember.name_key == name_key,
            )
        )
        if existing is not None:
            actor = self.authenticate(key)
            if (
                actor
                and actor.member_id == existing.id
                and actor.name == name
                and actor.role == role
            ):
                return actor
            raise ConflictError("This local participant name is already registered")
        member = ReviewerLabMember(
            id=str(uuid4()), project_id=self.project_id, name=name, name_key=name_key, role=role
        )
        self.session.add(member)
        return self._append(member, fingerprint, previous=None, granted_by=manager.id)

    def revise(
        self,
        member_id: str,
        change: ReviewerLabRoleChange,
        key: str | None,
        manager: ReviewerLabRole,
    ) -> ReviewerLabRole:
        member = self._member(member_id)
        prior = self._latest(member_id)
        if member.role == "manager":
            raise ValidationError("The initial local manager cannot be revoked here")
        fingerprint = self._new_fingerprint(key) if change.active else None
        if str(change.base_revision_id) != prior.id:
            if (
                prior.previous_revision_id == str(change.base_revision_id)
                and prior.active == change.active
            ):
                saved_key = self.session.get(ReviewerLabCredential, prior.id)
                if (saved_key.credential_sha256 if saved_key else None) == fingerprint:
                    return self._public(member, prior)
            raise ConflictError("Local role revision changed. Reload it before making a change.")
        return self._append(member, fingerprint, previous=prior, granted_by=manager.id)
