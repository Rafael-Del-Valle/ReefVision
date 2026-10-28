export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  graph: Record<string, unknown>;
}

const projectImages = {
  graph_id: "project-images-runtime",
  name: "Project images runtime",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 80 },
    },
    {
      node_id: "images",
      node_type: "project_images",
      parameters: {},
      position: { x: 360, y: 80 },
    },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
  ],
};

const computedScientificMetric = {
  graph_id: "computed-scientific-metric",
  name: "Computed scientific metric",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 80 },
    },
    {
      node_id: "records",
      node_type: "scientific_records_source",
      parameters: {
        record_ids: ["replace-with-scientific-record-id"],
      },
      position: { x: 360, y: 80 },
    },
    {
      node_id: "metric",
      node_type: "computed_metric",
      parameters: {
        definition_id: "replace-with-metric-definition-id",
        bindings: { input: "replace-with-scientific-record-id" },
      },
      position: { x: 700, y: 80 },
    },
  ],
  edges: [
    {
      edge_id: "project-records",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "records",
      target_port_id: "project",
    },
    {
      edge_id: "records-metric",
      source_node_id: "records",
      source_port_id: "records",
      target_node_id: "metric",
      target_port_id: "records",
    },
  ],
};

const localConsensus = {
  graph_id: "two-of-three-detection-consensus",
  name: "2-of-3 local detection consensus",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 280 },
    },
    {
      node_id: "images",
      node_type: "project_images",
      parameters: {},
      position: { x: 340, y: 280 },
    },
    ...["a", "b", "c"].map((suffix, index) => ({
      node_id: `model_${suffix}`,
      node_type: "registered_model_source",
      parameters: { model_id: `replace-with-model-${suffix}-id` },
      position: { x: 40, y: 40 + index * 180 },
    })),
    ...["a", "b", "c"].map((suffix, index) => ({
      node_id: `detect_${suffix}`,
      node_type: "detection_inference",
      parameters: { confidence: 0.25, iou: 0.5, device: "auto" },
      position: { x: 650, y: 40 + index * 180 },
    })),
    {
      node_id: "consensus",
      node_type: "detection_consensus",
      parameters: {
        required_votes: 2,
        iou_threshold: 0.5,
        confidence_threshold: 0.25,
        class_aware: true,
        box_strategy: "mean",
      },
      position: { x: 970, y: 220 },
    },
    {
      node_id: "review",
      node_type: "detection_review_gate",
      parameters: {},
      position: { x: 1270, y: 220 },
    },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
    ...["a", "b", "c"].flatMap((suffix) => [
      {
        edge_id: `project-model-${suffix}`,
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: `model_${suffix}`,
        target_port_id: "project",
      },
      {
        edge_id: `images-detect-${suffix}`,
        source_node_id: "images",
        source_port_id: "images",
        target_node_id: `detect_${suffix}`,
        target_port_id: "images",
      },
      {
        edge_id: `model-detect-${suffix}`,
        source_node_id: `model_${suffix}`,
        source_port_id: "model",
        target_node_id: `detect_${suffix}`,
        target_port_id: "model",
      },
      {
        edge_id: `detect-consensus-${suffix}`,
        source_node_id: `detect_${suffix}`,
        source_port_id: "proposals",
        target_node_id: "consensus",
        target_port_id: "predictions",
      },
    ]),
    {
      edge_id: "consensus-review",
      source_node_id: "consensus",
      source_port_id: "consensus",
      target_node_id: "review",
      target_port_id: "proposals",
    },
  ],
};

