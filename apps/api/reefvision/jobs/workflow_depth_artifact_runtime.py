"""Enrich Fusion depth artifacts with persisted scientific source semantics."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import DepthMap, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs

_ORIGINAL_DEPTH_ESTIMATION = workflow_runs._depth_estimation


def _source_kind(depth_map: DepthMap) -> str:
    explicit = dict(depth_map.metadata_json or {}).get("depth_source_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    if depth_map.provider_id == "luminance_relative":
        return "relative_fixture"
    if depth_map.provider_id == "depth_anything_v2_relative":
        return "relative_monocular"
    if depth_map.provider_id == "depth_anything_v2_metric":
        return "metric_monocular_estimate"
    return "relative_imported" if depth_map.depth_kind == "relative" else "imported_metric"


def _semantic_depth_estimation(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    outputs = _ORIGINAL_DEPTH_ESTIMATION(settings, factory, run, configuration, inputs)
    output = outputs.get("depth_maps")
    if output is None:
        return outputs
    artifact_type, payload = output
    enriched = dict(payload)
    depth_ids = [str(value) for value in enriched.get("depth_map_ids", [])]
    with factory() as session:
        maps = list(
            session.scalars(
                select(DepthMap)
                .where(
                    DepthMap.project_id == run.project_id,
                    DepthMap.id.in_(depth_ids),
                )
                .order_by(DepthMap.image_id, DepthMap.id)
            )
        )
    by_id = {item.id: item for item in maps}
    enriched["depth_maps"] = [
        {
            "depth_map_id": depth_id,
            "image_id": by_id[depth_id].image_id,
            "depth_kind": by_id[depth_id].depth_kind,
            "source_kind": _source_kind(by_id[depth_id]),
            "unit": by_id[depth_id].unit,
            "provider_id": by_id[depth_id].provider_id,
            "model_id": by_id[depth_id].model_id,
            "sha256": by_id[depth_id].sha256,
            "camera_intrinsics_present": isinstance(
                dict(by_id[depth_id].metadata_json or {}).get("camera_intrinsics"),
                dict,
            ),
        }
        for depth_id in depth_ids
        if depth_id in by_id
    ]
    enriched["source_kinds"] = list(
        dict.fromkeys(item["source_kind"] for item in enriched["depth_maps"])
    )
    enriched["units"] = list(
        dict.fromkeys(
            str(item["unit"])
            for item in enriched["depth_maps"]
            if item["unit"] is not None
        )
    )
    enriched["physical_depth"] = bool(enriched["depth_maps"]) and all(
        item["depth_kind"] == "metric" and item["unit"] is not None
        for item in enriched["depth_maps"]
    )
    return {"depth_maps": (artifact_type, enriched)}


workflow_runs._depth_estimation = _semantic_depth_estimation
