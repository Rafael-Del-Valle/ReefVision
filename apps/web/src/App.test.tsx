import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type {
  AnnotationSession,
  ClassVisibilityBundle,
  Project,
  ProjectImage,
  ProjectSummary,
} from "./api/client";

const systemVersion = {
  application_version: "1.0.1",
  backup_format_version: "1.0",
  environment: "test",
  data_dir: "C:/ReefVisionData",
  safe_mode: false,
  database_path: "C:/ReefVisionData/reefvision.db",
  current_schema_revision: "0009",
  expected_schema_revision: "0009",
};

const systemCompatibility = {
  application_version: "1.0.1",
  schema_status: "up_to_date",
  compatible_for_read_write: true,
  current_schema_revision: "0009",
  expected_schema_revision: "0009",
  pending_revisions: [],
  details: ["The database schema matches the current ReefVision code."],
};

const systemLogs = {
  logs_dir: "C:/ReefVisionData/logs",
  files: [
    {
      name: "api.log",
      path: "C:/ReefVisionData/logs/api.log",
      size_bytes: 2048,
      modified_at: "2026-07-09T00:00:00Z",
    },
  ],
};

const systemCommandShortcuts = {
  command_version: "1.0.1",
  command_directory: "C:/Users/test/AppData/Local/ReefVision/bin",
  support_directory: "C:/Users/test/AppData/Local/ReefVision/commands",
  repo_path: "C:/src/ReefVision/reefvision",
  path_contains_command_directory: false,
  start_command_exists: false,
  update_command_exists: false,
  support_start_exists: false,
  support_update_exists: false,
  start_command_managed: false,
  update_command_managed: false,
  verification_result: "repair_required",
  notes: [
    "The ReefVision command directory is not present in the current user's PATH.",
  ],
};

const backupList = [
  {
    id: "backup-1",
    job_id: "job-backup-1",
    status: "completed",
    format_version: "1.0",
    destination_path: "bk/backup-1",
    staging_path: "bk/.t/backup-1",
    manifest_path: "bk/backup-1/backup-manifest.json",
    completion_marker_path: "bk/backup-1/backup-complete.json",
    database_filename: "reefvision.db",
    request_json: {
      preview: {
        included_sections: ["database", "projects", "thumbnails"],
        estimated_file_count: 4,
        estimated_total_size_bytes: 4096,
      },
    },
    result_json: null,
    error_message: null,
    created_at: "2026-07-09T00:00:00Z",
    started_at: "2026-07-09T00:00:01Z",
    completed_at: "2026-07-09T00:00:05Z",
  },
];

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral polyp annotations",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: "Muricea pendula",
      state_name: "Closed",
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

function toProjectSummary(value: Project): ProjectSummary {
  return {
    id: value.id,
    name: value.name,
    slug: value.slug,
    description: value.description,
    storage_root: value.storage_root,
    default_annotation_type: value.default_annotation_type,
    georeference_height_offset_m: value.georeference_height_offset_m,
    georeference_height_evidence: value.georeference_height_evidence,
    created_at: value.created_at,
    updated_at: value.updated_at,
    archived_at: value.archived_at,
    label_class_count: value.label_classes.length,
    active_label_class_count: value.label_classes.filter(
      (item) => item.is_active,
    ).length,
  };
}

const image: ProjectImage = {
  id: "image-1",
  project_id: project.id,
  original_filename: "swiftia-01.png",
  managed_path: "projects/project-1/images/originals/image-1.png",
  thumbnail_path: null,
  sha256: "a".repeat(64),
  width_px: 1600,
  height_px: 1200,
  file_size_bytes: 1000,
  media_type: "image/png",
  import_source: "trial/swiftia-01.png",
  capture_timestamp: null,
  group_key: null,
  metadata_json: {},
  annotation_status: "unannotated",
  annotation_revision: 0,
  annotation_count: 0,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
};

const annotationSession: AnnotationSession = {
  image,
  label_classes: project.label_classes,
  annotations: [],
  counts_by_class: [{ label_class_id: "class-1", count: 0 }],
  previous_image_id: null,
  next_image_id: null,
};

const defaultClassVisibilityBundle: ClassVisibilityBundle = {
  project_id: project.id,
  user_identity: "local-user:test",
  supported_layer_types: [
    "annotations",
    "predictions",
    "qc_overlays",
    "video_tracks",
    "segmentation_overlays",
  ],
  precedence: [
    "temporary_qc_reveal",
    "session_override",
    "user_preference",
    "project_default",
    "visible_by_default",
  ],
  user_preferences: {
    annotations: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    predictions: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    qc_overlays: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    video_tracks: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    segmentation_overlays: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
  },
  project_defaults: {
    annotations: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    predictions: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    qc_overlays: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    video_tracks: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
    segmentation_overlays: {
      saved: false,
      hidden_class_ids: [],
      updated_at: null,
      updated_by_identity: null,
    },
  },
};