const cloudConsensus = {
  graph_id: "gpt-gemini-claude-auto-label",
  name: "GPT + Gemini + Claude 2-of-3 Auto Label",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 260 },
    },
    {
      node_id: "images",
      node_type: "project_images",
      parameters: {},
      position: { x: 330, y: 260 },
    },
    {
      node_id: "openai",
      node_type: "vlm_detection",
      parameters: {
        provider: "openai",
        model: "replace-with-openai-model",
        label_class_ids: ["replace-with-project-class-id"],
        prompt:
          "Detect every visible instance of the selected ReefVision classes.",
      },
      position: { x: 640, y: 40 },
    },
    {
      node_id: "gemini",
      node_type: "vlm_detection",
      parameters: {
        provider: "gemini",
        model: "replace-with-gemini-model",
        label_class_ids: ["replace-with-project-class-id"],
        prompt:
          "Detect every visible instance of the selected ReefVision classes.",
      },
      position: { x: 640, y: 260 },
    },
    {
      node_id: "claude",
      node_type: "vlm_detection",
      parameters: {
        provider: "anthropic",
        model: "replace-with-claude-model",
        label_class_ids: ["replace-with-project-class-id"],
        prompt:
          "Detect every visible instance of the selected ReefVision classes.",
      },
      position: { x: 640, y: 480 },
    },
    {
      node_id: "consensus",
      node_type: "detection_consensus",
      parameters: {
        required_votes: 2,
        iou_threshold: 0.5,
        confidence_threshold: 0,
        class_aware: true,
        box_strategy: "mean",
      },
      position: { x: 970, y: 260 },
    },
    {
      node_id: "review",
      node_type: "detection_review_gate",
      parameters: {},
      position: { x: 1280, y: 260 },
    },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
    ...["openai", "gemini", "claude"].flatMap((provider) => [
      {
        edge_id: `images-${provider}`,
        source_node_id: "images",
        source_port_id: "images",
        target_node_id: provider,
        target_port_id: "images",
      },
      {
        edge_id: `${provider}-consensus`,
        source_node_id: provider,
        source_port_id: "proposals",
        target_node_id: "consensus",
        target_port_id: "predictions",
      },
    ]),
    {
      edge_id: "consensus-review",
      source_node_id: "consensus",
      source_port_id: "consensus",
      target_node_id: "review",
      target_port_id: "proposals",
    },
  ],
};

const detectionTraining = {
  graph_id: "detection-training",
  name: "Detection training and inference",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 180 },
    },
    {
      node_id: "dataset",
      node_type: "dataset_version_source",
      parameters: { dataset_version_id: "replace-with-dataset-version-id" },
      position: { x: 330, y: 180 },
    },
    {
      node_id: "train",
      node_type: "model_training",
      parameters: {
        task: "detect",
        architecture: "yolo11n.yaml",
        run_name: "workflow-detection",
        device: "auto",
        precision: "fp32",
        training_config: { epochs: 50 },
      },
      position: { x: 650, y: 180 },
    },
    {
      node_id: "register",
      node_type: "register_trained_model",
      parameters: {},
      position: { x: 970, y: 180 },
    },
    {
      node_id: "infer",
      node_type: "detection_inference",
      parameters: { confidence: 0.25, iou: 0.5 },
      position: { x: 1280, y: 180 },
    },
  ],
  edges: [
    {
      edge_id: "project-dataset",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "dataset",
      target_port_id: "project",
    },
    {
      edge_id: "dataset-train",
      source_node_id: "dataset",
      source_port_id: "dataset",
      target_node_id: "train",
      target_port_id: "dataset",
    },
    {
      edge_id: "train-register",
      source_node_id: "train",
      source_port_id: "training",
      target_node_id: "register",
      target_port_id: "training",
    },
    {
      edge_id: "dataset-infer-images",
      source_node_id: "dataset",
      source_port_id: "images",
      target_node_id: "infer",
      target_port_id: "images",
    },
    {
      edge_id: "register-infer",
      source_node_id: "register",
      source_port_id: "model",
      target_node_id: "infer",
      target_port_id: "model",
    },
  ],
};

