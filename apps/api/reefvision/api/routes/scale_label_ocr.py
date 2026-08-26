"""Printed scale-label OCR proposal endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.scale_label_ocr import ScaleLabelOcrCandidate, ScaleLabelOcrRequest
from reefvision.services.scale_label_ocr import ScaleLabelOcrService

router = APIRouter(tags=["measurements"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/images/{image_id}/scale-label-ocr", response_model=ScaleLabelOcrCandidate)
def detect_scale_label_ocr(
    image_id: str,
    payload: ScaleLabelOcrRequest,
    request: Request,
    session: DbSession,
) -> ScaleLabelOcrCandidate:
    return ScaleLabelOcrService(session, request.app.state.settings).detect(image_id, payload)
