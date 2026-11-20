"""Bind local taxonomic decisions and independent visits to immutable result receipts."""

from collections.abc import Callable, Mapping
from functools import cached_property
from typing import TypeVar
from uuid import UUID

from pydantic import ValidationError as InvalidSnapshot
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.project import Project, utc_now
from reefvision.db.models.project_exchange_package import ProjectExchangePackage
from reefvision.db.models.taxonomy import (
    DetectabilityAssessment,
    DetectabilityPresenceReview,
    DetectabilityVisit,
    TaxonomyRecord,
    TaxonProposal,
    TaxonReview,
)
from reefvision.db.models.video_asset import VideoAsset
from reefvision.domain.detectability import calculate_detectability, survey_visit_exclusion
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse, EcologyIdentityRow
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabRole
from reefvision.schemas.taxonomy import (
    AssessmentVisit,
    DetectabilityAssessmentRead,
    DetectabilityRequest,
    DetectabilityResult,
    DetectabilityVisitCreate,
    DetectabilityVisitRead,
    DetectabilityVisitSnapshot,
    IdentityPin,
    LocalAttribution,
    PresenceReviewCreate,
    PresenceReviewRead,
    PresenceReviewSnapshot,
    TaxonomyModel,
    TaxonomyPage,
    TaxonomySource,
    TaxonProposalCreate,
    TaxonProposalRead,
    TaxonProposalSnapshot,
    TaxonReviewCreate,
    TaxonReviewRead,
    TaxonReviewSnapshot,
)
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.reviewer_lab_roles_v15 import ReviewerLabRoles
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.taxonomy import source_sha256

_Record = TypeVar("_Record", bound=TaxonomyRecord)
_View = TypeVar("_View", bound=TaxonomyModel)
_MAX_VISITS_PER_ASSESSMENT = 500


def read_taxonomy_snapshot(record: TaxonomyRecord, schema: type[_View]) -> _View:
    if canonical_json_sha256(record.snapshot_json) != record.content_sha256:
        raise ConflictError("Taxonomy or detectability record no longer matches its saved checksum")
    try:
        return schema.model_validate(record.snapshot_json)
    except InvalidSnapshot as exc:
        raise ConflictError(
            "Taxonomy or detectability record has an invalid saved snapshot"
        ) from exc


def taxonomy_identity_pin(identity: EcologyIdentityRow) -> IdentityPin:
    return IdentityPin(
        id=UUID(identity.id),
        organism_key=identity.organism_key,
        revision=identity.revision,
        kind=identity.kind,
        experimental_unit_type=identity.experimental_unit_type,
        experimental_unit_id=identity.experimental_unit_id,
        sha256=canonical_json_sha256(identity.model_dump(mode="json")),
    )


def taxonomy_identity_matches(
    current: EcologyIdentityRow, pin: IdentityPin, origin_ids: Mapping[str, str]
) -> bool:
    """Check the immutable original pin against its local project and identity bindings."""
    pin_id = str(pin.id)
    if origin_ids.get(pin_id, pin_id) != current.id:
        return False
    original_projects = {
        current.project_id,
        *(old for old, live in origin_ids.items() if live == current.project_id),
    }
    return any(
        taxonomy_identity_pin(current.model_copy(update={"id": pin_id, "project_id": project_id}))
        == pin
        for project_id in original_projects
    )


def _actor(role: ReviewerLabRole) -> LocalAttribution:
    return LocalAttribution.model_validate(
        {
            "member_id": role.member_id,
            "role_revision_id": role.id,
            "name": role.name,
            "role": role.role,
        }
    )


def _snapshot_values(snapshot: TaxonomyModel) -> dict[str, object]:
    raw = snapshot.model_dump(mode="json")
    return {"snapshot_json": raw, "content_sha256": canonical_json_sha256(raw)}


