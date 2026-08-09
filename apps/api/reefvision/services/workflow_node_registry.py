"""Static registry of workflow nodes with established ReefVision semantics."""

from __future__ import annotations

from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)


def _input(
    port_id: str,
    display_name: str,
    *accepted_types: str,
    required: bool = True,
    multiple: bool = False,
) -> WorkflowPortDefinition:
    return WorkflowPortDefinition(
        port_id=port_id,
        display_name=display_name,
        accepted_types=list(accepted_types),
        required=required,
        multiple=multiple,
    )


def _output(
    port_id: str,
    display_name: str,
    *produced_types: str,
) -> WorkflowPortDefinition:
    return WorkflowPortDefinition(
        port_id=port_id,
        display_name=display_name,
        accepted_types=list(produced_types),
        required=False,
        multiple=True,
    )


def workflow_node_registry() -> dict[str, WorkflowNodeDefinitionResponse]:
    definitions = [
        WorkflowNodeDefinitionResponse(
            node_type="project_source",
            display_name="Current Project",
            category="sources",
            description="Provide the project selected for graph validation and execution.",
            input_ports=[],
            output_ports=[_output("project", "Project", "project_reference")],
            required_parameters=[],
            optional_parameters={},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["The project ID comes from the API route, not graph JSON."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="project_images",
            display_name="Project Images",
            category="sources",
            description="Select managed images from the current project.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("images", "Images", "image_collection")],
            required_parameters=[],
            optional_parameters={"annotation_status": None, "group_key": None},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["Filters map to the existing project image query."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="dataset_version_source",
            display_name="Immutable Dataset Version",
            category="sources",
            description="Provide images and the immutable version record from one dataset version.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[
                _output("dataset", "Dataset Version", "dataset_version"),
                _output("images", "Version Images", "image_collection"),
            ],
            required_parameters=["dataset_version_id"],
            optional_parameters={"split": None},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["The selected version must be complete and belong to the project."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="registered_model_source",
            display_name="Registered Model",
            category="sources",
            description="Provide one project-scoped registered model checkpoint.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("model", "Model", "model_reference")],
            required_parameters=["model_id"],
            optional_parameters={},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["Downstream task compatibility is validated from model purpose and task."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="project_video_source",
            display_name="Project Video",
            category="sources",
            description="Provide one managed source video.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("video", "Video", "video_reference")],
            required_parameters=["video_id"],
            optional_parameters={},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["The video must belong to the selected project."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="verified_masks_source",
            display_name="Verified Masks",
            category="sources",
            description="Provide existing non-deleted verified mask annotations.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("masks", "Masks", "mask_annotations")],
            required_parameters=[],
            optional_parameters={"label_class_ids": [], "image_ids": []},
            execution_state="executable_source",
            executable=True,
            implementation_notes=["This node reads existing annotations and does not alter them."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="detection_inference",
            display_name="Detection Inference",
            category="inference",
            description="Run an existing registered detector over an image collection.",
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Detector", "model_reference"),
            ],
            output_ports=[_output("proposals", "Detection Proposals", "detection_proposals")],
            required_parameters=[],
            optional_parameters={"confidence": 0.25, "iou": 0.5, "device": "auto"},
            execution_state="executable_inference",
            executable=True,
            implementation_notes=[
                "Invokes the existing inference processor inline with a persisted child job to avoid nested-worker deadlock."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="detection_consensus",
            display_name="Detection Consensus",
            category="auto_label",
            description=(
                "Combine detections from multiple independent models or providers using configurable N-of-M voting."
            ),
            input_ports=[
                _input(
                    "predictions",
                    "Prediction Sources",
                    "detection_proposals",
                    multiple=True,
                )
            ],
            output_ports=[
                _output("consensus", "Consensus Detections", "detection_consensus"),
                _output("disagreements", "Consensus Failures", "detection_disagreements"),
            ],
            required_parameters=[],
            optional_parameters={
                "required_votes": 2,
                "iou_threshold": 0.5,
                "confidence_threshold": 0.0,
                "class_aware": True,
                "box_strategy": "mean",
            },
            execution_state="executable_consensus",
            executable=True,
            implementation_notes=[
                "Each upstream source contributes at most one vote to a matched detection.",
                "The same node accepts local detector outputs now and normalized GPT/Gemini/Claude outputs later.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="segmentation_inference",
            display_name="Segmentation Inference",
            category="inference",
            description="Plan registered instance-segmentation inference over images.",
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Segmenter", "model_reference"),
            ],
            output_ports=[_output("proposals", "Mask Proposals", "mask_proposals")],
            required_parameters=[],
            optional_parameters={"confidence": 0.25, "iou": 0.5, "device": "auto"},
            execution_state="adapter_pending",
            implementation_notes=["The existing segmentation operation still needs a workflow-safe direct adapter."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_inference",
            display_name="Classification Inference",
            category="inference",
            description="Plan top-k classifier inference over images.",
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Classifier", "model_reference"),
            ],
            output_ports=[
                _output("predictions", "Class Predictions", "classification_predictions")
            ],
            required_parameters=["label_set"],
            optional_parameters={"top_k": 5, "device": "auto"},
            execution_state="adapter_pending",
            implementation_notes=["The Phase 5 inference job still needs a workflow-safe direct adapter."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="detection_review_gate",
            display_name="Detection Review Gate",
            category="human_review",
            description="Require human acceptance or rejection of detection proposals.",
            input_ports=[
                _input(
                    "proposals",
                    "Detection Proposals",
                    "detection_proposals",
                    "detection_consensus",
                )
            ],
            output_ports=[_output("boxes", "Reviewed Boxes", "reviewed_boxes")],
            required_parameters=[],
            optional_parameters={"queue_name": None},
            execution_state="review_gate_pending",
            implementation_notes=["Graph execution must pause here until human review is complete."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="mask_review_gate",
            display_name="Mask Review Gate",
            category="human_review",
            description="Require human acceptance or rejection of mask proposals.",
            input_ports=[_input("proposals", "Mask Proposals", "mask_proposals")],
            output_ports=[_output("masks", "Reviewed Masks", "reviewed_masks")],
            required_parameters=[],
            optional_parameters={"queue_name": None},
            execution_state="review_gate_pending",
            implementation_notes=["Graph execution must pause here until human review is complete."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_review_gate",
            display_name="Classification Review Gate",
            category="human_review",
            description="Require human review of classification predictions.",
            input_ports=[
                _input("predictions", "Class Predictions", "classification_predictions")
            ],
            output_ports=[_output("labels", "Reviewed Labels", "reviewed_labels")],
            required_parameters=[],
            optional_parameters={},
            execution_state="review_gate_pending",
            implementation_notes=["Accepted results become normal image labels with provenance."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="mask_measurements",
            display_name="Coral Mask Measurements",
            category="analysis",
            description="Plan calibrated Phase 4 measurements from reviewed or existing masks.",
            input_ports=[_input("masks", "Masks", "reviewed_masks", "mask_annotations")],
            output_ports=[_output("measurements", "Measurement Table", "measurement_table")],
            required_parameters=[],
            optional_parameters={"profile": "default", "export_format": "csv"},
            execution_state="adapter_pending",
            implementation_notes=["The existing measurement services still need a typed workflow adapter."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="video_tracking",
            display_name="Video Tracking",
            category="video",
            description="Plan detector-plus-tracker execution for one managed video.",
            input_ports=[
                _input("video", "Video", "video_reference"),
                _input("model", "Detection Model", "model_reference"),
            ],
            output_ports=[_output("tracks", "Video Tracks", "video_tracks")],
            required_parameters=[],
            optional_parameters={
                "tracker": "bytetrack.yaml",
                "confidence": 0.25,
                "iou": 0.5,
                "minimum_track_frames": 2,
                "device": "auto",
            },
            execution_state="adapter_pending",
            implementation_notes=["The Phase 6 tracker still needs cancellation propagation from workflow runs."],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="project_exchange_export",
            display_name="Project Exchange Export",
            category="exports",
            description="Create a checksummed ReefVision exchange package inline in the workflow run.",
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("package", "Exchange Package", "project_exchange_package")],
            required_parameters=[],
            optional_parameters={
                "include_media": False,
                "include_model_weights": False,
                "include_generated_artifacts": False,
            },
            execution_state="executable_export",
            executable=True,
            implementation_notes=[
                "Executes the Phase 9 export builder directly to avoid nested-worker deadlock."
            ],
        ),
    ]
    return {item.node_type: item for item in definitions}
