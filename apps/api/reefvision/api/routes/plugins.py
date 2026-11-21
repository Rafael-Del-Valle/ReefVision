"""Install a local capability and run it on a deliberately selected project image."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.ml.plugin_worker import run_plugin
from reefvision.schemas.plugins import (
    PluginMeasurementPin,
    PluginPackage,
    PluginPage,
    PluginRecord,
    PluginStateChange,
)
from reefvision.schemas.scientific_data import ScientificRecordPage, ScientificRecordResponse
from reefvision.services.plugin_measurements import PluginMeasurementService
from reefvision.storage.plugins import PluginStorage

router = APIRouter(tags=["plugins"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("/plugins")
def list_plugins(
    request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
) -> PluginPage:
    return PluginStorage(request.app.state.settings).page(limit=limit, offset=offset)


@router.post("/plugins", status_code=201)
def install_plugin(request: Request, package: PluginPackage) -> PluginRecord:
    module = package.module_bytes()
    run_plugin(module)
    return PluginStorage(request.app.state.settings).install(package.manifest, module)


@router.patch("/plugins/{record_id}")
def set_plugin_state(record_id: UUID, change: PluginStateChange, request: Request) -> PluginRecord:
    return PluginStorage(request.app.state.settings).set_enabled(
        record_id, change.package_sha256, change.enabled
    )


@router.post("/projects/{project_id}/plugin-measurements")
def measure(
    project_id: UUID, pin: PluginMeasurementPin, request: Request, session: DbSession
) -> ScientificRecordResponse:
    result = PluginMeasurementService(session, request.app.state.settings).measure(project_id, pin)
    session.commit()
    return result


@router.get("/projects/{project_id}/plugin-measurements")
def history(
    project_id: UUID,
    request: Request,
    session: DbSession,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ScientificRecordPage:
    return PluginMeasurementService(session, request.app.state.settings).history(
        project_id, limit, offset
    )
