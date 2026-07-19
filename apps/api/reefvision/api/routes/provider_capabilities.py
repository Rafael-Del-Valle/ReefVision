"""Unified provider readiness and benchmark endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.provider_benchmark_jobs import (
    ProviderBenchmarkRunRequest,
    ProviderBenchmarkRunResponse,
)
from reefvision.schemas.provider_capabilities import (
    ProviderBenchmarkComparisonResponse,
    ProviderBenchmarkCreateRequest,
    ProviderBenchmarkRecord,
    ProviderCapabilityListResponse,
    ProviderCapabilityResponse,
)
from reefvision.services.provider_benchmark_jobs import ProviderBenchmarkJobService
from reefvision.services.provider_capabilities import ProviderCapabilityService

router = APIRouter(tags=["provider-capabilities"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ProviderCapabilityService:
    settings: Settings = request.app.state.settings
    return ProviderCapabilityService(session, settings)


@router.get("/provider-capabilities", response_model=ProviderCapabilityListResponse)
def list_provider_capabilities(
    request: Request,
    session: DbSession,
) -> ProviderCapabilityListResponse:
    """Return dependency, device, model-asset, and benchmark health for every provider."""

    return service(request, session).list()


@router.get(
    "/provider-capabilities/{provider_id}",
    response_model=ProviderCapabilityResponse,
)
def get_provider_capability(
    provider_id: str,
    request: Request,
    session: DbSession,
) -> ProviderCapabilityResponse:
    """Return the detailed readiness record for one provider."""

    return service(request, session).get(provider_id)


@router.post(
    "/provider-benchmarks",
    response_model=ProviderBenchmarkRecord,
    status_code=status.HTTP_201_CREATED,
)
def record_provider_benchmark(
    payload: ProviderBenchmarkCreateRequest,
    request: Request,
    session: DbSession,
) -> ProviderBenchmarkRecord:
    """Persist a benchmark produced by an accepted provider execution."""

    return service(request, session).record_benchmark(payload)


@router.post(
    "/provider-benchmarks/runs",
    response_model=ProviderBenchmarkRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_provider_benchmark(
    payload: ProviderBenchmarkRunRequest,
    request: Request,
    session: DbSession,
) -> ProviderBenchmarkRunResponse:
    """Queue a provider benchmark that executes through the restart-aware worker."""

    settings: Settings = request.app.state.settings
    return ProviderBenchmarkJobService(session, settings).queue(payload)


@router.get(
    "/provider-benchmarks/compare",
    response_model=ProviderBenchmarkComparisonResponse,
)
def compare_provider_benchmarks(
    request: Request,
    session: DbSession,
    provider_id: str | None = Query(default=None, min_length=1, max_length=100),
    task: str | None = Query(default=None, min_length=1, max_length=100),
) -> ProviderBenchmarkComparisonResponse:
    """Compare persisted provider benchmarks by throughput and peak VRAM."""

    return service(request, session).compare_benchmarks(
        provider_id=provider_id,
        task=task,
    )
