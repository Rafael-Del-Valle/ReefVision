"""Unified provider discovery, lifecycle, and acceptance endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.ml.provider_lifecycle import ProviderRuntimeManager
from reefvision.schemas.provider_lifecycle import (
    ProviderAcceptanceRecordListResponse,
    ProviderCancelResponse,
    ProviderDeviceRequest,
    ProviderDiscoveryResponse,
    ProviderHealthRequest,
    ProviderInferenceRequest,
    ProviderInferenceResponse,
    ProviderLifecycleActionResponse,
    ProviderMetadataRepairRequest,
    ProviderModelAssetListResponse,
    ProviderModelAssetResponse,
    TrustedExternalModelRegisterRequest,
)
from reefvision.services.provider_lifecycle import ProviderLifecycleService

router = APIRouter(tags=["provider-lifecycle"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ProviderLifecycleService:
    settings: Settings = request.app.state.settings
    runtime: ProviderRuntimeManager = request.app.state.provider_runtime
    return ProviderLifecycleService(session, settings, runtime)


@router.post(
    "/provider-models/discover",
    response_model=ProviderDiscoveryResponse,
)
def discover_provider_models(
    request: Request,
    session: DbSession,
) -> ProviderDiscoveryResponse:
    """Reconcile the managed manifest and restart-safe external registrations."""

    return service(request, session).discover()


@router.post(
    "/provider-models/external",
    response_model=ProviderModelAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_trusted_external_model(
    payload: TrustedExternalModelRegisterRequest,
    request: Request,
    session: DbSession,
) -> ProviderModelAssetResponse:
    """Register an external checkpoint in place without copying or modifying it."""

    return service(request, session).register_external(payload)


@router.get(
    "/provider-models",
    response_model=ProviderModelAssetListResponse,
)
def list_provider_models(
    request: Request,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    provider_id: str | None = Query(default=None, min_length=1, max_length=100),
    state: str | None = Query(default=None, min_length=1, max_length=30),
) -> ProviderModelAssetListResponse:
    return service(request, session).list_assets(
        limit=limit,
        offset=offset,
        provider_id=provider_id,
        state=state,
    )


@router.get(
    "/provider-models/{asset_id}",
    response_model=ProviderModelAssetResponse,
)
def get_provider_model(
    asset_id: str,
    request: Request,
    session: DbSession,
) -> ProviderModelAssetResponse:
    return service(request, session).get(asset_id)


@router.post(
    "/provider-models/{asset_id}/verify",
    response_model=ProviderLifecycleActionResponse,
)
def verify_provider_model(
    asset_id: str,
    request: Request,
    session: DbSession,
) -> ProviderLifecycleActionResponse:
    return service(request, session).verify(asset_id)


@router.post(
    "/provider-models/{asset_id}/diagnose",
    response_model=ProviderLifecycleActionResponse,
)
def diagnose_provider_model(
    asset_id: str,
    payload: ProviderDeviceRequest,
    request: Request,
    session: DbSession,
) -> ProviderLifecycleActionResponse:
    return service(request, session).diagnose(asset_id, payload.device)


@router.post(
    "/provider-models/{asset_id}/load",
    response_model=ProviderLifecycleActionResponse,
)
def load_provider_model(
    asset_id: str,
    payload: ProviderDeviceRequest,
    request: Request,
    session: DbSession,
) -> ProviderLifecycleActionResponse:
    return service(request, session).load(asset_id, payload.device)


@router.post(
    "/provider-models/{asset_id}/health-check",
    response_model=ProviderLifecycleActionResponse,
)
def health_check_provider_model(
    asset_id: str,
    payload: ProviderHealthRequest,
    request: Request,
    session: DbSession,
) -> ProviderLifecycleActionResponse:
    return service(request, session).health_check(
        asset_id,
        device=payload.device,
        kind=payload.kind,
        keep_loaded=payload.keep_loaded,
    )


@router.post(
    "/provider-models/{asset_id}/infer",
    response_model=ProviderInferenceResponse,
)
def infer_provider_model(
    asset_id: str,
    payload: ProviderInferenceRequest,
    request: Request,
    session: DbSession,
) -> ProviderInferenceResponse:
    return service(request, session).infer(asset_id, payload)


@router.post(
    "/provider-requests/{request_id}/cancel",
    response_model=ProviderCancelResponse,
)
def cancel_provider_request(
    request_id: str,
    request: Request,
    session: DbSession,
) -> ProviderCancelResponse:
    return service(request, session).cancel(request_id)


@router.post(
    "/provider-models/{asset_id}/unload",
    response_model=ProviderLifecycleActionResponse,
)
def unload_provider_model(
    asset_id: str,
    request: Request,
    session: DbSession,
) -> ProviderLifecycleActionResponse:
    return service(request, session).unload(asset_id)


@router.post(
    "/provider-models/{asset_id}/repair-metadata",
    response_model=ProviderModelAssetResponse,
)
def repair_provider_metadata(
    asset_id: str,
    payload: ProviderMetadataRepairRequest,
    request: Request,
    session: DbSession,
) -> ProviderModelAssetResponse:
    return service(request, session).repair_metadata(asset_id, confirmed=payload.confirmed)


@router.get(
    "/provider-acceptance-records",
    response_model=ProviderAcceptanceRecordListResponse,
)
def list_provider_acceptance_records(
    request: Request,
    session: DbSession,
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProviderAcceptanceRecordListResponse:
    return service(request, session).acceptance_records(
        asset_id=asset_id,
        limit=limit,
        offset=offset,
    )
