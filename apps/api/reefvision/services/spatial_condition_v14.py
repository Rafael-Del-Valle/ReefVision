"""Record and retrieve attributed condition evidence from project-owned originals."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from itertools import pairwise
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.spatial_asset_metadata_revision_v14 import SpatialAssetMetadataRevision
from reefvision.db.models.spatial_condition_v14 import (
    SpatialConditionRevision,
    SpatialConditionRubric,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.spatial_condition_v14 import (
    ConditionDecision,
    ConditionObservation,
    ConditionReport,
    ConditionRevision,
    Phase,
)
from reefvision.services.spatial_asset_metadata_revisions_v14 import (
    SpatialAssetMetadataRevisionService,
)
from reefvision.services.spatial_source_assets_v14 import SpatialSourceAssetService
from reefvision.storage.datasets import canonical_json_sha256

CONDITION_CONTENT_FIELDS = (
    "id",
    "project_id",
    "asset_id",
    "observation_id",
    "previous_revision_id",
    "phase",
    "observation_json",
    "decision_json",
)


def condition_content_sha256(row: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "schema_version": "reefvision-condition-revision-1",
            **{name: row[name] for name in CONDITION_CONTENT_FIELDS},
        }
    )


def condition_revision_sha256(row: SpatialConditionRevision) -> str:
    return condition_content_sha256({name: getattr(row, name) for name in CONDITION_CONTENT_FIELDS})


def condition_next_phase(
    previous: ConditionRevision,
    decision: ConditionDecision,
    earlier_review: ConditionDecision | None,
) -> Phase:
    observation = previous.observation
    actor = decision.actor_id.casefold()
    if actor == observation.observer_id.casefold() or (
        earlier_review is not None and actor == earlier_review.actor_id.casefold()
    ):
        raise ValidationError(
            "Observer, reviewer and adjudicator must have distinct local identities"
        )
    previous_time = (
        previous.decision.decided_at_utc if previous.decision else observation.observed_at_utc
    )
    if decision.decided_at_utc <= previous_time:
        raise ValidationError(
            "A decision must be dated after its preceding observation or decision"
        )
    if decision.label is not None and decision.label not in observation.rubric.labels:
        raise ValidationError("Decision label must be in the frozen rubric")
    if previous.phase == "observation":
        if decision.decision == "adjudicated":
            raise ValidationError(
                "Adjudication requires a preceding disputed or inconclusive review"
            )
        if decision.decision == "disagree" and decision.label == observation.label:
            raise ValidationError("A disagreement must identify a different label")
        return "review"
    if (
        previous.phase == "review"
        and previous.decision is not None
        and previous.decision.decision in {"disagree", "inconclusive"}
        and decision.decision in {"adjudicated", "inconclusive"}
    ):
        return "adjudication"
    raise ConflictError("This condition revision does not accept another decision")


class SpatialConditionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.sources = SpatialSourceAssetService(session, settings)
        self.metadata = SpatialAssetMetadataRevisionService(session, settings)

    def _scope(self, project_id: str, asset_id: str) -> tuple[str, str | None]:
        source = self.sources.get(project_id, asset_id)
        self.sources.read_verified(project_id, asset_id)
        metadata_id = self.session.scalar(
            select(SpatialAssetMetadataRevision.id)
            .where(
                SpatialAssetMetadataRevision.project_id == project_id,
                SpatialAssetMetadataRevision.spatial_source_asset_id == asset_id,
            )
            .order_by(SpatialAssetMetadataRevision.revision.desc())
            .limit(1)
        )
        if metadata_id is not None:
            self.metadata.get(project_id, asset_id, metadata_id)
        return source.sha256, metadata_id

    def _rubric(self, project_id: str, observation: ConditionObservation, *, create: bool) -> None:
        rubric = observation.rubric
        digest = canonical_json_sha256(rubric.model_dump(mode="json"))
        registered = self.session.get(
            SpatialConditionRubric, (project_id, rubric.rubric_id, rubric.version)
        )
        if registered is None and create:
            self.session.add(
                SpatialConditionRubric(
                    project_id=project_id,
                    rubric_id=rubric.rubric_id,
                    version=rubric.version,
                    content_sha256=digest,
                )
            )
            return
        if registered is None or registered.content_sha256 != digest:
            if create:
                raise ConflictError("This rubric version already has a different declaration")
            raise ValidationError("Stored condition rubric does not match its frozen declaration")

    def _row(self, project_id: str, asset_id: str, revision_id: str) -> SpatialConditionRevision:
        row = self.session.get(SpatialConditionRevision, revision_id)
        if row is None or row.project_id != project_id or row.asset_id != asset_id:
            raise NotFoundError("Condition revision not found for this project asset")
        return row

    def _response(
        self, row: SpatialConditionRevision, scope: tuple[str, str | None]
    ) -> ConditionRevision:
        source_sha256, latest_metadata_id = scope
        if condition_revision_sha256(row) != row.content_sha256:
            raise ValidationError("Stored condition evidence failed integrity validation")
        try:
            observation = ConditionObservation.model_validate(row.observation_json)
            decision = (
                ConditionDecision.model_validate(row.decision_json) if row.decision_json else None
            )
            if observation.source_sha256 != source_sha256:
                raise ValidationError("Condition evidence references a different original SHA-256")
            self._rubric(row.project_id, observation, create=False)
            metadata_uuid = observation.metadata_revision_id
            observed_metadata_id = str(metadata_uuid) if metadata_uuid is not None else None
            if observed_metadata_id is not None and observed_metadata_id != latest_metadata_id:
                self.metadata.get(row.project_id, row.asset_id, observed_metadata_id)
            return ConditionRevision.model_validate(
                {
                    "id": row.id,
                    "project_id": row.project_id,
                    "asset_id": row.asset_id,
                    "observation_id": row.observation_id,
                    "previous_revision_id": row.previous_revision_id,
                    "phase": row.phase,
                    "observation": observation,
                    "decision": decision,
                    "resolved_label": (
                        observation.label
                        if decision and decision.decision == "agree"
                        else decision.label
                        if decision and decision.decision == "adjudicated"
                        else None
                    ),
                    "stale_source_metadata": observed_metadata_id != latest_metadata_id,
                    "content_sha256": row.content_sha256,
                    "created_at": row.created_at.replace(tzinfo=UTC)
                    if row.created_at.tzinfo is None
                    else row.created_at.astimezone(UTC),
                }
            )
        except ValueError as exc:
            raise ValidationError("Stored condition evidence is invalid") from exc

    def _chain(
        self, row: SpatialConditionRevision, scope: tuple[str, str | None]
    ) -> list[ConditionRevision]:
        chain = [self._response(row, scope)]
        while chain[-1].previous_revision_id is not None and len(chain) < 3:
            previous_row = self._row(
                row.project_id, row.asset_id, str(chain[-1].previous_revision_id)
            )
            chain.append(self._response(previous_row, scope))
        chain.reverse()
        root = chain[0]
        if (
            root.previous_revision_id is not None
            or root.phase != "observation"
            or root.decision is not None
            or root.id != root.observation_id
        ):
            raise ValidationError("Stored condition revision ancestry is inconsistent")
        for index, (previous, current) in enumerate(pairwise(chain)):
            decision = current.decision
            if (
                current.observation_id != root.id
                or current.observation != root.observation
                or decision is None
            ):
                raise ValidationError("Stored condition revision ancestry is inconsistent")
            try:
                earlier_review = previous.decision if index else None
                if current.phase != condition_next_phase(previous, decision, earlier_review):
                    raise ValidationError("Stored condition revision phase is inconsistent")
            except ConflictError as exc:
                raise ValidationError("Stored condition revision ancestry is inconsistent") from exc
        return chain

    def _persist(self, row: SpatialConditionRevision) -> None:
        row.content_sha256 = condition_revision_sha256(row)
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Condition history or rubric changed; reload and retry") from exc

    def observe(
        self, project_id: str, asset_id: str, observation: ConditionObservation
    ) -> ConditionRevision:
        scope = self._scope(project_id, asset_id)
        if observation.source_sha256 != scope[0]:
            raise ValidationError("The observation must bind the verified original SHA-256")
        if (
            str(observation.metadata_revision_id)
            if observation.metadata_revision_id is not None
            else None
        ) != scope[1]:
            raise ConflictError("Asset metadata changed; reload before recording condition")
        self._rubric(project_id, observation, create=True)
        revision_id = str(uuid4())
        row = SpatialConditionRevision(
            id=revision_id,
            project_id=project_id,
            asset_id=asset_id,
            observation_id=revision_id,
            phase="observation",
            observation_json=observation.model_dump(mode="json"),
        )
        self._persist(row)
        return self._response(row, scope)

    def decide(
        self, project_id: str, asset_id: str, revision_id: str, decision: ConditionDecision
    ) -> ConditionRevision:
        scope = self._scope(project_id, asset_id)
        previous_row = self._row(project_id, asset_id, revision_id)
        previous = self._chain(previous_row, scope)[-1]
        if previous.stale_source_metadata:
            raise ConflictError("Asset metadata changed; record a new observation before review")
        earlier_review = previous.decision if previous.phase == "review" else None
        phase = condition_next_phase(previous, decision, earlier_review)
        row = SpatialConditionRevision(
            id=str(uuid4()),
            project_id=project_id,
            asset_id=asset_id,
            observation_id=previous_row.observation_id,
            previous_revision_id=revision_id,
            phase=phase,
            observation_json=previous_row.observation_json,
            decision_json=decision.model_dump(mode="json"),
        )
        self._persist(row)
        return self._response(row, scope)

    def list(
        self, project_id: str, asset_id: str, *, limit: int, offset: int, newest_first: bool = False
    ) -> list[ConditionRevision]:
        scope = self._scope(project_id, asset_id)
        columns = (SpatialConditionRevision.created_at, SpatialConditionRevision.id)
        ordering = tuple(col.desc() for col in columns) if newest_first else columns
        rows = self.session.scalars(
            select(SpatialConditionRevision)
            .where(
                SpatialConditionRevision.project_id == project_id,
                SpatialConditionRevision.asset_id == asset_id,
            )
            .order_by(*ordering)
            .limit(limit)
            .offset(offset)
        )
        return [self._chain(row, scope)[-1] for row in rows]

    def report(
        self, project_id: str, asset_id: str, revision_id: str, *, require_current: bool = False
    ) -> ConditionReport:
        scope = self._scope(project_id, asset_id)
        revisions = self._chain(self._row(project_id, asset_id, revision_id), scope)
        if require_current and revisions[-1].stale_source_metadata:
            raise ConflictError("The condition report references stale asset metadata")
        return ConditionReport(revision_id=revisions[-1].id, revisions=revisions)
