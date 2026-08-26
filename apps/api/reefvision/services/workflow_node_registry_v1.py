"""ReefVision 1.0 workflow-node registry extensions."""

from __future__ import annotations

from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.workflow_depth_3d import register_video_depth_3d_adapter
from reefvision.services.workflow_metric_depth_3d import (
    register_video_metric_depth_3d_adapter,
)
from reefvision.services.workflow_node_registry import (
    workflow_node_registry as base_workflow_node_registry,
)

register_video_depth_3d_adapter()
register_video_metric_depth_3d_adapter()


def workflow_node_registry() -> dict[str, WorkflowNodeDefinitionResponse]:
    """Return the M10 registry plus ReefVision 1.0 completion nodes."""

    registry = dict(base_workflow_node_registry())
    registry["video_depth_3d_analytics"] = WorkflowNodeDefinitionResponse(
        node_type="video_depth_3d_analytics",
        display_name="Metric Depth 3D Trajectories",
        category="Scientific analysis",
        description=(
            "Back-project calibrated metric depth samples onto incoming fish/video tracks "
            "to calculate X/Y/Z trajectories, 3D path length, displacement, speed, and depth."
        ),
        input_ports=[
            WorkflowPortDefinition(
                port_id="video",
                display_name="Video",
                accepted_types=["video_reference"],
            ),
            WorkflowPortDefinition(
                port_id="tracks",
                display_name="Video tracks",
                accepted_types=["video_tracks"],
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="trajectories",
                display_name="3D trajectories",
                accepted_types=["video_3d_trajectories"],
            )
        ],
        required_parameters=["depth_samples"],
        optional_parameters={
            "unit": "m",
            "maximum_frame_gap": None,
        },
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The selected video must have saved camera intrinsics before execution.",
            (
                "depth_samples accepts objects with frame, depth, optional confidence, and "
                "either track_id or track_number. Track numbers are resolved against the "
                "incoming video_tracks artifact."
            ),
            (
                "Depth values must already be calibrated metric measurements from stereo, "
                "RGB-D, or another validated metric source. Relative monocular depth maps "
                "are intentionally not treated as physical distance."
            ),
        ],
    )
    registry["video_metric_depth_3d"] = WorkflowNodeDefinitionResponse(
        node_type="video_metric_depth_3d",
        display_name="Automatic Metric Video Depth 3D",
        category="Scientific analysis",
        description=(
            "Estimate temporally consistent model-metric video depth, sample selected fish "
            "tracks robustly, and reconstruct X/Y/Z trajectories with saved camera intrinsics."
        ),
        input_ports=[
            WorkflowPortDefinition(
                port_id="video",
                display_name="Video",
                accepted_types=["video_reference"],
            ),
            WorkflowPortDefinition(
                port_id="tracks",
                display_name="Video tracks",
                accepted_types=["video_tracks"],
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="trajectories",
                display_name="Scientific 3D trajectories",
                accepted_types=["video_3d_trajectories"],
            )
        ],
        required_parameters=[],
        optional_parameters={
            "device": "auto",
            "input_size": 518,
            "max_res": 1280,
            "core_fraction": 0.6,
            "minimum_valid_fraction": 0.25,
            "maximum_frame_gap": None,
            "allow_model_download": False,
            "allow_resolution_fallback": True,
        },
        execution_state="executable",
        executable=True,
        implementation_notes=[
            (
                "Uses pinned Metric Video Depth Anything Small and existing "
                "ReefVision track interpolation."
            ),
            "The selected video must have saved camera intrinsics before execution.",
            (
                "Outputs are model-estimated metric depth and do not authorize "
                "physical measurement claims until independently validated underwater."
            ),
            (
                "Automatic model download is disabled by default so the installed "
                "model cannot change silently during a workflow."
            ),
        ],
    )
    return registry
