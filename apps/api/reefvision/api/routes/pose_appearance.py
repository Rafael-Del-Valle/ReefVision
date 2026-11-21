"""Appearance proposals, sealed reports, pixel previews and attributed decisions."""

import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.api.routes.reviewer_lab_v15 import Access, require_actor, service
from reefvision.db.models import PoseAppearanceStudy, VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.jobs.pose_appearance import submit, submit_replay
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_appearance import (
    AppearanceDecisionRequest,
    AppearanceObservationOption,
    AppearanceRequest,
    AppearanceResult,
    AppearanceSummary,
    Digest,
)
from reefvision.services.pose_appearance import (
    add_decision,
    observation_options,
    study_row,
    study_summary,
    view,
)
from reefvision.storage.pose_appearance import source_crops

router = APIRouter(prefix="/projects/{project_id}/pose-appearance", tags=["reefpose-appearance"])
Db = Annotated[Session, Depends(get_db_session)]


@router.get("/observations", response_model=list[AppearanceObservationOption])
def list_observations(
    project_id: UUID,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AppearanceObservationOption]:
    return observation_options(db, str(project_id), limit, offset)


@router.get("/studies", response_model=list[AppearanceSummary])
def list_studies(
    project_id: UUID,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AppearanceSummary]:
    rows = db.scalars(
        select(PoseAppearanceStudy)
        .where(PoseAppearanceStudy.project_id == str(project_id))
        .order_by(PoseAppearanceStudy.created_at.desc(), PoseAppearanceStudy.id)
        .offset(offset)
        .limit(limit)
    )
    return [study_summary(row) for row in rows]


@router.post("/studies", response_model=JobResponse, status_code=202)
def create_study(
    project_id: UUID, request: Request, payload: AppearanceRequest, db: Db
) -> JobResponse:
    return JobResponse.model_validate(
        submit(db, request.app.state.settings, str(project_id), payload)
    )


@router.get("/studies/{study_id}", response_model=AppearanceResult)
def get_study(project_id: UUID, study_id: UUID, db: Db, access: Access) -> AppearanceResult:
    lab = service(project_id, db)
    actor = require_actor(lab, access) if access else None
    return view(db, study_row(db, str(project_id), str(study_id)), actor)


@router.get("/studies/{study_id}/export", response_model=AppearanceResult)
def export_study(project_id: UUID, study_id: UUID, db: Db, response: Response) -> AppearanceResult:
    response.headers["Content-Disposition"] = (
        f'attachment; filename="reefpose-appearance-{study_id}.json"'
    )
    return view(db, study_row(db, str(project_id), str(study_id)))


class ReplayRequest(BaseModel):
    study_sha256: Digest
    operation_id: UUID


@router.post("/studies/{study_id}/replay", response_model=JobResponse, status_code=202)
def replay_study(project_id: UUID, study_id: UUID, payload: ReplayRequest, db: Db) -> JobResponse:
    return JobResponse.model_validate(
        submit_replay(
            db, str(project_id), str(study_id), payload.study_sha256, payload.operation_id
        )
    )


@router.post("/studies/{study_id}/reviews", response_model=AppearanceResult)
def review_study(
    project_id: UUID, study_id: UUID, payload: AppearanceDecisionRequest, db: Db, access: Access
) -> AppearanceResult:
    actor = require_actor(service(project_id, db), access, write=True)
    return add_decision(db, str(project_id), str(study_id), payload, actor)


@router.get("/studies/{study_id}/crops/{observation_id}")
def preview_crop(
    project_id: UUID, study_id: UUID, observation_id: UUID, request: Request, db: Db
) -> Response:
    row = study_row(db, str(project_id), str(study_id))
    crop = next(
        (x for x in row.payload_json["inputs"]["crops"] if x["key"] == str(observation_id)), None
    )
    if crop is None:
        raise NotFoundError("Observation is outside this appearance study")
    video = db.get(VideoAsset, row.source_id_map_json.get(crop["video_id"], crop["video_id"]))
    if video is None or video.project_id != str(project_id) or video.sha256 != crop["video_sha256"]:
        raise ValidationError("Original appearance recording is unavailable")
    image, _, sha = source_crops(
        request.app.state.settings,
        video,
        [(crop["key"], crop["frame"], crop["bbox_xywh"])],
        lambda: None,
    )[crop["key"]]
    if sha != row.payload_json["result"]["crop_pixels"][crop["key"]]["rgb_sha256"]:
        raise ValidationError("Reopened source crop pixels differ from the recorded digest")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")
