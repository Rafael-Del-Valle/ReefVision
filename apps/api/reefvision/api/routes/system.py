"""System-information and migration-status endpoints."""

import platform
import sys

from fastapi import APIRouter, Request
from sqlalchemy.engine import Engine

from reefvision.config import Settings
from reefvision.schemas.offline_update import OfflineUpdateReport, OfflineUpdateRequest
from reefvision.schemas.system import (
    SystemCommandShortcutRepairResponse,
    SystemCommandShortcutStatusResponse,
    SystemCompatibilityResponse,
    SystemDiagnosticsCreateRequest,
    SystemDiagnosticsCreateResponse,
    SystemDiagnosticsStatusResponse,
    SystemLogsLocationResponse,
    SystemMigrationPreflightResponse,
    SystemMigrationStatusResponse,
    SystemVersionResponse,
)
from reefvision.schemas.system_machine import SystemMachineCompatibilityResponse
from reefvision.services.system import SystemService
from reefvision.storage.offline_update import inspect_offline_update

router = APIRouter(tags=["system"])


def service(request: Request) -> SystemService:
    settings: Settings = request.app.state.settings
    engine: Engine = request.app.state.engine
    return SystemService(settings, engine)


@router.get("/system/version", response_model=SystemVersionResponse)
def get_system_version(request: Request) -> SystemVersionResponse:
    return service(request).version()


@router.get("/system/compatibility", response_model=SystemCompatibilityResponse)
def get_system_compatibility(request: Request) -> SystemCompatibilityResponse:
    return service(request).compatibility()


@router.get(
    "/system/compatibility/machine",
    response_model=SystemMachineCompatibilityResponse,
)
def get_system_machine_compatibility() -> SystemMachineCompatibilityResponse:
    return SystemMachineCompatibilityResponse(
        operating_system=platform.system(),
        os_release=platform.release(),
        os_version=platform.version(),
        architecture=platform.machine(),
        packaged_backend=bool(getattr(sys, "frozen", False)),
    )


@router.get("/system/logs/location", response_model=SystemLogsLocationResponse)
def get_logs_location(request: Request) -> SystemLogsLocationResponse:
    return service(request).logs_location()


@router.get(
    "/system/command-shortcuts",
    response_model=SystemCommandShortcutStatusResponse,
)
def get_command_shortcuts(request: Request) -> SystemCommandShortcutStatusResponse:
    return service(request).command_shortcut_status()


@router.post(
    "/system/command-shortcuts/repair",
    response_model=SystemCommandShortcutRepairResponse,
)
def repair_command_shortcuts(request: Request) -> SystemCommandShortcutRepairResponse:
    return service(request).repair_command_shortcuts()


@router.post("/system/diagnostics", response_model=SystemDiagnosticsCreateResponse)
def create_diagnostics(
    payload: SystemDiagnosticsCreateRequest,
    request: Request,
) -> SystemDiagnosticsCreateResponse:
    return service(request).create_diagnostics(payload)


@router.get("/system/diagnostics/{job_id}", response_model=SystemDiagnosticsStatusResponse)
def get_diagnostics(request: Request, job_id: str) -> SystemDiagnosticsStatusResponse:
    return service(request).diagnostics_status(job_id)


@router.get("/system/migrations/status", response_model=SystemMigrationStatusResponse)
def get_migration_status(request: Request) -> SystemMigrationStatusResponse:
    return service(request).migration_status()


@router.post("/system/migrations/preflight", response_model=SystemMigrationPreflightResponse)
def post_migration_preflight(request: Request) -> SystemMigrationPreflightResponse:
    return service(request).migration_preflight()


@router.post("/system/updates/inspect", response_model=OfflineUpdateReport)
def inspect_update_media(payload: OfflineUpdateRequest) -> OfflineUpdateReport:
    return inspect_offline_update(payload)
