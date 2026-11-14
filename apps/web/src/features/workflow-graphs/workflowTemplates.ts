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

function environmentalAnalysisGraph(
  graphId: string,
  name: string,
  nodeType: string,
  parameters: Record<string, unknown>,
) {
  return {
    graph_id: graphId,
    name,
    schema_version: "workflow-graph-0001",
    metadata: {
      scientific_scope: "descriptive_environmental_context",
      causal_claims_supported: false,
    },
    nodes: [
      {
        node_id: "project",
        node_type: "project_source",
        parameters: {},
        position: { x: 40, y: 80 },
      },
      {
        node_id: "analysis",
        node_type: nodeType,
        parameters,
        position: { x: 380, y: 80 },
      },
    ],
    edges: [
      {
        edge_id: "project-analysis",
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: "analysis",
        target_port_id: "project",
      },
    ],
  };
}

const environmentalAnalysisTemplates: WorkflowTemplate[] = [
  {
    id: "environmental-current-streamlines",
    name: "Persisted current streamlines",
    description:
      "Explicit paired current records and seeds â†’ deterministic frozen-field streamlines with immutable provenance.",
    graph: environmentalAnalysisGraph(
      "persisted-current-streamlines",
      "Persisted current streamlines",
      "current_streamline_analysis",
      {
        name: "Current streamlines",
        scientific_record_ids: ["replace-with-current-record-id"],
        seeds: [{ latitude: 32.7808, longitude: -79.9236 }],
        step_seconds: 60,
        max_steps: 1000,
        max_length_m: 100000,
        stagnation_m_s: 1e-9,
      },
    ),
  },
  {
    id: "environmental-lunar-context",
    name: "Persisted lunar context",
    description:
      "Explicit UTC timestamps â†’ deterministic offline lunar calculation â†’ immutable evidence.",
    graph: environmentalAnalysisGraph(
      "persisted-lunar-context",
      "Persisted lunar context",
      "lunar_context_analysis",
      {
        name: "Lunar context",
        observed_at: ["2026-04-03T13:00:00Z"],
      },
    ),
  },
  {
    id: "environmental-tidal-context",
    name: "Bounded NOAA tidal context",
    description:
      "Explicit station, datum, UTC time, and distance bounds â†’ separate observed and predicted tidal evidence.",
    graph: environmentalAnalysisGraph(
      "bounded-noaa-tidal-context",
      "Bounded NOAA tidal context",
      "tidal_context_analysis",
      {
        name: "Tidal context",
        observed_at: "2026-04-03T13:00:00Z",
        location: { latitude: 32.7808, longitude: -79.9236 },
        station_id: "8665530",
        datum: "MLLW",
        max_time_delta_s: 900,
        max_distance_m: 1000,
      },
    ),
  },
  {
    id: "environmental-event-windows",
    name: "Environmental event windows",
    description:
      "Saved threshold samples â†’ explicit bounded windows with deterministic overlap merging.",
    graph: environmentalAnalysisGraph(
      "environmental-event-windows",
      "Environmental event windows",
      "event_window_analysis",
      {
        name: "Environmental event windows",
        event_definition_id: "replace-with-threshold-definition-id",
        before_s: 3600,
        after_s: 3600,
        boundary_policy: "inclusive",
      },
    ),
  },
  {
    id: "environmental-observation-join",
    name: "Observationâ€“environment join",
    description:
      "Explicit biological records â†’ bounded time, location, and optional depth matching.",
    graph: environmentalAnalysisGraph(
      "observation-environment-join",
      "Observationâ€“environment join",
      "observation_environment_join",
      {
        name: "Observationâ€“environment join",
        observation_record_ids: ["replace-with-observation-record-id"],
        environmental_variable: "water_temperature",
        max_time_delta_s: 3600,
        max_distance_m: 1000,
        require_depth_match: false,
        max_depth_delta_m: 0,
      },
    ),
  },
  {
    id: "environmental-lagged-comparison",
    name: "Descriptive lagged comparison",
    description:
      "Saved observation join â†’ explicit lags with sample-reuse and pseudoreplication diagnostics.",
    graph: environmentalAnalysisGraph(
      "descriptive-lagged-comparison",
      "Descriptive lagged comparison",
      "lagged_comparison",
      {
        name: "Descriptive lagged comparison",
        join_result_id: "replace-with-join-result-id",
        lags_s: [-3600, 0, 3600],
      },
    ),
  },
];

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

