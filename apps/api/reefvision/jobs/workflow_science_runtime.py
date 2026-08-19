"""Wire full scientific services into fusion workflow execution.

The first workflow runtime intentionally used lightweight snapshot nodes. The full 1.0
release requires workflow nodes to execute the same calibrated measurement, behavior, and
active-learning engines that are available elsewhere in ReefVision rather than returning
metadata-only placeholders.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import get_settings
from reefvision.db.models import (
    DepthMap,
    ImageAsset,
    ImageEmbedding,
    MaskAnnotation,
    WorkflowArtifact,
    WorkflowRun,
)
from reefvision.jobs import workflow_runs
from reefvision.ml.active_learning_selection import (
    SelectionCandidate,
    SelectionStrategy,
    select_candidates,
)
from reefvision.schemas.videos import VideoAnalyticsRequest
from reefvision.services.depth_maps import DepthMapService
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.services.video_behavior import VideoBehaviorAnalysisService

_ACTIVE_LEARNING_STRATEGIES: set[str] = {
    "uncertainty",
    "least_confidence",
    "margin",
    "entropy",
    "farthest_point",
    "k_center",
    "kmeans_representative",
    "cluster_balanced",
    "density_aware",
    "pareto_uncertainty_diversity",
    "ensemble_disagreement",
}


def _workflow_measurements(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    """Calculate live 2D/calibrated and optional depth-aware coral measurements."""

    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    image_ids = workflow_runs._list_values(payloads, "image_ids")
    input_mask_ids = workflow_runs._list_values(
        payloads,
        "mask_annotation_ids",
        "mask_ids",
    )
    input_depth_map_ids = workflow_runs._list_values(payloads, "depth_map_ids")

    configured_masks = configuration.get("mask_annotation_ids")
    configured_mask_ids = (
        [str(value) for value in configured_masks]
        if isinstance(configured_masks, list)
        else []
    )
    requested_mask_ids = list(dict.fromkeys(configured_mask_ids or input_mask_ids))

    configured_depth = configuration.get("depth_map_ids")
    configured_depth_ids = (
        [str(value) for value in configured_depth]
        if isinstance(configured_depth, list)
        else []
    )
    requested_depth_ids = list(dict.fromkeys(configured_depth_ids or input_depth_map_ids))

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

        depth_by_image: dict[str, str] = {}
        if requested_depth_ids:
            depth_maps = list(
                session.scalars(
                    select(DepthMap)
                    .where(
                        DepthMap.project_id == run.project_id,
                        DepthMap.id.in_(requested_depth_ids),
                    )
                    .order_by(DepthMap.created_at, DepthMap.id)
                )
            )
            # If more than one aligned map is supplied for an image, the most recently
            # ordered map wins deterministically. Workflows can pin one ID in config when
            # a specific provider/depth kind is scientifically required.
            depth_by_image = {item.image_id: item.id for item in depth_maps}

        measurement_service = MaskMeasurementService(session, settings)
        depth_service = DepthMapService(session, settings)
        measurements: list[dict[str, Any]] = []
        for mask_id in mask_ids:
            measurement = measurement_service.measure(
                mask_id,
                label_class_ids=resolved_label_class_ids,
                scientific_names=resolved_scientific_names,
                state_names=resolved_state_names,
            ).model_dump(mode="json")
            depth_map_id = depth_by_image.get(str(measurement["image_id"]))
            if depth_map_id is not None:
                measurement["depth_measurement"] = depth_service.measure_mask(
                    mask_id,
                    depth_map_id=depth_map_id,
                ).model_dump(mode="json")
            else:
                measurement["depth_measurement"] = None
            measurements.append(measurement)

    return {
        "measurements": (
            "measurements",
            {
                "image_ids": list(
                    dict.fromkeys(str(item["image_id"]) for item in measurements)
                ),
                "mask_annotation_ids": mask_ids,
                "depth_map_ids": requested_depth_ids,
                "measurement_count": len(measurements),
                "measurements": measurements,
                "measurement_engine": "mask_measurements+depth_maps",
                "calibration_aware": True,
                "depth_aware": bool(requested_depth_ids),
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


def _float_sequence_map(configuration: dict[str, Any], key: str) -> dict[str, tuple[float, ...]]:
    raw = configuration.get(key)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, tuple[float, ...]] = {}
    for candidate_id, values in raw.items():
        if not isinstance(values, list):
            continue
        try:
            result[str(candidate_id)] = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            continue
    return result


def _ensemble_map(
    configuration: dict[str, Any],
) -> dict[str, tuple[tuple[float, ...], ...]]:
    raw = configuration.get("ensemble_probabilities")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, tuple[tuple[float, ...], ...]] = {}
    for candidate_id, members in raw.items():
        if not isinstance(members, list):
            continue
        parsed: list[tuple[float, ...]] = []
        for member in members:
            if not isinstance(member, list):
                parsed = []
                break
            try:
                parsed.append(tuple(float(value) for value in member))
            except (TypeError, ValueError):
                parsed = []
                break
        if parsed:
            result[str(candidate_id)] = tuple(parsed)
    return result


def _string_map(configuration: dict[str, Any], key: str) -> dict[str, str]:
    raw = configuration.get(key)
    if not isinstance(raw, dict):
        return {}
    return {
        str(candidate_id): str(value)
        for candidate_id, value in raw.items()
        if value is not None
    }


def _class_map(configuration: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = configuration.get("class_ids")
    if not isinstance(raw, dict):
        return {}
    return {
        str(candidate_id): tuple(str(value) for value in values)
        for candidate_id, values in raw.items()
        if isinstance(values, list)
    }


def _workflow_active_learning(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    """Execute the complete deterministic active-learning strategy registry."""

    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    image_ids = workflow_runs._list_values(payloads, "image_ids")
    embedding_model_id = str(configuration.get("embedding_model_id", "")).strip()
    if not embedding_model_id:
        for payload in payloads:
            value = payload.get("embedding_model_id")
            if isinstance(value, str) and value.strip():
                embedding_model_id = value.strip()
                break
    if not embedding_model_id:
        raise RuntimeError("Active-learning nodes require embedding_model_id")

    strategy_name = str(
        configuration.get("strategy", "pareto_uncertainty_diversity")
    ).strip()
    if strategy_name not in _ACTIVE_LEARNING_STRATEGIES:
        raise RuntimeError(f"Unsupported active-learning strategy: {strategy_name}")
    strategy = cast(SelectionStrategy, strategy_name)

    with factory() as session:
        query = select(ImageEmbedding).where(
            ImageEmbedding.project_id == run.project_id,
            ImageEmbedding.embedding_model_id == embedding_model_id,
            ImageEmbedding.status == "ready",
        )
        if image_ids:
            query = query.where(ImageEmbedding.image_id.in_(image_ids))
        embeddings = list(
            session.scalars(query.order_by(ImageEmbedding.image_id, ImageEmbedding.created_at))
        )

    latest_by_image: dict[str, ImageEmbedding] = {}
    for embedding in embeddings:
        latest_by_image[embedding.image_id] = embedding
    candidate_ids = image_ids or sorted(latest_by_image)

    probabilities = _float_sequence_map(configuration, "probabilities")
    ensemble_probabilities = _ensemble_map(configuration)
    group_ids = _string_map(configuration, "group_ids")
    fragment_ids = _string_map(configuration, "fragment_ids")
    class_ids = _class_map(configuration)
    raw_base_scores = configuration.get("base_scores")
    base_scores = raw_base_scores if isinstance(raw_base_scores, dict) else {}
    raw_manual_priority = configuration.get("manual_priority")
    manual_priority = (
        {str(value) for value in raw_manual_priority}
        if isinstance(raw_manual_priority, list)
        else set()
    )

    candidates: list[SelectionCandidate] = []
    for image_id in candidate_ids:
        try:
            base_score = float(base_scores.get(image_id, 0.0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid base score for active-learning candidate {image_id}") from exc
        candidates.append(
            SelectionCandidate(
                candidate_id=image_id,
                embedding=(
                    tuple(float(value) for value in latest_by_image[image_id].vector_json)
                    if image_id in latest_by_image
                    else None
                ),
                probabilities=probabilities.get(image_id, ()),
                ensemble_probabilities=ensemble_probabilities.get(image_id, ()),
                base_score=base_score,
                group_id=group_ids.get(image_id),
                fragment_id=fragment_ids.get(image_id),
                class_ids=class_ids.get(image_id, ()),
                manual_priority=image_id in manual_priority,
                metadata={"embedding_model_id": embedding_model_id},
            )
        )

    results = select_candidates(
        candidates,
        budget=int(configuration.get("maximum_items", 100)),
        strategy=strategy,
        seed=int(configuration.get("seed", 0)),
        group_limit=(
            int(configuration["maximum_items_per_group"])
            if configuration.get("maximum_items_per_group") is not None
            else None
        ),
        fragment_limit=(
            int(configuration["maximum_items_per_fragment"])
            if configuration.get("maximum_items_per_fragment") is not None
            else None
        ),
        uncertainty_weight=float(configuration.get("uncertainty_weight", 0.5)),
        diversity_weight=float(configuration.get("diversity_weight", 0.3)),
        density_weight=float(configuration.get("density_weight", 0.1)),
        disagreement_weight=float(configuration.get("disagreement_weight", 0.1)),
        base_score_weight=float(configuration.get("base_score_weight", 0.1)),
        class_balance_weight=float(configuration.get("class_balance_weight", 0.1)),
    )
    serialized = [asdict(item) for item in results]
    return {
        "review_batch": (
            "review_batch",
            {
                "embedding_model_id": embedding_model_id,
                "strategy": strategy,
                "candidate_count": len(candidates),
                "selected_count": len(results),
                "selected_image_ids": [item.candidate_id for item in results],
                "items": serialized,
                "provenance": {
                    "selector": "reefvision.ml.active_learning_selection.select_candidates",
                    "seed": int(configuration.get("seed", 0)),
                },
            },
        )
    }


# Install the full handlers without duplicating the workflow scheduler. Keeping the
# replacements localized also makes it straightforward for validation tests to compare
# workflow outputs against the direct production services.
workflow_runs._measurement_snapshot = _workflow_measurements
workflow_runs._behavior_snapshot = _workflow_behavior_analysis
workflow_runs._active_learning = _workflow_active_learning