const modelProviderPreflight = {
  providers: [
    {
      provider_name: "ultralytics",
      display_name: "Ultralytics detector",
      purpose: "detector",
      provider_version: "8.3.228",
      status: "ready",
      ready: true,
      tested_python: "3.12.x",
      current_python: "3.12.7",
      tested_platform: "Windows AMD64",
      current_platform: "Windows AMD64",
      tested_cuda: "12.1",
      current_cuda: "12.1",
      automatic_downloads_disabled: true,
      explicit_checkpoint_required: true,
      requirements_file: "requirements/providers-windows-cu121-py312.txt",
      packages: [
        {
          distribution_name: "ultralytics",
          required_version: "8.3.228",
          installed_version: "8.3.228",
          status: "ok",
        },
      ],
      issues: [],
    },
    {
      provider_name: "segment_anything",
      display_name: "Segment Anything assist",
      purpose: "assist",
      provider_version: "1.0",
      status: "ready",
      ready: true,
      tested_python: "3.12.x",
      current_python: "3.12.7",
      tested_platform: "Windows AMD64",
      current_platform: "Windows AMD64",
      tested_cuda: "12.1",
      current_cuda: "12.1",
      automatic_downloads_disabled: true,
      explicit_checkpoint_required: true,
      requirements_file: "requirements/providers-windows-cu121-py312.txt",
      packages: [
        {
          distribution_name: "segment-anything",
          required_version: "1.0",
          installed_version: "1.0",
          status: "ok",
        },
      ],
      issues: [],
    },
  ],
};

const modelProviderCatalog = [
  {
    provider_id: "ultralytics",
    display_name: "Ultralytics YOLO",
    provider_version: "8.3.228",
    package_version: "8.3.228",
    supported_model_families: [
      "Ultralytics YOLO object-detection checkpoints",
      "Ultralytics YOLO segmentation checkpoints",
    ],
    supported_tasks: ["detect", "segment"],
    supported_input_types: ["image"],
    supported_output_types: ["prediction_proposals", "bounding_boxes"],
    cpu_support: true,
    cuda_support: true,
    supported_precision_modes: ["fp32", "amp"],
    video_support: false,
    training_support: true,
    tiling_support: false,
    supported_execution_runtimes: ["pytorch"],
    required_packages: [],
    required_model_files: [".pt", ".pth"],
    code_license: "See the installed Ultralytics package license metadata.",
    weight_license:
      "Varies by checkpoint; users must verify checkpoint redistribution terms.",
    memory_recommendations: ["CUDA is recommended for larger checkpoints."],
    known_limitations: [
      "Detection and segmentation checkpoints currently generate box proposals in the ReefVision review workflow.",
    ],
    desktop_packaging_state: "base_sidecar_provider",
    clean_machine_verification_state: "pinned_stack_preflight_available",
    availability_status: "ready",
    availability_reason: null,
    default_registration_purpose: "detector",
    registerable: true,
    capabilities: {
      image_detection: true,
      image_instance_segmentation: false,
      image_semantic_segmentation: false,
      text_prompt_detection: false,
      image_example_detection: false,
      click_prompting: false,
      box_prompting: false,
      brush_prompting: false,
      mask_prompting: false,
      video_propagation: false,
      multi_object_tracking: false,
      training: true,
      validation: false,
      tiled_training: false,
      tiled_inference: false,
      export: false,
      cpu_inference: true,
      cuda_inference: true,
      fp16: false,
      quantized_inference: false,
      packaged_desktop_operation: true,
    },
  },
  {
    provider_id: "grounding_dino",
    display_name: "Grounding DINO",
    provider_version: "planned",
    package_version: null,
    supported_model_families: ["Grounding DINO text-conditioned detectors"],
    supported_tasks: ["open_vocabulary_detect", "phrase_grounding"],
    supported_input_types: ["image", "text_prompt"],
    supported_output_types: ["prediction_proposals", "bounding_boxes"],
    cpu_support: true,
    cuda_support: true,
    supported_precision_modes: ["fp32", "fp16"],
    video_support: false,
    training_support: false,
    tiling_support: false,
    supported_execution_runtimes: ["pytorch"],
    required_packages: [],
    required_model_files: [".safetensors", ".bin"],
    code_license:
      "Would depend on the pinned Transformers implementation and package metadata.",
    weight_license:
      "Varies by checkpoint; users must verify checkpoint redistribution terms.",
    memory_recommendations: [
      "Text-grounding checkpoints should be isolated behind an optional provider pack.",
    ],
    known_limitations: [
      "Transformers is not pinned or installed in the current desktop provider stack.",
    ],
    desktop_packaging_state: "optional_pack_required",
    clean_machine_verification_state: "not_verified",
    availability_status: "not_implemented",
    availability_reason:
      "Grounding DINO is not implemented in ReefVision and the compatible Transformers stack is not yet pinned for desktop packaging.",
    default_registration_purpose: "detector",
    registerable: false,
    capabilities: {
      image_detection: true,
      image_instance_segmentation: false,
      image_semantic_segmentation: false,
      text_prompt_detection: true,
      image_example_detection: false,
      click_prompting: false,
      box_prompting: false,
      brush_prompting: false,
      mask_prompting: false,
      video_propagation: false,
      multi_object_tracking: false,
      training: false,
      validation: false,
      tiled_training: false,
      tiled_inference: false,
      export: false,
      cpu_inference: true,
      cuda_inference: true,
      fp16: false,
      quantized_inference: false,
      packaged_desktop_operation: false,
    },
  },
];

