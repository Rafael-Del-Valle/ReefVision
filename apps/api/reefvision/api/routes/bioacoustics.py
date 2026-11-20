"""Project-scoped recording and bioacoustic review routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.bioacoustics import (
    AudioAnchorCreate,
    AudioAnchorRead,
    AudioAssetRead,
    AudioPage,
    AudioProposalCreate,
    AudioProposalRead,
    AudioReportCreate,
    AudioReportRead,
    AudioReviewCreate,
    AudioReviewRead,
    AudioWaveform,
)
from reefvision.services.bioacoustics import BioacousticsService, audio_asset_read
from reefvision.storage.datasets import canonical_json_bytes

router = APIRouter(prefix="/projects/{project_id}/bioacoustics/assets", tags=["bioacoustics"])
DbSession = Annotated[Session, Depends(get_db_session)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def service(request: Request, session: DbSession) -> BioacousticsService:
    return BioacousticsService(session, request.app.state.settings)


AudioService = Annotated[BioacousticsService, Depends(service)]


@router.get("", response_model=AudioPage[AudioAssetRead])
def list_audio(
    project_id: UUID, audio: AudioService, limit: PageLimit = 50, offset: PageOffset = 0
) -> AudioPage[AudioAssetRead]:
    return audio.list_assets(str(project_id), limit, offset)


@router.post("", response_model=AudioAssetRead, status_code=status.HTTP_201_CREATED)
def import_audio(
    project_id: UUID, audio: AudioService, file: Annotated[UploadFile, File()]
) -> AudioAssetRead:
    record = audio.import_recording(str(project_id), file.filename, file.file)
    audio.session.commit()
    return record


@router.get("/{asset_id}", response_model=AudioAssetRead)
def get_audio(project_id: UUID, asset_id: UUID, audio: AudioService) -> AudioAssetRead:
    return audio_asset_read(audio.asset(str(project_id), str(asset_id)))


@router.get("/{asset_id}/content", response_class=FileResponse)
def original_audio(project_id: UUID, asset_id: UUID, audio: AudioService) -> FileResponse:
    return FileResponse(audio.content(str(project_id), str(asset_id)), media_type="audio/wav")


@router.get("/{asset_id}/waveform", response_model=AudioWaveform)
def waveform(
    project_id: UUID,
    asset_id: UUID,
    audio: AudioService,
    channel: Annotated[int, Query(ge=0)] = 0,
    bins: Annotated[int, Query(ge=16, le=2048)] = 256,
) -> AudioWaveform:
    return audio.waveform(str(project_id), str(asset_id), channel, bins)


@router.get("/{asset_id}/proposals", response_model=AudioPage[AudioProposalRead])
def list_proposals(
    project_id: UUID,
    asset_id: UUID,
    audio: AudioService,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> AudioPage[AudioProposalRead]:
    return audio.proposals(str(project_id), str(asset_id), limit, offset)


@router.post(
    "/{asset_id}/proposals", response_model=AudioProposalRead, status_code=status.HTTP_201_CREATED
)
def create_proposal(
    project_id: UUID, asset_id: UUID, payload: AudioProposalCreate, audio: AudioService
) -> AudioProposalRead:
    result = audio.propose(str(project_id), str(asset_id), payload)
    audio.session.commit()
    return result


@router.get(
    "/{asset_id}/proposals/{proposal_id}/reviews", response_model=AudioPage[AudioReviewRead]
)
def list_reviews(
    project_id: UUID,
    asset_id: UUID,
    proposal_id: UUID,
    audio: AudioService,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> AudioPage[AudioReviewRead]:
    return audio.reviews(str(project_id), str(asset_id), str(proposal_id), limit, offset)


@router.post(
    "/{asset_id}/proposals/{proposal_id}/reviews",
    response_model=AudioReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def review_proposal(
    project_id: UUID,
    asset_id: UUID,
    proposal_id: UUID,
    payload: AudioReviewCreate,
    audio: AudioService,
) -> AudioReviewRead:
    review = audio.review(str(project_id), str(asset_id), str(proposal_id), payload)
    audio.session.commit()
    return review


@router.get("/{asset_id}/anchors", response_model=AudioPage[AudioAnchorRead])
def list_anchors(
    project_id: UUID,
    asset_id: UUID,
    audio: AudioService,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> AudioPage[AudioAnchorRead]:
    return audio.anchors(str(project_id), str(asset_id), limit, offset)


@router.post(
    "/{asset_id}/anchors", response_model=AudioAnchorRead, status_code=status.HTTP_201_CREATED
)
def create_anchor(
    project_id: UUID, asset_id: UUID, payload: AudioAnchorCreate, audio: AudioService
) -> AudioAnchorRead:
    result = audio.anchor(str(project_id), str(asset_id), payload)
    audio.session.commit()
    return result


@router.get("/{asset_id}/reports", response_model=AudioPage[AudioReportRead])
def list_reports(
    project_id: UUID,
    asset_id: UUID,
    audio: AudioService,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> AudioPage[AudioReportRead]:
    return audio.reports(str(project_id), str(asset_id), limit, offset)


@router.post(
    "/{asset_id}/reports", response_model=AudioReportRead, status_code=status.HTTP_201_CREATED
)
def freeze_report(
    project_id: UUID, asset_id: UUID, payload: AudioReportCreate, audio: AudioService
) -> AudioReportRead:
    report = audio.freeze(str(project_id), str(asset_id), payload)
    audio.session.commit()
    return report


@router.get("/{asset_id}/reports/{report_id}", response_model=AudioReportRead)
def get_report(
    project_id: UUID, asset_id: UUID, report_id: UUID, audio: AudioService
) -> AudioReportRead:
    return audio.report(str(project_id), str(report_id), str(asset_id))


@router.get("/{asset_id}/reports/{report_id}/export")
def export_report(
    project_id: UUID, asset_id: UUID, report_id: UUID, audio: AudioService
) -> Response:
    report = audio.report(str(project_id), str(report_id), str(asset_id))
    filename = f"bioacoustics-{report.report_sha256}.json"
    return Response(
        content=canonical_json_bytes(report.model_dump(mode="json")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