const reviewRetrain = {
  graph_id: "review-dataset-retrain",
  name: "Review → Dataset v2 → Retrain",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 300 },
    },
    {
      node_id: "parent_dataset",
      node_type: "dataset_version_source",
      parameters: { dataset_version_id: "replace-with-parent-dataset-id" },
      position: { x: 330, y: 80 },
    },
    {
      node_id: "initial_model",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-detector-model-id" },
      position: { x: 330, y: 500 },
    },
    {
      node_id: "infer_v1",
      node_type: "detection_inference",
      parameters: { confidence: 0.25, iou: 0.5 },
      position: { x: 640, y: 300 },
    },
    {
      node_id: "review",
      node_type: "detection_review_gate",
      parameters: {},
      position: { x: 940, y: 300 },
    },
    {
      node_id: "dataset_v2",
      node_type: "dataset_version_create",
      parameters: {
        name: "Reviewed dataset v2",
        reuse_parent_assignments: true,
      },
      position: { x: 1240, y: 180 },
    },
    {
      node_id: "retrain",
      node_type: "model_training",
      parameters: {
        task: "detect",
        run_name: "active-learning-retrain",
        training_config: { epochs: 50 },
      },
      position: { x: 1240, y: 500 },
    },
    {
      node_id: "register_v2",
      node_type: "register_trained_model",
      parameters: {},
      position: { x: 1530, y: 500 },
    },
  ],
  edges: [
    {
      edge_id: "project-parent",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "parent_dataset",
      target_port_id: "project",
    },
    {
      edge_id: "project-model",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "initial_model",
      target_port_id: "project",
    },
    {
      edge_id: "parent-infer",
      source_node_id: "parent_dataset",
      source_port_id: "images",
      target_node_id: "infer_v1",
      target_port_id: "images",
    },
    {
      edge_id: "model-infer",
      source_node_id: "initial_model",
      source_port_id: "model",
      target_node_id: "infer_v1",
      target_port_id: "model",
    },
    {
      edge_id: "infer-review",
      source_node_id: "infer_v1",
      source_port_id: "proposals",
      target_node_id: "review",
      target_port_id: "proposals",
    },
    {
      edge_id: "project-v2",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "dataset_v2",
      target_port_id: "project",
    },
    {
      edge_id: "parent-v2",
      source_node_id: "parent_dataset",
      source_port_id: "dataset",
      target_node_id: "dataset_v2",
      target_port_id: "parent_dataset",
    },
    {
      edge_id: "review-v2",
      source_node_id: "review",
      source_port_id: "boxes",
      target_node_id: "dataset_v2",
      target_port_id: "reviewed",
    },
    {
      edge_id: "v2-retrain",
      source_node_id: "dataset_v2",
      source_port_id: "dataset",
      target_node_id: "retrain",
      target_port_id: "dataset",
    },
    {
      edge_id: "initial-retrain",
      source_node_id: "initial_model",
      source_port_id: "model",
      target_node_id: "retrain",
      target_port_id: "initial_model",
    },
    {
      edge_id: "retrain-register",
      source_node_id: "retrain",
      source_port_id: "training",
      target_node_id: "register_v2",
      target_port_id: "training",
    },
  ],
};

const classificationTraining = {
  graph_id: "classification-training",
  name: "Classification training",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 180 },
    },
    {
      node_id: "dataset",
      node_type: "dataset_version_source",
      parameters: { dataset_version_id: "replace-with-dataset-version-id" },
      position: { x: 330, y: 180 },
    },
    {
      node_id: "classification_dataset",
      node_type: "classification_dataset_materialize",
      parameters: {
        mode: "image",
        label_set: "default",
        minimum_crop_pixels: 16,
      },
      position: { x: 640, y: 180 },
    },
    {
      node_id: "train_classifier",
      node_type: "classification_training",
      parameters: {
        architecture: "yolo11n-cls.pt",
        epochs: 50,
        image_size: 224,
        batch: 16,
        device: "auto",
      },
      position: { x: 960, y: 180 },
    },
    {
      node_id: "infer_classifier",
      node_type: "classification_inference",
      parameters: { label_set: "default", top_k: 5, device: "auto" },
      position: { x: 1280, y: 180 },
    },
  ],
  edges: [
    {
      edge_id: "project-dataset",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "dataset",
      target_port_id: "project",
    },
    {
      edge_id: "dataset-classification",
      source_node_id: "dataset",
      source_port_id: "dataset",
      target_node_id: "classification_dataset",
      target_port_id: "dataset",
    },
    {
      edge_id: "classification-train",
      source_node_id: "classification_dataset",
      source_port_id: "classification_dataset",
      target_node_id: "train_classifier",
      target_port_id: "classification_dataset",
    },
    {
      edge_id: "dataset-infer",
      source_node_id: "dataset",
      source_port_id: "images",
      target_node_id: "infer_classifier",
      target_port_id: "images",
    },
    {
      edge_id: "model-infer",
      source_node_id: "train_classifier",
      source_port_id: "model",
      target_node_id: "infer_classifier",
      target_port_id: "model",
    },
  ],
};

