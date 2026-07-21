"""Restart-safe, checksummed tabular and structured tracking export bundles."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    ArtifactRecord,
    LabelClass,
    Project,
    VideoAnalysisRun,
    VideoAsset,
    VideoTrack,
    VideoTrackingEvaluation,
    VideoZoneRecord,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_exports import VideoDataExportRequest, VideoDataExportResponse
from reefvision.schemas.videos import VideoAssetResponse
from reefvision.services.video_tracks import (
    active_track_observations,
    interpolate_track,
    observation_center,
    track_response,
)
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.videos import remove_video_export, write_video_data_export


class VideoDataExportService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def export(
        self,
        video_id: str,
        request: VideoDataExportRequest,
    ) -> VideoDataExportResponse:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        project = self.session.get(Project, video.project_id)
        if project is None:
            raise NotFoundError("Video project not found")
        query = select(VideoTrack).where(VideoTrack.video_id == video.id)
        if not request.include_archived_tracks:
            query = query.where(VideoTrack.deleted_at.is_(None))
        tracks = list(self.session.scalars(query.order_by(VideoTrack.track_number, VideoTrack.id)))
        if not tracks:
            raise ValidationError("No tracks are available for export")
        class_names = {
            item.id: item.name
            for item in self.session.scalars(
                select(LabelClass).where(LabelClass.project_id == video.project_id)
            )
        }
        rows: list[dict[str, Any]] = []
        for track in tracks:
            metadata = dict(track.metadata_json or {})
            observations = (
                interpolate_track(track, video)
                if request.include_interpolated
                else active_track_observations(track, video)
            )
            for observation in observations:
                center_x, center_y = observation_center(observation)
                rows.append(
                    {
                        "frame": observation.frame_index,
                        "time_seconds": (
                            observation.timestamp_seconds
                            if observation.timestamp_seconds is not None
                            else observation.frame_index / video.fps
                        ),
                        "track_id": track.id,
                        "tracker_id": track.track_number,
                        "observation_id": observation.id or "",
                        "label_class_id": track.label_class_id or "",
                        "class_name": class_names.get(track.label_class_id or "", ""),
                        "centroid_x": center_x,
                        "centroid_y": center_y,
                        "x_min": observation.x_min,
                        "y_min": observation.y_min,
                        "x_max": observation.x_max,
                        "y_max": observation.y_max,
                        "confidence": (
                            observation.confidence if observation.confidence is not None else ""
                        ),
                        "source": observation.source,
                        "manual_edit": observation.manual_edit,
                        "track_revision": track.revision,
                        "observation_revision": observation.revision,
                        "track_status": track.status,
                        "is_ground_truth": track.is_ground_truth,
                        "origin_job_id": track.origin_job_id or "",
                        "detector_model_id": metadata.get("model_id", ""),
                        "detector_model_checksum": metadata.get("model_sha256")
                        or metadata.get("model_checksum", ""),
                        "detector_provider": metadata.get("provider_name", ""),
                        "tracker": metadata.get("tracker", ""),
                        "tracker_options": metadata.get("tracker_options", {}),
                    }
                )
        if not rows:
            raise ValidationError("No active track observations are available for export")
        files: dict[str, bytes] = {}
        if "csv" in request.formats:
            csv_output = io.StringIO(newline="")
            fieldnames = list(rows[0])
            csv_writer = csv.DictWriter(csv_output, fieldnames=fieldnames)
            csv_writer.writeheader()
            for row in rows:
                csv_writer.writerow(
                    {
                        **row,
                        "tracker_options": canonical_json_bytes(row["tracker_options"]).decode(
                            "utf-8"
                        ),
                    }
                )
            files["tracks.csv"] = csv_output.getvalue().encode("utf-8")
        if "mot" in request.formats:
            mot_output = io.StringIO(newline="")
            mot_writer = csv.writer(mot_output, lineterminator="\n")
            for row in rows:
                mot_writer.writerow(
                    [
                        int(row["frame"]) + 1,
                        row["tracker_id"],
                        row["x_min"],
                        row["y_min"],
                        float(row["x_max"]) - float(row["x_min"]),
                        float(row["y_max"]) - float(row["y_min"]),
                        row["confidence"] if row["confidence"] != "" else 1.0,
                        -1,
                        -1,
                        -1,
                    ]
                )
            files["tracks-mot.txt"] = mot_output.getvalue().encode("utf-8")
        analyses = (
            list(
                self.session.scalars(
                    select(VideoAnalysisRun)
                    .where(VideoAnalysisRun.video_id == video.id)
                    .order_by(VideoAnalysisRun.created_at, VideoAnalysisRun.id)
                )
            )
            if request.include_analysis_runs
            else []
        )
        evaluations = (
            list(
                self.session.scalars(
                    select(VideoTrackingEvaluation)
                    .where(VideoTrackingEvaluation.video_id == video.id)
                    .order_by(
                        VideoTrackingEvaluation.created_at,
                        VideoTrackingEvaluation.id,
                    )
                )
            )
            if request.include_evaluation_runs
            else []
        )
        zones = list(
            self.session.scalars(
                select(VideoZoneRecord)
                .where(
                    VideoZoneRecord.video_id == video.id,
                    VideoZoneRecord.deleted_at.is_(None),
                )
                .order_by(VideoZoneRecord.name, VideoZoneRecord.id)
            )
        )
        if "json" in request.formats:
            files["tracks.json"] = canonical_json_bytes(
                {
                    "format": "reefvision_video_tracks_v2",
                    "video": VideoAssetResponse.model_validate(video).model_dump(mode="json"),
                    "calibration": dict(video.metadata_json or {}).get("calibration"),
                    "tracks": [
                        track_response(track, video).model_dump(mode="json") for track in tracks
                    ],
                    "trajectory_rows": rows,
                    "zones": [
                        {
                            "id": zone.id,
                            "name": zone.name,
                            "x_min": zone.x_min,
                            "y_min": zone.y_min,
                            "x_max": zone.x_max,
                            "y_max": zone.y_max,
                            "revision": zone.revision,
                        }
                        for zone in zones
                    ],
                    "analysis_runs": [item.result_json for item in analyses],
                    "evaluation_runs": [item.result_json for item in evaluations],
                }
            )
        if "npz" in request.formats:
            npz_output = io.BytesIO()
            np.savez_compressed(
                npz_output,
                frame=np.asarray([int(row["frame"]) for row in rows], dtype=np.int64),
                time_seconds=np.asarray(
                    [float(row["time_seconds"]) for row in rows], dtype=np.float64
                ),
                track_id=np.asarray([str(row["track_id"]) for row in rows], dtype="U36"),
                tracker_id=np.asarray([int(row["tracker_id"]) for row in rows], dtype=np.int64),
                label_class_id=np.asarray(
                    [str(row["label_class_id"]) for row in rows], dtype="U36"
                ),
                bbox=np.asarray(
                    [
                        [
                            float(row["x_min"]),
                            float(row["y_min"]),
                            float(row["x_max"]),
                            float(row["y_max"]),
                        ]
                        for row in rows
                    ],
                    dtype=np.float64,
                ),
                centroid=np.asarray(
                    [[float(row["centroid_x"]), float(row["centroid_y"])] for row in rows],
                    dtype=np.float64,
                ),
                confidence=np.asarray(
                    [
                        float(row["confidence"]) if row["confidence"] != "" else np.nan
                        for row in rows
                    ],
                    dtype=np.float64,
                ),
                manual_edit=np.asarray([bool(row["manual_edit"]) for row in rows], dtype=np.bool_),
            )
            files["tracks.npz"] = npz_output.getvalue()
        artifact_id = str(uuid4())
        relative_root = f"{project.storage_root}/video-exports/data-{artifact_id}"
        manifest = {
            "format": "reefvision-video-data-export",
            "format_version": "2.0",
            "reefvision_version": __version__,
            "created_at": datetime.now(UTC).isoformat(),
            "artifact_id": artifact_id,
            "project_id": project.id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "video_metadata": VideoAssetResponse.model_validate(video).model_dump(mode="json"),
            "calibration": dict(video.metadata_json or {}).get("calibration"),
            "formats": request.formats,
            "parameters": request.model_dump(mode="json"),
            "track_revisions": [
                {
                    "track_id": track.id,
                    "track_number": track.track_number,
                    "revision": track.revision,
                    "origin_job_id": track.origin_job_id,
                    "source_type": track.source_type,
                    "provenance": dict(track.metadata_json or {}),
                }
                for track in tracks
            ],
            "zone_revisions": [{"zone_id": zone.id, "revision": zone.revision} for zone in zones],
            "analysis_runs": [
                {"analysis_id": item.id, "sha256": item.result_sha256} for item in analyses
            ],
            "evaluation_runs": [
                {"evaluation_id": item.id, "sha256": item.result_sha256} for item in evaluations
            ],
            "row_count": len(rows),
        }
        write_result = write_video_data_export(
            self.settings,
            relative_root=relative_root,
            files=files,
            manifest=manifest,
        )
        try:
            artifact = ArtifactRecord(
                id=artifact_id,
                project_id=project.id,
                artifact_type="video_tracking_data_bundle",
                created_by="video_data_export",
                reefvision_version=__version__,
                source_kind="video",
                source_id=video.id,
                source_checksum=video.sha256,
                source_annotation_revision=max(track.revision for track in tracks),
                parameters_json=request.model_dump(mode="json"),
                postprocessing_json={
                    "formats": request.formats,
                    "row_count": len(rows),
                    "manifest_sha256": write_result.manifest_sha256,
                },
                review_status="unreviewed",
                managed_path=write_result.archive_path,
                checksum=write_result.archive_sha256,
                size_bytes=write_result.archive_size_bytes,
                metadata_json={
                    "manifest_path": write_result.manifest_path,
                    "output_path": write_result.output_path,
                    "file_checksums": write_result.file_checksums,
                },
            )
            self.session.add(artifact)
            self.session.commit()
        except Exception:
            self.session.rollback()
            remove_video_export(
                self.settings,
                output_path=write_result.output_path,
                archive_path=write_result.archive_path,
            )
            raise
        return VideoDataExportResponse(
            artifact_id=artifact.id,
            video_id=video.id,
            archive_path=write_result.archive_path,
            manifest_path=write_result.manifest_path,
            archive_sha256=write_result.archive_sha256,
            archive_size_bytes=write_result.archive_size_bytes,
            manifest_sha256=write_result.manifest_sha256,
            formats=list(request.formats),
        )
