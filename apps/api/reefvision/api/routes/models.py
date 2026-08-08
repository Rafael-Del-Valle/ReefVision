"""Model registration and inference endpoints."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.ml.dependencies import (
    ProviderPreflightReport,
    cached_lightweight_provider_preflight,
)
from reefvision.ml.provider_hub import (
    cached_model_provider_catalog,
    cached_runtime_provider_statuses,
    get_model_provider,
    get_model_provider_capabilities,
)
from reefvision.ml.segmentation_provider_catalog import (
    segmentation_capability_matrix,
    segmentation_provider_descriptor,
)
from reefvision.ml.ultralytics_registry import (
    cached_ultralytics_training_registry_summary,
    ultralytics_training_registry,
    validate_ultralytics_training_configuration,
)
from reefvision.schemas.bootstrap import (
    UltralyticsTrainingRegistrySummarySnapshotResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.models import (
    InferenceJobCreateRequest,
    ModelProviderCapabilityMatrixResponse,
    ModelProviderResponse,
    ModelRegistrationResponse,
    ProviderDependencyPackageResponse,
    ProviderDependencyPreflightResponse,
    ProviderDependencyStatusResponse,
    RegisterModelFromRunRequest,
    RuntimeProviderStatusResponse,
    UltralyticsTrainingConfigurationValidationRequest,
    UltralyticsTrainingConfigurationValidationResponse,
    UltralyticsTrainingRegistryResponse,
)
from reefvision.services.semantic_models import SemanticModelService

router = APIRouter(tags=["models"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SemanticModelService:
    return SemanticModelService(session, request.app.state.settings)


@router.get(
    "/models/provider-preflight",
    response_model=ProviderDependencyPreflightResponse,
)
def get_provider_preflight(
    request: Request,
    refresh: bool = False,
) -> ProviderDependencyPreflightResponse:
    return _serialize_provider_preflight(
        cached_lightweight_provider_preflight(
            request.app.state.settings,
            refresh=refresh,
        ).value
    )


@router.get("/model-providers", response_model=list[ModelProviderResponse])
def get_model_providers(
    request: Request,
    refresh: bool = False,
) -> list[ModelProviderResponse]:
    return [
        ModelProviderResponse.model_validate(asdict(segmentation_provider_descriptor(item)))
        for item in cached_model_provider_catalog(
            request.app.state.settings,
            refresh=refresh,
        ).value
    ]


@router.get(
    "/model-providers/{provider_id}",
    response_model=ModelProviderResponse,
)
def get_model_provider_detail(
    provider_id: str,
    request: Request,
) -> ModelProviderResponse:
    provider = get_model_provider(provider_id, request.app.state.settings)
    return ModelProviderResponse.model_validate(asdict(segmentation_provider_descriptor(provider)))


@router.get(
    "/model-providers/{provider_id}/capabilities",
    response_model=ModelProviderCapabilityMatrixResponse,
)
def get_model_provider_capability_detail(
    provider_id: str,
    request: Request,
) -> ModelProviderCapabilityMatrixResponse:
    capabilities = get_model_provider_capabilities(
        provider_id,
        request.app.state.settings,
    )
    return ModelProviderCapabilityMatrixResponse.model_validate(
        asdict(segmentation_capability_matrix(provider_id, capabilities))
    )


@router.get(
    "/runtime-providers/status",
    response_model=list[RuntimeProviderStatusResponse],
)
def get_runtime_provider_statuses(
    refresh: bool = False,
) -> list[RuntimeProviderStatusResponse]:
    return [
        RuntimeProviderStatusResponse.model_validate(asdict(item))
        for item in cached_runtime_provider_statuses(refresh=refresh).value
    ]


@router.get(
    "/models/ultralytics/training-registry/summary",
    response_model=UltralyticsTrainingRegistrySummarySnapshotResponse,
)
def get_ultralytics_training_registry_summary(
    request: Request,
    refresh: bool = False,
) -> UltralyticsTrainingRegistrySummarySnapshotResponse:
    return UltralyticsTrainingRegistrySummarySnapshotResponse.model_validate(
        cached_ultralytics_training_registry_summary(
            request.app.state.settings,
            refresh=refresh,
        ).value,
        from_attributes=True,
    )


@router.get(
    "/models/ultralytics/training-registry",
    response_model=UltralyticsTrainingRegistryResponse,
)
def get_ultralytics_training_registry(
    request: Request,
) -> UltralyticsTrainingRegistryResponse:
    return UltralyticsTrainingRegistryResponse.model_validate(
        ultralytics_training_registry(request.app.state.settings),
        from_attributes=True,
    )


@router.post(
    "/models/ultralytics/training-registry/validate",
    response_model=UltralyticsTrainingConfigurationValidationResponse,
)
def validate_ultralytics_training_registry(
    payload: UltralyticsTrainingConfigurationValidationRequest,
    request: Request,
) -> UltralyticsTrainingConfigurationValidationResponse:
    result = validate_ultralytics_training_configuration(
        task=payload.task,
        mode=payload.mode,
        parameters=payload.parameters,
        search_space=[item.model_dump() for item in payload.search_space],
        expected_ultralytics_version=payload.expected_ultralytics_version,
        settings=request.app.state.settings,
    )
    return UltralyticsTrainingConfigurationValidationResponse.model_validate(
        result,
        from_attributes=True,
    )


@router.get(
    "/projects/{project_id}/models",
    response_model=list[ModelRegistrationResponse],
)
def list_models(
    project_id: str,
    request: Request,
    session: DbSession,
    purpose: str | None = None,
) -> list[ModelRegistrationResponse]:
    return service(request, session).list_models(project_id, purpose=purpose)


@router.get("/models/{model_id}", response_model=ModelRegistrationResponse)
def get_model(
    model_id: str,
    request: Request,
    session: DbSession,
) -> ModelRegistrationResponse:
    return service(request, session).get_model(model_id)


@router.post(
    "/projects/{project_id}/models/register",
    response_model=ModelRegistrationResponse,
)
async def register_model(
    project_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    purpose: Annotated[str, Form(...)],
    provider_name: Annotated[str | None, Form()] = None,
    display_name: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> ModelRegistrationResponse:
    return service(request, session).register_model_upload(
        project_id,
        purpose=purpose,
        provider_name=provider_name,
        upload_filename=file.filename,
        upload_stream=file.file,
        display_name=display_name,
        notes=notes,
    )


@router.post(
    "/projects/{project_id}/models/register-from-run",
    response_model=ModelRegistrationResponse,
)
def register_model_from_run(
    project_id: str,
    payload: RegisterModelFromRunRequest,
    request: Request,
    session: DbSession,
) -> ModelRegistrationResponse:
    return service(request, session).register_model_from_run(project_id, payload)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(
    model_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_model(model_id)


@router.post(
    "/projects/{project_id}/inference-jobs",
    response_model=JobResponse,
)
def create_inference_job(
    project_id: str,
    payload: InferenceJobCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return service(request, session).create_inference_job(project_id, payload)


def _serialize_provider_preflight(
    reports: list[ProviderPreflightReport],
) -> ProviderDependencyPreflightResponse:
    return ProviderDependencyPreflightResponse(
        providers=[
            ProviderDependencyStatusResponse(
                provider_name=report.provider_name,
                display_name=report.display_name,
                purpose=report.purpose,
                provider_version=report.provider_version,
                status=report.status,
                ready=report.ready,
                tested_python=report.tested_python,
                current_python=report.current_python,
                tested_platform=report.tested_platform,
                current_platform=report.current_platform,
                tested_cuda=report.tested_cuda,
                current_cuda=report.current_cuda,
                automatic_downloads_disabled=report.automatic_downloads_disabled,
                explicit_checkpoint_required=report.explicit_checkpoint_required,
                requirements_file=report.requirements_file,
                issues=list(report.issues),
                packages=[
                    ProviderDependencyPackageResponse(
                        distribution_name=item.distribution_name,
                        required_version=item.required_version,
                        installed_version=item.installed_version,
                        status=item.status,
                    )
                    for item in report.package_statuses
                ],
            )
            for report in reports
        ]
    )