const runtimeProviderStatuses = [
  {
    runtime_id: "pytorch",
    display_name: "PyTorch",
    package_name: "torch",
    package_version: "2.5.1+cu121",
    available: true,
    status: "ready",
    supports_cpu: true,
    supports_cuda: true,
    notes: ["Reference runtime for the implemented ReefVision providers."],
  },
  {
    runtime_id: "onnxruntime",
    display_name: "ONNX Runtime",
    package_name: "onnxruntime",
    package_version: null,
    available: false,
    status: "missing",
    supports_cpu: true,
    supports_cuda: true,
    notes: [
      "No ONNX Runtime model registration or execution path exists in ReefVision yet.",
    ],
  },
];

const trainingProviders = [
  {
    provider_id: "ultralytics",
    display_name: "Ultralytics YOLO",
    provider_version: "8.3.228",
    supported_tasks: ["detect"],
    supported_precision_modes: ["fp32", "amp"],
    supports_tiling: false,
    supports_tuning: false,
    supports_packaged_desktop: true,
    warning:
      "This Training foundation currently supports only Ultralytics object detection.",
    architectures: [
      {
        architecture_id: "yolo11.yaml",
        display_name: "yolo11",
        task: "detect",
        source: "11/yolo11.yaml",
      },
    ],
  },
];

const trainingDrafts = [
  {
    id: "draft-1",
    project_id: project.id,
    name: "Draft 1",
    run_name: "cpt-detect",
    notes: "Detection baseline",
    dataset_version_id: "version-1",
    dataset_manifest_sha256: "f".repeat(64),
    split_manifest_sha256: "e".repeat(64),
    task: "detect",
    catalog_model_id: "ultralytics/yolo11/detect/x",
    provider_id: "ultralytics",
    architecture: "yolo11.yaml",
    initial_checkpoint_source: "scratch",
    initial_checkpoint_model_id: null,
    device: "auto",
    precision: "fp32",
    random_seed: 11,
    tiling_config: { mode: "none", tile_width: 640, tile_height: 640 },
    training_config: { epochs: 5, batch: 4, imgsz: 640, patience: 10 },
    tuning_config: { mode: "disabled" },
    evaluation_config: { split: "validation", conf: 0.25, iou: 0.45 },
    resource_limits: { max_disk_usage_gb: 5 },
    validation_state: {
      status: "ready",
      warnings: [],
      blockers: [],
      dataset: {
        dataset_version_id: "version-1",
        dataset_manifest_sha256: "f".repeat(64),
        split_manifest_sha256: "e".repeat(64),
        image_count: 3,
        annotation_count: 6,
        split_counts: { train: 2, validation: 1 },
        group_count: 2,
        warnings: [],
      },
      leakage_audit: {
        blocked: false,
        warnings: [],
        blockers: [],
        image_leak_count: 0,
        group_leak_count: 0,
      },
      resource_snapshot: { requested_device: "auto" },
      provider_dependency_status: { provider_name: "ultralytics", ready: true },
    },
    created_at: "2026-07-09T00:00:00Z",
    updated_at: "2026-07-09T00:00:00Z",
  },
];

const trainingRuns = [
  {
    id: "training-run-1",
    project_id: project.id,
    draft_id: "draft-1",
    dataset_version_id: "version-1",
    dataset_manifest_sha256: "f".repeat(64),
    split_manifest_sha256: "e".repeat(64),
    task: "detect",
    provider_id: "ultralytics",
    architecture: "yolo11.yaml",
    initial_checkpoint_source: "scratch",
    initial_checkpoint_model_id: null,
    device: "auto",
    precision: "fp32",
    run_name: "cpt-detect",
    notes: "Detection baseline",
    random_seed: 11,
    tiling_config: { mode: "none" },
    training_config: { epochs: 5, batch: 4, imgsz: 640 },
    tuning_config: { mode: "disabled" },
    evaluation_config: { split: "validation" },
    resource_limits: { max_disk_usage_gb: 5 },
    preflight_report: {},
    draft_snapshot: {},
    status: "completed",
    stage: "completed",
    progress_epoch: 5,
    progress_total_epochs: 5,
    metrics: { "metrics/mAP50(B)": 0.7 },
    metrics_history: {},
    warnings: [],
    artifact_manifest: {},
    logs_path: "projects/project-1/training/training.log",
    result_checkpoint_path: "projects/project-1/training/best.pt",
    job_id: "job-training-1",
    error_message: null,
    created_at: "2026-07-09T00:00:00Z",
    started_at: "2026-07-09T00:00:10Z",
    completed_at: "2026-07-09T00:01:10Z",
    updated_at: "2026-07-09T00:01:10Z",
  },
];

const experiments = [
  {
    id: "experiment-1",
    project_id: project.id,
    training_run_id: "training-run-1",
    dataset_version_id: "version-1",
    dataset_manifest_sha256: "f".repeat(64),
    split_manifest_sha256: "e".repeat(64),
    task: "detect",
    provider_id: "ultralytics",
    architecture: "yolo11.yaml",
    summary_metrics_json: { "metrics/mAP50(B)": 0.7 },
    comparison_warnings_json: [],
    artifact_manifest_json: {},
    package_versions_json: { ultralytics: "8.3.228" },
    created_at: "2026-07-09T00:01:10Z",
  },
];

