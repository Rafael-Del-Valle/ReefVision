"""Fail-closed metric-depth semantics for CoralVision Fusion coral measurements."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import DepthMap, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs
from reefvision.schemas.depth import CameraIntrinsics

_ORIGINAL_MEASUREMENT_SNAPSHOT = workflow_runs._measurement_snapshot
_DEFAULT_ALLOWED_SOURCE_KINDS = {
    "metric_monocular_estimate",
    "calibrated_metric",
    "imported_metric",
    "rgbd_metric",
    "stereo_metric",
}


def _depth_source_kind(depth_map: DepthMap) -> str:
    explicit = dict(depth_map.metadata_json or {}).get("depth_source_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    if depth_map.provider_id == "depth_anything_v2_metric":
        return "metric_monocular_estimate"
    return "imported_metric" if depth_map.depth_kind == "metric" else "relative_imported"


def _metric_coral_surface_snapshot(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    mode = str(configuration.get("measurement_mode", "coral_mask")).strip().casefold()
    if mode != "coral_metric_surface":
        return _ORIGINAL_MEASUREMENT_SNAPSHOT(factory, run, configuration, inputs)

    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    input_depth_ids = workflow_runs._list_values(payloads, "depth_map_ids")
    configured = configuration.get("depth_map_ids")
    configured_ids = [str(value) for value in configured] if isinstance(configured, list) else []
    requested_ids = list(dict.fromkeys(configured_ids or input_depth_ids))
    if not requested_ids:
        raise RuntimeError("coral_metric_surface measurement requires a connected metric depth map")

    raw_allowed = configuration.get("allowed_depth_source_kinds")
    allowed = (
        {str(value) for value in raw_allowed}
        if isinstance(raw_allowed, list)
        else set(_DEFAULT_ALLOWED_SOURCE_KINDS)
    )
    if not allowed:
        raise RuntimeError("allowed_depth_source_kinds cannot be empty in metric surface mode")

    with factory() as session:
        depth_maps = list(
            session.scalars(
                select(DepthMap).where(
                    DepthMap.project_id == run.project_id,
                    DepthMap.id.in_(requested_ids),
                )
            )
        )
        if len(depth_maps) != len(requested_ids):
            raise RuntimeError("One or more metric surface depth maps are missing from the project")
        source_kinds: dict[str, str] = {}
        for depth_map in depth_maps:
            source_kind = _depth_source_kind(depth_map)
            source_kinds[depth_map.id] = source_kind
            if depth_map.depth_kind != "metric":
                raise RuntimeError(
                    "coral_metric_surface cannot use relative depth; select calibrated/imported "
                    "metric, RGB-D, stereo, or a metric monocular depth source"
                )
            if not depth_map.unit:
                raise RuntimeError("Metric coral surface depth requires a physical depth unit")
            if source_kind not in allowed:
                raise RuntimeError(
                    f"Depth source kind {source_kind!r} is not allowed by this workflow"
                )
            raw_intrinsics = dict(depth_map.metadata_json or {}).get("camera_intrinsics")
            if not isinstance(raw_intrinsics, dict):
                raise RuntimeError(
                    "Metric coral surface measurement requires camera intrinsics on every depth map"
                )
            try:
                CameraIntrinsics.model_validate(raw_intrinsics)
            except ValueError as exc:
                raise RuntimeError("Metric coral surface camera intrinsics are invalid") from exc

    outputs = _ORIGINAL_MEASUREMENT_SNAPSHOT(factory, run, configuration, inputs)
    output = outputs.get("measurements")
    if output is None:
        raise RuntimeError("Metric coral surface workflow produced no measurements artifact")
    artifact_type, payload = output
    enriched = dict(payload)
    enriched["measurement_mode"] = "coral_metric_surface"
    enriched["physical_depth_required"] = True
    enriched["allowed_depth_source_kinds"] = sorted(allowed)
    enriched["depth_source_kinds"] = source_kinds
    enriched["surface_semantics"] = {
        "metric_projected_area": "camera-facing pinhole projected area",
        "visible_surface_area_3d": (
            "triangulated camera-visible depth surface; hidden/back-facing coral surface is excluded"
        ),
        "whole_object_surface_area_reconstructed": False,
    }
    return {"measurements": (artifact_type, enriched)}


workflow_runs._measurement_snapshot = _metric_coral_surface_snapshot
