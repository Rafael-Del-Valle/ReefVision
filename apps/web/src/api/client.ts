import { getApiBaseUrl } from "../runtime";
import * as core from "./client-core";

export * from "./client-core";

type JsonRecord = Record<string, unknown>;

async function compatibilityRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers,
    });
  } catch {
    throw new core.ApiRequestError(
      "ReefVision could not reach the local API. Confirm the API is running and retry.",
    );
  }
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    let details: JsonRecord | null = null;
    try {
      const payload = (await response.json()) as {
        detail?: string | JsonRecord;
      };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object") {
        details = payload.detail;
        if (typeof payload.detail.reason === "string") {
          message = payload.detail.reason;
        }
      }
    } catch {
      // Preserve the HTTP fallback when an error response has no JSON body.
    }
    throw new core.ApiRequestError(message, details);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function querySuffix(
  values: Record<string, string | number | boolean | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  return search.size ? `?${search}` : "";
}

export interface ModelCatalogExpectedFile {
  filename: string;
  source_url: string;
  revision: string;
  sha256: string;
  size_bytes: number;
}

export interface ModelCatalogEntry {
  catalog_id: string;
  display_name: string;
  display_summary: string;
  category:
    "pretrained_catalog" | "my_trained_models" | "imported_custom_models";
  provider_id: string;
  provider: string;
  provider_version: string;
  architecture: string;
  architecture_family: string;
  variant: string;
  model_variant: string;
  model_size: string | null;
  task: core.ModelCatalogTask;
  trainable: boolean;
  inference_supported: boolean;
  inference: boolean;
  video_compatibility: boolean;
  prompt_assist_compatibility: boolean;
  tiling_compatibility: boolean;
  tuning_compatibility: boolean;
  checkpoint_identifier: string | null;
  checkpoint_source: string;
  download_source_type: string;
  expected_files: ModelCatalogExpectedFile[];
  expected_size: number | null;
  expected_file_size: number | null;
  expected_checksum: string | null;
  license_summary: string;
  model_weight_license: string;
  package_license: string;
  provider_pack_id: string | null;
  required_provider_pack: string | null;
  required_package_versions: string[];
  recommended_ram: number | null;
  recommended_vram: number | null;
  minimum_recommended_ram_gb: number | null;
  minimum_recommended_vram_gb: number | null;
  supported_devices: string[];
  supported_runtimes: string[];
  supported_runtime: string[];
  supported_precision: string[];
  expected_input_size?: {
    width: number;
    height: number;
  } | null;
  desktop_support: string;
  desktop_package_status: string;
  clean_machine_verification_status: string;
  availability: "available" | "experimental" | "unavailable";
  deprecation_status: "active" | "deprecated" | "experimental";
  replacement_model_id: string | null;
  known_limitations: string[];
  installation_state: core.ModelCatalogInstallationState;
  installation_reason: string | null;
  installation_job_id: string | null;
  installed_asset_id: string | null;
  installed_path: string | null;
  installed_checksum: string | null;
  advanced_only: boolean;
  requires_confirmation: boolean;
  selection_kind: core.ModelCatalogSelectionKind;
  architecture_reference: string | null;
  resolved_model_id: string | null;
  compatibility_reasons: string[];
  local_path?: string | null;
  managed_path?: string | null;
  catalog_revision?: string;
  checksum?: string | null;
  size_bytes?: number | null;
  source_type?: string;
  scratch_only?: boolean;
  pretrained?: boolean;
  registration_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ModelCatalogResponse {
  schema_version: number;
  catalog_version: string;
  application_version: string | null;
  models: ModelCatalogEntry[];
  validation_warnings: string[];
  rejected_entries: number;
  source_path: string | null;
  last_refresh_timestamp: string | null;
  entries?: ModelCatalogEntry[];
  pagination?: {
    page: number;
    page_size: number;
    total: number;
    pages: number;
  };
  filters?: core.ModelCatalogFilters;
}

function normalizeModelCatalogEntry(
  entry: Partial<ModelCatalogEntry>,
): ModelCatalogEntry {
  return {
    catalog_id: entry.catalog_id ?? "",
    display_name: entry.display_name ?? "",
    display_summary: entry.display_summary ?? "",
    category: entry.category ?? "pretrained_catalog",
    provider_id: entry.provider_id ?? entry.provider ?? "",
    provider: entry.provider ?? entry.provider_id ?? "",
    provider_version: entry.provider_version ?? "unknown",
    architecture: entry.architecture ?? "",
    architecture_family: entry.architecture_family ?? entry.architecture ?? "",
    variant: entry.variant ?? entry.model_variant ?? "",
    model_variant: entry.model_variant ?? entry.variant ?? "",
    model_size: entry.model_size ?? null,
    task: entry.task ?? "detect",
    trainable: entry.trainable ?? false,
    inference_supported: entry.inference_supported ?? entry.inference ?? false,
    inference: entry.inference ?? entry.inference_supported ?? false,
    video_compatibility: entry.video_compatibility ?? false,
    prompt_assist_compatibility: entry.prompt_assist_compatibility ?? false,
    tiling_compatibility: entry.tiling_compatibility ?? false,
    tuning_compatibility: entry.tuning_compatibility ?? false,
    checkpoint_identifier: entry.checkpoint_identifier ?? null,
    checkpoint_source:
      entry.checkpoint_source ?? entry.source_type ?? "unknown",
    download_source_type: entry.download_source_type ?? "unknown",
    expected_files: entry.expected_files ?? [],
    expected_size: entry.expected_size ?? entry.expected_file_size ?? null,
    expected_file_size: entry.expected_file_size ?? entry.expected_size ?? null,
    expected_checksum: entry.expected_checksum ?? entry.checksum ?? null,
    license_summary:
      entry.license_summary ?? entry.model_weight_license ?? "Unknown",
    model_weight_license:
      entry.model_weight_license ?? entry.license_summary ?? "Unknown",
    package_license: entry.package_license ?? "Unknown",
    provider_pack_id:
      entry.provider_pack_id ?? entry.required_provider_pack ?? null,
    required_provider_pack:
      entry.required_provider_pack ?? entry.provider_pack_id ?? null,
    required_package_versions: entry.required_package_versions ?? [],
    recommended_ram:
      entry.recommended_ram ?? entry.minimum_recommended_ram_gb ?? null,
    recommended_vram:
      entry.recommended_vram ?? entry.minimum_recommended_vram_gb ?? null,
    minimum_recommended_ram_gb:
      entry.minimum_recommended_ram_gb ?? entry.recommended_ram ?? null,
    minimum_recommended_vram_gb:
      entry.minimum_recommended_vram_gb ?? entry.recommended_vram ?? null,
    supported_devices: entry.supported_devices ?? [],
    supported_runtimes:
      entry.supported_runtimes ?? entry.supported_runtime ?? [],
    supported_runtime:
      entry.supported_runtime ?? entry.supported_runtimes ?? [],
    supported_precision: entry.supported_precision ?? [],
    desktop_support:
      entry.desktop_support ?? entry.desktop_package_status ?? "unknown",
    desktop_package_status:
      entry.desktop_package_status ?? entry.desktop_support ?? "unknown",
    clean_machine_verification_status:
      entry.clean_machine_verification_status ?? "unknown",
    availability: entry.availability ?? "unavailable",
    deprecation_status: entry.deprecation_status ?? "active",
    replacement_model_id: entry.replacement_model_id ?? null,
    known_limitations: entry.known_limitations ?? [],
    installation_state: entry.installation_state ?? "Unavailable",
    installation_reason: entry.installation_reason ?? null,
    installation_job_id: entry.installation_job_id ?? null,
    installed_asset_id: entry.installed_asset_id ?? null,
    installed_path:
      entry.installed_path ?? entry.managed_path ?? entry.local_path ?? null,
    installed_checksum: entry.installed_checksum ?? entry.checksum ?? null,
    advanced_only: entry.advanced_only ?? false,
    requires_confirmation: entry.requires_confirmation ?? false,
    selection_kind: entry.selection_kind ?? "planned_unavailable",
    architecture_reference: entry.architecture_reference ?? null,
    resolved_model_id: entry.resolved_model_id ?? entry.registration_id ?? null,
    compatibility_reasons: entry.compatibility_reasons ?? [],
    local_path: entry.local_path ?? entry.installed_path ?? null,
    managed_path: entry.managed_path ?? entry.installed_path ?? null,
    catalog_revision: entry.catalog_revision ?? "unknown",
    checksum: entry.checksum ?? entry.installed_checksum ?? null,
    size_bytes:
      entry.size_bytes ??
      entry.expected_file_size ??
      entry.expected_size ??
      null,
    source_type: entry.source_type ?? entry.checkpoint_source ?? "unknown",
    scratch_only: entry.scratch_only ?? false,
    pretrained: entry.pretrained ?? true,
    registration_id: entry.registration_id ?? entry.resolved_model_id ?? null,
    created_at: entry.created_at ?? null,
    updated_at: entry.updated_at ?? null,
  };
}

function normalizeModelCatalog(
  payload: Partial<ModelCatalogResponse> & {
    models?: ModelCatalogEntry[];
    entries?: ModelCatalogEntry[];
  },
): ModelCatalogResponse {
  const models = (payload.models ?? payload.entries ?? []).map(
    normalizeModelCatalogEntry,
  );
  return {
    schema_version: payload.schema_version ?? 1,
    catalog_version: payload.catalog_version ?? "unknown",
    application_version: payload.application_version ?? null,
    models,
    validation_warnings: payload.validation_warnings ?? [],
    rejected_entries: payload.rejected_entries ?? 0,
    source_path: payload.source_path ?? null,
    last_refresh_timestamp: payload.last_refresh_timestamp ?? null,
    entries: models,
    pagination: payload.pagination ?? {
      page: 1,
      page_size: models.length,
      total: models.length,
      pages: models.length ? 1 : 0,
    },
    filters: payload.filters ?? { providers: [], architectures: [] },
  };
}

export interface ModelProviderPackage {
  distribution_name: string;
  required_version: string | null;
  installed_version: string | null;
  status: string;
}

export interface ModelProviderCapabilityMatrix {
  image_detection: boolean;
  image_instance_segmentation: boolean;
  image_semantic_segmentation: boolean;
  text_prompt_detection: boolean;
  image_example_detection: boolean;
  click_prompting: boolean;
  box_prompting: boolean;
  brush_prompting: boolean;
  mask_prompting: boolean;
  video_propagation: boolean;
  multi_object_tracking: boolean;
  training: boolean;
  validation: boolean;
  tiled_training: boolean;
  tiled_inference: boolean;
  export: boolean;
  cpu_inference: boolean;
  cuda_inference: boolean;
  fp16: boolean;
  quantized_inference: boolean;
  packaged_desktop_operation: boolean;
}

export interface ModelProvider {
  provider_id: string;
  display_name: string;
  provider_version: string;
  package_version: string | null;
  supported_model_families: string[];
  supported_tasks: string[];
  supported_input_types: string[];
  supported_output_types: string[];
  cpu_support: boolean;
  cuda_support: boolean;
  supported_precision_modes: string[];
  video_support: boolean;
  training_support: boolean;
  tiling_support: boolean;
  supported_execution_runtimes: string[];
  required_packages: ModelProviderPackage[];
  required_model_files: string[];
  code_license: string;
  weight_license: string;
  memory_recommendations: string[];
  known_limitations: string[];
  desktop_packaging_state: string;
  clean_machine_verification_state: string;
  availability_status: string;
  availability_reason: string | null;
  default_registration_purpose: string | null;
  registerable: boolean;
  capabilities: ModelProviderCapabilityMatrix;
}

export interface ProviderDependencyPackage {
  distribution_name: string;
  required_version: string;
  installed_version: string | null;
  status: string;
}

export interface ProviderDependencyStatus {
  provider_name: string;
  provider_id?: string;
  display_name: string;
  purpose: string;
  provider_version: string;
  status: string;
  ready: boolean;
  tested_python: string;
  current_python: string;
  tested_platform: string;
  current_platform: string;
  tested_cuda: string | null;
  current_cuda: string | null;
  automatic_downloads_disabled: boolean;
  explicit_checkpoint_required: boolean;
  requirements_file: string;
  packages: ProviderDependencyPackage[];
  issues: string[];
}

export interface ProviderDependencyPreflightResponse {
  providers: ProviderDependencyStatus[];
}

export interface RuntimeProviderStatus {
  runtime_id: string;
  provider_id?: string;
  display_name: string;
  package_name: string | null;
  package_version: string | null;
  available: boolean;
  status: string;
  installation_state?: core.ModelCatalogInstallationState;
  reason?: string | null;
  executable_path?: string | null;
  supports_cpu: boolean;
  supports_cuda: boolean;
  notes: string[];
  checked_at?: string;
}

export interface UltralyticsTrainingRegistrySummarySnapshot {
  provider_name: string;
  provider_version: string;
  ultralytics_version: string | null;
  pinned_version_matches_installed: boolean;
  supported_tasks: string[];
  supported_modes: string[];
  summary: {
    parameter_count: number;
    reefvision_supported_parameter_count: number;
    tunable_parameter_count: number;
    native_tune_parameter_count: number;
    fixed_only_parameter_count: number;
  };
}

export interface ModelHubBootstrapResponse {
  application_version: string;
  catalog: ModelCatalogResponse;
  models: core.ModelRegistration[];
  providers: ModelProvider[];
  provider_preflight: ProviderDependencyPreflightResponse | null;
  runtime_statuses: RuntimeProviderStatus[];
  training_compatibility: UltralyticsTrainingRegistrySummarySnapshot | null;
  provider_summary_states: Record<string, string>;
  validation_warnings: string[];
  last_refresh_timestamp: string;
  provider_catalog_checked_at: string | null;
  provider_preflight_checked_at: string | null;
  runtime_statuses_checked_at: string | null;
  training_compatibility_checked_at: string | null;
}

export interface TrainingProviderArchitecture {
  architecture_id: string;
  display_name: string;
  task: string;
  source: string;
}

export interface TrainingProvider {
  provider_id: string;
  display_name: string;
  provider_version: string;
  supported_tasks: string[];
  supported_precision_modes: string[];
  supports_tiling: boolean;
  supports_tuning: boolean;
  supports_packaged_desktop: boolean;
  warning: string | null;
  architectures: TrainingProviderArchitecture[];
}

export interface TrainingDraft {
  id: string;
  project_id: string;
  name: string;
  run_name: string | null;
  notes: string | null;
  dataset_version_id: string | null;
  dataset_manifest_sha256: string | null;
  split_manifest_sha256: string | null;
  task: string | null;
  catalog_model_id: string | null;
  provider_id: string | null;
  architecture: string | null;
  initial_checkpoint_source: string;
  initial_checkpoint_model_id: string | null;
  resolved_model_asset_id: string | null;
  resolved_model_checksum: string | null;
  parameter_registry_version: string | null;
  selected_preset: string | null;
  installation_state: string | null;
  device: string;
  precision: string;
  random_seed: number | null;
  tiling_config: JsonRecord;
  training_config: JsonRecord;
  tuning_config: JsonRecord;
  evaluation_config: JsonRecord;
  resource_limits: JsonRecord;
  validation_state: JsonRecord;
  configuration_json?: JsonRecord;
  created_at: string;
  updated_at: string;
}

export interface TrainingDraftSummary {
  id: string;
  project_id: string;
  name: string;
  run_name: string | null;
  dataset_version_id: string | null;
  task: string | null;
  catalog_model_id: string | null;
  provider_id: string | null;
  architecture: string | null;
  initial_checkpoint_source: string;
  validation_status: "ready" | "ready_with_warnings" | "blocked" | null;
  warning_count: number;
  blocker_count: number;
  created_at: string;
  updated_at: string;
}

export interface TrainingLeakageAudit {
  blocked: boolean;
  warnings: string[];
  blockers: string[];
  image_leak_count: number;
  group_leak_count: number;
}

export interface TrainingPreflight extends JsonRecord {
  status: "ready" | "ready_with_warnings" | "blocked";
  warnings: string[];
  blockers: string[];
  dataset: {
    dataset_version_id: string | null;
    dataset_manifest_sha256: string | null;
    split_manifest_sha256: string | null;
    image_count: number;
    annotation_count: number;
    mask_annotation_count: number;
    polygon_count: number;
    raster_mask_count: number;
    split_counts: Record<string, number>;
    polygon_counts_by_split: Record<string, number>;
    raster_counts_by_split: Record<string, number>;
    group_count: number;
    warnings: string[];
  };
  leakage_audit: TrainingLeakageAudit;
  resource_snapshot: JsonRecord;
  provider_dependency_status: JsonRecord;
}

export interface TrainingRunSummary {
  id: string;
  project_id: string;
  draft_id: string | null;
  dataset_version_id: string | null;
  dataset_manifest_sha256: string;
  split_manifest_sha256: string;
  task: string;
  catalog_model_id: string | null;
  provider_id: string;
  architecture: string;
  initial_checkpoint_source: string;
  initial_checkpoint_model_id: string | null;
  resolved_model_asset_id: string | null;
  resolved_model_checksum: string | null;
  parameter_registry_version: string | null;
  selected_preset: string | null;
  installation_state: string | null;
  device: string;
  precision: string;
  run_name: string;
  notes: string | null;
  random_seed: number | null;
  tiling_config: JsonRecord;
  training_config: JsonRecord;
  tuning_config: JsonRecord;
  tuning_config_json: JsonRecord;
  evaluation_config: JsonRecord;
  resource_limits: JsonRecord;
  preflight_report: JsonRecord;
  draft_snapshot: JsonRecord;
  status: string;
  stage: string;
  progress_epoch: number;
  progress_current_epoch: number;
  progress_total_epochs: number;
  metrics: JsonRecord;
  metrics_json: Record<string, number>;
  metrics_history: JsonRecord;
  warnings: string[];
  blockers?: string[];
  artifact_manifest: JsonRecord;
  artifact_manifest_json: JsonRecord;
  logs_path: string | null;
  result_checkpoint_path: string | null;
  job_id: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export type TrainingRunDetail = TrainingRunSummary;

function normalizeTrainingRun(
  run: Partial<TrainingRunSummary>,
): TrainingRunSummary {
  const tuning = run.tuning_config ?? run.tuning_config_json ?? {};
  const metrics = run.metrics ?? run.metrics_json ?? {};
  const artifactManifest =
    run.artifact_manifest ?? run.artifact_manifest_json ?? {};
  return {
    id: run.id ?? "",
    project_id: run.project_id ?? "",
    draft_id: run.draft_id ?? null,
    dataset_version_id: run.dataset_version_id ?? null,
    dataset_manifest_sha256: run.dataset_manifest_sha256 ?? "",
    split_manifest_sha256: run.split_manifest_sha256 ?? "",
    task: run.task ?? "detect",
    catalog_model_id: run.catalog_model_id ?? null,
    provider_id: run.provider_id ?? "",
    architecture: run.architecture ?? "",
    initial_checkpoint_source: run.initial_checkpoint_source ?? "scratch",
    initial_checkpoint_model_id: run.initial_checkpoint_model_id ?? null,
    resolved_model_asset_id: run.resolved_model_asset_id ?? null,
    resolved_model_checksum: run.resolved_model_checksum ?? null,
    parameter_registry_version: run.parameter_registry_version ?? null,
    selected_preset: run.selected_preset ?? null,
    installation_state: run.installation_state ?? null,
    device: run.device ?? "auto",
    precision: run.precision ?? "fp32",
    run_name: run.run_name ?? "",
    notes: run.notes ?? null,
    random_seed: run.random_seed ?? null,
    tiling_config: run.tiling_config ?? {},
    training_config: run.training_config ?? {},
    tuning_config: tuning,
    tuning_config_json: tuning,
    evaluation_config: run.evaluation_config ?? {},
    resource_limits: run.resource_limits ?? {},
    preflight_report: run.preflight_report ?? {},
    draft_snapshot: run.draft_snapshot ?? {},
    status: run.status ?? "queued",
    stage: run.stage ?? "queued",
    progress_epoch: run.progress_epoch ?? run.progress_current_epoch ?? 0,
    progress_current_epoch:
      run.progress_current_epoch ?? run.progress_epoch ?? 0,
    progress_total_epochs: run.progress_total_epochs ?? 0,
    metrics,
    metrics_json: metrics as Record<string, number>,
    metrics_history: run.metrics_history ?? {},
    warnings: run.warnings ?? [],
    blockers: run.blockers ?? [],
    artifact_manifest: artifactManifest,
    artifact_manifest_json: artifactManifest,
    logs_path: run.logs_path ?? null,
    result_checkpoint_path: run.result_checkpoint_path ?? null,
    job_id: run.job_id ?? null,
    error_message: run.error_message ?? null,
    created_at: run.created_at ?? "",
    started_at: run.started_at ?? null,
    completed_at: run.completed_at ?? null,
    updated_at: run.updated_at ?? run.created_at ?? "",
  };
}

export interface TrainingWorkspaceBootstrapResponse {
  draft_summaries: TrainingDraftSummary[];
  selected_draft: TrainingDraft | null;
  providers: TrainingProvider[];
  catalog: ModelCatalogResponse;
}

export interface TrainingTilingEstimate {
  blocked: boolean;
  warnings: string[];
  tile_count: number;
  positive_tile_count: number;
  background_tile_count: number;
  estimated_storage_bytes: number;
  preview_tiles: Array<{
    image_id: string;
    split: string;
    x: number;
    y: number;
    width: number;
    height: number;
    retained_annotation_count: number;
  }>;
}

export interface TrainingDraftWritePayload {
  name: string;
  run_name?: string | null;
  notes?: string | null;
  dataset_version_id?: string | null;
  task?: string | null;
  catalog_model_id?: string | null;
  provider_id?: string | null;
  architecture?: string | null;
  initial_checkpoint_source?: string;
  initial_checkpoint_model_id?: string | null;
  device?: string;
  precision?: string;
  random_seed?: number | null;
  tiling_config?: JsonRecord;
  training_config?: JsonRecord;
  tuning_config?: JsonRecord;
  evaluation_config?: JsonRecord;
  resource_limits?: JsonRecord;
  validation_state?: JsonRecord;
}

export interface ExperimentComparison {
  experiments: core.ExperimentRecord[];
  warnings: string[];
}

export type DatasetSplit = "train" | "validation" | "test" | "unassigned";
export type DatasetSplitMethod = "group_random" | "random" | "manual" | "none";

export interface DatasetVersionCreatePayload {
  name: string;
  notes?: string;
  parent_version_id?: string;
  eligible_annotation_statuses: core.AnnotationStatus[];
  split_method: DatasetSplitMethod;
  requested_ratios?: {
    train: number;
    validation: number;
    test: number;
  };
  split_seed?: number;
  reuse_parent_assignments: boolean;
  manual_assignments?: Array<{
    image_id: string;
    split: DatasetSplit;
  }>;
}

export interface PredictionProposal {
  id: string;
  project_id: string;
  image_id: string;
  model_id: string;
  model_display_name: string;
  inference_job_id: string;
  model_checksum: string;
  label_class_id: string | null;
  predicted_label: string;
  predicted_index: number | null;
  confidence: number;
  geometry_kind: string;
  polygon_json: number[][] | null;
  mask_path: string | null;
  mask_content_sha256: string | null;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  review_status: string;
  was_edited: boolean;
  reviewer_action_at: string | null;
  accepted_annotation_id: string | null;
  accepted_mask_annotation_id: string | null;
  inference_settings_json: JsonRecord;
  provenance_json: JsonRecord | null;
  created_at: string;
}

export interface PredictionListResponse {
  items: PredictionProposal[];
  counts: Record<string, number>;
  proposals?: PredictionProposal[];
  total?: number;
}

export interface PredictionMaskAnnotation {
  id: string;
  image_id: string;
  label_class_id: string | null;
  geometry_kind: "polygon" | "raster_mask";
  mask_path: string | null;
  polygon_json: number[][] | null;
  x_min: number | null;
  y_min: number | null;
  x_max: number | null;
  y_max: number | null;
  area_pixels: number | null;
  source_type: string;
  provenance_json: JsonRecord | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
}

export interface PredictionReviewResponse {
  proposal: PredictionProposal;
  annotation: core.AnnotationRecord | null;
  mask_annotation: PredictionMaskAnnotation | null;
}

export interface PredictionBulkReviewResponse {
  reviewed_count: number;
  created_annotations: core.AnnotationRecord[];
  created_mask_annotations: PredictionMaskAnnotation[];
}

export interface AssistSession {
  session_id: string;
  project_id: string;
  image_id: string;
  model_id: string;
  model_display_name: string;
  provider_name: string;
  provider_version: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  add_stroke_count: number;
  subtract_stroke_count: number;
  positive_point_count: number;
  negative_point_count: number;
  brush_radius: number | null;
  source_prediction_id: string | null;
  prompt_type: string | null;
  candidate_box: {
    x_min: number;
    y_min: number;
    x_max: number;
    y_max: number;
  } | null;
  candidate_mask_png_base64: string | null;
}

export interface ImportItem extends core.ImportItem {
  filename: string;
}

export interface ImageImportReport {
  project_id: string;
  successful: ImportItem[];
  duplicates: ImportItem[];
  unsupported: ImportItem[];
  failed: ImportItem[];
}

function normalizeImportReport(
  report: core.ImageImportReport,
): ImageImportReport {
  const map = (items: core.ImportItem[]): ImportItem[] =>
    items.map((item) => ({
      ...item,
      filename: item.source,
    }));
  return {
    project_id: report.project_id,
    successful: map(report.successful),
    duplicates: map(report.duplicates),
    unsupported: map(report.unsupported),
    failed: map(report.failed),
  };
}

export async function getProjectModelCatalog(
  projectId: string,
  options: {
    workflow?: core.ModelCatalogWorkflow;
    task?: core.ModelCatalogTask;
    includeUnavailable?: boolean;
  } = {},
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  const payload = await compatibilityRequest<ModelCatalogResponse>(
    `/projects/${projectId}/model-catalog${querySuffix({
      workflow: options.workflow,
      task: options.task,
      include_unavailable: options.includeUnavailable,
    })}`,
    { signal },
  );
  return normalizeModelCatalog(payload);
}

export async function getModelHubBootstrap(
  projectId: string,
  signal?: AbortSignal,
): Promise<ModelHubBootstrapResponse> {
  const payload = await compatibilityRequest<ModelHubBootstrapResponse>(
    `/projects/${projectId}/model-hub/bootstrap`,
    { signal },
  );
  return {
    ...payload,
    catalog: normalizeModelCatalog(payload.catalog),
  };
}

export async function getModelProviderPreflight(
  options: { refresh?: boolean; signal?: AbortSignal } = {},
): Promise<ProviderDependencyPreflightResponse> {
  return compatibilityRequest<ProviderDependencyPreflightResponse>(
    `/models/provider-preflight${querySuffix({ refresh: options.refresh })}`,
    { signal: options.signal },
  );
}

export async function getRuntimeProviderStatuses(
  options: { refresh?: boolean; signal?: AbortSignal } = {},
): Promise<RuntimeProviderStatus[]> {
  return compatibilityRequest<RuntimeProviderStatus[]>(
    `/runtime-providers/status${querySuffix({ refresh: options.refresh })}`,
    { signal: options.signal },
  );
}

export async function getUltralyticsTrainingRegistrySummary(
  options: { refresh?: boolean; signal?: AbortSignal } = {},
): Promise<UltralyticsTrainingRegistrySummarySnapshot> {
  return compatibilityRequest<UltralyticsTrainingRegistrySummarySnapshot>(
    `/models/ultralytics/training-registry/summary${querySuffix({
      refresh: options.refresh,
    })}`,
    { signal: options.signal },
  );
}

export async function installCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<core.JobRecord> {
  return compatibilityRequest<core.JobRecord>(
    `/projects/${projectId}/model-installs/${catalogId}`,
    {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    },
  );
}

export async function verifyCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<{
  catalog_id: string;
  installation_state: core.ModelCatalogInstallationState;
  verified: boolean;
  expected_checksum: string | null;
  actual_checksum: string | null;
  path: string | null;
  reason: string | null;
}> {
  return compatibilityRequest(
    `/projects/${projectId}/model-verifications/${catalogId}`,
    { method: "POST" },
  );
}

export async function removeCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<void> {
  await compatibilityRequest<void>(
    `/projects/${projectId}/model-installs/${catalogId}`,
    { method: "DELETE" },
  );
}

export async function getModels(
  projectId: string,
  purposeOrSignal?: string | AbortSignal,
  signal?: AbortSignal,
): Promise<core.ModelRegistration[]> {
  const purpose =
    typeof purposeOrSignal === "string" ? purposeOrSignal : undefined;
  const requestSignal =
    typeof purposeOrSignal === "string" ? signal : purposeOrSignal;
  return compatibilityRequest<core.ModelRegistration[]>(
    `/projects/${projectId}/models${querySuffix({ purpose })}`,
    { signal: requestSignal },
  );
}

export async function registerModel(
  projectId: string,
  input:
    | FormData
    | {
        file: File;
        purpose: string;
        providerName?: string;
        displayName?: string;
        notes?: string;
      },
): Promise<core.ModelRegistration> {
  const formData =
    input instanceof FormData
      ? input
      : (() => {
          const data = new FormData();
          data.append("file", input.file);
          data.append("purpose", input.purpose);
          if (input.providerName)
            data.append("provider_name", input.providerName);
          if (input.displayName) data.append("display_name", input.displayName);
          if (input.notes) data.append("notes", input.notes);
          return data;
        })();
  return compatibilityRequest<core.ModelRegistration>(
    `/projects/${projectId}/models/register`,
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function createInferenceJob(
  projectOrImageId: string,
  payload:
    | {
        model_id: string;
        image_ids: string[];
        confidence_threshold: number;
        iou_threshold?: number;
        device: string;
      }
    | {
        model_id: string;
        confidence_threshold: number;
        device: string;
      },
): Promise<core.JobRecord> {
  if ("image_ids" in payload) {
    return compatibilityRequest<core.JobRecord>(
      `/projects/${projectOrImageId}/inference-jobs`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  }
  return core.createInferenceJob(projectOrImageId, payload);
}

export async function updateImage(
  imageId: string,
  payload: Partial<
    Pick<
      core.ProjectImage,
      "annotation_status" | "capture_timestamp" | "group_key"
    >
  >,
): Promise<core.ProjectImage> {
  return compatibilityRequest<core.ProjectImage>(`/images/${imageId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function importImages(
  projectId: string,
  files: File[],
): Promise<ImageImportReport> {
  return normalizeImportReport(await core.importImages(projectId, files));
}

export async function importImagesFromPaths(
  projectId: string,
  sources: core.ImageImportSource[],
): Promise<ImageImportReport> {
  return normalizeImportReport(
    await core.importImagesFromPaths(projectId, sources),
  );
}

export async function getClassVisibilityBundle(
  projectId: string,
  signal?: AbortSignal,
): Promise<core.ClassVisibilityBundle> {
  return compatibilityRequest<core.ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility`,
    { signal },
  );
}

export async function saveClassVisibilityPreference(
  projectId: string,
  layerType: core.ClassVisibilityLayerType,
  payload: core.ClassVisibilityUpdatePayload,
): Promise<core.ClassVisibilityScopeState> {
  return compatibilityRequest<core.ClassVisibilityScopeState>(
    `/projects/${projectId}/class-visibility/preferences/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteClassVisibilityPreference(
  projectId: string,
  layerType: core.ClassVisibilityLayerType,
): Promise<void> {
  await compatibilityRequest<void>(
    `/projects/${projectId}/class-visibility/preferences/${layerType}`,
    { method: "DELETE" },
  );
}

export async function saveProjectClassVisibilityDefault(
  projectId: string,
  layerType: core.ClassVisibilityLayerType,
  payload: core.ClassVisibilityUpdatePayload,
): Promise<core.ClassVisibilityScopeState> {
  return compatibilityRequest<core.ClassVisibilityScopeState>(
    `/projects/${projectId}/class-visibility/defaults/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteProjectClassVisibilityDefault(
  projectId: string,
  layerType: core.ClassVisibilityLayerType,
): Promise<void> {
  await compatibilityRequest<void>(
    `/projects/${projectId}/class-visibility/defaults/${layerType}`,
    { method: "DELETE" },
  );
}

export async function getProjectLabelClassUsage(
  projectId: string,
  classId: string,
  signal?: AbortSignal,
): Promise<core.LabelClassUsage> {
  return compatibilityRequest<core.LabelClassUsage>(
    `/projects/${projectId}/classes/${classId}/usage`,
    { signal },
  );
}

export async function mergeLabelClass(
  sourceClassId: string,
  target:
    | string
    | {
        target_class_id: string;
      },
): Promise<core.LabelClassMergeResponse> {
  return core.mergeLabelClass(
    sourceClassId,
    typeof target === "string" ? target : target.target_class_id,
  );
}

type ClassPreviewPayload = {
  target_class_id: string;
  notes?: string | null;
};

type ClassExecutePayload = {
  operation_id: string;
  preview_checksum: string;
  notes?: string | null;
};

export async function previewLabelClassReassign(
  projectId: string,
  classId: string,
  payload: ClassPreviewPayload,
): Promise<core.ClassOperationRecord> {
  return compatibilityRequest<core.ClassOperationRecord>(
    `/projects/${projectId}/classes/${classId}/reassign/preview`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function executeLabelClassReassign(
  projectId: string,
  classId: string,
  payload: ClassExecutePayload,
): Promise<core.ClassOperationRecord> {
  return compatibilityRequest<core.ClassOperationRecord>(
    `/projects/${projectId}/classes/${classId}/reassign`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function previewLabelClassReassignDelete(
  projectId: string,
  classId: string,
  payload: ClassPreviewPayload,
): Promise<core.ClassOperationRecord> {
  return compatibilityRequest<core.ClassOperationRecord>(
    `/projects/${projectId}/classes/${classId}/reassign-delete/preview`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function executeLabelClassReassignDelete(
  projectId: string,
  classId: string,
  payload: ClassExecutePayload,
): Promise<core.ClassOperationRecord> {
  return compatibilityRequest<core.ClassOperationRecord>(
    `/projects/${projectId}/classes/${classId}/reassign-delete`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function previewDatasetVersion(
  projectId: string,
  payload: DatasetVersionCreatePayload,
): Promise<core.DatasetVersionPreview> {
  return compatibilityRequest<core.DatasetVersionPreview>(
    `/projects/${projectId}/dataset-version-previews`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function createDatasetVersion(
  projectId: string,
  payload: DatasetVersionCreatePayload,
): Promise<core.DatasetVersionRecord> {
  return compatibilityRequest<core.DatasetVersionRecord>(
    `/projects/${projectId}/dataset-versions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export const getDatasetVersionComparison = core.compareDatasetVersions;

export async function createDatasetExport(
  versionId: string,
  format: core.DatasetExportFormat = "yolo_detection",
): Promise<core.DatasetExportCreateResponse> {
  return compatibilityRequest<core.DatasetExportCreateResponse>(
    `/dataset-versions/${versionId}/exports`,
    {
      method: "POST",
      body: JSON.stringify({ format }),
    },
  );
}

export const datasetExportDownloadUrl = core.exportDownloadUrl;
export const datasetExportManifestUrl = core.exportManifestUrl;

export async function createQualityControlRun(
  projectId: string,
  payload: {
    rule_categories: core.QualityControlRuleCategory[];
    thresholds: core.QualityControlThresholdConfig;
    selected_rule_ids?: string[];
    created_by?: string;
  },
): Promise<core.QualityControlRunRecord> {
  return compatibilityRequest<core.QualityControlRunRecord>(
    `/projects/${projectId}/quality-control-runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function createDatasetVersionQualityControlRun(
  versionId: string,
  payload: {
    rule_categories: core.QualityControlRuleCategory[];
    thresholds: core.QualityControlThresholdConfig;
    selected_rule_ids?: string[];
    created_by?: string;
  },
): Promise<core.QualityControlRunRecord> {
  return compatibilityRequest<core.QualityControlRunRecord>(
    `/dataset-versions/${versionId}/quality-control-runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getPredictions(
  imageId: string,
  filters: {
    modelId?: string;
    labelClassId?: string;
    minConfidence?: number;
    reviewStatus?: string;
  },
  signal?: AbortSignal,
): Promise<PredictionListResponse> {
  return compatibilityRequest<PredictionListResponse>(
    `/images/${imageId}/prediction-proposals${querySuffix({
      model_id: filters.modelId,
      label_class_id: filters.labelClassId,
      min_confidence: filters.minConfidence,
      review_status: filters.reviewStatus,
    })}`,
    { signal },
  );
}

export async function acceptPrediction(
  proposalId: string,
  payload: {
    label_class_id?: string | null;
    x_min?: number;
    y_min?: number;
    x_max?: number;
    y_max?: number;
    polygon_json?: number[][];
  },
): Promise<PredictionReviewResponse> {
  return compatibilityRequest<PredictionReviewResponse>(
    `/prediction-proposals/${proposalId}/accept`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function rejectPrediction(
  proposalId: string,
): Promise<PredictionReviewResponse> {
  return compatibilityRequest<PredictionReviewResponse>(
    `/prediction-proposals/${proposalId}/reject`,
    { method: "POST" },
  );
}

export async function bulkReviewPredictions(payload: {
  action: "accept" | "reject";
  proposal_ids: string[];
}): Promise<PredictionBulkReviewResponse> {
  return compatibilityRequest<PredictionBulkReviewResponse>(
    "/prediction-proposals/bulk-review",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function predictionMaskContentUrl(proposalId: string): string {
  return `${getApiBaseUrl()}/prediction-proposals/${encodeURIComponent(proposalId)}/mask`;
}

export async function createAssistSession(
  imageId: string,
  payload: {
    model_id: string;
    device: string;
    source_prediction_id?: string;
  },
): Promise<AssistSession> {
  return compatibilityRequest<AssistSession>(
    `/images/${imageId}/assist-sessions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function brushAssistSession(
  sessionId: string,
  payload: {
    mode: "add" | "subtract";
    brush_radius: number;
    strokes: Array<{ points: Array<{ x: number; y: number }> }>;
  },
): Promise<AssistSession> {
  return compatibilityRequest<AssistSession>(
    `/assist-sessions/${sessionId}/brush`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function boxAssistSession(
  sessionId: string,
  payload: { x_min: number; y_min: number; x_max: number; y_max: number },
): Promise<AssistSession> {
  return compatibilityRequest<AssistSession>(
    `/assist-sessions/${sessionId}/box`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function resetAssistSession(
  sessionId: string,
): Promise<AssistSession> {
  return compatibilityRequest<AssistSession>(
    `/assist-sessions/${sessionId}/reset`,
    { method: "POST" },
  );
}

export async function getTrainingWorkspaceBootstrap(
  projectId: string,
  selectedDraftOrSignal?: string | AbortSignal,
  signal?: AbortSignal,
): Promise<TrainingWorkspaceBootstrapResponse> {
  const requestSignal =
    typeof selectedDraftOrSignal === "string" ? signal : selectedDraftOrSignal;
  const payload =
    await compatibilityRequest<TrainingWorkspaceBootstrapResponse>(
      `/projects/${projectId}/training/bootstrap`,
      { signal: requestSignal },
    );
  return {
    ...payload,
    catalog: normalizeModelCatalog(payload.catalog),
  };
}

export interface TrainingProviderParameter {
  name: string;
  display_name: string;
  value_type: string;
  default_value: unknown;
  supported_tasks: string[];
  supported_modes: string[];
  reefvision_supported: boolean;
}

export interface TrainingProviderParametersResponse extends JsonRecord {
  parameters: TrainingProviderParameter[];
}

export async function getTrainingProviderParameters(
  providerId: string,
  signal?: AbortSignal,
): Promise<TrainingProviderParametersResponse> {
  return compatibilityRequest<TrainingProviderParametersResponse>(
    `/training/providers/${providerId}/parameters`,
    { signal },
  );
}

export async function getTrainingDrafts(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingDraft[]> {
  return compatibilityRequest<TrainingDraft[]>(
    `/projects/${projectId}/training-drafts`,
    { signal },
  );
}

export async function getTrainingDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<TrainingDraft> {
  return compatibilityRequest<TrainingDraft>(`/training-drafts/${draftId}`, {
    signal,
  });
}

export async function createTrainingDraft(
  projectId: string,
  payload: TrainingDraftWritePayload,
): Promise<TrainingDraft> {
  return compatibilityRequest<TrainingDraft>(
    `/projects/${projectId}/training-drafts`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function saveTrainingDraft(
  projectId: string,
  payload: TrainingDraftWritePayload,
): Promise<TrainingDraft> {
  return createTrainingDraft(projectId, payload);
}

export async function updateTrainingDraft(
  draftId: string,
  payload: Partial<TrainingDraftWritePayload>,
): Promise<TrainingDraft> {
  return compatibilityRequest<TrainingDraft>(`/training-drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function runTrainingPreflight(
  projectId: string,
  payload: TrainingDraftWritePayload | JsonRecord,
): Promise<TrainingPreflight> {
  return compatibilityRequest<TrainingPreflight>(
    `/projects/${projectId}/training-preflight`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function estimateTrainingTiling(
  projectId: string,
  payload: {
    dataset_version_id: string;
    tiling_config: JsonRecord;
  },
): Promise<TrainingTilingEstimate> {
  return compatibilityRequest<TrainingTilingEstimate>(
    `/projects/${projectId}/training-tiling/estimate`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function createTrainingRun(
  projectId: string,
  payload: { draft_id: string },
): Promise<TrainingRunDetail> {
  const run = await compatibilityRequest<Partial<TrainingRunSummary>>(
    `/projects/${projectId}/training-runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  return normalizeTrainingRun(run);
}

export async function getTrainingRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingRunSummary[]> {
  const runs = await compatibilityRequest<Array<Partial<TrainingRunSummary>>>(
    `/projects/${projectId}/training-runs`,
    { signal },
  );
  return runs.map(normalizeTrainingRun);
}

export async function getTrainingRun(
  runId: string,
  signal?: AbortSignal,
): Promise<TrainingRunDetail> {
  const run = await compatibilityRequest<Partial<TrainingRunSummary>>(
    `/training-runs/${runId}`,
    { signal },
  );
  return normalizeTrainingRun(run);
}

export async function cancelTrainingRun(
  runId: string,
): Promise<TrainingRunDetail> {
  const run = await compatibilityRequest<Partial<TrainingRunSummary>>(
    `/training-runs/${runId}/cancel`,
    { method: "POST" },
  );
  return normalizeTrainingRun(run);
}

export async function compareExperiments(
  experimentIds: string[],
): Promise<ExperimentComparison>;
export async function compareExperiments(
  baseExperimentId: string,
  compareExperimentId: string,
): Promise<core.TrainingExperimentComparison>;
export async function compareExperiments(
  first: string[] | string,
  second?: string,
): Promise<ExperimentComparison | core.TrainingExperimentComparison> {
  if (Array.isArray(first)) {
    return compatibilityRequest<ExperimentComparison>("/experiments/compare", {
      method: "POST",
      body: JSON.stringify({ experiment_ids: first }),
    });
  }
  return core.compareExperiments(first, second ?? "");
}
