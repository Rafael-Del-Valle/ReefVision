"""FastAPI application factory and default app instance."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from reefvision import __version__
from reefvision.api.router import api_router
from reefvision.config import Settings, get_settings
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.domain.errors import (
    ArtifactMissingError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from reefvision.jobs.worker import thumbnail_worker_loop
from reefvision.logging_utils import configure_rotating_json_logging, default_api_log_path
from reefvision.ml.advanced_inference_runtime import apply_advanced_inference_runtime_patch
from reefvision.ml.advanced_provider_runtime import apply_advanced_provider_runtime_patches
from reefvision.ml.advanced_training_catalog_runtime import apply_advanced_training_catalog_patch
from reefvision.ml.assist_runtime import AssistRuntime
from reefvision.ml.catalog_expansion import apply_catalog_expansion_runtime_patches
from reefvision.ml.dependencies import configure_provider_runtime
from reefvision.ml.fastsam_runtime_patch import apply_fastsam_runtime_patch
from reefvision.ml.native_unet_registration_runtime import apply_native_unet_registration_patch
from reefvision.ml.provider_contract import (
    ProviderCancelledError,
    ProviderLifecycleError,
    ProviderOutOfMemoryError,
    ProviderUnavailableError,
)
from reefvision.ml.provider_lifecycle import ProviderRuntimeManager
from reefvision.ml.sam_runtime_patch import apply_sam_runtime_patch
from reefvision.services.bundled_models import (
    install_bundled_catalog_models,
    reconcile_bundled_model_jobs,
)
from reefvision.services.bundled_transformers_models import (
    install_bundled_transformers_models,
)
from reefvision.services.model_catalog import validate_catalog_startup

LOGGER = logging.getLogger("reefvision.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    if active_settings.safe_mode:
        active_settings.background_worker_enabled = False
    active_settings.ensure_directories()
    os.environ["REEFVISION_CONFIG_DIR"] = str(active_settings.resolved_data_dir / "config")
    apply_catalog_expansion_runtime_patches()
    apply_fastsam_runtime_patch()
    apply_sam_runtime_patch()
    apply_advanced_provider_runtime_patches()
    apply_advanced_training_catalog_patch()
    apply_native_unet_registration_patch()
    apply_advanced_inference_runtime_patch()
    configure_rotating_json_logging(
        default_api_log_path(active_settings),
        default_component="api",
        max_bytes=active_settings.log_max_bytes,
        backup_count=active_settings.log_backup_count,
    )
    configure_provider_runtime(active_settings)
    catalog_startup_warnings = validate_catalog_startup()

    bundled_catalog_ids: list[str]
    bundled_transformers_models: dict[str, object]
    bundled_warnings: list[str]
    transformer_warnings: list[str]
    if active_settings.env == "test":
        bundled_catalog_ids = []
        bundled_transformers_models = {}
        bundled_warnings = []
        transformer_warnings = []
    else:
        bundled_catalog_ids, bundled_warnings = install_bundled_catalog_models(active_settings)
        bundled_transformers_models, transformer_warnings = install_bundled_transformers_models(
            active_settings
        )

    catalog_startup_warnings.extend(bundled_warnings)
    catalog_startup_warnings.extend(transformer_warnings)
    engine = create_database_engine(active_settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        reconcile_bundled_model_jobs(session_factory, bundled_catalog_ids)
        LOGGER.info(
            "ReefVision API starting",
            extra={
                "event_id": "api_startup",
                "component": "api",
                "data_dir": str(active_settings.resolved_data_dir),
                "bundled_catalog_model_count": len(bundled_catalog_ids),
                "bundled_transformers_model_count": len(bundled_transformers_models),
            },
        )
        stop_event = asyncio.Event()
        worker_task: asyncio.Task[None] | None = None
        if active_settings.background_worker_enabled:
            worker_task = asyncio.create_task(
                thumbnail_worker_loop(
                    active_settings, application.state.session_factory, stop_event
                )
            )
        try:
            yield
        finally:
            stop_event.set()
            if worker_task is not None:
                await worker_task
            application.state.provider_runtime.unload()
            engine.dispose()
            LOGGER.info(
                "ReefVision API stopped",
                extra={
                    "event_id": "api_shutdown",
                    "component": "api",
                    "data_dir": str(active_settings.resolved_data_dir),
                },
            )

    app = FastAPI(title="ReefVision API", version=__version__, lifespan=lifespan)
    app.state.settings = active_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.assist_runtime = AssistRuntime(active_settings)
    app.state.provider_runtime = ProviderRuntimeManager()
    app.state.catalog_startup_warnings = catalog_startup_warnings
    app.state.bundled_catalog_ids = bundled_catalog_ids
    app.state.bundled_transformers_models = bundled_transformers_models
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.allowed_web_origins,
        allow_origin_regex=active_settings.allowed_web_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(ArtifactMissingError)
    async def handle_missing_artifact(_: Request, exc: ArtifactMissingError) -> JSONResponse:
        LOGGER.warning(
            "Managed artifact missing",
            extra={
                "event_id": "api_artifact_missing",
                "component": "api",
                "error_code": "artifact_missing",
            },
        )
        return JSONResponse(status_code=410, content={"detail": str(exc)})

    @app.exception_handler(ProviderLifecycleError)
    async def handle_provider_failure(_: Request, exc: ProviderLifecycleError) -> JSONResponse:
        if isinstance(exc, ProviderOutOfMemoryError):
            status_code = 507
        elif isinstance(exc, ProviderUnavailableError):
            status_code = 503
        elif isinstance(exc, ProviderCancelledError):
            status_code = 409
        else:
            status_code = 422
        LOGGER.warning(
            "Provider lifecycle failure",
            extra={
                "event_id": "provider_lifecycle_failure",
                "component": "provider",
                "error_code": exc.code,
            },
        )
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        LOGGER.warning(
            "Resource not found",
            extra={"event_id": "api_not_found", "component": "api", "error_code": "not_found"},
        )
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def handle_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        LOGGER.warning(
            "Request conflict",
            extra={"event_id": "api_conflict", "component": "api", "error_code": "conflict"},
        )
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def handle_validation(_: Request, exc: ValidationError) -> JSONResponse:
        LOGGER.warning(
            "Validation failed",
            extra={
                "event_id": "api_validation_error",
                "component": "api",
                "error_code": "validation_error",
            },
        )
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(api_router)
    return app


app = create_app()
