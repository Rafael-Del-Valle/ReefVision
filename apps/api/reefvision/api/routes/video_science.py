"""Calibrated video-science and depth-aware trajectory routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.video_science import (
    CalibratedVideoTrackAnalyticsResponse,
    VideoCameraIntrinsicsResponse,
    VideoCameraIntrinsicsSetRequest,
    VideoDepthTrackAnalyticsRequest,
    VideoDepthTrackAnalyticsResponse,
    VideoSchoolingAnalyticsRequest,
    VideoSchoolingAnalyticsResponse,
    VideoSpatialCalibrationResponse,
    VideoSpatialCalibrationSetRequest,
)
from reefvision.services.video_science import VideoScienceService

router = APIRouter(tags=["video-science"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/videos/{video_id}/calibration",
    response_model=VideoSpatialCalibrationResponse,
)
def get_video_calibration(
    video_id: str,
    session: DbSession,
) -> VideoSpatialCalibrationResponse:
    return VideoScienceService(session).get_calibration(video_id)


@router.put(
    "/videos/{video_id}/calibration",
    response_model=VideoSpatialCalibrationResponse,
)
def set_video_calibration(
    video_id: str,
    payload: VideoSpatialCalibrationSetRequest,
    session: DbSession,
) -> VideoSpatialCalibrationResponse:
    return VideoScienceService(session).set_calibration(video_id, payload)


@router.delete(
    "/videos/{video_id}/calibration",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_video_calibration(video_id: str, session: DbSession) -> Response:
    VideoScienceService(session).clear_calibration(video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/video-tracks/{track_id}/calibrated-analytics",
    response_model=CalibratedVideoTrackAnalyticsResponse,
)
def calibrated_track_analytics(
    track_id: str,
    session: DbSession,
) -> CalibratedVideoTrackAnalyticsResponse:
    return VideoScienceService(session).calibrated_track_analytics(track_id)


@router.post(
    "/videos/{video_id}/schooling-analytics",
    response_model=VideoSchoolingAnalyticsResponse,
)
def schooling_analytics(
    video_id: str,
    payload: VideoSchoolingAnalyticsRequest,
    session: DbSession,
) -> VideoSchoolingAnalyticsResponse:
    return VideoScienceService(session).schooling_analytics(video_id, payload)


@router.get(
    "/videos/{video_id}/camera-intrinsics",
    response_model=VideoCameraIntrinsicsResponse,
)
def get_video_camera_intrinsics(
    video_id: str,
    session: DbSession,
) -> VideoCameraIntrinsicsResponse:
    return VideoScienceService(session).get_camera_intrinsics(video_id)


@router.put(
    "/videos/{video_id}/camera-intrinsics",
    response_model=VideoCameraIntrinsicsResponse,
)
def set_video_camera_intrinsics(
    video_id: str,
    payload: VideoCameraIntrinsicsSetRequest,
    session: DbSession,
) -> VideoCameraIntrinsicsResponse:
    return VideoScienceService(session).set_camera_intrinsics(video_id, payload)


@router.delete(
    "/videos/{video_id}/camera-intrinsics",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_video_camera_intrinsics(video_id: str, session: DbSession) -> Response:
    VideoScienceService(session).clear_camera_intrinsics(video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/videos/{video_id}/depth-track-analytics",
    response_model=VideoDepthTrackAnalyticsResponse,
)
def depth_track_analytics(
    video_id: str,
    payload: VideoDepthTrackAnalyticsRequest,
    session: DbSession,
) -> VideoDepthTrackAnalyticsResponse:
    return VideoScienceService(session).depth_track_analytics(video_id, payload)