const samMeasurements = {
  graph_id: "reviewed-boxes-to-measurements",
  name: "Detection → SAM/SAM2 → Measurements",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 220 },
    },
    {
      node_id: "images",
      node_type: "project_images",
      parameters: {},
      position: { x: 330, y: 100 },
    },
    {
      node_id: "detector",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-detector-model-id" },
      position: { x: 330, y: 340 },
    },
    {
      node_id: "detect",
      node_type: "detection_inference",
      parameters: {},
      position: { x: 640, y: 100 },
    },
    {
      node_id: "box_review",
      node_type: "detection_review_gate",
      parameters: {},
      position: { x: 940, y: 100 },
    },
    {
      node_id: "assist_model",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-sam-or-sam2-model-id" },
      position: { x: 640, y: 420 },
    },
    {
      node_id: "assist_masks",
      node_type: "prompt_assist_masks",
      parameters: { device: "auto" },
      position: { x: 1240, y: 220 },
    },
    {
      node_id: "mask_review",
      node_type: "mask_review_gate",
      parameters: {},
      position: { x: 1510, y: 220 },
    },
    {
      node_id: "measure",
      node_type: "mask_measurements",
      parameters: {},
      position: { x: 1510, y: 480 },
    },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
    {
      edge_id: "project-detector",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "detector",
      target_port_id: "project",
    },
    {
      edge_id: "images-detect",
      source_node_id: "images",
      source_port_id: "images",
      target_node_id: "detect",
      target_port_id: "images",
    },
    {
      edge_id: "detector-detect",
      source_node_id: "detector",
      source_port_id: "model",
      target_node_id: "detect",
      target_port_id: "model",
    },
    {
      edge_id: "detect-review",
      source_node_id: "detect",
      source_port_id: "proposals",
      target_node_id: "box_review",
      target_port_id: "proposals",
    },
    {
      edge_id: "project-assist",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "assist_model",
      target_port_id: "project",
    },
    {
      edge_id: "review-assist",
      source_node_id: "box_review",
      source_port_id: "boxes",
      target_node_id: "assist_masks",
      target_port_id: "boxes",
    },
    {
      edge_id: "model-assist",
      source_node_id: "assist_model",
      source_port_id: "model",
      target_node_id: "assist_masks",
      target_port_id: "model",
    },
    {
      edge_id: "assist-review",
      source_node_id: "assist_masks",
      source_port_id: "proposals",
      target_node_id: "mask_review",
      target_port_id: "proposals",
    },
    {
      edge_id: "review-measure",
      source_node_id: "mask_review",
      source_port_id: "masks",
      target_node_id: "measure",
      target_port_id: "masks",
    },
  ],
};

