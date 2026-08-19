"""Wire scientific measurement and behavior services into fusion workflow execution.

The original workflow runtime intentionally started with lightweight snapshot nodes.  The
full 1.0 release requires those nodes to execute the same calibrated science services that
are available elsewhere in ReefVision, rather than returning metadata-only placeholders.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import get_settings
from reefvision.db.models import ImageAsset, MaskAnnotation, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs
from reefvision.schemas.videos import VideoAnalyticsRequest
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.services.video_behavior import VideoBehaviorAnalysisService


def _workflow_measurements(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    """Calculate live coral measurements for masks selected by a workflow node."""

    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    image_ids = workflow_runs._list_values(payloads, "image_ids")
    input_mask_ids = workflow_runs._list_values(
        payloads,
        "mask_annotation_ids",
        "mask_ids",
    )
    configured = configuration.get("mask_annotation_ids")
    configured_mask_ids = (
        [str(value) for value in configured]
        if isinstance(configured, list)
        else []
    )
    requested_mask_ids = list(
        dict.fromkeys(configured_mask_ids or input_mask_ids)
    )

    label_class_ids = configuration.get("label_class_ids")
    scientific_names = configuration.get("scientific_names")
    state_names = configuration.get("state_names")
    resolved_label_class_ids = (
        [str(value) for value in label_class_ids]
        if isinstance(label_class_ids, list)
        else None
    )
    resolved_scientific_names = (
        [str(value) for value in scientific_names]
        if isinstance(scientific_names, list)
        else None
    )
    resolved_state_names = (
        [str(value) for value in state_names]
        if isinstance(state_names, list)
        else None
    )

    settings = get_settings()
    with factory() as session:
        query = (
            select(MaskAnnotation.id)
            .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
            .where(
                ImageAsset.project_id == run.project_id,
                MaskAnnotation.deleted_at.is_(None),
            )
        )
        if requested_mask_ids:
            query = query.where(MaskAnnotation.id.in_(requested_mask_ids))
        elif image_ids:
            query = query.where(MaskAnnotation.image_id.in_(image_ids))
        mask_ids = list(
            session.scalars(query.order_by(MaskAnnotation.image_id, MaskAnnotation.id))
        )
        service = MaskMeasurementService(session, settings)
        measurements = [
            service.measure(
                mask_id,
                label_class_ids=resolved_label_class_ids,
                scientific_names=resolved_scientific_names,
                state_names=resolved_state_names,
            ).model_dump(mode="json")
            for mask_id in mask_ids
        ]

    return {
        "measurements": (
            "measurements",
            {
                "image_ids": list(
                    dict.fromkeys(str(item["image_id"]) for item in measurements)
                ),
                "mask_annotation_ids": mask_ids,
                "measurement_count": len(measurements),
                "measurements": measurements,
                "measurement_engine": "mask_measurements",
                "calibration_aware": True,
                "filters": {
                    "label_class_ids": resolved_label_class_ids or [],
                    "scientific_names": resolved_scientific_names or [],
                    "state_names": resolved_state_names or [],
                },
            },
        )
    }


def _workflow_behavior_analysis(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    """Run full trajectory/zone/schooling analytics for workflow video inputs."""

    video_ids = workflow_runs._list_values(
        [workflow_runs._artifact_payload(item) for item in inputs],
        "video_ids",
    )
    settings = get_settings()
    analyses: list[dict[str, Any]] = []
    with factory() as session:
        service = VideoBehaviorAnalysisService(session, settings)
        for video_id in video_ids:
            response = service.analytics(
                video_id,
                VideoAnalyticsRequest(persist_result=True),
            )
            analyses.append(response.model_dump(mode="json"))

    track_ids = list(
        dict.fromkeys(
            str(track["track_id"])
            for analysis in analyses
            for track in analysis.get("tracks", [])
            if isinstance(track, dict) and track.get("track_id") is not None
        )
    )
    analysis_ids = [
        str(analysis["analysis_id"])
        for analysis in analyses
        if analysis.get("analysis_id") is not None
    ]
    return {
        "measurements": (
            "measurements",
            {
                "video_ids": video_ids,
                "track_ids": track_ids,
                "analysis_ids": analysis_ids,
                "analysis_count": len(analyses),
                "analyses": analyses,
                "measurement_engine": "video_behavior",
                "calibration_aware": True,
            },
        )
    }


# Install the full-science handlers without duplicating the workflow scheduler.  Keeping
# the replacement localized also makes it straightforward for validation tests to compare
# the workflow outputs with the direct service APIs.
workflow_runs._measurement_snapshot = _workflow_measurements
workflow_runs._behavior_snapshot = _workflow_behavior_analysis
