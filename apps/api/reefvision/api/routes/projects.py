"""Project and label-class endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.projects import (
    LabelClassCreate,
    LabelClassMergeRequest,
    LabelClassMergeResponse,
    LabelClassResponse,
    LabelClassUpdate,
    LabelClassUsageResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdate,
)
from reefvision.services.projects import ProjectService

router = APIRouter(tags=["projects"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ProjectService:
    settings: Settings = request.app.state.settings
    return ProjectService(session, settings)


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request, session: DbSession) -> ProjectResponse:
    return ProjectResponse.model_validate(service(request, session).create_project(payload))


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    request: Request,
    session: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ProjectResponse]:
    projects = service(request, session).list_projects(include_archived=include_archived)
    return [ProjectResponse.model_validate(project) for project in projects]


@router.get("/project-summaries", response_model=list[ProjectSummaryResponse])
def list_project_summaries(
    request: Request,
    session: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ProjectSummaryResponse]:
    return service(request, session).list_project_summaries(include_archived=include_archived)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, request: Request, session: DbSession) -> ProjectResponse:
    return ProjectResponse.model_validate(service(request, session).get_project(project_id))


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str, payload: ProjectUpdate, request: Request, session: DbSession
) -> ProjectResponse:
    project = service(request, session).update_project(project_id, payload)
    return ProjectResponse.model_validate(project)


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
def archive_project(project_id: str, request: Request, session: DbSession) -> ProjectResponse:
    return ProjectResponse.model_validate(service(request, session).archive_project(project_id))


@router.get("/projects/{project_id}/classes", response_model=list[LabelClassResponse])
def list_classes(project_id: str, request: Request, session: DbSession) -> list[LabelClassResponse]:
    classes = service(request, session).list_classes(project_id)
    return [LabelClassResponse.model_validate(item) for item in classes]


@router.post(
    "/projects/{project_id}/classes",
    response_model=LabelClassResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_class(
    project_id: str,
    payload: LabelClassCreate,
    request: Request,
    session: DbSession,
) -> LabelClassResponse:
    return LabelClassResponse.model_validate(
        service(request, session).create_class(project_id, payload)
    )


@router.patch("/classes/{class_id}", response_model=LabelClassResponse)
def update_class(
    class_id: str,
    payload: LabelClassUpdate,
    request: Request,
    session: DbSession,
) -> LabelClassResponse:
    label_class = service(request, session).update_class(class_id, payload)
    return LabelClassResponse.model_validate(label_class)


@router.post("/classes/{class_id}/deactivate", response_model=LabelClassResponse)
def deactivate_class(class_id: str, request: Request, session: DbSession) -> LabelClassResponse:
    return LabelClassResponse.model_validate(service(request, session).deactivate_class(class_id))


@router.post("/classes/{class_id}/archive", response_model=LabelClassResponse)
def archive_class(class_id: str, request: Request, session: DbSession) -> LabelClassResponse:
    return LabelClassResponse.model_validate(service(request, session).archive_class(class_id))


@router.post("/classes/{class_id}/restore", response_model=LabelClassResponse)
def restore_class(class_id: str, request: Request, session: DbSession) -> LabelClassResponse:
    return LabelClassResponse.model_validate(service(request, session).restore_class(class_id))


@router.get("/classes/{class_id}/usage", response_model=LabelClassUsageResponse)
def class_usage(class_id: str, request: Request, session: DbSession) -> LabelClassUsageResponse:
    return service(request, session).usage_for_class(class_id)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class(class_id: str, request: Request, session: DbSession) -> None:
    service(request, session).delete_class(class_id)


@router.post("/classes/{class_id}/merge", response_model=LabelClassMergeResponse)
def merge_class(
    class_id: str,
    payload: LabelClassMergeRequest,
    request: Request,
    session: DbSession,
) -> LabelClassMergeResponse:
    return service(request, session).merge_class(class_id, payload)