const ultralyticsTrainingRegistry = {
  provider_name: "ultralytics",
  provider_version: "8.3.228",
  ultralytics_version: "8.3.228",
  pinned_version_matches_installed: true,
  supported_tasks: ["detect", "segment"],
  supported_modes: ["train", "val", "predict", "export", "tune"],
  method_signatures: {
    train: "(self, trainer=None, **kwargs: 'Any')",
    val: "(self, validator=None, **kwargs: 'Any')",
    predict:
      "(self, source=None, stream=False, predictor=None, **kwargs: 'Any')",
    export: "(self, **kwargs: 'Any') -> 'str'",
    tune: "(self, use_ray=False, iterations=10, *args: 'Any', **kwargs: 'Any')",
  },
  summary: {
    parameter_count: 105,
    reefvision_supported_parameter_count: 82,
    tunable_parameter_count: 31,
    native_tune_parameter_count: 23,
    fixed_only_parameter_count: 29,
  },
  parameters: [
    {
      name: "epochs",
      display_name: "Epochs",
      category: "core_training",
      value_type: "int",
      default_value: 100,
      minimum: 1,
      maximum: 1000,
      choices: [],
      supported_tasks: ["detect", "segment"],
      supported_modes: ["train", "tune"],
      reefvision_supported: true,
      tunable: true,
      fixed_only: false,
      native_tune_default: false,
      help_text: "Total training epochs.",
      dependency_rules: [],
      supported_version: "8.3.228",
      native_tune_minimum: null,
      native_tune_maximum: null,
      native_tune_gain: null,
      native_tune_scale: null,
    },
    {
      name: "lr0",
      display_name: "Initial Learning Rate",
      category: "optimization",
      value_type: "float",
      default_value: 0.01,
      minimum: 0.00001,
      maximum: 0.1,
      choices: [],
      supported_tasks: ["detect", "segment"],
      supported_modes: ["train", "tune"],
      reefvision_supported: true,
      tunable: true,
      fixed_only: false,
      native_tune_default: true,
      help_text: "Initial learning rate.",
      dependency_rules: [],
      supported_version: "8.3.228",
      native_tune_minimum: 0.00001,
      native_tune_maximum: 0.1,
      native_tune_gain: null,
      native_tune_scale: "log",
    },
    {
      name: "overlap_mask",
      display_name: "Overlap Mask",
      category: "segmentation",
      value_type: "bool",
      default_value: true,
      minimum: null,
      maximum: null,
      choices: [false, true],
      supported_tasks: ["segment"],
      supported_modes: ["train", "tune"],
      reefvision_supported: true,
      tunable: true,
      fixed_only: false,
      native_tune_default: false,
      help_text: "Segmentation mask overlap behavior.",
      dependency_rules: ["Available only for ReefVision segment workflows."],
      supported_version: "8.3.228",
      native_tune_minimum: null,
      native_tune_maximum: null,
      native_tune_gain: null,
      native_tune_scale: null,
    },
    {
      name: "dropout",
      display_name: "Dropout",
      category: "unsupported_task",
      value_type: "float",
      default_value: 0,
      minimum: 0,
      maximum: 1,
      choices: [],
      supported_tasks: [],
      supported_modes: ["train", "tune"],
      reefvision_supported: false,
      tunable: false,
      fixed_only: true,
      native_tune_default: false,
      help_text: "Classification-only dropout parameter.",
      dependency_rules: [
        "Classification-only parameter. ReefVision does not currently implement classify training.",
      ],
      supported_version: "8.3.228",
      native_tune_minimum: null,
      native_tune_maximum: null,
      native_tune_gain: null,
      native_tune_scale: null,
    },
  ],
};

const modelCatalogBootstrap = {
  schema_version: 1,
  catalog_version: "test-catalog",
  models: [
    {
      catalog_id: "ultralytics/yolo11/detect/x",
      display_name: "YOLO11 X",
      display_summary: "Pinned object-detection preset",
      category: "pretrained_catalog",
      provider: "ultralytics",
      provider_version: "8.3.228",
      architecture_family: "yolo11",
      model_variant: "x",
      model_size: "x",
      task: "detect",
      trainable: true,
      inference: true,
      video_compatibility: false,
      prompt_assist_compatibility: false,
      tiling_compatibility: false,
      tuning_compatibility: false,
      checkpoint_identifier: null,
      checkpoint_source: "builtin",
      expected_checksum: null,
      expected_file_size: null,
      model_weight_license: "Varies by checkpoint",
      package_license: "See Ultralytics package metadata",
      required_provider_pack: null,
      required_package_versions: ["ultralytics==8.3.228"],
      supported_runtime: ["pytorch"],
      supported_devices: ["cpu", "cuda"],
      supported_precision: ["fp32", "amp"],
      expected_input_size: { width: 640, height: 640 },
      minimum_recommended_ram_gb: 8,
      minimum_recommended_vram_gb: 8,
      desktop_package_status: "base_sidecar_provider",
      clean_machine_verification_status: "pinned_stack_preflight_available",
      deprecation_status: "active",
      replacement_model_id: null,
      known_limitations: [],
      installation_state: "Ready",
      installation_reason: null,
      advanced_only: false,
      requires_confirmation: true,
      selection_kind: "builtin_architecture",
      architecture_reference: "yolo11.yaml",
      resolved_model_id: "builtin_architecture:yolo11.yaml",
    },
  ],
};