const poseActiveLearningRetrain = {
  graph_id: "pose-active-learning-retrain",
  name: "Pose Active Learning → retrain",
  schema_version: "workflow-graph-0001",
  metadata: {
    workflow_kind: "scientist_active_learning_loop",
    truth_policy: "scientist_verified_only",
    feedback_loop: {
      from_node_id: "register",
      to_node_id: "pose",
      label: "Next iteration: trained model → inference",
      description:
        "Use the newly registered pose model as the seed model for the next saved workflow revision. This visual cue is not an executable cyclic edge.",
    },
  },
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 300 },
    },
    {
      node_id: "video",
      node_type: "project_video_source",
      parameters: { video_id: "replace-with-video-id" },
      position: { x: 340, y: 80 },
    },
    {
      node_id: "seed",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-pose-model-id" },
      position: { x: 340, y: 540 },
    },
    {
      node_id: "pose",
      node_type: "pose_inference",
      parameters: { device: "auto", confidence: 0.25 },
      position: { x: 650, y: 280 },
    },
    {
      node_id: "temporal",
      node_type: "pose_temporal_association",
      parameters: {},
      position: { x: 960, y: 280 },
    },
    {
      node_id: "pose_review",
      node_type: "pose_review_gate",
      parameters: {},
      position: { x: 1270, y: 280 },
    },
    {
      node_id: "al",
      node_type: "pose_active_learning",
      parameters: { requested_size: 20, diversity_balance: true },
      position: { x: 1580, y: 120 },
    },
    {
      node_id: "al_review",
      node_type: "pose_active_learning_review_gate",
      parameters: {},
      position: { x: 1890, y: 120 },
    },
    {
      node_id: "freeze",
      node_type: "pose_training_dataset_freeze",
      parameters: { name: "Verified pose training dataset" },
      position: { x: 2200, y: 120 },
    },
    {
      node_id: "pose_export",
      node_type: "pose_training_export",
      parameters: { format: "native" },
      position: { x: 2510, y: 20 },
    },
    {
      node_id: "train",
      node_type: "pose_model_training",
      parameters: {
        run_name: "workflow-pose-retrain",
        initialization_mode: "registered_model",
        device: "auto",
        precision: "fp32",
        training_config: {
          epochs: 50,
          patience: 20,
          batch: 8,
          imgsz: 640,
          optimizer: "auto",
          workers: 2,
          cache: false,
          plots: true,
        },
      },
      position: { x: 2510, y: 340 },
    },
    {
      node_id: "register",
      node_type: "register_trained_model",
      parameters: {},
      position: { x: 2820, y: 340 },
    },
    {
      node_id: "results",
      node_type: "training_results_package",
      parameters: {
        include_excel: true,
        include_machine_data: true,
        include_native_artifacts: true,
        include_logs: true,
        checkpoint_mode: "best",
      },
      position: { x: 2820, y: 600 },
    },
  ],
  edges: [
    {
      edge_id: "project-video",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "video",
      target_port_id: "project",
    },
    {
      edge_id: "project-seed",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "seed",
      target_port_id: "project",
    },
    {
      edge_id: "video-pose",
      source_node_id: "video",
      source_port_id: "video",
      target_node_id: "pose",
      target_port_id: "video",
    },
    {
      edge_id: "seed-pose",
      source_node_id: "seed",
      source_port_id: "model",
      target_node_id: "pose",
      target_port_id: "model",
    },
    {
      edge_id: "pose-temporal",
      source_node_id: "pose",
      source_port_id: "poses",
      target_node_id: "temporal",
      target_port_id: "poses",
    },
    {
      edge_id: "temporal-review",
      source_node_id: "temporal",
      source_port_id: "tracks",
      target_node_id: "pose_review",
      target_port_id: "tracks",
    },
    {
      edge_id: "review-al",
      source_node_id: "pose_review",
      source_port_id: "poses",
      target_node_id: "al",
      target_port_id: "tracks",
    },
    {
      edge_id: "al-review",
      source_node_id: "al",
      source_port_id: "round",
      target_node_id: "al_review",
      target_port_id: "round",
    },
    {
      edge_id: "review-freeze",
      source_node_id: "al_review",
      source_port_id: "verified_round",
      target_node_id: "freeze",
      target_port_id: "verified_round",
    },
    {
      edge_id: "freeze-export",
      source_node_id: "freeze",
      source_port_id: "dataset",
      target_node_id: "pose_export",
      target_port_id: "dataset",
    },
    {
      edge_id: "freeze-train",
      source_node_id: "freeze",
      source_port_id: "dataset",
      target_node_id: "train",
      target_port_id: "dataset",
    },
    {
      edge_id: "seed-train",
      source_node_id: "seed",
      source_port_id: "model",
      target_node_id: "train",
      target_port_id: "initial_model",
    },
    {
      edge_id: "train-register",
      source_node_id: "train",
      source_port_id: "training",
      target_node_id: "register",
      target_port_id: "training",
    },
    {
      edge_id: "train-results",
      source_node_id: "train",
      source_port_id: "training",
      target_node_id: "results",
      target_port_id: "training",
    },
  ],
};

