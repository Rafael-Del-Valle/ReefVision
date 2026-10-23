"""Versioned ecological identities; never promote registry metadata to verified data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.project import Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_identity import (
    EcologyIdentityCreate,
    EcologyIdentityFields,
    EcologyIdentityRegistryResponse,
    EcologyIdentityRevisionCreate,
    EcologyIdentityRow,
)
from reefvision.storage.datasets import canonical_json_sha256


class EcologyIdentityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def _latest(self, project_id: str) -> dict[str, EcologyIdentityRevision]:
        records = self.session.scalars(
            select(EcologyIdentityRevision)
            .where(EcologyIdentityRevision.project_id == project_id)
            .order_by(
                EcologyIdentityRevision.organism_key,
                EcologyIdentityRevision.revision.desc(),
            )
        )
        latest: dict[str, EcologyIdentityRevision] = {}
        for record in records:
            latest.setdefault(record.organism_key, record)
        return latest

    @staticmethod
    def _parent_valid(
        key: str,
        payload: EcologyIdentityFields,
        latest: dict[str, EcologyIdentityRevision],
    ) -> None:
        parent_key = payload.parent_colony_key
        if parent_key is None:
            return
        if parent_key == key:
            raise ValidationError("An organism cannot be its own parent colony")
        parent = latest.get(parent_key)
        if parent is None or parent.kind != "colony":
            raise ValidationError("Parent colony must be registered in the same project")

    def _append(
        self,
        project_id: str,
        key: str,
        revision: int,
        payload: EcologyIdentityFields,
    ) -> EcologyIdentityRow:
        record = EcologyIdentityRevision(
            project_id=project_id,
            organism_key=key,
            revision=revision,
            kind=payload.kind,
            parent_colony_key=payload.parent_colony_key,
            experimental_unit_type=payload.experimental_unit_type,
            experimental_unit_id=payload.experimental_unit_id,
            reason=payload.reason,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Concurrent or duplicate ecological identity revision") from exc
        self.session.refresh(record)
        return EcologyIdentityRow.model_validate(record)

    def register(self, project_id: str, payload: EcologyIdentityCreate) -> EcologyIdentityRow:
        self._project(project_id)
        latest = self._latest(project_id)
        if payload.organism_key in latest:
            raise ConflictError("Organism key already registered in this project")
        self._parent_valid(payload.organism_key, payload, latest)
        return self._append(project_id, payload.organism_key, 1, payload)

    def revise(
        self,
        project_id: str,
        organism_key: str,
        payload: EcologyIdentityRevisionCreate,
    ) -> EcologyIdentityRow:
        self._project(project_id)
        latest = self._latest(project_id)
        current = latest.get(organism_key)
        if current is None:
            raise NotFoundError("Ecological organism not found in project")
        if current.revision != payload.expected_revision:
            raise ConflictError("Stale organism revision; reload before changing identity")
        self._parent_valid(organism_key, payload, latest)
        return self._append(project_id, organism_key, current.revision + 1, payload)

    def registry(self, project_id: str) -> EcologyIdentityRegistryResponse:
        self._project(project_id)
        latest = self._latest(project_id)
        identities = [
            EcologyIdentityRow.model_validate(record)
            for _, record in sorted(latest.items())
        ]
        fingerprint_rows = [
            {
                "id": row.id,
                "organism_key": row.organism_key,
                "revision": row.revision,
                "kind": row.kind,
                "parent_colony_key": row.parent_colony_key,
                "experimental_unit_type": row.experimental_unit_type,
                "experimental_unit_id": row.experimental_unit_id,
            }
            for row in identities
        ]
        return EcologyIdentityRegistryResponse(
            project_id=project_id,
            identities=identities,
            snapshot_sha256=canonical_json_sha256(
                {"schema_version": "ecology-identity-registry-0001",
                 "project_id": project_id, "identities": fingerprint_rows}
            ),
        )
