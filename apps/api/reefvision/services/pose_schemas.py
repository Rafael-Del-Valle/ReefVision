"""Canonical project anatomy schema revision management."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import PoseLandmarkSchema, PoseLandmarkSchemaRevision, Project
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.schemas.pose_schemas import (
    AnatomyRevisionRequest,
    AnatomySchemaCreateRequest,
    AnatomySchemaDetailResponse,
    AnatomySchemaRevisionResponse,
)
from reefvision.storage.datasets import canonical_json_sha256

ANATOMY_SCHEMA_VERSION = "pose-anatomy-0002"


def _legacy_id(label: str, occurrence: int, total: int) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", label.casefold()).strip("_") or "landmark"
    if not slug[0].isalpha():
        slug = f"landmark_{slug}"
    return slug if total == 1 else f"{slug}_{occurrence + 1}"


def definition_for_revision(revision: PoseLandmarkSchemaRevision) -> dict[str, Any]:
    """Return a canonical definition without mutating legacy stored revisions."""

    if revision.definition_json is not None:
        return dict(revision.definition_json)
    totals = Counter(str(label) for label in revision.expanded_labels_json)
    seen: Counter[str] = Counter()
    landmarks: list[dict[str, Any]] = []
    for raw_label in revision.expanded_labels_json:
        label = str(raw_label)
        occurrence = seen[label]
        seen[label] += 1
        item: dict[str, Any] = {
            "id": _legacy_id(label, occurrence, totals[label]),
            "name": label,
            "required": True,
        }
        if totals[label] > 1:
            item["repeat_group"] = label
            item["repeat_index"] = occurrence
        landmarks.append(item)
    return {"schema_version": ANATOMY_SCHEMA_VERSION, "landmarks": landmarks, "edges": []}


class PoseSchemaService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _schema(self, schema_id: str) -> PoseLandmarkSchema:
        schema = self.session.get(PoseLandmarkSchema, schema_id)
        if schema is None:
            raise NotFoundError("Pose anatomy schema not found")
        return schema

    @staticmethod
    def _definition(payload: AnatomyRevisionRequest) -> dict[str, Any]:
        return {
            "schema_version": ANATOMY_SCHEMA_VERSION,
            "landmarks": [
                item.model_dump(mode="json", exclude_none=True) for item in payload.landmarks
            ],
            "edges": [item.model_dump(mode="json") for item in payload.edges],
        }

    @staticmethod
    def _projections(definition: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        landmarks = list(definition["landmarks"])
        labels = [str(item["name"]) for item in landmarks]
        counts = Counter(labels)
        groups: list[dict[str, Any]] = []
        for label in labels:
            if not any(item["name"] == label for item in groups):
                groups.append({"name": label, "count": counts[label]})
        return groups, labels

    def _response(
        self,
        schema: PoseLandmarkSchema,
        revision: PoseLandmarkSchemaRevision,
    ) -> AnatomySchemaRevisionResponse:
        legacy = revision.definition_json is None
        definition = definition_for_revision(revision)
        return AnatomySchemaRevisionResponse.model_validate(
            {
                "id": schema.id,
                "name": schema.name,
                "revision": revision.revision,
                "schema_version": definition.get("schema_version", ANATOMY_SCHEMA_VERSION),
                "landmarks": definition.get("landmarks", []),
                "edges": definition.get("edges", []),
                "groups": revision.groups_json,
                "expanded_labels": revision.expanded_labels_json,
                "keypoint_count": revision.keypoint_count,
                "allows_repeated_labels": revision.allows_repeated_labels,
                "content_hash": revision.content_hash,
                "legacy_projection": legacy,
                "created_at": revision.created_at,
            }
        )

    def _append_revision(
        self,
        schema: PoseLandmarkSchema,
        payload: AnatomyRevisionRequest,
    ) -> AnatomySchemaRevisionResponse:
        definition = self._definition(payload)
        groups, labels = self._projections(definition)
        content_hash = canonical_json_sha256(definition)
        latest = self.session.scalar(
            select(func.max(PoseLandmarkSchemaRevision.revision)).where(
                PoseLandmarkSchemaRevision.schema_id == schema.id
            )
        )
        revision = PoseLandmarkSchemaRevision(
            schema_id=schema.id,
            revision=int(latest or 0) + 1,
            schema_version=ANATOMY_SCHEMA_VERSION,
            groups_json=groups,
            expanded_labels_json=labels,
            keypoint_count=len(labels),
            allows_repeated_labels=len(labels) != len(set(labels)),
            definition_json=definition,
            content_hash=content_hash,
        )
        self.session.add(revision)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("This anatomy schema revision already exists") from exc
        self.session.refresh(revision)
        return self._response(schema, revision)

    def create(
        self,
        project_id: str,
        payload: AnatomySchemaCreateRequest,
    ) -> AnatomySchemaRevisionResponse:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        schema = PoseLandmarkSchema(project_id=project_id, name=payload.name)
        self.session.add(schema)
        self.session.flush()
        try:
            return self._append_revision(schema, payload)
        except Exception:
            self.session.rollback()
            raise

    def append_revision(
        self,
        schema_id: str,
        payload: AnatomyRevisionRequest,
    ) -> AnatomySchemaRevisionResponse:
        return self._append_revision(self._schema(schema_id), payload)

    def list_project(self, project_id: str) -> list[AnatomySchemaRevisionResponse]:
        rows = self.session.execute(
            select(PoseLandmarkSchema, PoseLandmarkSchemaRevision)
            .join(
                PoseLandmarkSchemaRevision,
                PoseLandmarkSchemaRevision.schema_id == PoseLandmarkSchema.id,
            )
            .where(PoseLandmarkSchema.project_id == project_id)
            .order_by(
                PoseLandmarkSchema.created_at,
                PoseLandmarkSchemaRevision.revision.desc(),
            )
        ).all()
        latest: dict[str, AnatomySchemaRevisionResponse] = {}
        for schema, revision in rows:
            latest.setdefault(schema.id, self._response(schema, revision))
        return list(latest.values())

    def detail(self, schema_id: str) -> AnatomySchemaDetailResponse:
        schema = self._schema(schema_id)
        revisions = list(
            self.session.scalars(
                select(PoseLandmarkSchemaRevision)
                .where(PoseLandmarkSchemaRevision.schema_id == schema.id)
                .order_by(PoseLandmarkSchemaRevision.revision.desc())
            )
        )
        return AnatomySchemaDetailResponse(
            id=schema.id,
            project_id=schema.project_id,
            name=schema.name,
            revisions=[self._response(schema, item) for item in revisions],
        )
