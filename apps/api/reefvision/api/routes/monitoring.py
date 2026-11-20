"""Project-scoped monitoring and append-only decisions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.monitoring import (
    MonitoringAlertPage,
    MonitoringAlertRead,
    MonitoringAlertReviewCreate,
    MonitoringAlertReviewPage,
    MonitoringAlertReviewRead,
    MonitoringAssessmentCreate,
    MonitoringAssessmentPage,
    MonitoringAssessmentRead,
    MonitoringRuleCreate,
    MonitoringRulePage,
    MonitoringRuleRead,
)
from reefvision.services.monitoring import MonitoringService

router = APIRouter(prefix="/projects/{project_id}/monitoring", tags=["monitoring"])
DbSession = Annotated[Session, Depends(get_db_session)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def service(request: Request, session: DbSession) -> MonitoringService:
    return MonitoringService(session, request.app.state.settings)


Monitor = Annotated[MonitoringService, Depends(service)]


@router.get("/rules", response_model=MonitoringRulePage)
def list_rules(
    project_id: UUID, monitoring: Monitor, limit: PageLimit = 50, offset: PageOffset = 0
) -> MonitoringRulePage:
    return monitoring.list_rules(str(project_id), limit=limit, offset=offset)


@router.get("/rules/{rule_id}", response_model=MonitoringRuleRead)
def get_rule(project_id: UUID, rule_id: UUID, monitoring: Monitor) -> MonitoringRuleRead:
    return monitoring.get_rule(str(project_id), str(rule_id))


@router.post("/rules", response_model=MonitoringRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    project_id: UUID, payload: MonitoringRuleCreate, monitoring: Monitor
) -> MonitoringRuleRead:
    record = monitoring.create_rule(str(project_id), payload)
    monitoring.session.commit()
    return record


@router.get("/assessments", response_model=MonitoringAssessmentPage)
def list_assessments(
    project_id: UUID,
    monitoring: Monitor,
    rule_id: UUID | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> MonitoringAssessmentPage:
    return monitoring.list_assessments(
        str(project_id), rule_id=str(rule_id) if rule_id else None, limit=limit, offset=offset
    )


@router.get("/assessments/{assessment_id}", response_model=MonitoringAssessmentRead)
def get_assessment(
    project_id: UUID, assessment_id: UUID, monitoring: Monitor
) -> MonitoringAssessmentRead:
    return monitoring.get_assessment(str(project_id), str(assessment_id))


@router.post(
    "/assessments", response_model=MonitoringAssessmentRead, status_code=status.HTTP_201_CREATED
)
def create_assessment(
    project_id: UUID, payload: MonitoringAssessmentCreate, monitoring: Monitor
) -> MonitoringAssessmentRead:
    record = monitoring.create_assessment(str(project_id), payload)
    monitoring.session.commit()
    return record


@router.get("/alerts", response_model=MonitoringAlertPage)
def list_alerts(
    project_id: UUID,
    monitoring: Monitor,
    assessment_id: UUID | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> MonitoringAlertPage:
    return monitoring.list_alerts(
        str(project_id),
        assessment_id=str(assessment_id) if assessment_id else None,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts/{alert_id}", response_model=MonitoringAlertRead)
def get_alert(project_id: UUID, alert_id: UUID, monitoring: Monitor) -> MonitoringAlertRead:
    return monitoring.get_alert(str(project_id), str(alert_id))


@router.get("/alerts/{alert_id}/reviews", response_model=MonitoringAlertReviewPage)
def list_reviews(
    project_id: UUID,
    alert_id: UUID,
    monitoring: Monitor,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> MonitoringAlertReviewPage:
    return monitoring.list_reviews(str(project_id), str(alert_id), limit=limit, offset=offset)


@router.post(
    "/alerts/{alert_id}/reviews",
    response_model=MonitoringAlertReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def review_alert(
    project_id: UUID, alert_id: UUID, payload: MonitoringAlertReviewCreate, monitoring: Monitor
) -> MonitoringAlertReviewRead:
    review = monitoring.review_alert(str(project_id), str(alert_id), payload)
    monitoring.session.commit()
    return review