class TaxonomyService:
    def __init__(self, session: Session, settings: Settings, project_id: str) -> None:
        self.session = session
        self.settings = settings
        self.project_id = project_id

    def require_project(self) -> Project:
        project = self.session.get(Project, self.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _mutable_project(self) -> None:
        if self.require_project().archived_at is not None:
            raise ConflictError(
                "Reopen this archived project to record taxonomy or survey evidence"
            )

    @cached_property
    def registry(self) -> EcologyIdentityRegistryResponse:
        return EcologyIdentityService(self.session).registry(self.project_id)

    @cached_property
    def origin_ids(self) -> dict[str, str]:
        imported = self.session.scalar(
            select(ProjectExchangePackage)
            .where(
                ProjectExchangePackage.project_id == self.project_id,
                ProjectExchangePackage.direction == "import",
                ProjectExchangePackage.status == "complete",
            )
            .order_by(ProjectExchangePackage.created_at.desc(), ProjectExchangePackage.id.desc())
            .limit(1)
        )
        if imported is None:
            return {}
        options = imported.options_json or {}
        origin = options.get("origin_id_map") or options.get("id_map", {})
        if not isinstance(origin, dict):
            return {}
        return {
            old: local
            for old, local in origin.items()
            if isinstance(old, str) and isinstance(local, str)
        }

    def _live_id(self, identifier: object) -> str:
        value = str(identifier)
        return self.origin_ids.get(value, value)

    def _row(self, model: type[_Record], row_id: str) -> _Record:
        row = self.session.get(model, row_id)
        if row is None or row.project_id != self.project_id:
            raise NotFoundError("Taxonomy or detectability record not found in this project")
        return row

    def verify_source(self, source: TaxonomySource) -> str:
        asset: ImageAsset | VideoAsset | None
        if source.kind == "image":
            asset = self.session.get(ImageAsset, self._live_id(source.id))
        else:
            asset = self.session.get(VideoAsset, self._live_id(source.id))
        if asset is None or asset.project_id != self.project_id:
            raise NotFoundError("Survey source is unavailable in this project")
        if asset.sha256 != source.sha256:
            raise ConflictError("Survey source metadata differs from its pinned checksum")
        try:
            actual = source_sha256(self.settings, asset.managed_path)
        except (OSError, ValidationError) as exc:
            raise ConflictError("The original survey source is missing or unreadable") from exc
        if actual != source.sha256:
            raise ConflictError("The original survey bytes differ from their pinned checksum")
        return asset.id

    def _commit(self, row: TaxonomyRecord) -> None:
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("This review revision or visit has already been recorded") from exc

    def _page(
        self,
        model: type[_Record],
        reader: Callable[[_Record], _View],
        *,
        limit: int,
        offset: int,
        parent_filter: ColumnElement[bool] | None = None,
        chronological: bool = False,
    ) -> TaxonomyPage[_View]:
        self.require_project()
        where = [model.project_id == self.project_id]
        if parent_filter is not None:
            where.append(parent_filter)
        order = (
            (model.created_at, model.id)
            if chronological
            else (model.created_at.desc(), model.id.desc())
        )
        items = self.session.scalars(
            select(model).where(*where).order_by(*order).limit(limit).offset(offset)
        )
        total = self.session.scalar(select(func.count()).select_from(model).where(*where)) or 0
        return TaxonomyPage(
            items=[reader(row) for row in items], total=total, limit=limit, offset=offset
        )

    def _latest_taxon_review(self, proposal_id: str) -> TaxonReviewRead | None:
        row = self.session.scalar(
            select(TaxonReview)
            .where(
                TaxonReview.project_id == self.project_id, TaxonReview.proposal_id == proposal_id
            )
            .order_by(TaxonReview.revision.desc())
            .limit(1)
        )
        return self._read_review(row) if row is not None else None

    def _latest_presence(self, visit_id: str) -> PresenceReviewRead | None:
        row = self.session.scalar(
            select(DetectabilityPresenceReview)
            .where(
                DetectabilityPresenceReview.project_id == self.project_id,
                DetectabilityPresenceReview.visit_id == visit_id,
            )
            .order_by(DetectabilityPresenceReview.revision.desc())
            .limit(1)
        )
        return self._read_presence(row) if row is not None else None

    @staticmethod
    def _read_review(row: TaxonReview) -> TaxonReviewRead:
        return TaxonReviewRead.model_validate(
            {
                "id": row.id,
                "revision": row.revision,
                "review_sha256": row.content_sha256,
                "review": read_taxonomy_snapshot(row, TaxonReviewSnapshot),
            }
        )

    @staticmethod
    def _read_presence(row: DetectabilityPresenceReview) -> PresenceReviewRead:
        return PresenceReviewRead.model_validate(
            {
                "id": row.id,
                "revision": row.revision,
                "review_sha256": row.content_sha256,
                "review": read_taxonomy_snapshot(row, PresenceReviewSnapshot),
            }
        )

    def _proposal_read(
        self, row: TaxonProposal, review: TaxonReviewRead | None
    ) -> TaxonProposalRead:
        snapshot = read_taxonomy_snapshot(row, TaxonProposalSnapshot)
        if (
            self._live_id(snapshot.identity.id) != row.identity_revision_id
            or self._live_id(snapshot.author.role_revision_id) != row.author_role_revision_id
        ):
            raise ConflictError("Taxonomy proposal no longer matches its local identity or author")
        if review and review.review.target_sha256 != row.content_sha256:
            raise ConflictError("Taxonomy decision no longer matches its proposal")
        return TaxonProposalRead.model_validate(
            {
                "id": row.id,
                "project_id": self.project_id,
                "proposal": snapshot,
                "proposal_sha256": row.content_sha256,
                "state": review.review.decision if review else "proposed",
                "review_revision": review.revision if review else 0,
            }
        )

    def _read_proposal(self, row: TaxonProposal) -> TaxonProposalRead:
        return self._proposal_read(row, self._latest_taxon_review(row.id))

    def _read_visit(self, row: DetectabilityVisit) -> DetectabilityVisitRead:
        presence = self._latest_presence(row.id)
        if presence and presence.review.target_sha256 != row.content_sha256:
            raise ConflictError("Known-presence decision no longer matches its visit")
        return DetectabilityVisitRead.model_validate(
            {
                "id": row.id,
                "project_id": self.project_id,
                "visit": read_taxonomy_snapshot(row, DetectabilityVisitSnapshot),
                "visit_sha256": row.content_sha256,
                "presence_revision": presence.revision if presence else 0,
                "presence_status": presence.review.decision if presence else "pending",
            }
        )

    def _read_assessment(self, row: DetectabilityAssessment) -> DetectabilityAssessmentRead:
        return DetectabilityAssessmentRead.model_validate(
            {
                "id": row.id,
                "project_id": self.project_id,
                "result_sha256": row.content_sha256,
                "result": read_taxonomy_snapshot(row, DetectabilityResult),
            }
        )

    def get_proposal(self, row_id: str) -> TaxonProposalRead:
        return self._read_proposal(self._row(TaxonProposal, row_id))

    def list_proposals(self, limit: int, offset: int) -> TaxonomyPage[TaxonProposalRead]:
        return self._page(TaxonProposal, self._read_proposal, limit=limit, offset=offset)

    def create_proposal(
        self, body: TaxonProposalCreate, author: ReviewerLabRole
    ) -> TaxonProposalRead:
        self._mutable_project()
        identity = next(
            (row for row in self.registry.identities if row.id == str(body.identity_revision_id)),
            None,
        )
        if not identity:
            raise ConflictError("Choose a current registered organism revision in this project")
        self.verify_source(body.source)
        snapshot = TaxonProposalSnapshot(
            **body.model_dump(),
            author=_actor(author),
            identity=taxonomy_identity_pin(identity),
            proposed_at=utc_now(),
        )
        row = TaxonProposal(
            project_id=self.project_id,
            identity_revision_id=identity.id,
            author_role_revision_id=author.id,
            **_snapshot_values(snapshot),
        )
        self._commit(row)
        return self._proposal_read(row, None)

    def list_reviews(
        self, proposal_id: str, limit: int, offset: int
    ) -> TaxonomyPage[TaxonReviewRead]:
        self._row(TaxonProposal, proposal_id)
        return self._page(
            TaxonReview,
            self._read_review,
            limit=limit,
            offset=offset,
            parent_filter=TaxonReview.proposal_id == proposal_id,
            chronological=True,
        )

    def review_proposal(
        self, proposal_id: str, body: TaxonReviewCreate, actor: ReviewerLabRole
    ) -> TaxonReviewRead:
        self._mutable_project()
        proposal = self.get_proposal(proposal_id)
        if body.expected_revision != proposal.review_revision:
            raise ConflictError("This proposal has a newer decision. Reopen its review history.")
        if self._live_id(proposal.proposal.author.member_id) == actor.member_id:
            raise ConflictError(
                "The author cannot independently review their own taxonomy proposal"
            )
        if body.decision == "confirmed":
            current_identity = next(
                (
                    row
                    for row in self.registry.identities
                    if row.organism_key == proposal.proposal.identity.organism_key
                ),
                None,
            )
            if not current_identity or not taxonomy_identity_matches(
                current_identity, proposal.proposal.identity, self.origin_ids
            ):
                raise ConflictError(
                    "The registered organism changed. Submit a proposal for the current revision."
                )
            self.verify_source(proposal.proposal.source)
            self._assert_one_confirmed_taxon(proposal)
        snapshot = TaxonReviewSnapshot(
            **body.model_dump(),
            target_sha256=proposal.proposal_sha256,
            reviewer=_actor(actor),
            reviewed_at=utc_now(),
        )
        row = TaxonReview(
            project_id=self.project_id,
            proposal_id=proposal_id,
            reviewer_role_revision_id=actor.id,
            revision=proposal.review_revision + 1,
            **_snapshot_values(snapshot),
        )
        self._commit(row)
        return self._read_review(row)

    def _assert_one_confirmed_taxon(self, proposal: TaxonProposalRead) -> None:
        others = self.session.scalars(
            select(TaxonProposal).where(
                TaxonProposal.project_id == self.project_id,
                TaxonProposal.identity_revision_id == self._live_id(proposal.proposal.identity.id),
                TaxonProposal.id != str(proposal.id),
            )
        )
        for row in others:
            other = self._read_proposal(row)
            if other.state == "confirmed" and other.proposal.rank == proposal.proposal.rank:
                raise ConflictError(
                    "This organism already has a confirmed proposal at that rank. "
                    "Review that decision first."
                )

    def list_visits(self, limit: int, offset: int) -> TaxonomyPage[DetectabilityVisitRead]:
        return self._page(DetectabilityVisit, self._read_visit, limit=limit, offset=offset)

    def get_visit(self, row_id: str) -> DetectabilityVisitRead:
        return self._read_visit(self._row(DetectabilityVisit, row_id))

    def create_visit(
        self, body: DetectabilityVisitCreate, observer: ReviewerLabRole
    ) -> DetectabilityVisitRead:
        self._mutable_project()
        proposal = self.get_proposal(str(body.proposal_id))
        if body.source:
            self.verify_source(body.source)
        snapshot = DetectabilityVisitSnapshot(
            **body.model_dump(),
            identity=proposal.proposal.identity,
            proposal_sha256=proposal.proposal_sha256,
            observer=_actor(observer),
            recorded_at=utc_now(),
        )
        row = DetectabilityVisit(
            project_id=self.project_id,
            proposal_id=str(body.proposal_id),
            observer_role_revision_id=observer.id,
            organism_key=snapshot.identity.organism_key,
            protocol=body.protocol,
            started_at=body.started_at,
            **_snapshot_values(snapshot),
        )
        self._commit(row)
        return self._read_visit(row)

    def list_presence(
        self, visit_id: str, limit: int, offset: int
    ) -> TaxonomyPage[PresenceReviewRead]:
        self._row(DetectabilityVisit, visit_id)
        return self._page(
            DetectabilityPresenceReview,
            self._read_presence,
            limit=limit,
            offset=offset,
            parent_filter=DetectabilityPresenceReview.visit_id == visit_id,
            chronological=True,
        )

    def review_presence(
        self, visit_id: str, body: PresenceReviewCreate, actor: ReviewerLabRole
    ) -> PresenceReviewRead:
        self._mutable_project()
        visit = self.get_visit(visit_id)
        if body.expected_revision != visit.presence_revision:
            raise ConflictError(
                "This visit has a newer presence decision. Reopen its review history."
            )
        if self._live_id(visit.visit.observer.member_id) == actor.member_id:
            raise ConflictError(
                "The visit author cannot independently confirm presence for their own visit"
            )
        if body.source is not None:
            self.verify_source(body.source)
            if visit.visit.source and visit.visit.source.sha256 == body.source.sha256:
                raise ConflictError(
                    "Known presence requires reference bytes separate from the observed visit"
                )
        snapshot = PresenceReviewSnapshot(
            **body.model_dump(),
            target_sha256=visit.visit_sha256,
            reviewer=_actor(actor),
            reviewed_at=utc_now(),
        )
        row = DetectabilityPresenceReview(
            project_id=self.project_id,
            visit_id=visit_id,
            reviewer_role_revision_id=actor.id,
            revision=visit.presence_revision + 1,
            **_snapshot_values(snapshot),
        )
        self._commit(row)
        return self._read_presence(row)

    def list_assessments(
        self, limit: int, offset: int
    ) -> TaxonomyPage[DetectabilityAssessmentRead]:
        return self._page(
            DetectabilityAssessment, self._read_assessment, limit=limit, offset=offset
        )

    def get_assessment(self, row_id: str) -> DetectabilityAssessmentRead:
        return self._read_assessment(self._row(DetectabilityAssessment, row_id))

    def create_assessment(self, body: DetectabilityRequest) -> DetectabilityAssessmentRead:
        ReviewerLabRoles(self.session, self.project_id).ensure_project(write=True)
        self._mutable_project()
        rows = list(
            self.session.scalars(
                select(DetectabilityVisit)
                .where(
                    DetectabilityVisit.project_id == self.project_id,
                    DetectabilityVisit.protocol == body.protocol,
                    DetectabilityVisit.started_at >= body.window_start,
                    DetectabilityVisit.started_at < body.window_end,
                )
                .order_by(DetectabilityVisit.started_at, DetectabilityVisit.id)
                .limit(_MAX_VISITS_PER_ASSESSMENT + 1)
            )
        )
        if len(rows) > _MAX_VISITS_PER_ASSESSMENT:
            raise ValidationError(
                "Choose a shorter survey window. Each assessment supports at most 500 visits."
            )
        current = {row.organism_key: row for row in self.registry.identities}
        shared_parents = set(self.registry.cross_unit_shared_parent_colony_keys)
        shared_identities = {
            row.organism_key
            for row in self.registry.identities
            if row.parent_colony_key in shared_parents
        }
        checks: dict[tuple[str, str, str], bool] = {}
        records: list[AssessmentVisit] = []
        for row in rows:
            tax_review = self._latest_taxon_review(row.proposal_id)
            proposal = self._proposal_read(self._row(TaxonProposal, row.proposal_id), tax_review)
            if (
                proposal.proposal.scientific_name.casefold() != body.scientific_name.casefold()
                or proposal.proposal.rank != body.rank
            ):
                continue
            presence = self._latest_presence(row.id)
            visit = read_taxonomy_snapshot(row, DetectabilityVisitSnapshot)
            if (presence and presence.review.target_sha256 != row.content_sha256) or (
                visit.proposal_sha256 != proposal.proposal_sha256
                or visit.identity != proposal.proposal.identity
            ):
                raise ConflictError(
                    "Visit evidence no longer matches its pinned proposal or review"
                )
            records.append(
                AssessmentVisit.model_validate(
                    {
                        "id": row.id,
                        "visit_sha256": row.content_sha256,
                        "visit": visit,
                        "proposal": proposal,
                        "presence_review": presence,
                        "taxonomy_review": tax_review,
                        "exclusion": self._visit_exclusion(
                            body, visit, proposal, presence, current, shared_identities, checks
                        ),
                    }
                )
            )
        result = calculate_detectability(body, records)
        values = _snapshot_values(result)
        existing = self.session.scalar(
            select(DetectabilityAssessment).where(
                DetectabilityAssessment.project_id == self.project_id,
                DetectabilityAssessment.content_sha256 == values["content_sha256"],
            )
        )
        if existing is not None:
            return self._read_assessment(existing)
        assessment = DetectabilityAssessment(project_id=self.project_id, **values)
        self._commit(assessment)
        return self._read_assessment(assessment)

    def _visit_exclusion(
        self,
        request: DetectabilityRequest,
        visit: DetectabilityVisitSnapshot,
        proposal: TaxonProposalRead,
        presence: PresenceReviewRead | None,
        current: dict[str, EcologyIdentityRow],
        shared_identities: set[str],
        checks: dict[tuple[str, str, str], bool],
    ) -> str | None:
        exclusion = survey_visit_exclusion(request, visit, proposal, presence)
        if exclusion is not None:
            return exclusion
        assert presence is not None
        identity = visit.identity
        live_identity = current.get(identity.organism_key)
        if live_identity is None or not taxonomy_identity_matches(
            live_identity, identity, self.origin_ids
        ):
            return "organism_revision_changed"
        if identity.organism_key in shared_identities:
            return "shared_parent_across_units"
        sources = (visit.source, presence.review.source, proposal.proposal.source)
        for source in sources:
            if source is None:
                return "source_unavailable"
            key = (source.kind, str(source.id), source.sha256)
            if key not in checks:
                try:
                    self.verify_source(source)
                    checks[key] = True
                except (ConflictError, NotFoundError):
                    checks[key] = False
            if not checks[key]:
                return "source_unavailable"
        return None
