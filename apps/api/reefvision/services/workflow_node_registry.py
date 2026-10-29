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
            node_type="scientific_records_source",
            display_name="Scientific Records",
            category="sources",
            description=(
                "Load explicit immutable scientific records for a computed metric without "
                "searching or guessing inputs."
            ),
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[_output("records", "Scientific Records", "scientific_record_collection")],
            required_parameters=["record_ids"],
            optional_parameters={},
            execution_state="executable_source",
            executable=True,
            implementation_notes=[
                "Every record ID is project-scoped and checksum-verified at execution time."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="computed_metric",
            display_name="Computed Scientific Metric",
            category="analysis",
            description=(
                "Evaluate one persisted safe unit-aware metric definition and save its result."
            ),
            input_ports=[_input("records", "Scientific Records", "scientific_record_collection")],
            output_ports=[_output("result", "Computed Metric Result", "computed_metric_result")],
            required_parameters=["definition_id", "bindings"],
            optional_parameters={},
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Uses the same immutable definition/result service as the standalone Metrics UI.",
                "Bindings map declared formula symbols to record IDs in the connected source.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="environmental_threshold",
            display_name="Environmental Threshold Samples",
            category="analysis",
            description=(
                "Evaluate bounded environmental observations against an explicit threshold "
                "without interpolating values or inferring event durations."
            ),
            input_ports=[_input("project", "Project", "project_reference")],
            output_ports=[
                _output(
                    "samples",
                    "Threshold Samples",
                    "environmental_threshold_samples",
                )
            ],
            required_parameters=["query"],
            optional_parameters={},
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "The query uses the validated environmental threshold request schema.",
                "Only currently eligible QC-passing observations are included.",
                "Persisted results contain original record IDs, checksums, and provenance.",
                "An empty result is valid; this node does not infer event durations.",
            ],
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
            implementation_notes=[
                "The selected version must be complete and belong to the project."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="dataset_version_create",
            display_name="Create Dataset Version",
            category="training",
            description=(
                "Freeze current reviewed annotations, masks, and measurements into a new "
                "immutable dataset version."
            ),
            input_ports=[
                _input("project", "Project", "project_reference"),
                _input(
                    "parent_dataset",
                    "Parent Dataset",
                    "dataset_version",
                    required=False,
                ),
                _input(
                    "reviewed",
                    "Reviewed Results",
                    "reviewed_boxes",
                    "reviewed_masks",
                    "reviewed_labels",
                    required=False,
                    multiple=True,
                ),
            ],
            output_ports=[
                _output("dataset", "Dataset Version", "dataset_version"),
                _output("images", "Version Images", "image_collection"),
            ],
            required_parameters=[],
            optional_parameters={
                "name": None,
                "notes": None,
                "eligible_annotation_statuses": ["reviewed"],
                "split_method": "random",
                "requested_ratios": {"train": 0.7, "validation": 0.2, "test": 0.1},
                "split_seed": 42,
                "reuse_parent_assignments": None,
            },
            execution_state="executable_training",
            executable=True,
            implementation_notes=[
                "Uses the same measurement-aware, mask-aware immutable snapshot service as the "
                "Dataset workspace.",
                "Reviewed inputs establish execution order; canonical project state is frozen "
                "only after those review nodes complete.",
                "A workflow-run/node identity makes retries idempotent instead of creating "
                "duplicate dataset versions.",
                "Parent split assignments are reused by default when a parent dataset is "
                "connected.",
            ],
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
            implementation_notes=[
                "Downstream task compatibility is validated from model purpose and task."
            ],
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
                "Invokes the existing inference processor inline with a persisted child job."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="vlm_detection",
            display_name="Cloud VLM Detection",
            category="auto_label",
            description=(
                "Run OpenAI, Gemini, or Claude vision over project images and normalize "
                "detections into ReefVision classes for consensus voting."
            ),
            input_ports=[_input("images", "Images", "image_collection")],
            output_ports=[_output("proposals", "VLM Detections", "detection_proposals")],
            required_parameters=["provider", "model", "label_class_ids"],
            optional_parameters={
                "prompt": "Detect every visible instance of the selected classes.",
            },
            execution_state="executable_cloud_auto_label",
            executable=True,
            implementation_notes=[
                "Cloud inference is disabled by default and requires explicit runtime opt-in.",
                "API credentials come only from protected environment settings and are not "
                "artifacts.",
                "VLM confidence is treated as uncalibrated vote-only evidence.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="detection_consensus",
            display_name="Detection Consensus",
            category="auto_label",
            description=(
                "Combine detections from independent models or providers using N-of-M voting."
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
                "Local detectors and cloud VLM detections share the same normalized input type.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="segmentation_inference",
            display_name="Segmentation Inference",
            category="inference",
            description="Run registered instance or semantic segmentation over images.",
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Segmenter", "model_reference"),
            ],
            output_ports=[_output("proposals", "Mask Proposals", "mask_proposals")],
            required_parameters=[],
            optional_parameters={"confidence": 0.25, "iou": 0.5, "device": "auto"},
            execution_state="executable_inference",
            executable=True,
            implementation_notes=[
                "Reuses the production instance/semantic inference processor and persists "
                "child-job provenance."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_inference",
            display_name="Classification Inference",
            category="inference",
            description="Run top-k registered classifier inference over images.",
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Classifier", "model_reference"),
            ],
            output_ports=[
                _output("predictions", "Class Predictions", "classification_predictions")
            ],
            required_parameters=["label_set"],
            optional_parameters={"top_k": 5, "device": "auto"},
            execution_state="executable_inference",
            executable=True,
            implementation_notes=[
                "Reuses the Phase 5 classification inference processor and reviewable predictions."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_dataset_materialize",
            display_name="Classification Dataset",
            category="training",
            description=(
                "Materialize a whole-image or crop classification dataset from an immutable "
                "dataset version."
            ),
            input_ports=[_input("dataset", "Dataset Version", "dataset_version")],
            output_ports=[
                _output(
                    "classification_dataset", "Classification Dataset", "classification_dataset"
                )
            ],
            required_parameters=[],
            optional_parameters={
                "mode": "image",
                "label_set": "default",
                "minimum_crop_pixels": 16,
            },
            execution_state="executable_training",
            executable=True,
            implementation_notes=[
                "Uses the existing immutable classification dataset materializer.",
                "Modes are image, box_crop, and mask_crop.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_training",
            display_name="Classification Training",
            category="training",
            description=(
                "Train an Ultralytics classifier and return the automatically registered model."
            ),
            input_ports=[
                _input("classification_dataset", "Classification Dataset", "classification_dataset")
            ],
            output_ports=[_output("model", "Registered Classifier", "model_reference")],
            required_parameters=[],
            optional_parameters={
                "architecture": "yolo11n-cls.pt",
                "run_name": "classification",
                "epochs": 50,
                "image_size": 224,
                "batch": 16,
                "device": "auto",
            },
            execution_state="executable_training",
            executable=True,
            implementation_notes=[
                "Reuses the production classification_training job inline to avoid nested-worker "
                "deadlock.",
                "The production job registers the trained classifier automatically.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="model_training",
            display_name="Model Training",
            category="training",
            description=(
                "Train or retrain detection, instance-segmentation, or semantic-segmentation "
                "models from an immutable ReefVision dataset version."
            ),
            input_ports=[
                _input("dataset", "Dataset Version", "dataset_version"),
                _input(
                    "initial_model",
                    "Initial Model",
                    "model_reference",
                    required=False,
                ),
            ],
            output_ports=[_output("training", "Training Result", "training_result")],
            required_parameters=["task"],
            optional_parameters={
                "draft_name": None,
                "run_name": None,
                "notes": None,
                "catalog_model_id": None,
                "provider_id": None,
                "architecture": None,
                "device": "auto",
                "precision": "fp32",
                "random_seed": None,
                "tiling_config": {},
                "training_config": {},
                "tuning_config": {},
                "evaluation_config": {},
                "resource_limits": {},
            },
            execution_state="executable_training",
            executable=True,
            implementation_notes=[
                "Uses the existing Training workspace preflight and task-aware production worker.",
                "Supported tasks are detect, segment, and semantic_segment.",
                "An optional registered detector or segmenter seeds retraining without creating "
                "a separate retrain code path.",
                "Semantic nnU-Net training currently starts from scratch.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="register_trained_model",
            display_name="Register Trained Model",
            category="training",
            description=(
                "Register a completed workflow training checkpoint in ReefVision's normal model "
                "registry."
            ),
            input_ports=[_input("training", "Training Result", "training_result")],
            output_ports=[_output("model", "Registered Model", "model_reference")],
            required_parameters=[],
            optional_parameters={"display_name": None, "notes": None},
            execution_state="executable_training",
            executable=True,
            implementation_notes=[
                "Preserves dataset, split, experiment, architecture, provider, and checkpoint "
                "lineage.",
                "The resulting model_reference can feed normal inference or later retraining "
                "nodes.",
                (
                    "Trained pose checkpoints are bound to the exact existing frozen "
                    "landmark-schema revision used for training; registration does not "
                    "invent a replacement pose schema."
                ),
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="detection_review_gate",
            display_name="Detection Review Gate",
            category="human_review",
            description="Pause until detection proposals or consensus detections are reviewed.",
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
            execution_state="pausable_review_gate",
            executable=True,
            implementation_notes=[
                "Execution persists a waiting-for-review state and resumes without rerunning "
                "completed nodes."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="prompt_assist_masks",
            display_name="Prompt Assist Masks",
            category="auto_label",
            description=(
                "Convert reviewed detection boxes into reviewable raster mask proposals using "
                "a registered box-prompt assist model."
            ),
            input_ports=[
                _input("boxes", "Reviewed Boxes", "reviewed_boxes"),
                _input("model", "Assist Model", "model_reference"),
            ],
            output_ports=[_output("proposals", "Mask Proposals", "mask_proposals")],
            required_parameters=[],
            optional_parameters={"device": "auto"},
            execution_state="executable_prompt_assist",
            executable=True,
            implementation_notes=[
                "Uses the provider-neutral AnnotationAssistProvider box-prompt interface.",
                "Outputs remain pending PredictionProposals until the Mask Review Gate approves "
                "them.",
                "Works with Segment Anything and registered local SAM2 bundles.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="relative_depth_estimation",
            display_name="Relative Depth Estimation",
            category="analysis",
            description=(
                "Run a registered Depth Anything V2 model over project images and persist "
                "relative-depth arrays plus 16-bit preview maps."
            ),
            input_ports=[
                _input("images", "Images", "image_collection"),
                _input("model", "Depth Model", "model_reference"),
            ],
            output_ports=[_output("depth_maps", "Relative Depth Maps", "relative_depth_maps")],
            required_parameters=[],
            optional_parameters={"device": "auto"},
            execution_state="executable_depth",
            executable=True,
            implementation_notes=[
                "Depth Anything V2 outputs are relative monocular depth, not metric distance.",
                "Artifacts persist float32 .npy data, 16-bit PNG previews, and checksums.",
                "metric_units remains null unless a future calibrated conversion node is added.",
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="mask_review_gate",
            display_name="Mask Review Gate",
            category="human_review",
            description="Pause until segmentation proposals are reviewed.",
            input_ports=[_input("proposals", "Mask Proposals", "mask_proposals")],
            output_ports=[_output("masks", "Reviewed Masks", "reviewed_masks")],
            required_parameters=[],
            optional_parameters={"queue_name": None},
            execution_state="pausable_review_gate",
            executable=True,
            implementation_notes=[
                "Execution persists a waiting-for-review state and resumes after all proposals "
                "are reviewed."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="classification_review_gate",
            display_name="Classification Review Gate",
            category="human_review",
            description="Pause until classification predictions are reviewed.",
            input_ports=[_input("predictions", "Class Predictions", "classification_predictions")],
            output_ports=[_output("labels", "Reviewed Labels", "reviewed_labels")],
            required_parameters=[],
            optional_parameters={},
            execution_state="pausable_review_gate",
            executable=True,
            implementation_notes=[
                "Execution persists a waiting-for-review state and resumes after classification "
                "review."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="mask_measurements",
            display_name="Coral Mask Measurements",
            category="analysis",
            description="Calculate calibrated Phase 4 measurements from verified masks.",
            input_ports=[_input("masks", "Masks", "reviewed_masks", "mask_annotations")],
            output_ports=[_output("measurements", "Measurement Table", "measurement_table")],
            required_parameters=[],
            optional_parameters={"profile": "default"},
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Uses the existing scientific measurement service and emits typed measurement rows."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="video_tracking",
            display_name="Video Tracking",
            category="video",
            description="Run detector-plus-tracker execution for one managed video.",
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
            execution_state="executable_video",
            executable=True,
            implementation_notes=[
                "Reuses the Phase 6 production tracker and records its child job and tracks."
            ],
        ),
        WorkflowNodeDefinitionResponse(
            node_type="project_exchange_export",
            display_name="Project Exchange Export",
            category="exports",
            description=(
                "Create a checksummed ReefVision exchange package inline in the workflow run."
            ),
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
