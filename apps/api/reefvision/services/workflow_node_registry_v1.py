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
from reefvision.services.workflow_pose import register_pose_workflow_adapters
from reefvision.services.workflow_pose_training import (
    register_pose_training_workflow_adapter,
)
from reefvision.services.workflow_results_packages import (
    register_results_package_workflow_adapter,
)

register_video_depth_3d_adapter()
register_video_metric_depth_3d_adapter()
register_pose_workflow_adapters()
register_pose_training_workflow_adapter()
register_results_package_workflow_adapter()


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

    # ------------------------------------------------------------------
    # Phase 10A: pose, behavior, active-learning, and frozen-training
    # workflow contracts.
    #
    # These definitions intentionally begin as contract-only nodes.
    # Phase 10A-2 binds them to the already validated production services
    # rather than creating duplicate scientific implementations here.
    # ------------------------------------------------------------------

    registry.update(
        {
            "pose_inference": WorkflowNodeDefinitionResponse(
                node_type="pose_inference",
                display_name="Pose Inference",
                category="Pose",
                description=(
                    "Run a registered pose model over one managed video and persist "
                    "canonical ReefVision video tracks containing pose observations."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="video",
                        display_name="Video",
                        accepted_types=["video_reference"],
                    ),
                    WorkflowPortDefinition(
                        port_id="model",
                        display_name="Pose model",
                        accepted_types=["model_reference"],
                    ),
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="poses",
                        display_name="Pose tracks",
                        accepted_types=["pose_tracks"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={
                    "device": "auto",
                    "confidence": 0.25,
                },
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must reuse ReefVision's production pose/video "
                        "tracking provider path."
                    ),
                    (
                        "Repeated semantic landmark labels must remain canonical and "
                        "must not be flattened into unique biological labels."
                    ),
                    (
                        "Model/provider/checkpoint and source-video identity must be "
                        "retained in the workflow artifact."
                    ),
                ],
            ),
            "pose_temporal_association": WorkflowNodeDefinitionResponse(
                node_type="pose_temporal_association",
                display_name="Temporal Pose Association",
                category="Pose",
                description=(
                    "Build persistent landmark identities and temporal association "
                    "provenance from canonical pose tracks."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="poses",
                        display_name="Pose tracks",
                        accepted_types=["pose_tracks"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="tracks",
                        display_name="Temporal pose tracks",
                        accepted_types=["pose_temporal_tracks"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={},
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must use PoseTemporalTrackingService rather "
                        "than reimplementing temporal association."
                    ),
                    (
                        "Identity breaks, occlusions, association confidence, and human "
                        "corrections remain canonical persisted state."
                    ),
                ],
            ),
            "pose_review_gate": WorkflowNodeDefinitionResponse(
                node_type="pose_review_gate",
                display_name="Pose Review Gate",
                category="Human review",
                description=(
                    "Pause a workflow until pose/landmark association output has been "
                    "reviewed through ReefVision's scientist-facing pose editor."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="tracks",
                        display_name="Temporal pose tracks",
                        accepted_types=["pose_temporal_tracks"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="poses",
                        display_name="Reviewed pose tracks",
                        accepted_types=["reviewed_pose_tracks"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={},
                execution_state="pausable_review_gate",
                executable=True,
                implementation_notes=[
                    "Machine-generated pose state is not equivalent to scientist-verified truth.",
                    (
                        "Resume must continue from persisted review state without "
                        "rerunning completed upstream nodes."
                    ),
                ],
            ),
            "behavior_dynamics": WorkflowNodeDefinitionResponse(
                node_type="behavior_dynamics",
                display_name="Behavior Dynamics",
                category="Scientific analysis",
                description=(
                    "Calculate deterministic behavior bouts, occupancy/dwell summaries, "
                    "and state transitions from scientist-reviewed tracks."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="poses",
                        display_name="Reviewed pose tracks",
                        accepted_types=["reviewed_pose_tracks"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="analysis",
                        display_name="Behavior analysis",
                        accepted_types=["behavior_analysis"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=["ethogram_revision_id"],
                optional_parameters={
                    "start_frame": None,
                    "end_frame": None,
                },
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must delegate to BehaviorDynamicsService "
                        "using an immutable ethogram revision."
                    ),
                    ("Output provenance must retain source track revisions and ethogram identity."),
                ],
            ),
            "pose_active_learning": WorkflowNodeDefinitionResponse(
                node_type="pose_active_learning",
                display_name="Pose Active Learning",
                category="Active learning",
                description=(
                    "Create an explainable pose-specific acquisition round from canonical "
                    "temporally associated pose state."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="tracks",
                        display_name="Temporal pose tracks",
                        accepted_types=[
                            "pose_temporal_tracks",
                            "reviewed_pose_tracks",
                        ],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="round",
                        display_name="Pose Active Learning round",
                        accepted_types=["pose_active_learning_round"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={
                    "requested_size": 20,
                    "diversity_balance": True,
                },
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must delegate to PoseActiveLearningService "
                        "and preserve explainable acquisition components."
                    ),
                    (
                        "Provider-native uncertainty may only be used where the provider "
                        "actually exposes it."
                    ),
                ],
            ),
            "pose_active_learning_review_gate": WorkflowNodeDefinitionResponse(
                node_type="pose_active_learning_review_gate",
                display_name="Pose Active Learning Review",
                category="Human review",
                description=(
                    "Pause until Active Learning candidates have explicit scientist "
                    "review outcomes."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="round",
                        display_name="Pose Active Learning round",
                        accepted_types=["pose_active_learning_round"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="verified_round",
                        display_name="Verified pose round",
                        accepted_types=["verified_pose_active_learning_round"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={},
                execution_state="pausable_review_gate",
                executable=True,
                implementation_notes=[
                    (
                        "Pending or skipped candidates must never be represented as "
                        "verified training truth."
                    ),
                    ("The workflow must resume from persisted scientist review state."),
                ],
            ),
            "pose_training_dataset_freeze": WorkflowNodeDefinitionResponse(
                node_type="pose_training_dataset_freeze",
                display_name="Freeze Pose Training Dataset",
                category="Training",
                description=(
                    "Freeze scientist-verified Active Learning candidates into the "
                    "immutable Phase 9 pose-training dataset format."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="verified_round",
                        display_name="Verified pose round",
                        accepted_types=["verified_pose_active_learning_round"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="dataset",
                        display_name="Frozen pose dataset",
                        accepted_types=["pose_training_dataset"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={
                    "name": None,
                    "notes": None,
                },
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must call PoseTrainingDatasetService and "
                        "must not reproduce its hashing/materialization logic."
                    ),
                    (
                        "Phase 9 immutable manifest/item hashes and schema identity "
                        "remain authoritative."
                    ),
                ],
            ),
            "pose_training_export": WorkflowNodeDefinitionResponse(
                node_type="pose_training_export",
                display_name="Pose Training Export",
                category="Exports",
                description=(
                    "Export an immutable frozen pose dataset in ReefVision native or "
                    "supported external retraining formats."
                ),
                input_ports=[
                    WorkflowPortDefinition(
                        port_id="dataset",
                        display_name="Frozen pose dataset",
                        accepted_types=["pose_training_dataset"],
                    )
                ],
                output_ports=[
                    WorkflowPortDefinition(
                        port_id="package",
                        display_name="Pose training package",
                        accepted_types=["pose_training_package"],
                        required=False,
                        multiple=True,
                    )
                ],
                required_parameters=[],
                optional_parameters={
                    "format": "native",
                },
                execution_state="executable_pose_workflow",
                executable=True,
                implementation_notes=[
                    (
                        "Runtime execution must reuse the Phase 9 immutable native package "
                        "or PoseTrainingExportService."
                    ),
                    (
                        "Lossy external formats must continue to report conversion losses "
                        "explicitly."
                    ),
                ],
            ),
        }
    )

    registry["pose_training_dataset"] = WorkflowNodeDefinitionResponse(
        node_type="pose_training_dataset",
        display_name="Frozen Pose Dataset",
        category="Inputs",
        description="Select an existing immutable scientist-verified pose training dataset.",
        input_ports=[],
        output_ports=[
            WorkflowPortDefinition(
                port_id="dataset",
                display_name="Frozen pose dataset",
                accepted_types=["pose_training_dataset"],
                required=False,
            )
        ],
        required_parameters=["dataset_id"],
        optional_parameters={"manifest_sha256": None},
        execution_state="executable_pose_dataset",
        executable=True,
        implementation_notes=["Preserves the frozen dataset manifest and landmark schema."],
    )

    registry["pose_model_training"] = WorkflowNodeDefinitionResponse(
        node_type="pose_model_training",
        display_name="Train Pose Model",
        category="Training",
        description=(
            "Train a YOLO11 pose architecture or continue a registered model from an immutable, "
            "scientist-verified ReefVision pose dataset."
        ),
        input_ports=[
            WorkflowPortDefinition(
                port_id="dataset",
                display_name="Frozen pose training dataset",
                accepted_types=["pose_training_dataset"],
            ),
            WorkflowPortDefinition(
                port_id="validation_dataset",
                display_name="Frozen pose validation dataset",
                accepted_types=["pose_training_dataset"],
                required=False,
            ),
            WorkflowPortDefinition(
                port_id="initial_model",
                display_name="Initial registered pose model",
                accepted_types=["model_reference"],
                required=False,
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="training",
                display_name="Pose training result",
                accepted_types=["training_result"],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=[],
        optional_parameters={
            # "auto" resolves to the connected seed model, or random init when absent.
            "initialization_mode": "auto",
            "architecture": "yolo11n-pose.yaml",
            "run_name": "workflow-pose-retrain",
            "notes": None,
            "device": "auto",
            "precision": "fp32",
            "random_seed": None,
            "require_validation_dataset": False,
            "training_config": {
                "epochs": 50,
                "patience": 20,
                "batch": 8,
                "imgsz": 640,
                "optimizer": "auto",
                "workers": 2,
                "cache": False,
                "plots": True,
            },
            "resource_limits": {},
        },
        execution_state="executable_pose_training",
        executable=True,
        implementation_notes=[
            (
                "Training truth must come from an immutable "
                "scientist-verified pose_training_dataset."
            ),
            (
                "Random initialization uses a weight-free YOLO11 pose architecture. "
                "For registered initialization, the checkpoint must be an Ultralytics "
                "task=pose model whose bound landmark schema matches the "
                "frozen dataset."
            ),
            (
                "A separate frozen validation dataset may be connected. "
                "If none is supplied, validation is disabled; training "
                "frames are never silently reused as validation evidence."
            ),
            (
                "Execution produces the normal ReefVision training_result "
                "artifact so Results Package integration remains shared."
            ),
        ],
    )

    registry["training_results_package"] = WorkflowNodeDefinitionResponse(
        node_type="training_results_package",
        display_name="Training Results Package",
        category="Exports",
        description=(
            "Build and verify ReefVision's scientific Results Package "
            "from one completed workflow training result."
        ),
        input_ports=[
            WorkflowPortDefinition(
                port_id="training",
                display_name="Training Result",
                accepted_types=["training_result"],
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="package",
                display_name="Results Package",
                accepted_types=["results_package"],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=[],
        optional_parameters={
            "include_excel": True,
            "include_machine_data": True,
            "include_native_artifacts": True,
            "include_logs": True,
            "checkpoint_mode": "best",
        },
        execution_state="executable_results_package",
        executable=True,
        implementation_notes=[
            ("Delegates to ResultsPackageService rather than reimplementing package generation."),
            (
                "Dataset, split, checkpoint, workflow-artifact, and "
                "training-run lineage are checked before packaging."
            ),
            (
                "The generated package is immediately verified before "
                "a workflow artifact is emitted."
            ),
        ],
    )

    return registry
