"""Project-local taxonomy, independent known-presence review and detectable visits."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from reefvision.api.routes.reviewer_lab_v15 import Access, DbSession, require_actor
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabRole
from reefvision.schemas.taxonomy import (
    DetectabilityAssessmentRead,
    DetectabilityRequest,
    DetectabilityVisitCreate,
    DetectabilityVisitRead,
    PresenceReviewCreate,
    PresenceReviewRead,
    TaxonomyPage,
    TaxonProposalCreate,
    TaxonProposalRead,
    TaxonReviewCreate,
    TaxonReviewRead,
)
from reefvision.services.reviewer_lab_v15 import ReviewerLabService
from reefvision.services.taxonomy import TaxonomyService
from reefvision.storage.datasets import canonical_json_bytes

router = APIRouter(prefix="/projects/{project_id}/taxonomy", tags=["taxonomy and detectability"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def service(project_id: UUID, request: Request, session: DbSession) -> TaxonomyService:
    return TaxonomyService(session, request.app.state.settings, str(project_id))


Taxonomy = Annotated[TaxonomyService, Depends(service)]


def _write_actor(
    taxonomy: TaxonomyService, access: Access, *, independent: bool = False
) -> ReviewerLabRole:
    actor = require_actor(
        ReviewerLabService(taxonomy.session, taxonomy.project_id), access, write=True
    )
    if independent and actor.role not in ("reviewer", "adjudicator"):
        raise HTTPException(403, "Review requires a current local reviewer or adjudicator role")
    return actor


@router.get("/proposals")
def list_proposals(
    taxonomy: Taxonomy, limit: PageLimit = 50, offset: PageOffset = 0
) -> TaxonomyPage[TaxonProposalRead]:
    return taxonomy.list_proposals(limit, offset)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: UUID, taxonomy: Taxonomy) -> TaxonProposalRead:
    return taxonomy.get_proposal(str(proposal_id))


@router.post("/proposals", status_code=201)
def create_proposal(
    body: TaxonProposalCreate, taxonomy: Taxonomy, access: Access
) -> TaxonProposalRead:
    return taxonomy.create_proposal(body, _write_actor(taxonomy, access))


@router.get("/proposals/{proposal_id}/reviews")
def list_reviews(
    proposal_id: UUID, taxonomy: Taxonomy, limit: PageLimit = 50, offset: PageOffset = 0
) -> TaxonomyPage[TaxonReviewRead]:
    return taxonomy.list_reviews(str(proposal_id), limit, offset)


@router.post("/proposals/{proposal_id}/reviews", status_code=201)
def review_proposal(
    proposal_id: UUID, body: TaxonReviewCreate, taxonomy: Taxonomy, access: Access
) -> TaxonReviewRead:
    actor = _write_actor(taxonomy, access, independent=True)
    if str(taxonomy.get_proposal(str(proposal_id)).proposal.author.member_id) == actor.member_id:
        raise HTTPException(
            403, "The author cannot independently review their own taxonomy proposal"
        )
    return taxonomy.review_proposal(str(proposal_id), body, actor)


@router.get("/visits")
def list_visits(
    taxonomy: Taxonomy, limit: PageLimit = 50, offset: PageOffset = 0
) -> TaxonomyPage[DetectabilityVisitRead]:
    return taxonomy.list_visits(limit, offset)


@router.get("/visits/{visit_id}")
def get_visit(visit_id: UUID, taxonomy: Taxonomy) -> DetectabilityVisitRead:
    return taxonomy.get_visit(str(visit_id))


@router.post("/visits", status_code=201)
def create_visit(
    body: DetectabilityVisitCreate, taxonomy: Taxonomy, access: Access
) -> DetectabilityVisitRead:
    return taxonomy.create_visit(body, _write_actor(taxonomy, access))


@router.get("/visits/{visit_id}/presence-reviews")
def list_presence(
    visit_id: UUID, taxonomy: Taxonomy, limit: PageLimit = 50, offset: PageOffset = 0
) -> TaxonomyPage[PresenceReviewRead]:
    return taxonomy.list_presence(str(visit_id), limit, offset)


@router.post("/visits/{visit_id}/presence-reviews", status_code=201)
def review_presence(
    visit_id: UUID, body: PresenceReviewCreate, taxonomy: Taxonomy, access: Access
) -> PresenceReviewRead:
    actor = _write_actor(taxonomy, access, independent=True)
    if str(taxonomy.get_visit(str(visit_id)).visit.observer.member_id) == actor.member_id:
        raise HTTPException(
            403, "The visit author cannot independently confirm presence for their own visit"
        )
    return taxonomy.review_presence(str(visit_id), body, actor)


@router.get("/assessments")
def list_assessments(
    taxonomy: Taxonomy, limit: PageLimit = 20, offset: PageOffset = 0
) -> TaxonomyPage[DetectabilityAssessmentRead]:
    return taxonomy.list_assessments(limit, offset)


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: UUID, taxonomy: Taxonomy) -> DetectabilityAssessmentRead:
    return taxonomy.get_assessment(str(assessment_id))


@router.get("/assessments/{assessment_id}/export")
def export_assessment(assessment_id: UUID, taxonomy: Taxonomy) -> Response:
    report = taxonomy.get_assessment(str(assessment_id))
    return Response(
        content=canonical_json_bytes(report.model_dump(mode="json")),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="detectability-{assessment_id}.json"'
        },
    )


@router.post("/assessments", status_code=201)
def create_assessment(
    body: DetectabilityRequest, taxonomy: Taxonomy
) -> DetectabilityAssessmentRead:
    return taxonomy.create_assessment(body)
