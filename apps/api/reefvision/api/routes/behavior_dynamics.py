"""Scientist-ready behavior ethogram and dynamics routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.behavior_classifier import (
    BehaviorExportFormat,
    BehaviorModelResponse,
    BehaviorModelTrainRequest,
    BehaviorPredictionResponse,
    BehaviorPredictionReviewRequest,
    BehaviorPredictionRunRequest,
    BehaviorPredictionRunResponse,
)
from reefvision.schemas.behavior_dynamics import (
    BehaviorBoutCreateRequest,
    BehaviorBoutResponse,
    BehaviorDynamicsRequest,
    BehaviorDynamicsResponse,
    BehaviorEthogramCreateRequest,
    BehaviorEthogramResponse,
)
from reefvision.schemas.behavior_features import (
    BehaviorFeatureRequest,
    BehaviorFeatureVectorResponse,
)
from reefvision.services.behavior_dynamics import BehaviorDynamicsService
from reefvision.services.behavior_exports import BehaviorExportService
from reefvision.services.behavior_features import BehaviorFeatureService
from reefvision.services.behavior_model_training import BehaviorModelTrainingService
from reefvision.services.behavior_predictions import BehaviorPredictionService

router = APIRouter(tags=["behavior-dynamics"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/behavior-ethograms",
    response_model=BehaviorEthogramResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_behavior_ethogram(
    project_id: str,
    payload: BehaviorEthogramCreateRequest,
    session: DbSession,
) -> BehaviorEthogramResponse:
    return BehaviorDynamicsService(session).create_ethogram(project_id, payload)


@router.post(
    "/behavior-ethograms/{ethogram_series_id}/revisions",
    response_model=BehaviorEthogramResponse,
    status_code=status.HTTP_201_CREATED,
)
def revise_behavior_ethogram(
    ethogram_series_id: str,
    payload: BehaviorEthogramCreateRequest,
    session: DbSession,
) -> BehaviorEthogramResponse:
    return BehaviorDynamicsService(session).revise_ethogram(
        ethogram_series_id,
        payload,
    )


@router.get(
    "/projects/{project_id}/behavior-ethograms",
    response_model=list[BehaviorEthogramResponse],
)
def list_behavior_ethograms(
    project_id: str,
    session: DbSession,
) -> list[BehaviorEthogramResponse]:
    return BehaviorDynamicsService(session).list_ethograms(project_id)


@router.post(
    "/video-tracks/{track_id}/behavior-bouts",
    response_model=BehaviorBoutResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_behavior_bout(
    track_id: str,
    payload: BehaviorBoutCreateRequest,
    session: DbSession,
) -> BehaviorBoutResponse:
    return BehaviorDynamicsService(session).create_bout(track_id, payload)


@router.get(
    "/video-tracks/{track_id}/behavior-bouts",
    response_model=list[BehaviorBoutResponse],
)
def list_behavior_bouts(
    track_id: str,
    session: DbSession,
    ethogram_revision_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[BehaviorBoutResponse]:
    return BehaviorDynamicsService(session).list_bouts(
        track_id,
        ethogram_revision_id,
    )


@router.post(
    "/video-tracks/{track_id}/behavior-dynamics",
    response_model=BehaviorDynamicsResponse,
)
def behavior_dynamics(
    track_id: str,
    payload: BehaviorDynamicsRequest,
    session: DbSession,
) -> BehaviorDynamicsResponse:
    return BehaviorDynamicsService(session).analyze(track_id, payload)


@router.post(
    "/video-tracks/{track_id}/behavior-features",
    response_model=BehaviorFeatureVectorResponse,
)
def behavior_features(
    track_id: str,
    payload: BehaviorFeatureRequest,
    session: DbSession,
) -> BehaviorFeatureVectorResponse:
    return BehaviorFeatureService(session).extract(track_id, payload)


@router.post(
    "/projects/{project_id}/behavior-models",
    response_model=BehaviorModelResponse,
    status_code=status.HTTP_201_CREATED,
)
def train_behavior_model(
    project_id: str,
    payload: BehaviorModelTrainRequest,
    session: DbSession,
) -> BehaviorModelResponse:
    return BehaviorModelTrainingService(session).train(project_id, payload)


@router.get(
    "/projects/{project_id}/behavior-models",
    response_model=list[BehaviorModelResponse],
)
def list_behavior_models(
    project_id: str,
    session: DbSession,
    ethogram_revision_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[BehaviorModelResponse]:
    return BehaviorModelTrainingService(session).list_models(
        project_id,
        ethogram_revision_id,
    )


@router.post(
    "/video-tracks/{track_id}/behavior-predictions",
    response_model=BehaviorPredictionRunResponse,
)
def run_behavior_predictions(
    track_id: str,
    payload: BehaviorPredictionRunRequest,
    session: DbSession,
) -> BehaviorPredictionRunResponse:
    return BehaviorPredictionService(session).run(track_id, payload)


@router.get(
    "/video-tracks/{track_id}/behavior-predictions",
    response_model=list[BehaviorPredictionResponse],
)
def list_behavior_predictions(
    track_id: str,
    session: DbSession,
    model_id: Annotated[str | None, Query(max_length=36)] = None,
    review_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[BehaviorPredictionResponse]:
    return BehaviorPredictionService(session).list_predictions(
        track_id,
        model_id=model_id,
        review_status=review_status,
    )


@router.put(
    "/behavior-predictions/{prediction_id}/review",
    response_model=BehaviorPredictionResponse,
)
def review_behavior_prediction(
    prediction_id: str,
    payload: BehaviorPredictionReviewRequest,
    session: DbSession,
) -> BehaviorPredictionResponse:
    return BehaviorPredictionService(session).review(prediction_id, payload)


@router.get("/video-tracks/{track_id}/behavior-export")
def export_behavior_data(
    track_id: str,
    session: DbSession,
    ethogram_revision_id: Annotated[str, Query(min_length=1, max_length=36)],
    export_format: Annotated[BehaviorExportFormat, Query(alias="format")],
    model_id: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    payload = BehaviorExportService(session).export(
        track_id,
        ethogram_revision_id,
        export_format,
        model_id=model_id,
    )
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "X-ReefVision-Behavior-Export-Format": export_format,
        },
    )