export function createPoseArchitectureWorkflow(
  architecture = "yolo11n-pose.yaml",
) {
  return {
    graph_id: "pose-architecture-training",
    name: "Pose architecture training",
    schema_version: "workflow-graph-0001",
    metadata: { truth_policy: "scientist_verified_only" },
    nodes: [
      {
        node_id: "dataset",
        node_type: "pose_training_dataset",
        parameters: { dataset_id: "" },
        position: { x: 40, y: 80 },
      },
      {
        node_id: "train",
        node_type: "pose_model_training",
        parameters: {
          run_name: "pose-from-scratch",
          initialization_mode: "random",
          architecture,
          device: "auto",
          precision: "fp32",
          training_config: { epochs: 50, batch: 8, imgsz: 640, workers: 2 },
        },
        position: { x: 360, y: 80 },
      },
      {
        node_id: "register",
        node_type: "register_trained_model",
        parameters: {},
        position: { x: 680, y: 80 },
      },
      {
        node_id: "results",
        node_type: "training_results_package",
        parameters: {},
        position: { x: 680, y: 320 },
      },
    ],
    edges: [
      {
        edge_id: "dataset-train",
        source_node_id: "dataset",
        source_port_id: "dataset",
        target_node_id: "train",
        target_port_id: "dataset",
      },
      {
        edge_id: "train-register",
        source_node_id: "train",
        source_port_id: "training",
        target_node_id: "register",
        target_port_id: "training",
      },
      {
        edge_id: "train-results",
        source_node_id: "train",
        source_port_id: "training",
        target_node_id: "results",
        target_port_id: "training",
      },
    ],
  };
}

export const workflowTemplates: WorkflowTemplate[] = [
  {
    id: "pose-architecture-training",
    name: "Pose architecture → train from scratch",
    description:
      "Choose a frozen scientist-verified pose dataset and a YOLO11 pose architecture. Train from random initialization, then register the output with its landmark schema and provenance.",
    graph: createPoseArchitectureWorkflow(),
  },
  {
    id: "pose-active-learning-retrain",
    name: "Pose Active Learning → retrain",
    description:
      "Pose inference → temporal identity → scientist review → Active Learning → verified dataset → retrain → register → Results Package, with a visual next-iteration cue.",
    graph: poseActiveLearningRetrain,
  },
  {
    id: "computed-scientific-metric",
    name: "Computed scientific metric",
    description:
      "Explicit scientific records → safe unit-aware definition → immutable result.",
    graph: computedScientificMetric,
  },
  {
    id: "project-images",
    name: "Project images",
    description: "Minimal executable source workflow.",
    graph: projectImages,
  },
  {
    id: "local-consensus",
    name: "Local 2-of-3 consensus",
    description: "Three registered detectors vote before human review.",
    graph: localConsensus,
  },
  {
    id: "cloud-consensus",
    name: "GPT + Gemini + Claude",
    description:
      "Three cloud VLM providers feed a 2-of-3 detection consensus review gate.",
    graph: cloudConsensus,
  },
  {
    id: "detection-training",
    name: "Detection training",
    description: "Immutable dataset → train → register → inference.",
    graph: detectionTraining,
  },
  {
    id: "review-retrain",
    name: "Review → Dataset v2 → Retrain",
    description:
      "Review predictions, freeze a child dataset version, and retrain from the prior detector.",
    graph: reviewRetrain,
  },
  {
    id: "classification-training",
    name: "Classification training",
    description:
      "Dataset version → classification materialization → train → inference.",
    graph: classificationTraining,
  },
  {
    id: "sam-measurements",
    name: "SAM/SAM2 measurements",
    description:
      "Detection review → Prompt Assist masks → mask review → coral measurements.",
    graph: samMeasurements,
  },
];