const reviewedAnnotationAggregate = {
  graph_id: "reviewed-annotation-aggregate",
  name: "Reviewed annotation aggregate",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 80 },
    },
    {
      node_id: "aggregate",
      node_type: "annotation_aggregate",
      parameters: {
        definition_id: "replace-with-aggregate-definition-id",
        image_ids: ["replace-with-reviewed-image-id"],
      },
      position: { x: 380, y: 80 },
    },
  ],
  edges: [
    {
      edge_id: "project-aggregate",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "aggregate",
      target_port_id: "project",
    },
  ],
};

const verifiedMaskCoverage = {
  graph_id: "verified-mask-coverage",
  name: "Verified mask area and coverage",
  schema_version: "workflow-graph-0001",
  nodes: [
    {
      node_id: "project",
      node_type: "project_source",
      parameters: {},
      position: { x: 40, y: 80 },
    },
    {
      node_id: "coverage",
      node_type: "mask_coverage",
      parameters: {
        definition_id: "replace-with-mask-coverage-definition-id",
        image_ids: ["replace-with-reviewed-image-id"],
      },
      position: { x: 380, y: 80 },
    },
  ],
  edges: [
    {
      edge_id: "project-coverage",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "coverage",
      target_port_id: "project",
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
  name: "Review â†’ Dataset v2 â†’ Retrain",
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
  name: "Detection â†’ SAM/SAM2 â†’ Measurements",
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
  name: "Pose Active Learning â†’ retrain",
  schema_version: "workflow-graph-0001",
  metadata: {
    workflow_kind: "scientist_active_learning_loop",
    truth_policy: "scientist_verified_only",
    feedback_loop: {
      from_node_id: "register",
      to_node_id: "pose",
      label: "Next iteration: trained model â†’ inference",
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
  const nativeReefPose = architecture === "reefpose-s";
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
          provider_id: nativeReefPose ? "reefpose" : "ultralytics",
          initialization_mode: "random",
          architecture,
          device: "auto",
          precision: nativeReefPose ? "amp" : "fp32",
          training_config: nativeReefPose
            ? {
                epochs: 50,
                batch: 8,
                input_height: 256,
                input_width: 256,
                learning_rate: 0.0003,
                weight_decay: 0.0001,
                workers: 2,
              }
            : { epochs: 50, batch: 8, imgsz: 640, workers: 2 },
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

export function createPoseComparisonWorkflow() {
  return {
    graph_id: "pose-model-comparison",
    name: "Pose model comparison",
    schema_version: "workflow-graph-0001",
    metadata: { truth_policy: "scientist_verified_only" },
    nodes: [
      {
        node_id: "dataset",
        node_type: "pose_training_dataset",
        parameters: { dataset_id: "" },
        position: { x: 40, y: 180 },
      },
      ...["a", "b"].map((suffix, index) => ({
        node_id: `model_${suffix}`,
        node_type: "registered_model_source",
        parameters: { model_id: `replace-with-pose-model-${suffix}-id` },
        position: { x: 40, y: 360 + index * 180 },
      })),
      {
        node_id: "evaluate",
        node_type: "pose_model_evaluation",
        parameters: {
          device: "auto",
          pck_thresholds: [0.05, 0.1, 0.2],
          calibration_threshold: 0.1,
          calibration_bins: 10,
          confidence_thresholds: [0, 0.25, 0.5, 0.75, 0.9],
        },
        position: { x: 420, y: 260 },
      },
    ],
    edges: [
      {
        edge_id: "dataset-evaluate",
        source_node_id: "dataset",
        source_port_id: "dataset",
        target_node_id: "evaluate",
        target_port_id: "dataset",
      },
      ...["a", "b"].map((suffix) => ({
        edge_id: `model-${suffix}-evaluate`,
        source_node_id: `model_${suffix}`,
        source_port_id: "model",
        target_node_id: "evaluate",
        target_port_id: "models",
      })),
    ],
  };
}

export function createPoseIdentityEvaluationWorkflow() {
  return {
    graph_id: "pose-identity-evaluation",
    name: "Multi-animal pose identity evaluation",
    schema_version: "workflow-graph-0001",
    metadata: {
      truth_policy: "scientist_verified_only",
      synthetic_data_warning:
        "Synthetic fixtures validate engineering behavior, not biological accuracy.",
    },
    nodes: [
      {
        node_id: "project",
        node_type: "project_source",
        parameters: {},
        position: { x: 40, y: 100 },
      },
      {
        node_id: "video",
        node_type: "project_video_source",
        parameters: { video_id: "" },
        position: { x: 300, y: 40 },
      },
      {
        node_id: "model",
        node_type: "registered_model_source",
        parameters: { model_id: "" },
        position: { x: 300, y: 180 },
      },
      {
        node_id: "pose",
        node_type: "pose_inference",
        parameters: { device: "auto" },
        position: { x: 580, y: 100 },
      },
      {
        node_id: "associate",
        node_type: "pose_identity_association",
        parameters: {
          max_gap_frames: 5,
          max_normalized_distance: 1.5,
          acceptance_threshold: 0.75,
          low_confidence_threshold: 0.6,
        },
        position: { x: 860, y: 100 },
      },
      {
        node_id: "review",
        node_type: "pose_identity_review_gate",
        parameters: {},
        position: { x: 1140, y: 100 },
      },
      {
        node_id: "evaluate",
        node_type: "pose_identity_evaluation",
        parameters: { truth_dataset_id: "", spatial_iou_threshold: 0.5 },
        position: { x: 1420, y: 100 },
      },
      {
        node_id: "export",
        node_type: "pose_identity_export",
        parameters: { format: "json" },
        position: { x: 1700, y: 100 },
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
        edge_id: "project-model",
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: "model",
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
        edge_id: "model-pose",
        source_node_id: "model",
        source_port_id: "model",
        target_node_id: "pose",
        target_port_id: "model",
      },
      {
        edge_id: "pose-associate",
        source_node_id: "pose",
        source_port_id: "poses",
        target_node_id: "associate",
        target_port_id: "poses",
      },
      {
        edge_id: "associate-review",
        source_node_id: "associate",
        source_port_id: "tracks",
        target_node_id: "review",
        target_port_id: "tracks",
      },
      {
        edge_id: "review-evaluate",
        source_node_id: "review",
        source_port_id: "tracks",
        target_node_id: "evaluate",
        target_port_id: "tracks",
      },
      {
        edge_id: "evaluate-export",
        source_node_id: "evaluate",
        source_port_id: "evaluation",
        target_node_id: "export",
        target_port_id: "evaluation",
      },
    ],
  };
}

export function createBiologicalMovementWorkflow() {
  const nodes = [
    ["project", "project_source", {}, 40],
    ["video", "project_video_source", { video_id: "" }, 300],
    ["model", "registered_model_source", { model_id: "" }, 300],
    ["pose", "pose_inference", { device: "auto" }, 560],
    ["associate", "pose_identity_association", {}, 820],
    ["identity_review", "pose_identity_review_gate", {}, 1080],
    [
      "measure",
      "anatomical_measurement",
      {
        definitions: [
          {
            id: "gape",
            name: "Gape distance",
            kind: "distance",
            landmark_ids: ["upper_jaw", "lower_jaw"],
          },
        ],
        maximum_gap_s: 0.25,
      },
      1340,
    ],
    [
      "detect",
      "biological_event_detection",
      {
        cycles: [
          {
            measurement_definition_id: "gape",
            open_threshold: 6,
            close_threshold: 3,
            minimum_amplitude: 4,
            minimum_duration_s: 0.1,
            maximum_gap_s: 0.25,
          },
        ],
      },
      1600,
    ],
    ["event_review", "biological_event_review_gate", {}, 1860],
    ["export", "biological_movement_export", { format: "json" }, 2120],
  ].map(([node_id, node_type, parameters, x]) => ({
    node_id,
    node_type,
    parameters,
    position: { x, y: 100 },
  }));
  const link = (
    edge_id: string,
    source_node_id: string,
    source_port_id: string,
    target_node_id: string,
    target_port_id: string,
  ) => ({
    edge_id,
    source_node_id,
    source_port_id,
    target_node_id,
    target_port_id,
  });
  return {
    graph_id: "reefpose-biological-movement",
    name: "ReefPose biological movement analysis",
    schema_version: "workflow-graph-0001",
    metadata: {
      truth_policy: "scientist_reviewed_events_only",
      synthetic_data_warning:
        "Synthetic fixtures validate engineering behavior, not biological accuracy.",
    },
    nodes,
    edges: [
      link("project-video", "project", "project", "video", "project"),
      link("project-model", "project", "project", "model", "project"),
      link("video-pose", "video", "video", "pose", "video"),
      link("model-pose", "model", "model", "pose", "model"),
      link("pose-associate", "pose", "poses", "associate", "poses"),
      link(
        "associate-review",
        "associate",
        "tracks",
        "identity_review",
        "tracks",
      ),
      link("review-measure", "identity_review", "tracks", "measure", "tracks"),
      link(
        "measure-detect",
        "measure",
        "measurements",
        "detect",
        "measurements",
      ),
      link("detect-review", "detect", "events", "event_review", "events"),
      link("review-export", "event_review", "events", "export", "events"),
    ],
  };
}

export const workflowTemplates: WorkflowTemplate[] = [
  ...environmentalAnalysisTemplates,
  {
    id: "verified-mask-coverage",
    name: "Verified mask area and coverage",
    description:
      "Explicit reviewed images â†’ overlap-safe mask union and coverage â†’ immutable result.",
    graph: verifiedMaskCoverage,
  },
  {
    id: "reviewed-annotation-aggregate",
    name: "Reviewed annotation aggregate",
    description:
      "Explicit reviewed images â†’ replicate-aware verified annotation count â†’ immutable result.",
    graph: reviewedAnnotationAggregate,
  },
  {
    id: "pose-model-comparison",
    name: "Pose models â†’ scientific comparison",
    description:
      "Evaluate multiple registered pose models on one frozen scientist-verified dataset and preserve a reproducible comparison report.",
    graph: createPoseComparisonWorkflow(),
  },
  {
    id: "reefpose-biological-movement",
    name: "ReefPose biological movement",
    description:
      "Pose inference â†’ identity review â†’ anatomical measurements â†’ event detection â†’ scientist review â†’ reproducible export.",
    graph: createBiologicalMovementWorkflow(),
  },
  {
    id: "pose-architecture-training",
    name: "Pose architecture â†’ train from scratch",
    description:
      "Choose a frozen scientist-verified pose dataset and a YOLO11 pose architecture. Train from random initialization, then register the output with its landmark schema and provenance.",
    graph: createPoseArchitectureWorkflow(),
  },
  {
    id: "reefpose-native-training",
    name: "Native ReefPose training",
    description:
      "Train ReefPose-S from random initialization on an immutable verified pose dataset and register the completed checkpoint.",
    graph: createPoseArchitectureWorkflow("reefpose-s"),
  },
  {
    id: "pose-active-learning-retrain",
    name: "Pose Active Learning â†’ retrain",
    description:
      "Pose inference â†’ temporal identity â†’ scientist review â†’ Active Learning â†’ verified dataset â†’ retrain â†’ register â†’ Results Package, with a visual next-iteration cue.",
    graph: poseActiveLearningRetrain,
  },
  {
    id: "computed-scientific-metric",
    name: "Computed scientific metric",
    description:
      "Explicit scientific records â†’ safe unit-aware definition â†’ immutable result.",
    graph: computedScientificMetric,
  },
  {
    id: "pose-identity-evaluation",
    name: "Multi-animal pose identity evaluation",
    description:
      "Pose inference â†’ deterministic individual association â†’ scientist identity review â†’ IDF1 evaluation â†’ provenance-preserving export.",
    graph: createPoseIdentityEvaluationWorkflow(),
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
    description: "Immutable dataset â†’ train â†’ register â†’ inference.",
    graph: detectionTraining,
  },
  {
    id: "review-retrain",
    name: "Review â†’ Dataset v2 â†’ Retrain",
    description:
      "Review predictions, freeze a child dataset version, and retrain from the prior detector.",
    graph: reviewRetrain,
  },
  {
    id: "classification-training",
    name: "Classification training",
    description:
      "Dataset version â†’ classification materialization â†’ train â†’ inference.",
    graph: classificationTraining,
  },
  {
    id: "sam-measurements",
    name: "SAM/SAM2 measurements",
    description:
      "Detection review â†’ Prompt Assist masks â†’ mask review â†’ coral measurements.",
    graph: samMeasurements,
  },
];