function toTrainingDraftSummary(draft: (typeof trainingDrafts)[number]) {
  return {
    id: draft.id,
    project_id: draft.project_id,
    name: draft.name,
    run_name: draft.run_name,
    dataset_version_id: draft.dataset_version_id,
    task: draft.task,
    catalog_model_id: draft.catalog_model_id ?? null,
    provider_id: draft.provider_id,
    architecture: draft.architecture,
    initial_checkpoint_source: draft.initial_checkpoint_source,
    validation_status: draft.validation_state.status,
    warning_count: draft.validation_state.warnings.length,
    blocker_count: draft.validation_state.blockers.length,
    created_at: draft.created_at,
    updated_at: draft.updated_at,
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi({
  projects = [],
  images = [],
  session = annotationSession,
  models = [],
  datasetVersions = [],
  exports = [],
  qcRuns = [],
  reviewQueues = [],
  providerPreflight = modelProviderPreflight,
  providerCatalog = modelProviderCatalog,
  runtimeStatuses = runtimeProviderStatuses,
  trainingRegistry = ultralyticsTrainingRegistry,
  trainingProvidersCatalog = trainingProviders,
  savedTrainingDrafts = trainingDrafts,
  savedTrainingRuns = trainingRuns,
  savedExperiments = experiments,
  backupHistory = backupList,
  shortcutStatus = systemCommandShortcuts,
}: {
  projects?: Project[];
  images?: ProjectImage[];
  session?: AnnotationSession;
  models?: unknown[];
  datasetVersions?: unknown[];
  exports?: unknown[];
  qcRuns?: unknown[];
  reviewQueues?: unknown[];
  providerPreflight?: unknown;
  providerCatalog?: unknown;
  runtimeStatuses?: unknown;
  trainingRegistry?: unknown;
  trainingProvidersCatalog?: unknown[];
  savedTrainingDrafts?: typeof trainingDrafts;
  savedTrainingRuns?: typeof trainingRuns;
  savedExperiments?: typeof experiments;
  backupHistory?: unknown[];
  shortcutStatus?: typeof systemCommandShortcuts;
} = {}) {
  const trainingDraftSummaries = savedTrainingDrafts.map(
    toTrainingDraftSummary,
  );
  const trainingWorkspaceBootstrap = {
    draft_summaries: trainingDraftSummaries,
    selected_draft: savedTrainingDrafts[0] ?? null,
    providers: trainingProvidersCatalog,
    catalog: modelCatalogBootstrap,
  };
  const modelHubBootstrap = {
    catalog: modelCatalogBootstrap,
    models,
    providers: providerCatalog,
    provider_preflight: providerPreflight,
    runtime_statuses: runtimeStatuses,
    training_compatibility: {
      provider_name: "ultralytics",
      provider_version: "8.3.228",
      ultralytics_version: "8.3.228",
      pinned_version_matches_installed: true,
      supported_tasks: ["detect", "segment"],
      supported_modes: ["train", "val", "predict", "export", "tune"],
      summary: {
        parameter_count: 105,
        reefvision_supported_parameter_count: 82,
        tunable_parameter_count: 31,
        native_tune_parameter_count: 23,
        fixed_only_parameter_count: 29,
      },
    },
    provider_catalog_checked_at: "2026-07-09T00:00:00Z",
    provider_preflight_checked_at: "2026-07-09T00:00:00Z",
    runtime_statuses_checked_at: "2026-07-09T00:00:00Z",
    training_compatibility_checked_at: "2026-07-09T00:00:00Z",
  };

  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return jsonResponse({ status: "ok", version: "1.0.1" });
      }
      if (url.endsWith("/system/version")) {
        return jsonResponse(systemVersion);
      }
      if (url.endsWith("/system/compatibility")) {
        return jsonResponse(systemCompatibility);
      }
      if (url.endsWith("/system/logs/location")) {
        return jsonResponse(systemLogs);
      }
      if (
        url.endsWith("/system/command-shortcuts") &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(shortcutStatus);
      }
      if (
        url.endsWith("/system/command-shortcuts/repair") &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          status: {
            ...shortcutStatus,
            path_contains_command_directory: true,
            start_command_exists: true,
            update_command_exists: true,
            support_start_exists: true,
            support_update_exists: true,
            start_command_managed: true,
            update_command_managed: true,
            verification_result: "ready",
            notes: [],
          },
          output:
            "Installed start-reefvision and update-reefvision into the ReefVision command directory.",
        });
      }
      if (
        url.endsWith("/backups") &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(backupHistory);
      }
      if (url.endsWith("/system/diagnostics") && init?.method === "POST") {
        return jsonResponse({
          job: {
            id: "diagnostics-job-1",
            project_id: null,
            job_type: "diagnostics",
            status: "queued",
            progress_current: 0,
            progress_total: 1,
            request_json: {},
            result_json: { stage: "queued" },
            error_message: null,
            created_at: "2026-07-09T00:00:00Z",
            started_at: null,
            completed_at: null,
          },
        });
      }
      if (url.includes("/system/diagnostics/")) {
        return jsonResponse({
          job: {
            id: "diagnostics-job-1",
            project_id: null,
            job_type: "diagnostics",
            status: "succeeded",
            progress_current: 1,
            progress_total: 1,
            request_json: {},
            result_json: {
              stage: "completed",
              bundle_path: "diagnostics/reefvision-diagnostics.zip",
              bundle_size_bytes: 2048,
              diagnostic_bundle_version: "1.0",
            },
            error_message: null,
            created_at: "2026-07-09T00:00:00Z",
            started_at: "2026-07-09T00:00:01Z",
            completed_at: "2026-07-09T00:00:03Z",
          },
          bundle_path: "diagnostics/reefvision-diagnostics.zip",
          bundle_size_bytes: 2048,
          diagnostic_bundle_version: "1.0",
        });
      }
      if (
        url.endsWith("/project-summaries") &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(projects.map(toProjectSummary));
      }
      if (
        url.endsWith("/projects") &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(projects);
      }
      if (url.endsWith("/projects") && init?.method === "POST") {
        return jsonResponse(project, 201);
      }
      if (url.endsWith(`/projects/${project.id}`)) {
        return jsonResponse(project);
      }
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: images,
          total: images.length,
          page: 1,
          page_size: 24,
          pages: images.length > 0 ? 1 : 0,
        });
      }
      if (url.includes(`/projects/${project.id}/dataset-versions`)) {
        return jsonResponse(datasetVersions);
      }
      if (
        url.endsWith(`/projects/${project.id}/exchange-packages`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse([]);
      }
      if (url.endsWith(`/projects/${project.id}/training/bootstrap`)) {
        return jsonResponse(trainingWorkspaceBootstrap);
      }
      if (url.endsWith(`/projects/${project.id}/model-hub/bootstrap`)) {
        return jsonResponse(modelHubBootstrap);
      }
      if (url.endsWith("/training/providers")) {
        return jsonResponse(trainingProvidersCatalog);
      }
      if (url.endsWith("/training/providers/ultralytics/parameters")) {
        return jsonResponse(trainingRegistry);
      }
      if (url.includes(`/projects/${project.id}/training-draft-summaries`)) {
        return jsonResponse(
          savedTrainingDrafts.map((draft) => ({
            id: draft.id,
            project_id: draft.project_id,
            name: draft.name,
            run_name: draft.run_name,
            dataset_version_id: draft.dataset_version_id,
            task: draft.task,
            provider_id: draft.provider_id,
            architecture: draft.architecture,
            initial_checkpoint_source: draft.initial_checkpoint_source,
            validation_status: draft.validation_state?.status ?? null,
            warning_count: draft.validation_state?.warnings?.length ?? 0,
            blocker_count: draft.validation_state?.blockers?.length ?? 0,
            created_at: draft.created_at,
            updated_at: draft.updated_at,
          })),
        );
      }
      if (url.includes(`/projects/${project.id}/training-drafts`)) {
        return jsonResponse(savedTrainingDrafts);
      }
      if (url.endsWith(`/training-drafts/${trainingDrafts[0].id}`)) {
        return jsonResponse(trainingDrafts[0]);
      }
      if (url.includes(`/projects/${project.id}/training-runs`)) {
        return jsonResponse(savedTrainingRuns);
      }
      if (url.includes(`/projects/${project.id}/experiments`)) {
        return jsonResponse(savedExperiments);
      }
      if (url.includes("/models/provider-preflight")) {
        return jsonResponse(providerPreflight);
      }
      if (url.includes("/model-providers")) {
        return jsonResponse(providerCatalog);
      }
      if (url.includes("/runtime-providers/status")) {
        return jsonResponse(runtimeStatuses);
      }
      if (url.includes("/models/ultralytics/training-registry/summary")) {
        return jsonResponse(modelHubBootstrap.training_compatibility);
      }
      if (url.endsWith("/models/ultralytics/training-registry")) {
        return jsonResponse(trainingRegistry);
      }
      if (url.includes(`/projects/${project.id}/models`)) {
        return jsonResponse(models);
      }
      if (url.includes(`/projects/${project.id}/exports`)) {
        return jsonResponse(exports);
      }
      if (url.includes(`/projects/${project.id}/quality-control-runs`)) {
        return jsonResponse(qcRuns);
      }
      if (url.includes(`/projects/${project.id}/review-queues`)) {
        return jsonResponse(reviewQueues);
      }
      if (url.endsWith(`/projects/${project.id}/class-visibility`)) {
        return jsonResponse(defaultClassVisibilityBundle);
      }
      if (url.endsWith(`/images/${image.id}/annotations`)) {
        return jsonResponse(session);
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

beforeEach(() => {
  window.localStorage.setItem("reefvision.onboarding.dismissed.1.0.2", "true");
});

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("shows API status and an empty project dashboard", async () => {
    mockApi({ projects: [] });
    renderApp();

    expect(
      screen.getByRole("heading", { name: "ReefVision" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Local service 1.0.1")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "No projects yet" }),
    ).toBeInTheDocument();
  });

  it("opens the shared keyboard shortcut reference and restores focus", async () => {
    mockApi({ projects: [] });
    renderApp();
    const trigger = await screen.findByRole("button", {
      name: "Keyboard shortcuts",
    });

    await userEvent.click(trigger);
    expect(
      screen.getByRole("dialog", { name: "Keyboard shortcuts" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Full-image SAM proposals")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Keyboard shortcuts" }),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("opens system status and displays the current release line", async () => {
    mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      within(await screen.findByLabelText("Local system summary")).getByRole(
        "button",
        {
          name: /System status/,
        },
      ),
    );

    expect(await screen.findAllByText("1.0.1")).not.toHaveLength(0);
    expect(screen.getByText("1.0")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getAllByText("0009")).toHaveLength(2);
    expect(screen.getByText("Backups and restore")).toBeInTheDocument();
    expect(screen.getByText("Create diagnostics bundle")).toBeInTheDocument();
    expect(
      screen.getByText("Install or Repair Command-Line Shortcuts"),
    ).toBeInTheDocument();
    expect(screen.getByText("repair_required")).toBeInTheDocument();
  });

  it("repairs command shortcuts from system status", async () => {
    mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      within(await screen.findByLabelText("Local system summary")).getByRole(
        "button",
        {
          name: /System status/,
        },
      ),
    );

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Install or Repair Command-Line Shortcuts",
      }),
    );

    expect(await screen.findByText("Verification: ready")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Installed start-reefvision and update-reefvision into the ReefVision command directory.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the onboarding modal on first run and lets the user dismiss it", async () => {
    window.localStorage.clear();
    mockApi({ projects: [] });
    renderApp();

    expect(
      await screen.findByRole("heading", {
        name: /Welcome to ReefVision 1.0.2/,
      }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Don't show on startup" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /Welcome to ReefVision 1.0.2/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it("requires an explicit submit after first-run project creation navigation", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Create a project" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Create project" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Welcome to ReefVision/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Project name")).toHaveFocus();

    const projectWrites = () =>
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      );
    expect(projectWrites()).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByRole("dialog", { name: "Create project" }),
    ).not.toBeInTheDocument();
    expect(projectWrites()).toHaveLength(0);
  });

  it("waits for delayed project summaries before focusing the saved project", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [project] });
    const originalFetch = fetchMock.getMockImplementation();
    let resolveProjects: (response: Response) => void = () => {
      throw new Error("Project request was not started");
    };
    const delayedProjects = new Promise<Response>((resolve) => {
      resolveProjects = resolve;
    });
    fetchMock.mockImplementation((input, init) => {
      if (
        String(input).endsWith("/projects") &&
        (!init?.method || init.method === "GET")
      ) {
        return delayedProjects;
      }
      return originalFetch!(input, init);
    });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose an existing project" }),
    );
    expect(
      screen.queryByRole("button", { name: "Open CPT Coral Study" }),
    ).not.toBeInTheDocument();

    resolveProjects(jsonResponse([project]));
    const openProject = await screen.findByRole("button", {
      name: "Open CPT Coral Study",
    });
    await waitFor(() => expect(openProject).toHaveFocus());
    expect(
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("does not steal focus after the researcher navigates while projects load", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [project] });
    const originalFetch = fetchMock.getMockImplementation();
    let resolveProjects: (response: Response) => void = () => {
      throw new Error("Project request was not started");
    };
    const delayedProjects = new Promise<Response>((resolve) => {
      resolveProjects = resolve;
    });
    fetchMock.mockImplementation((input, init) => {
      if (
        String(input).endsWith("/projects") &&
        (!init?.method || init.method === "GET")
      ) {
        return delayedProjects;
      }
      return originalFetch!(input, init);
    });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose an existing project" }),
    );
    const newProject = screen.getByRole("button", { name: "New project" });
    newProject.focus();
    expect(newProject).toHaveFocus();

    resolveProjects(jsonResponse([project]));
    expect(
      await screen.findByRole("button", { name: "Open CPT Coral Study" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(newProject).toHaveFocus());
    expect(
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("offers existing projects from first-run help without creating or selecting data", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [project] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose an existing project" }),
    );

    expect(
      screen.queryByRole("heading", { name: /Welcome to ReefVision/ }),
    ).not.toBeInTheDocument();
    const openProject = await screen.findByRole("button", {
      name: "Open CPT Coral Study",
    });
    expect(openProject).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(openProject));
    expect(
      screen.queryByRole("dialog", { name: "Create project" }),
    ).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("hands focus to New project when onboarding has no saved projects", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose an existing project" }),
    );
    const newProject = screen.getByRole("button", { name: "New project" });
    await waitFor(() => expect(document.activeElement).toBe(newProject));
    expect(
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("creates a project from onboarding only after an explicit form submission", async () => {
    window.localStorage.clear();
    const fetchMock = mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "Create a project" }),
    );
    const projectWrites = () =>
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/projects") && options?.method === "POST",
      );
    expect(projectWrites()).toHaveLength(0);

    await userEvent.type(
      screen.getByLabelText("Project name"),
      "New coral survey",
    );
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Create project" })).getByRole(
        "button",
        { name: "Create project" },
      ),
    );

    await waitFor(() => expect(projectWrites()).toHaveLength(1));
    expect(projectWrites()[0][1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "New coral survey",
          description: "",
          template: "blank",
        }),
      }),
    );
  });

  it("opens a project and displays its stable classes", async () => {
    mockApi({ projects: [project] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: "Classes" }));

    expect(
      screen.getByRole("heading", { name: "CPT Coral Study" }),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Muricea Closed")).toBeInTheDocument();
    expect(screen.getByText("Muricea pendula | Closed")).toBeInTheDocument();
  });

  it("opens the managed image gallery for a project", async () => {
    mockApi({ projects: [project] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "Project gallery" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No images yet")).toBeInTheDocument();
    expect(screen.getByText("Import files")).toBeInTheDocument();
    expect(screen.getByText("Import folder")).toBeInTheDocument();
  });

  it("opens the dataset versions workspace for a project", async () => {
    mockApi({ projects: [project], datasetVersions: [], exports: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(
      screen.getByRole("tab", { name: "Dataset versions" }),
    );

    expect(
      screen.getByRole("tab", { name: "Dataset versions" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByText("No dataset versions yet"),
    ).toBeInTheDocument();
  });

  it("opens the project interoperability workspace", async () => {
    mockApi({ projects: [project] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(
      screen.getByRole("tab", { name: "Interoperability" }),
    );

    expect(
      screen.getByRole("tab", { name: "Interoperability" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByRole("heading", { name: "Project interoperability" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Create exchange package")).toBeInTheDocument();
    expect(
      screen.getByText("Inspect or import exchange package"),
    ).toBeInTheDocument();
  });

  it("opens the Training workspace for a project", async () => {
    mockApi({
      projects: [project],
      datasetVersions: [
        {
          id: "version-1",
          project_id: project.id,
          version_number: 1,
          name: "Training dataset",
          notes: null,
          parent_version_id: null,
          status: "complete",
          requested_split_method: "group_random",
          resolved_split_method: "group_random",
          eligible_annotation_statuses_json: ["reviewed"],
          requested_ratios_json: { train: 0.7, validation: 0.2, test: 0.1 },
          achieved_ratios_json: { train: 0.67, validation: 0.33, test: 0 },
          split_seed: 11,
          reuse_parent_assignments: false,
          missing_group_key_count: 0,
          warnings_json: [],
          class_map_json: [],
          manifest_sha256: "f".repeat(64),
          image_count: 3,
          annotation_count: 6,
          created_by: "local_user",
          reefvision_version: "1.0.1",
          schema_version: "0006",
          error_message: null,
          created_at: "2026-07-09T00:00:00Z",
          completed_at: "2026-07-09T00:00:00Z",
        },
      ],
      models: [],
    });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: /Models & AI/ }));
    await userEvent.click(screen.getByRole("tab", { name: "Training" }));

    expect(screen.getByRole("tab", { name: "Training" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByText("Pinned-provider workflow"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Active draft")).toHaveValue("draft-1");
    expect(await screen.findByText("Start training")).toBeInTheDocument();
  });

  it("allows retrying training when the saved preflight is blocked", async () => {
    const blockedDrafts: typeof trainingDrafts = trainingDrafts.map(
      (draft) => ({
        ...draft,
        validation_state: {
          ...draft.validation_state,
          status: "blocked",
        },
      }),
    );

    mockApi({
      projects: [project],
      models: [],
      savedTrainingDrafts: blockedDrafts,
    });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: "Models & AI" }));
    await userEvent.click(screen.getByRole("tab", { name: "Training" }));

    const startButton = await screen.findByRole("button", {
      name: "Start training",
    });

    expect(startButton).toBeEnabled();
  });

  it("opens the models workspace and shows Ultralytics training compatibility", async () => {
    mockApi({ projects: [project], models: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: /Models & AI/ }));
    await userEvent.click(screen.getByRole("tab", { name: "Model Hub" }));

    expect(
      await screen.findByRole("heading", {
        name: "Pinned Ultralytics registry",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Ultralytics 8.3.228")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Training uses local architecture configurations or explicitly registered checkpoints/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Register Existing Model" })[0],
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Model provider catalog" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Grounding DINO" }),
    ).toBeInTheDocument();
  });

  it("opens the quality-control dashboard for a project", async () => {
    mockApi({ projects: [project], datasetVersions: [], qcRuns: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: /Review/ }));
    await userEvent.click(screen.getByRole("tab", { name: "Quality control" }));

    expect(
      await screen.findByRole("heading", { name: "Quality Control" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Start checks")).toBeInTheDocument();
  });

  it("opens the review-queue dashboard for a project", async () => {
    mockApi({ projects: [project], datasetVersions: [], reviewQueues: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(screen.getByRole("tab", { name: /Review/ }));
    await userEvent.click(screen.getByRole("tab", { name: "Review queue" }));

    expect(
      await screen.findByRole("heading", { name: "Review Queue" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Generate ranking")).toBeInTheDocument();
  });

  it("creates a project with the blank class baseline", async () => {
    const fetchMock = mockApi({ projects: [] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: "New project" }),
    );
    await userEvent.type(
      screen.getByLabelText("Project name"),
      "CPT Coral Study",
    );
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Octocoral polyp annotations" },
    });
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Create project" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/projects$/),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            name: "CPT Coral Study",
            description: "Octocoral polyp annotations",
            template: "blank",
          }),
        }),
      ),
    );
  });

  it("opens the annotation editor from the gallery", async () => {
    mockApi({ projects: [project], images: [image] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Annotate" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("annotation-save-state")).toHaveTextContent(
        "Ready",
      ),
    );
    expect(screen.getByText("Manual annotation editor")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to gallery" }),
    ).toBeInTheDocument();
  });

  it("supports arrow-key navigation between workspace groups", async () => {
    mockApi({ projects: [project] });
    renderApp();

    await userEvent.click(
      await screen.findByRole("button", { name: /CPT Coral Study/ }),
    );
    const dataGroup = screen.getByRole("tab", { name: "Data & annotation" });
    dataGroup.focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Models & AI" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Model Hub" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });

  it("does not expose historical product names in the application shell", async () => {
    mockApi({ projects: [] });
    renderApp();

    await screen.findByRole("heading", { name: "ReefVision" });
    expect(
      screen.queryByText(/CoralVision|CoralAnnotator/i),
    ).not.toBeInTheDocument();
  });
});
