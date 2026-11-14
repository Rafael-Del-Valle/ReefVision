"""Scientist review and exports of projected coral graphs."""

import csv
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models.coral_graph import (
    CoralBranchCorrespondenceRevision,
    CoralGraphRevision,
    CoralGrowthRecord,
)
from reefvision.schemas.coral_graph import (
    CorrespondenceRecord,
    CorrespondenceReview,
    GraphRecord,
    GraphReview,
    GrowthChange,
    GrowthRecord,
    GrowthRequest,
)
from reefvision.services.coral_graph import CoralGraphService

router = APIRouter(prefix="/projects/{project_id}/ecology", tags=["reviewed coral graphs"])
DbSession = Annotated[Session, Depends(get_db_session)]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0)]


@router.get("/coral-graphs")
def list_graphs(
    project_id: UUID,
    request: Request,
    session: DbSession,
    analysis_id: UUID | None = None,
    mask_id: UUID | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> list[GraphRecord]:
    return CoralGraphService(session, request.app.state.settings).list_graphs(
        str(project_id),
        analysis_id=str(analysis_id) if analysis_id else None,
        limit=limit,
        offset=offset,
        mask_id=str(mask_id) if mask_id else None,
    )


@router.post("/coral-graphs", status_code=201)
def review_graph(
    project_id: UUID, payload: GraphReview, request: Request, session: DbSession
) -> GraphRecord:
    return CoralGraphService(session, request.app.state.settings).review_graph(
        str(project_id), payload
    )


@router.get("/coral-graphs/{revision_id}")
def get_graph(
    project_id: UUID, revision_id: UUID, request: Request, session: DbSession
) -> GraphRecord:
    service = CoralGraphService(session, request.app.state.settings)
    return service.graph_record(
        service.owned(CoralGraphRevision, str(project_id), str(revision_id))
    )


@router.get("/coral-graphs/{revision_id}/measurements.csv")
def export_graph(
    project_id: UUID, revision_id: UUID, request: Request, session: DbSession
) -> Response:
    graph = get_graph(project_id, revision_id, request, session)
    snapshot = graph.snapshot
    stream = StringIO(newline="")
    output = csv.writer(stream)
    output.writerow(
        [
            "project_id",
            "colony",
            "graph_id",
            "graph_revision_id",
            "review_decision",
            "current",
            "source_image_id",
            "observed_at",
            "analysis_id",
            "mask_revision",
            "graph_sha256",
            "calibration_sha256",
            "method",
            "qc",
            "branch_id",
            "source_junction_id",
            "target_junction_id",
            "length_px",
            "length_2d",
            "total_px",
            "total_2d",
            "unit",
            "reviewer",
            "reviewed_at",
        ]
    )
    for edge in snapshot.edges:
        output.writerow(
            [
                graph.project_id,
                snapshot.organism_key,
                graph.graph_id,
                graph.id,
                graph.decision,
                graph.current,
                snapshot.image_id,
                snapshot.observed_at.isoformat(),
                graph.analysis_id,
                snapshot.mask_revision,
                graph.content_sha256,
                snapshot.calibration_sha256,
                snapshot.method,
                "|".join(snapshot.qc),
                edge.id,
                edge.source_node_id,
                edge.target_node_id,
                edge.node_to_node_length_pixels,
                edge.length_physical,
                snapshot.total_pixels,
                snapshot.total_physical,
                snapshot.calibration.unit if snapshot.calibration else None,
                graph.reviewer,
                graph.created_at.isoformat(),
            ]
        )
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="coral-branches.csv"'},
    )


@router.get("/coral-correspondences")
def list_correspondence(
    project_id: UUID,
    request: Request,
    session: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> list[CorrespondenceRecord]:
    return CoralGraphService(session, request.app.state.settings).list_correspondences(
        str(project_id), limit=limit, offset=offset
    )


@router.post("/coral-correspondences", status_code=201)
def review_correspondence(
    project_id: UUID, payload: CorrespondenceReview, request: Request, session: DbSession
) -> CorrespondenceRecord:
    return CoralGraphService(session, request.app.state.settings).review_correspondence(
        str(project_id), payload
    )


@router.get("/coral-correspondences/{revision_id}")
def get_correspondence(
    project_id: UUID, revision_id: UUID, request: Request, session: DbSession
) -> CorrespondenceRecord:
    service = CoralGraphService(session, request.app.state.settings)
    return service.correspondence_record(
        service.owned(CoralBranchCorrespondenceRevision, str(project_id), str(revision_id))
    )


@router.get("/coral-growth")
def list_growth(
    project_id: UUID,
    request: Request,
    session: DbSession,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> list[GrowthRecord]:
    return CoralGraphService(session, request.app.state.settings).list_growth(
        str(project_id), limit=limit, offset=offset
    )


@router.post("/coral-growth", status_code=201)
def save_growth(
    project_id: UUID, payload: GrowthRequest, request: Request, session: DbSession
) -> GrowthRecord:
    return CoralGraphService(session, request.app.state.settings).save_growth(
        str(project_id), str(payload.correspondence_revision_id)
    )


@router.get("/coral-growth/{record_id}")
def get_growth(
    project_id: UUID, record_id: UUID, request: Request, session: DbSession
) -> GrowthRecord:
    service = CoralGraphService(session, request.app.state.settings)
    return service.growth_record(service.owned(CoralGrowthRecord, str(project_id), str(record_id)))


@router.get("/coral-growth/{record_id}/results.csv")
def export_growth(
    project_id: UUID, record_id: UUID, request: Request, session: DbSession
) -> Response:
    growth = get_growth(project_id, record_id, request, session)
    result = growth.snapshot
    stream = StringIO(newline="")
    output = csv.writer(stream)
    output.writerow(
        [
            "project_id",
            "colony",
            "record_id",
            "correspondence_revision_id",
            "result_sha256",
            "earlier_date",
            "later_date",
            "elapsed_days",
            "unit",
            "method",
            "stale_reasons",
            "status",
            "earlier_branch_ids",
            "later_branch_ids",
            "earlier_length",
            "later_length",
            "absolute_change",
            "change_per_day",
        ]
    )
    context = [
        growth.project_id,
        result.organism_key,
        growth.id,
        growth.correspondence_revision_id,
        growth.content_sha256,
        result.earlier_observed_at.isoformat(),
        result.later_observed_at.isoformat(),
        result.elapsed_days,
        result.unit,
        result.method,
        "|".join(growth.stale_reasons),
    ]
    rows: list[tuple[str, list[str], list[str], GrowthChange | None]] = [
        ("total" if result.total else "total_withheld", [], [], result.total)
    ]
    rows.extend(
        (row.status, row.earlier_branch_ids, row.later_branch_ids, row.change)
        for row in result.branches
    )
    for status, earlier, later, change in rows:
        output.writerow(
            [
                *context,
                status,
                "|".join(earlier),
                "|".join(later),
                *(list(change.model_dump().values()) if change else [None] * 4),
            ]
        )
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="coral-growth.csv"'},
    )
