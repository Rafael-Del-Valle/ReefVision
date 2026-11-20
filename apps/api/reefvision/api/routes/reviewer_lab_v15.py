"""Local role-scoped review sessions, blinded assignments, and sealed reports."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.reviewer_lab_v15 import (
    ReviewerLabAdjudication,
    ReviewerLabDecision,
    ReviewerLabInitialize,
    ReviewerLabJudgement,
    ReviewerLabReport,
    ReviewerLabReportSummary,
    ReviewerLabRole,
    ReviewerLabRoleChange,
    ReviewerLabRoleCreate,
    ReviewerLabRound,
    ReviewerLabRoundCreate,
    ReviewerLabStatus,
    ReviewRole,
)
from reefvision.services.images import ImageService
from reefvision.services.reviewer_lab_v15 import ReviewerLabService


def no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/projects/{project_id}/reviewer-lab",
    tags=["reviewer-lab"],
    dependencies=[Depends(no_cache)],
)

DbSession = Annotated[Session, Depends(get_db_session)]
Access = Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))]
NewKey = Annotated[str | None, Header(alias="X-ReefVision-Role-Key")]


def service(project_id: UUID, session: DbSession) -> ReviewerLabService:
    return ReviewerLabService(session, str(project_id))


Lab = Annotated[ReviewerLabService, Depends(service)]


def require_actor(
    lab: ReviewerLabService,
    access: HTTPAuthorizationCredentials | None,
    role: ReviewRole | None = None,
    *,
    write: bool = False,
) -> ReviewerLabRole:
    if access is None:
        raise HTTPException(401, "A current local Reviewer Lab key is required")
    if write:
        lab.roles.ensure_project(write=True)
    actor = lab.roles.authenticate(access.credentials)
    if actor is None:
        raise HTTPException(401, "A current local Reviewer Lab key is required")
    if role and actor.role != role:
        raise HTTPException(403, "This operation requires a different local Reviewer Lab role")
    return actor


@router.get("/status")
def get_status(lab: Lab) -> ReviewerLabStatus:
    return ReviewerLabStatus(initialized=lab.roles.initialized())


@router.post("/initialize", status_code=201)
def initialize(
    payload: ReviewerLabInitialize, lab: Lab, role_key: NewKey = None
) -> ReviewerLabRole:
    return lab.roles.initialize(payload.name, role_key)


@router.get("/session")
def get_session(lab: Lab, access: Access) -> ReviewerLabRole:
    return require_actor(lab, access)


@router.get("/roles")
def list_roles(lab: Lab, access: Access) -> list[ReviewerLabRole]:
    require_actor(lab, access, "manager")
    return lab.roles.list()


@router.post("/roles", status_code=201)
def add_role(
    payload: ReviewerLabRoleCreate, lab: Lab, access: Access, role_key: NewKey = None
) -> ReviewerLabRole:
    manager = require_actor(lab, access, "manager", write=True)
    return lab.roles.add(payload.name, payload.role, role_key, manager)


@router.post("/roles/{member_id}/revisions", status_code=201)
def revise_role(
    member_id: UUID,
    payload: ReviewerLabRoleChange,
    lab: Lab,
    access: Access,
    role_key: NewKey = None,
) -> ReviewerLabRole:
    manager = require_actor(lab, access, "manager", write=True)
    return lab.roles.revise(str(member_id), payload, role_key, manager)


@router.get("/rounds", response_model_exclude_none=True)
def list_rounds(lab: Lab, access: Access) -> list[ReviewerLabRound]:
    return lab.rounds(require_actor(lab, access))


@router.post("/rounds", status_code=201, response_model_exclude_none=True)
def create_round(payload: ReviewerLabRoundCreate, lab: Lab, access: Access) -> ReviewerLabRound:
    actor = require_actor(lab, access, "manager", write=True)
    return lab.create_round(actor, payload)


@router.get("/rounds/{round_id}", response_model_exclude_none=True)
def get_round(round_id: UUID, lab: Lab, access: Access) -> ReviewerLabRound:
    return lab.view(str(round_id), require_actor(lab, access))


@router.get("/rounds/{round_id}/subjects/{subject_id}/image", response_class=FileResponse)
def image(
    round_id: UUID, subject_id: UUID, request: Request, lab: Lab, access: Access
) -> FileResponse:
    source = lab.image(str(round_id), str(subject_id), require_actor(lab, access))
    image_service = ImageService(lab.session, request.app.state.settings)
    return FileResponse(
        image_service.content_path_for_image(source),
        media_type=source.media_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/rounds/{round_id}/subjects/{subject_id}/decision", status_code=201)
def decide(
    round_id: UUID,
    subject_id: UUID,
    payload: ReviewerLabJudgement,
    lab: Lab,
    access: Access,
) -> ReviewerLabDecision:
    actor = require_actor(lab, access, "reviewer", write=True)
    return lab.submit(str(round_id), str(subject_id), actor, payload)


@router.post("/rounds/{round_id}/subjects/{subject_id}/adjudication", status_code=201)
def resolve(
    round_id: UUID,
    subject_id: UUID,
    payload: ReviewerLabAdjudication,
    lab: Lab,
    access: Access,
) -> ReviewerLabDecision:
    actor = require_actor(lab, access, "adjudicator", write=True)
    return lab.submit(str(round_id), str(subject_id), actor, payload)


@router.post("/rounds/{round_id}/seal", status_code=201)
def seal(round_id: UUID, lab: Lab, access: Access) -> ReviewerLabReport:
    return lab.seal(str(round_id), require_actor(lab, access, "manager", write=True))


@router.get("/reports")
def list_reports(lab: Lab) -> list[ReviewerLabReportSummary]:
    return lab.reports()


@router.get("/reports/{report_id}")
def get_report(report_id: UUID, lab: Lab) -> ReviewerLabReport:
    return lab.report(str(report_id))


@router.get("/reports/{report_id}/export")
def export(report_id: UUID, lab: Lab, response: Response) -> ReviewerLabReport:
    report = lab.report(str(report_id))
    response.headers["Content-Disposition"] = (
        f'attachment; filename="reviewer-lab-{report_id}.json"'
    )
    response.headers["X-ReefVision-Content-SHA256"] = report.content_sha256
    return report
