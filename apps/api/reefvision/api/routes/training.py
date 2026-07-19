"""Training workspace API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.bootstrap import TrainingWorkspaceBootstrapResponse
from reefvision.schemas.models import UltralyticsTrainingRegistryResponse
from reefvision.schemas.training import (
    ExperimentCompareRequest,
    ExperimentCompareResponse,
    ExperimentRecordResponse,
    TrainingDraftPatchRequest,
    TrainingDraftResponse,
    TrainingDraftSummaryResponse,
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderResponse,
    TrainingRunCreateRequest,
    TrainingRunResponse,
    TrainingTilingEstimateResponse,
    TrainingTilingRequest,
)
from reefvision.services.advanced_training import AdvancedTrainingService
from reefvision.services.bootstrap import BootstrapService
from reefvision.services.segmentation_catalog import SegmentationModelCatalogService

router = APIRouter(tags=["training"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AdvancedTrainingService:
    settings: Settings = request.app.state.settings
    result = AdvancedTrainingService(session, settings)
    result.catalog = SegmentationModelCatalogService(session, settings)
    return result


def bootstrap_service(request: Request, session: Session) -> BootstrapService:
    settings: Settings = request.app.state.settings
    return BootstrapService(session, settings)


@router.get(
    "/projects/{project_id}/training/bootstrap",
    response_model=TrainingWorkspaceBootstrapResponse,
)
def get_training_workspace_bootstrap(
    project_id: str,
    request: Request,
    session: DbSession,
) -> TrainingWorkspaceBootstrapResponse:
    return bootstrap_service(request, session).training_workspace_bootstrap(project_id)


@router.get("/training/providers", response_model=list[TrainingProviderResponse])
def list_training_providers(
    request: Request,
    session: DbSession,
) -> list[TrainingProviderResponse]:
    return service(request, session).list_providers()


@router.get(
    "/training/providers/{provider_id}/parameters",
    response_model=UltralyticsTrainingRegistryResponse,
)
def get_training_provider_parameters(
    provider_id: str,
    request: Request,
    session: DbSession,
) -> UltralyticsTrainingRegistryResponse:
    snapshot = service(request, session).get_provider_parameters(provider_id)
    return UltralyticsTrainingRegistryResponse.model_validate(snapshot, from_attributes=True)


@router.get(
    "/projects/{project_id}/training-drafts",
    response_model=list[TrainingDraftResponse],
)
def list_training_drafts(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingDraftResponse]:
    return service(request, session).list_drafts(project_id)


@router.get(
    "/projects/{project_id}/training-draft-summaries",
    response_model=list[TrainingDraftSummaryResponse],
)
def list_training_draft_summaries(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingDraftSummaryResponse]:
    return service(request, session).list_draft_summaries(project_id)


@router.post(
    "/projects/{project_id}/training-drafts",
    response_model=TrainingDraftResponse,
)
def create_training_draft(
    project_id: str,
    payload: TrainingDraftWriteRequest,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).create_draft(project_id, payload)


@router.get("/training-drafts/{draft_id}", response_model=TrainingDraftResponse)
def get_training_draft(
    draft_id: str,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).get_draft(draft_id)


@router.patch("/training-drafts/{draft_id}", response_model=TrainingDraftResponse)
def patch_training_draft(
    draft_id: str,
    payload: TrainingDraftPatchRequest,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).update_draft(draft_id, payload)


@router.delete("/training-drafts/{draft_id}", status_code=204)
def delete_training_draft(
    draft_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_draft(draft_id)


@router.post(
    "/projects/{project_id}/training-preflight",
    response_model=TrainingPreflightResponse,
)
def run_training_preflight(
    project_id: str,
    payload: TrainingDraftWriteRequest,
    request: Request,
    session: DbSession,
) -> TrainingPreflightResponse:
    return service(request, session).preflight(project_id, payload)


@router.post(
    "/projects/{project_id}/training-tiling/estimate",
    response_model=TrainingTilingEstimateResponse,
)
def estimate_training_tiling(
    project_id: str,
    payload: TrainingTilingRequest,
    request: Request,
    session: DbSession,
) -> TrainingTilingEstimateResponse:
    return service(request, session).estimate_tiling(project_id, payload)


@router.post(
    "/projects/{project_id}/training-runs",
    response_model=TrainingRunResponse,
)
def create_training_run(
    project_id: str,
    payload: TrainingRunCreateRequest,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).create_run(project_id, payload)


@router.get(
    "/projects/{project_id}/training-runs",
    response_model=list[TrainingRunResponse],
)
def list_training_runs(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingRunResponse]:
    return service(request, session).list_runs(project_id)


@router.get("/training-runs/{run_id}", response_model=TrainingRunResponse)
def get_training_run(
    run_id: str,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).get_run(run_id)


@router.post("/training-runs/{run_id}/cancel", response_model=TrainingRunResponse)
def cancel_training_run(
    run_id: str,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).cancel_run(run_id)


@router.get(
    "/projects/{project_id}/experiments",
    response_model=list[ExperimentRecordResponse],
)
def list_project_experiments(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ExperimentRecordResponse]:
    return service(request, session).list_experiments(project_id)


@router.post("/experiments/compare", response_model=ExperimentCompareResponse)
def compare_experiments(
    payload: ExperimentCompareRequest,
    request: Request,
    session: DbSession,
) -> ExperimentCompareResponse:
    return service(request, session).compare_experiments(payload)
