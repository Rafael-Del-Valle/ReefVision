import { getApiBaseUrl, getRuntimeContext } from "../runtime";

export interface HealthResponse {
  status: string;
  version: string;
}

export interface SystemVersionResponse {
  application_version: string;
  backup_format_version: string;
  environment: string;
  data_dir: string;
  safe_mode: boolean;
  database_path: string | null;
  current_schema_revision: string | null;
  expected_schema_revision: string | null;
}

export interface SystemCompatibilityResponse {
  application_version: string;
  schema_status:
    | "up_to_date"
    | "migration_required"
    | "uninitialized"
    | "database_newer_than_code";
  compatible_for_read_write: boolean;
  current_schema_revision: string | null;
  expected_schema_revision: string | null;
  pending_revisions: string[];
  details: string[];
}

export interface SystemLogFileResponse {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: string;
}

export interface SystemLogsLocationResponse {
  logs_dir: string;
  files: SystemLogFileResponse[];
}

export interface SystemDiagnosticsCreateResponse {
  job: JobRecord;
}

export interface SystemDiagnosticsStatusResponse {
  job: JobRecord;
  bundle_path: string | null;
  bundle_size_bytes: number | null;
  diagnostic_bundle_version: string | null;
}

export interface SystemCommandShortcutStatusResponse {
  command_version: string;
  command_directory: string;
  support_directory: string;
  repo_path: string | null;
  path_contains_command_directory: boolean;
  start_command_exists: boolean;
  update_command_exists: boolean;
  support_start_exists: boolean;
  support_update_exists: boolean;
  start_command_managed: boolean;
  update_command_managed: boolean;
  verification_result: string;
  notes: string[];
}

export interface SystemCommandShortcutRepairResponse {
  status: SystemCommandShortcutStatusResponse;
  output: string;
}

export interface LabelClass {
  id: string;
  project_id: string;
  class_index: number;
  display_order: number;
  name: string;
  scientific_name: string | null;
  state_name: string | null;
  description: string | null;
  display_color: string;
  is_active: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LabelClassUsageCount {
  key: string;
  label: string;
  count: number;
  mutable: boolean;
  immutable: boolean;
}

export interface LabelClassUsage {
  class_id: string;
  project_id: string;
  class_name: string;
  is_active: boolean;
  archived_at: string | null;
  total_references: number;
  mutable_reference_count: number;
  immutable_reference_count: number;
  can_delete: boolean;
  delete_blockers: string[];
  compatibility_warnings: string[];
  counts: LabelClassUsageCount[];
}

export interface LabelClassMergeCount {
  key: string;
  label: string;
  count: number;
}

export interface LabelClassMergeResponse {
  source_class: LabelClass;
  target_class: LabelClass;
  affected_counts: LabelClassMergeCount[];
  immutable_reference_counts: LabelClassMergeCount[];
  warnings: string[];
}

export type ClassOperationType = "reassign" | "reassign_delete";

export type ClassOperationStatus =
  | "previewed"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "rolled_back"
  | "cancelled";

export interface ClassOperationClassSnapshot {
  id: string;
  name: string;
  class_index: number;
  display_order: number;
  display_color: string;
  scientific_name: string | null;
  state_name: string | null;
  description: string | null;
  archived_at: string | null;
}

export interface ClassOperationRecordGroup {
  key: string;
  label: string;
  count: number;
  record_ids: string[];
}

export interface ClassOperationCompatibilityImpact {
  key: string;
  label: string;
  status: string;
  message: string;
  record_ids: string[];
}

export interface ClassOperationPlan {
  mutable_records: ClassOperationRecordGroup[];
  protected_records: ClassOperationRecordGroup[];
  blocking_records: ClassOperationRecordGroup[];
  compatibility_impacts: ClassOperationCompatibilityImpact[];
  warnings: string[];
  blockers: string[];
}

export interface ClassOperationRecord {
  id: string;
  project_id: string;
  source_class_id: string;
  target_class_id: string | null;
  operation_type: ClassOperationType;
  status: ClassOperationStatus;
  preview_checksum: string;
  requested_by_identity: string;
  source_class: ClassOperationClassSnapshot;
  target_class: ClassOperationClassSnapshot | null;
  plan: ClassOperationPlan;
  affected_counts: ClassOperationRecordGroup[];
  protected_reference_counts: ClassOperationRecordGroup[];
  warnings: string[];
  failures: string[];
  rollback_result: Record<string, unknown>;
  final_state: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  storage_root: string;
  default_annotation_type: string;
  georeference_height_offset_m: number;
  georeference_height_evidence: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  label_classes: LabelClass[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  storage_root: string;
  default_annotation_type: string;
  georeference_height_offset_m: number;
  georeference_height_evidence: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  label_class_count: number;
  active_label_class_count: number;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  georeference_height_offset_m?: number;
  georeference_height_evidence?: string;
  template: "blank";
}

export interface LabelClassCreate {
  class_index: number;
  name: string;
  scientific_name?: string;
  state_name?: string;
  description?: string;
  display_color: string;
}

export type AnnotationStatus =
  "unannotated" | "in_progress" | "annotated" | "reviewed" | "excluded";

export interface ProjectImage {
  id: string;
  project_id: string;
  original_filename: string;
  managed_path: string;
  thumbnail_path: string | null;
  sha256: string;
  width_px: number;
  height_px: number;
  file_size_bytes: number;
  media_type: string;
  import_source: string | null;
  capture_timestamp: string | null;
  group_key: string | null;
  metadata_json: Record<string, unknown>;
  annotation_status: AnnotationStatus;
  annotation_revision: number;
  annotation_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectImageListItem {
  id: string;
  project_id: string;
  original_filename: string;
  thumbnail_path: string | null;
  width_px: number;
  height_px: number;
  group_key: string | null;
  annotation_status: AnnotationStatus;
  annotation_revision: number;
  annotation_count: number;
  created_at: string;
  updated_at: string;
}

export interface AnnotationRecord {
  id: string;
  image_id: string;
  label_class_id: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  source_type: string;
  source_model_id: string | null;
  source_prediction_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
}

export interface AnnotationCount {
  label_class_id: string;
  count: number;
}

export interface AnnotationSession {
  image: ProjectImage;
  label_classes: LabelClass[];
  annotations: AnnotationRecord[];
  counts_by_class: AnnotationCount[];
  previous_image_id: string | null;
  next_image_id: string | null;
}

export type ClassVisibilityLayerType =
  | "annotations"
  | "predictions"
  | "qc_overlays"
  | "video_tracks"
  | "segmentation_overlays";

export interface ClassVisibilityScopeState {
  saved: boolean;
  hidden_class_ids: string[];
  updated_at: string | null;
  updated_by_identity: string | null;
}

export interface ClassVisibilityBundle {
  project_id: string;
  user_identity: string;
  supported_layer_types: ClassVisibilityLayerType[];
  precedence: string[];
  user_preferences: Record<ClassVisibilityLayerType, ClassVisibilityScopeState>;
  project_defaults: Record<ClassVisibilityLayerType, ClassVisibilityScopeState>;
}

export interface ClassVisibilityUpdatePayload {
  hidden_class_ids: string[];
}

export interface AnnotationDraftPayload {
  id: string;
  label_class_id: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface AnnotationSavePayload {
  base_revision: number;
  annotation_status: AnnotationStatus;
  annotations: AnnotationDraftPayload[];
}

export interface AnnotationSaveResponse {
  image: ProjectImage;
  annotations: AnnotationRecord[];
  counts_by_class: AnnotationCount[];
}

export interface ModelRegistration {
  id: string;
  project_id: string;
  purpose: "detector" | "assist" | "segmenter";
  display_name: string;
  source_filename: string;
  managed_path: string;
  sha256: string;
  file_size_bytes: number;
  framework: string;
  task: string;
  provider_name: string;
  provider_version: string;
  class_map_json: Record<string, unknown>;
  input_size_json: Record<string, unknown> | null;
  metadata_json: Record<string, unknown>;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export type ModelCatalogCategory =
  | "architecture"
  | "provider_requirement"
  | "pretrained_catalog"
  | "my_trained_models"
  | "imported_custom_models";

export type ModelCatalogTask =
  | "pose"
  | "classify"
  | "detect"
  | "segment"
  | "semantic_segment"
  | "open_vocabulary_detect"
  | "example_guided_detect"
  | "assist_segmentation"
  | "video_propagation"
  | "track"
  | "caption"
  | "phrase_grounding"
  | "relative_depth"
  | "metric_video_depth";

export type ModelCatalogInstallationState =
  | "Model Required"
  | "Available"
  | "Not Installed"
  | "Provider Required"
  | "Downloading"
  | "Verifying"
  | "Installing"
  | "Ready"
  | "Update Available"
  | "Incompatible"
  | "Blocked"
  | "Corrupted"
  | "Unavailable";

export type ModelCatalogSelectionKind =
  | "model_required"
  | "builtin_architecture"
  | "managed_catalog_model"
  | "registered_model"
  | "planned_unavailable";

export type ModelCatalogWorkflow =
  "training" | "prompt_assist" | "smart_mask" | "video" | "model_hub";

export interface ModelCatalogEntry {
  architecture_id?: string | null;
  training_supported?: boolean;
  inference_requires_registered_model?: boolean;
  catalog_id: string;
  display_name: string;
  display_summary: string;
  category: ModelCatalogCategory;
  provider_id: string;
  architecture: string;
  variant: string;
  inference_supported: boolean;
  download_source_type: string;
  expected_files: Array<{
    filename: string;
    source_url: string;
    revision: string;
    sha256: string;
    size_bytes: number;
  }>;
  expected_size: number | null;
  license_summary: string;
  provider_pack_id: string | null;
  recommended_ram: number | null;
  recommended_vram: number | null;
  supported_runtimes: string[];
  desktop_support: string;
  availability: "available" | "experimental" | "unavailable";
  provider: string;
  provider_version: string;
  architecture_family: string;
  model_variant: string;
  model_size: string | null;
  task: ModelCatalogTask;
  trainable: boolean;
  inference: boolean;
  video_compatibility: boolean;
  prompt_assist_compatibility: boolean;
  tiling_compatibility: boolean;
  tuning_compatibility: boolean;
  checkpoint_identifier: string | null;
  checkpoint_source: string;
  expected_checksum: string | null;
  expected_file_size: number | null;
  model_weight_license: string;
  package_license: string;
  required_provider_pack: string | null;
  required_package_versions: string[];
  supported_runtime: string[];
  supported_devices: string[];
  supported_precision: string[];
  expected_input_size: { width: number | null; height: number | null } | null;
  minimum_recommended_ram_gb: number | null;
  minimum_recommended_vram_gb: number | null;
  desktop_package_status: string;
  clean_machine_verification_status: string;
  deprecation_status: "active" | "deprecated" | "experimental";
  replacement_model_id: string | null;
  known_limitations: string[];
  installation_state: ModelCatalogInstallationState;
  installation_reason: string | null;
  installation_job_id: string | null;
  installed_asset_id: string | null;
  installed_path: string | null;
  installed_checksum: string | null;
  advanced_only: boolean;
  requires_confirmation: boolean;
  selection_kind: ModelCatalogSelectionKind;
  architecture_reference: string | null;
  resolved_model_id: string | null;
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
}

export interface CatalogReadinessResponse {
  catalog_id: string;
  installation_state: ModelCatalogInstallationState;
  installation_reason: string | null;
  provider_id: string;
  provider_version: string | null;
  provider_ready: boolean;
  expected_files_valid: boolean;
  checked_at: string;
}

export interface CatalogVerifyResponse {
  catalog_id: string;
  installation_state: ModelCatalogInstallationState;
  verified: boolean;
  expected_checksum: string | null;
  actual_checksum: string | null;
  path: string | null;
  reason: string | null;
}

export interface TrackerCatalogEntry {
  tracker_id: string;
  display_name: string;
  provider: string;
  provider_version: string;
  task: "track";
  installation_state: ModelCatalogInstallationState;
  installation_reason: string | null;
  supported_runtime: string[];
  supported_devices: string[];
  desktop_package_status: string;
  clean_machine_verification_status: string;
  known_limitations: string[];
  required_package_versions: string[];
}

export interface TrackerCatalogResponse {
  schema_version: number;
  catalog_version: string;
  trackers: TrackerCatalogEntry[];
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

export interface TrainingDatasetSummary {
  dataset_version_id: string | null;
  dataset_manifest_sha256: string | null;
  split_manifest_sha256: string | null;
  image_count: number;
  annotation_count: number;
  split_counts: Record<string, number>;
  group_count: number;
  warnings: string[];
}

export interface TrainingLeakageAudit {
  blocked: boolean;
  warnings: string[];
  blockers: string[];
  image_leak_count: number;
  group_leak_count: number;
}

export interface TrainingPreflight {
  status: "ready" | "ready_with_warnings" | "blocked";
  warnings: string[];
  blockers: string[];
  dataset: TrainingDatasetSummary;
  leakage_audit: TrainingLeakageAudit;
  resource_snapshot: Record<string, unknown>;
  provider_dependency_status: Record<string, unknown>;
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
  initial_checkpoint_source: "scratch" | "registered_model" | "managed_catalog";
  initial_checkpoint_model_id: string | null;
  resolved_model_asset_id: string | null;
  resolved_model_checksum: string | null;
  parameter_registry_version: string | null;
  selected_preset: string | null;
  installation_state: string | null;
  device: string;
  precision: string;
  random_seed: number | null;
  tiling_config: Record<string, unknown>;
  training_config: Record<string, unknown>;
  tuning_config: Record<string, unknown>;
  evaluation_config: Record<string, unknown>;
  resource_limits: Record<string, unknown>;
  validation_state: TrainingPreflight | Record<string, unknown>;
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

export interface TrainingRun {
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
  tiling_config: Record<string, unknown>;
  training_config: Record<string, unknown>;
  tuning_config: Record<string, unknown>;
  evaluation_config: Record<string, unknown>;
  resource_limits: Record<string, unknown>;
  preflight_report: Record<string, unknown>;
  draft_snapshot: Record<string, unknown>;
  status: string;
  stage: string;
  progress_epoch: number;
  progress_total_epochs: number;
  metrics: Record<string, unknown>;
  metrics_history: Record<string, unknown>;
  warnings: string[];
  artifact_manifest: Record<string, unknown>;
  logs_path: string | null;
  result_checkpoint_path: string | null;
  job_id: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface TrainingArtifact {
  name: string;
  category: string;
  relative_path: string;
  size_bytes: number;
  previewable: boolean;
}

export interface TuningTrial {
  trial_number: number;
  status: "completed" | "failed" | "cancelled" | "pruned" | string;
  fitness: number | null;
  metrics: Record<string, number>;
  hyperparameters: Record<string, number | string | boolean>;
  duration_seconds: number | null;
  epoch_history: Array<Record<string, number>>;
  artifacts: TrainingArtifact[];
  native_values: Record<string, unknown>;
  error_message?: string | null;
}

export interface TuningResults {
  fitness_definition: string;
  search_space: Record<string, unknown>;
  max_trials: number | null;
  epochs_per_trial: number | null;
  patience: number | null;
  trials: TuningTrial[];
  best_trial_number: number | null;
  best_hyperparameters: Record<string, number | string | boolean>;
  stopped_early?: boolean;
}

export interface ResultsPackageOptions {
  include_excel: boolean;
  include_machine_data: boolean;
  include_native_artifacts: boolean;
  include_logs: boolean;
  checkpoint_mode: "none" | "best" | "best_and_last" | "retained";
}

export interface ResultsPackageResult {
  run_id: string;
  package_type: "training" | "tuning";
  package_name: string;
  archive_name: string;
  archive_size_bytes: number;
  verification_status: "verified";
  warnings: string[];
  download_url: string;
}

export async function createResultsPackage(
  runId: string,
  options: ResultsPackageOptions,
): Promise<ResultsPackageResult> {
  return request<ResultsPackageResult>(
    `/training-runs/${encodeURIComponent(runId)}/results-packages`,
    { method: "POST", body: JSON.stringify(options) },
  );
}

export function resultsPackageDownloadUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`;
}

export function trainingArtifactUrl(
  runId: string,
  artifactIndex: number,
): string {
  return `${getApiBaseUrl()}/training-runs/${encodeURIComponent(runId)}/artifacts/${artifactIndex}`;
}

export interface TrainingTilingPreviewTile {
  image_id: string;
  split: string;
  x: number;
  y: number;
  width: number;
  height: number;
  retained_annotation_count: number;
}

export interface TrainingTilingEstimate {
  blocked: boolean;
  warnings: string[];
  tile_count: number;
  positive_tile_count: number;
  background_tile_count: number;
  estimated_storage_bytes: number;
  preview_tiles: TrainingTilingPreviewTile[];
}

export interface ExperimentRecord {
  id: string;
  project_id: string;
  training_run_id: string;
  dataset_version_id: string | null;
  dataset_manifest_sha256: string;
  split_manifest_sha256: string;
  task: string;
  provider_id: string;
  architecture: string;
  summary_metrics_json: Record<string, unknown>;
  comparison_warnings_json: string[];
  artifact_manifest_json: Record<string, unknown>;
  package_versions_json: Record<string, unknown>;
  created_at: string;
}

export interface ExperimentCompareResponse {
  experiments: ExperimentRecord[];
  warnings: string[];
}

export interface ProviderDependencyPackage {
  distribution_name: string;
  required_version: string;
  installed_version: string | null;
  status: "ok" | "missing" | "incompatible";
}

export interface ProviderDependencyStatus {
  provider_name: string;
  display_name: string;
  purpose: "detector" | "assist";
  provider_version: string;
  status: "ready" | "missing" | "incompatible";
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
  default_registration_purpose: "detector" | "assist" | null;
  registerable: boolean;
  capabilities: ModelProviderCapabilityMatrix;
}

export interface RuntimeProviderStatus {
  runtime_id: string;
  display_name: string;
  package_name: string | null;
  package_version: string | null;
  available: boolean;
  status: string;
  supports_cpu: boolean;
  supports_cuda: boolean;
  notes: string[];
}

export interface UltralyticsTrainingRegistrySummary {
  parameter_count: number;
  reefvision_supported_parameter_count: number;
  tunable_parameter_count: number;
  native_tune_parameter_count: number;
  fixed_only_parameter_count: number;
}

export interface UltralyticsTrainingRegistryParameter {
  name: string;
  display_name: string;
  category: string;
  value_type: string;
  default_value: unknown;
  minimum: number | null;
  maximum: number | null;
  choices: unknown[];
  supported_tasks: string[];
  supported_modes: string[];
  reefvision_supported: boolean;
  tunable: boolean;
  fixed_only: boolean;
  native_tune_default: boolean;
  help_text: string;
  dependency_rules: string[];
  supported_version: string;
  native_tune_minimum: number | null;
  native_tune_maximum: number | null;
  native_tune_gain: number | null;
  native_tune_scale: string | null;
}

export interface UltralyticsTrainingRegistryResponse {
  provider_name: string;
  provider_version: string;
  ultralytics_version: string | null;
  pinned_version_matches_installed: boolean;
  supported_tasks: string[];
  supported_modes: string[];
  method_signatures: Record<string, string>;
  summary: UltralyticsTrainingRegistrySummary;
  parameters: UltralyticsTrainingRegistryParameter[];
}

export interface UltralyticsTrainingRegistrySummarySnapshot {
  provider_name: string;
  provider_version: string;
  ultralytics_version: string | null;
  pinned_version_matches_installed: boolean;
  supported_tasks: string[];
  supported_modes: string[];
  summary: UltralyticsTrainingRegistrySummary;
}

export interface ModelHubBootstrapResponse {
  application_version: string;
  catalog: ModelCatalogResponse;
  models: ModelRegistration[];
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

export interface TrainingWorkspaceBootstrapResponse {
  draft_summaries: TrainingDraftSummary[];
  selected_draft: TrainingDraft | null;
  providers: TrainingProvider[];
  catalog: ModelCatalogResponse;
}

export interface UltralyticsTrainingSearchSpaceField {
  name: string;
  minimum?: number | null;
  maximum?: number | null;
  discrete_values?: unknown[];
  fixed_value?: unknown;
  scale?: string;
  integer?: boolean | null;
}

export interface UltralyticsTrainingValidationResponse {
  ultralytics_version: string | null;
  requested_mode: string;
  normalized_mode: string;
  validated_parameters: Record<string, unknown>;
  validated_search_space: Array<{
    name: string;
    minimum: number | null;
    maximum: number | null;
    discrete_values: unknown[];
    fixed_value: unknown;
    scale: string;
    integer: boolean;
  }>;
  warnings: string[];
}

export interface JobRecord {
  id: string;
  project_id: string | null;
  job_type: string;
  status: string;
  progress_current: number;
  progress_total: number;
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface BackupRecord {
  id: string;
  job_id: string | null;
  status: string;
  format_version: string;
  destination_path: string;
  staging_path: string | null;
  manifest_path: string;
  completion_marker_path: string;
  database_filename: string;
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface BackupCreateResponse {
  backup: BackupRecord;
  job: JobRecord;
}

export interface BackupVerificationResponse {
  backup_id: string;
  status: "valid" | "valid_with_warnings" | "invalid" | "unsupported";
  format_version: string | null;
  application_version: string | null;
  current_schema_revision: string | null;
  completion_marker_present: boolean;
  manifest_path: string;
  database_filename: string | null;
  file_count: number;
  total_size_bytes: number | null;
  item_counts: Record<string, number>;
  missing_files: string[];
  checksum_failures: string[];
  duplicate_entries: string[];
  warnings: string[];
  errors: string[];
}

export interface BackupRestoreResponse {
  backup_id: string;
  destination_path: string;
  verification_status: "valid" | "valid_with_warnings";
  warnings: string[];
  job: JobRecord;
}

export type QualityControlSeverity = "error" | "warning" | "info";
export type QualityControlIssueStatus =
  | "open"
  | "acknowledged"
  | "dismissed"
  | "resolved_in_later_run"
  | "no_longer_applicable";
export type QualityControlRuleCategory =
  | "annotation_geometry"
  | "annotation_semantics"
  | "image_integrity"
  | "predictions"
  | "statistics"
  | "dataset_versions";

export interface QualityControlThresholdConfig {
  small_box_min_width_px: number;
  small_box_min_height_px: number;
  near_duplicate_iou_threshold: number;
  same_class_overlap_iou_threshold: number;
  different_class_overlap_iou_threshold: number;
  boundary_touch_margin_px: number;
  annotation_count_mad_multiplier: number;
  class_imbalance_majority_ratio: number;
  suspicious_bulk_acceptance_min_count: number;
  suspicious_bulk_acceptance_window_minutes: number;
  overlap_spatial_cell_px: number;
}

export interface QualityControlRunRecord {
  id: string;
  project_id: string;
  dataset_version_id: string | null;
  job_id: string | null;
  scope_type: string;
  status: string;
  rule_categories_json: string[];
  selected_rule_ids_json: string[];
  thresholds_json: Record<string, unknown>;
  configuration_json: Record<string, unknown>;
  input_checksums_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  issue_count: number;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  error_message: string | null;
}

export interface QualityControlIssue {
  id: string;
  quality_control_run_id: string;
  project_id: string;
  dataset_version_id: string | null;
  image_id: string | null;
  rule_id: string;
  rule_version: string;
  severity: QualityControlSeverity;
  status: QualityControlIssueStatus;
  fingerprint: string;
  title: string;
  explanation: string;
  annotation_ids_json: string[];
  prediction_ids_json: string[];
  class_ids_json: string[];
  measured_values_json: Record<string, unknown>;
  thresholds_json: Record<string, unknown>;
  resolution_metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  dismissed_at: string | null;
  dismissed_by: string | null;
  dismissed_reason: string | null;
  resolution_run_id: string | null;
}

export interface QualityControlIssuePage {
  items: QualityControlIssue[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface QualityControlRunComparisonIssue {
  fingerprint: string;
  rule_id: string;
  severity: QualityControlSeverity;
  title: string;
  image_id: string | null;
}

export interface QualityControlRunComparison {
  base_run_id: string;
  compare_run_id: string;
  added_count: number;
  resolved_count: number;
  unchanged_count: number;
  added: QualityControlRunComparisonIssue[];
  resolved: QualityControlRunComparisonIssue[];
}

export interface ReviewScoreWeights {
  low_mean_confidence: number;
  low_min_confidence: number;
  pending_proposals: number;
  rejection_rate: number;
  count_disagreement: number;
  unresolved_qc_severity: number;
  rare_class_presence: number;
  edited_acceptance_rate: number;
  unreviewed_state: number;
  missing_group_metadata: number;
  incomplete_provenance: number;
  recent_import: number;
  stale_review_state: number;
}

export interface ReviewScoreComponent {
  signal_id: string;
  label: string;
  raw_value: number;
  normalized_value: number;
  weight: number;
  contribution: number;
  description: string;
}

export type ReviewQueueItemState =
  "pending" | "in_progress" | "completed" | "skipped";

export interface ReviewQueueRecord {
  id: string;
  project_id: string;
  dataset_version_id: string | null;
  source_quality_control_run_id: string | null;
  regenerated_from_queue_id: string | null;
  scope_type: string;
  status: string;
  formula_id: string;
  formula_version: string;
  configuration_json: Record<string, unknown>;
  input_checksums_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  item_count: number;
  created_by: string;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface ReviewQueueItem {
  id: string;
  review_queue_id: string;
  project_id: string;
  dataset_version_id: string | null;
  image_id: string;
  split: string | null;
  review_state: ReviewQueueItemState;
  score: number;
  rank_position: number;
  highest_qc_severity: QualityControlSeverity | null;
  label_class_ids_json: string[];
  model_ids_json: string[];
  related_issue_ids_json: string[];
  signal_values_json: Record<string, unknown>;
  normalized_signals_json: Record<string, number>;
  weights_json: Record<string, number>;
  score_breakdown_json: ReviewScoreComponent[];
  input_checksum: string;
  reason_summary: string | null;
  skip_reason: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  returned_at: string | null;
}

export interface ReviewQueueItemPage {
  items: ReviewQueueItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type ReviewQueueBulkAction = "start" | "skip" | "return" | "complete";

export interface ReviewQueueBulkResponse {
  queue_id: string;
  action: ReviewQueueBulkAction;
  changed_count: number;
  items: ReviewQueueItem[];
  requires_researcher_review: boolean;
}

export type ReviewQueueEventType =
  | "comment"
  | "assign"
  | "unassign"
  | "triage_start"
  | "triage_skip"
  | "triage_return"
  | "triage_complete";

export interface ReviewQueueEvent {
  id: string;
  review_queue_id: string;
  review_queue_item_id: string;
  project_id: string;
  client_request_id: string;
  event_type: ReviewQueueEventType;
  actor: string;
  comment: string | null;
  assignee: string | null;
  created_at: string;
}

export interface ReviewQueueEventsPage {
  items: ReviewQueueEvent[];
  total: number;
  page: number;
  page_size: number;
  current_assignee: string | null;
  requires_researcher_review: boolean;
}

export interface ReviewQueueEventCreate {
  client_request_id: string;
  event_type: "comment" | "assign" | "unassign";
  actor: string;
  comment?: string;
  assignee?: string;
}

export type DatasetSplit = "train" | "validation" | "test" | "unassigned";
export type DatasetSplitMethod = "none" | "manual" | "random" | "group_random";

export interface DatasetSplitRatios {
  train: number;
  validation: number;
  test: number;
}

export interface DatasetVersionPreviewImage {
  image_id: string;
  original_filename: string;
  annotation_status: AnnotationStatus;
  group_key: string | null;
  annotation_count: number;
  proposed_split: DatasetSplit;
}

export interface DatasetVersionSplitSummary {
  split: DatasetSplit;
  image_count: number;
  annotation_count: number;
}

export interface DatasetVersionPreviewClassCount {
  label_class_id: string;
  class_index: number;
  class_name: string;
  count: number;
}

export interface DatasetVersionPreview {
  requested_split_method: DatasetSplitMethod;
  resolved_split_method: DatasetSplitMethod;
  eligible_image_count: number;
  eligible_annotation_count: number;
  missing_group_key_count: number;
  warnings: string[];
  split_summary: DatasetVersionSplitSummary[];
  per_class_counts: DatasetVersionPreviewClassCount[];
  images: DatasetVersionPreviewImage[];
}

export interface DatasetVersionRecord {
  id: string;
  project_id: string;
  version_number: number;
  name: string;
  notes: string | null;
  parent_version_id: string | null;
  status: string;
  requested_split_method: DatasetSplitMethod;
  resolved_split_method: DatasetSplitMethod;
  eligible_annotation_statuses_json: string[];
  requested_ratios_json: DatasetSplitRatios | null;
  achieved_ratios_json: DatasetSplitRatios | null;
  split_seed: number | null;
  reuse_parent_assignments: boolean;
  missing_group_key_count: number;
  warnings_json: string[];
  class_map_json: Array<Record<string, unknown>>;
  manifest_sha256: string;
  image_count: number;
  annotation_count: number;
  created_by: string;
  reefvision_version: string;
  schema_version: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DatasetVersionComparisonItem {
  image_id: string;
  original_filename: string;
  from_split: DatasetSplit | null;
  to_split: DatasetSplit | null;
  from_annotation_count: number;
  to_annotation_count: number;
}

export interface DatasetVersionComparison {
  base_version_id: string;
  compare_version_id: string;
  added_images: DatasetVersionComparisonItem[];
  removed_images: DatasetVersionComparisonItem[];
  changed_images: DatasetVersionComparisonItem[];
  annotation_delta: number;
}

export interface DatasetVersionManifest {
  dataset_version_id: string;
  manifest_sha256: string;
  manifest_json: Record<string, unknown>;
}

export interface DatasetVersionRequestBase {
  parent_version_id?: string | null;
  eligible_annotation_statuses: AnnotationStatus[];
  split_method: DatasetSplitMethod;
  requested_ratios?: DatasetSplitRatios;
  split_seed?: number | null;
  reuse_parent_assignments?: boolean;
  manual_assignments?: Array<{ image_id: string; split: DatasetSplit }>;
}

export interface DatasetVersionCreatePayload extends DatasetVersionRequestBase {
  name: string;
  notes?: string;
  creator?: string;
}

export interface ExportRecord {
  id: string;
  project_id: string;
  dataset_version_id: string;
  job_id: string | null;
  format: string;
  output_path: string;
  manifest_path: string;
  archive_path: string;
  request_json: Record<string, unknown>;
  status: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DatasetExportCreateResponse {
  export: ExportRecord;
  job: JobRecord;
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
  geometry_kind?:
    "bounding_box" | "rotated_box" | "polygon_mask" | "raster_mask" | string;
  polygon_json?: number[][] | null;
  mask_path?: string | null;
  mask_content_sha256?: string | null;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  review_status: string;
  was_edited: boolean;
  reviewer_action_at: string | null;
  accepted_annotation_id: string | null;
  accepted_mask_annotation_id?: string | null;
  inference_settings_json: Record<string, unknown>;
  provenance_json: Record<string, unknown> | null;
  created_at: string;
}

export interface PredictionListResponse {
  items: PredictionProposal[];
  counts: Record<string, number>;
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

export interface ImagePage {
  items: ProjectImageListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ImportItem {
  filename: string;
  relative_path: string | null;
  status: "successful" | "duplicate" | "unsupported" | "failed";
  detail: string | null;
  image_id: string | null;
  duplicate_image_id: string | null;
  thumbnail_job_id: string | null;
}

export interface ImageImportReport {
  project_id: string;
  successful: ImportItem[];
  duplicates: ImportItem[];
  unsupported: ImportItem[];
  failed: ImportItem[];
}

export interface ImageFilters {
  page?: number;
  pageSize?: number;
  filename?: string;
  annotationStatus?: string;
  groupKey?: string;
  sortBy?: "newest" | "oldest" | "filename" | "annotations";
}

export class ApiRequestError extends Error {
  details: Record<string, unknown> | null;

  constructor(message: string, details: Record<string, unknown> | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.details = details;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 30_000,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  const controller = new AbortController();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
  } catch {
    if (timedOut) {
      throw new ApiRequestError(
        `ReefVision did not respond within ${Math.round(timeoutMs / 1000)} seconds.`,
      );
    }
    const runtime = getRuntimeContext();
    const message = runtime.desktopMode
      ? "ReefVision could not reach its local desktop API. Retry the request or restart ReefVision."
      : "ReefVision could not reach the ReefVision API. Confirm the local API is running and retry.";
    throw new ApiRequestError(message);
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", abortFromCaller);
  }
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    let details: Record<string, unknown> | null = null;
    try {
      const payload = (await response.json()) as {
        detail?: string | Record<string, unknown>;
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        details = payload.detail;
        if (typeof payload.detail.reason === "string") {
          message = payload.detail.reason;
        }
      }
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new ApiRequestError(message, details);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function imageThumbnailUrl(imageId: string): string {
  return `${getApiBaseUrl()}/images/${imageId}/thumbnail?renderer=2`;
}

export function imageContentUrl(imageId: string): string {
  return `${getApiBaseUrl()}/images/${imageId}/content`;
}

export function imageDisplayUrl(imageId: string): string {
  return `${getApiBaseUrl()}/images/${imageId}/display`;
}

export function predictionMaskUrl(proposalId: string): string {
  return `${getApiBaseUrl()}/prediction-proposals/${encodeURIComponent(proposalId)}/mask`;
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { signal });
}

export async function getSystemVersion(
  signal?: AbortSignal,
): Promise<SystemVersionResponse> {
  return request<SystemVersionResponse>("/system/version", { signal });
}

export async function getSystemCompatibility(
  signal?: AbortSignal,
): Promise<SystemCompatibilityResponse> {
  return request<SystemCompatibilityResponse>("/system/compatibility", {
    signal,
  });
}

export async function getSystemLogsLocation(
  signal?: AbortSignal,
): Promise<SystemLogsLocationResponse> {
  return request<SystemLogsLocationResponse>("/system/logs/location", {
    signal,
  });
}

export async function getSystemCommandShortcuts(
  signal?: AbortSignal,
): Promise<SystemCommandShortcutStatusResponse> {
  return request<SystemCommandShortcutStatusResponse>(
    "/system/command-shortcuts",
    {
      signal,
    },
  );
}

export async function repairSystemCommandShortcuts(): Promise<SystemCommandShortcutRepairResponse> {
  return request<SystemCommandShortcutRepairResponse>(
    "/system/command-shortcuts/repair",
    {
      method: "POST",
    },
  );
}

export async function createSystemDiagnostics(payload: {
  strict_redaction: boolean;
  notes?: string;
}): Promise<SystemDiagnosticsCreateResponse> {
  return request<SystemDiagnosticsCreateResponse>("/system/diagnostics", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSystemDiagnosticsStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<SystemDiagnosticsStatusResponse> {
  return request<SystemDiagnosticsStatusResponse>(
    `/system/diagnostics/${jobId}`,
    { signal },
  );
}

export async function getBackups(
  signal?: AbortSignal,
): Promise<BackupRecord[]> {
  return request<BackupRecord[]>("/backups", { signal });
}

export async function createBackup(payload: {
  include_exports: boolean;
  include_logs: boolean;
  notes?: string;
}): Promise<BackupCreateResponse> {
  return request<BackupCreateResponse>("/backups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function verifyBackup(
  backupId: string,
): Promise<BackupVerificationResponse> {
  return request<BackupVerificationResponse>(`/backups/${backupId}/verify`, {
    method: "POST",
  });
}

export async function restoreBackup(
  backupId: string,
  payload: { destination_name?: string; overwrite_existing?: boolean },
): Promise<BackupRestoreResponse> {
  return request<BackupRestoreResponse>(`/backups/${backupId}/restore`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getProjects(signal?: AbortSignal): Promise<Project[]> {
  return request<Project[]>("/projects", { signal });
}

export async function getProjectSummaries(
  signal?: AbortSignal,
): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>("/project-summaries", { signal });
}

export async function getProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<Project> {
  return request<Project>(`/projects/${projectId}`, { signal });
}

export async function createProject(payload: ProjectCreate): Promise<Project> {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function archiveProject(projectId: string): Promise<Project> {
  return request<Project>(`/projects/${projectId}/archive`, { method: "POST" });
}

export async function createLabelClass(
  projectId: string,
  payload: LabelClassCreate,
): Promise<LabelClass> {
  return request<LabelClass>(`/projects/${projectId}/classes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateLabelClass(
  classId: string,
  payload: Partial<
    Pick<LabelClass, "name" | "display_order" | "display_color" | "description">
  >,
): Promise<LabelClass> {
  return request<LabelClass>(`/classes/${classId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deactivateLabelClass(
  classId: string,
): Promise<LabelClass> {
  return request<LabelClass>(`/classes/${classId}/deactivate`, {
    method: "POST",
  });
}

export async function archiveLabelClass(classId: string): Promise<LabelClass> {
  return request<LabelClass>(`/classes/${classId}/archive`, {
    method: "POST",
  });
}

export async function restoreLabelClass(classId: string): Promise<LabelClass> {
  return request<LabelClass>(`/classes/${classId}/restore`, {
    method: "POST",
  });
}

export async function getLabelClassUsage(
  classId: string,
  signal?: AbortSignal,
): Promise<LabelClassUsage> {
  return request<LabelClassUsage>(`/classes/${classId}/usage`, { signal });
}

export async function getProjectLabelClassUsage(
  projectId: string,
  classId: string,
  signal?: AbortSignal,
): Promise<LabelClassUsage> {
  return request<LabelClassUsage>(
    `/projects/${projectId}/classes/${classId}/usage`,
    {
      signal,
    },
  );
}

export async function deleteLabelClass(classId: string): Promise<void> {
  await request<void>(`/classes/${classId}`, { method: "DELETE" });
}

export async function mergeLabelClass(
  classId: string,
  payload: { target_class_id: string },
): Promise<LabelClassMergeResponse> {
  return request<LabelClassMergeResponse>(`/classes/${classId}/merge`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function previewLabelClassReassign(
  projectId: string,
  classId: string,
  payload: { target_class_id: string; notes?: string | null },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
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
  payload: {
    operation_id: string;
    preview_checksum: string;
    notes?: string | null;
  },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
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
  payload: { target_class_id: string; notes?: string | null },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
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
  payload: {
    operation_id: string;
    preview_checksum: string;
    notes?: string | null;
  },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
    `/projects/${projectId}/classes/${classId}/reassign-delete`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getClassOperation(
  operationId: string,
  signal?: AbortSignal,
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(`/class-operations/${operationId}`, {
    signal,
  });
}

export async function getImages(
  projectId: string,
  filters: ImageFilters,
  signal?: AbortSignal,
): Promise<ImagePage> {
  const search = new URLSearchParams();
  search.set("page", String(filters.page ?? 1));
  search.set("page_size", String(filters.pageSize ?? 24));
  if (filters.filename) search.set("filename", filters.filename);
  if (filters.annotationStatus) {
    search.set("annotation_status", filters.annotationStatus);
  }
  if (filters.groupKey) search.set("group_key", filters.groupKey);
  if (filters.sortBy) search.set("sort_by", filters.sortBy);
  return request<ImagePage>(`/projects/${projectId}/images?${search}`, {
    signal,
  });
}

export async function importImages(
  projectId: string,
  files: File[],
): Promise<ImageImportReport> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file, file.name);
    const relativePath =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
      file.name;
    formData.append("relative_paths", relativePath);
  });
  return request<ImageImportReport>(
    `/projects/${projectId}/imports/images`,
    {
      method: "POST",
      body: formData,
    },
    10 * 60_000,
  );
}

export async function updateImage(
  imageId: string,
  payload: Partial<Pick<ProjectImage, "group_key" | "annotation_status">>,
): Promise<ProjectImage> {
  return request<ProjectImage>(`/images/${imageId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function getAnnotationSession(
  imageId: string,
  signal?: AbortSignal,
): Promise<AnnotationSession> {
  return request<AnnotationSession>(`/images/${imageId}/annotations`, {
    signal,
  });
}

export async function getClassVisibilityBundle(
  projectId: string,
  signal?: AbortSignal,
): Promise<ClassVisibilityBundle> {
  return request<ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility`,
    {
      signal,
    },
  );
}

export async function saveClassVisibilityPreference(
  projectId: string,
  layerType: ClassVisibilityLayerType,
  payload: ClassVisibilityUpdatePayload,
): Promise<ClassVisibilityScopeState> {
  return request<ClassVisibilityScopeState>(
    `/projects/${projectId}/class-visibility/preferences/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteClassVisibilityPreference(
  projectId: string,
  layerType: ClassVisibilityLayerType,
): Promise<void> {
  return request<void>(
    `/projects/${projectId}/class-visibility/preferences/${layerType}`,
    {
      method: "DELETE",
    },
  );
}

export async function saveProjectClassVisibilityDefault(
  projectId: string,
  layerType: ClassVisibilityLayerType,
  payload: ClassVisibilityUpdatePayload,
): Promise<ClassVisibilityScopeState> {
  return request<ClassVisibilityScopeState>(
    `/projects/${projectId}/class-visibility/defaults/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteProjectClassVisibilityDefault(
  projectId: string,
  layerType: ClassVisibilityLayerType,
): Promise<void> {
  return request<void>(
    `/projects/${projectId}/class-visibility/defaults/${layerType}`,
    {
      method: "DELETE",
    },
  );
}

export async function saveAnnotations(
  imageId: string,
  payload: AnnotationSavePayload,
): Promise<AnnotationSaveResponse> {
  return request<AnnotationSaveResponse>(`/images/${imageId}/annotations`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getDatasetVersions(
  projectId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionRecord[]> {
  return request<DatasetVersionRecord[]>(
    `/projects/${projectId}/dataset-versions`,
    { signal },
  );
}

export async function previewDatasetVersion(
  projectId: string,
  payload: DatasetVersionRequestBase,
): Promise<DatasetVersionPreview> {
  return request<DatasetVersionPreview>(
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
): Promise<DatasetVersionRecord> {
  return request<DatasetVersionRecord>(
    `/projects/${projectId}/dataset-versions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getDatasetVersionComparison(
  versionId: string,
  otherVersionId: string,
): Promise<DatasetVersionComparison> {
  const search = new URLSearchParams({ other_version_id: otherVersionId });
  return request<DatasetVersionComparison>(
    `/dataset-versions/${versionId}/compare?${search}`,
  );
}

export async function getDatasetVersionManifest(
  versionId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionManifest> {
  return request<DatasetVersionManifest>(
    `/dataset-versions/${versionId}/manifest`,
    {
      signal,
    },
  );
}

export async function getExports(
  projectId: string,
  datasetVersionId?: string,
  signal?: AbortSignal,
): Promise<ExportRecord[]> {
  const search = new URLSearchParams();
  if (datasetVersionId) search.set("dataset_version_id", datasetVersionId);
  const suffix = search.size ? `?${search}` : "";
  return request<ExportRecord[]>(`/projects/${projectId}/exports${suffix}`, {
    signal,
  });
}

export async function createDatasetExport(
  versionId: string,
): Promise<DatasetExportCreateResponse> {
  return request<DatasetExportCreateResponse>(
    `/dataset-versions/${versionId}/exports`,
    {
      method: "POST",
      body: JSON.stringify({ format: "yolo_detection" }),
    },
  );
}

export function datasetExportDownloadUrl(exportId: string): string {
  return `${getApiBaseUrl()}/exports/${exportId}/download`;
}

export function datasetExportManifestUrl(exportId: string): string {
  return `${getApiBaseUrl()}/exports/${exportId}/manifest`;
}

export async function getModels(
  projectId: string,
  purpose?: "detector" | "assist",
  signal?: AbortSignal,
): Promise<ModelRegistration[]> {
  const search = new URLSearchParams();
  if (purpose) search.set("purpose", purpose);
  const suffix = search.size ? `?${search}` : "";
  return request<ModelRegistration[]>(
    `/projects/${projectId}/models${suffix}`,
    {
      signal,
    },
  );
}

export async function getProjectModelCatalog(
  projectId: string,
  filters?: {
    workflow?: ModelCatalogWorkflow;
    task?: ModelCatalogTask;
    includeUnavailable?: boolean;
  },
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  const search = new URLSearchParams();
  if (filters?.workflow) search.set("workflow", filters.workflow);
  if (filters?.task) search.set("task", filters.task);
  if (filters?.includeUnavailable !== undefined) {
    search.set("include_unavailable", String(filters.includeUnavailable));
  }
  const suffix = search.size ? `?${search}` : "";
  return request<ModelCatalogResponse>(
    `/projects/${projectId}/model-catalog${suffix}`,
    { signal },
    5_000,
  );
}

export async function installCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<JobRecord> {
  return request<JobRecord>(
    `/projects/${projectId}/model-installs/${encodeURIComponent(catalogId)}`,
    { method: "POST", body: JSON.stringify({ confirmed: true }) },
  );
}

export async function getCatalogModelReadiness(
  projectId: string,
  catalogId: string,
  signal?: AbortSignal,
): Promise<CatalogReadinessResponse> {
  return request<CatalogReadinessResponse>(
    `/projects/${projectId}/model-readiness/${encodeURIComponent(catalogId)}`,
    { signal },
  );
}

export async function verifyCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<CatalogVerifyResponse> {
  return request<CatalogVerifyResponse>(
    `/projects/${projectId}/model-verifications/${encodeURIComponent(catalogId)}`,
    { method: "POST" },
  );
}

export async function removeCatalogModel(
  projectId: string,
  catalogId: string,
): Promise<void> {
  await request<void>(
    `/projects/${projectId}/model-installs/${encodeURIComponent(catalogId)}`,
    { method: "DELETE" },
  );
}

export async function getModelHubBootstrap(
  projectId: string,
  signal?: AbortSignal,
): Promise<ModelHubBootstrapResponse> {
  return request<ModelHubBootstrapResponse>(
    `/projects/${projectId}/model-hub/bootstrap`,
    { signal },
  );
}

export async function getProjectModelCatalogItem(
  projectId: string,
  catalogId: string,
): Promise<ModelCatalogEntry> {
  return request<ModelCatalogEntry>(
    `/projects/${projectId}/model-catalog/${encodeURIComponent(catalogId)}`,
  );
}

export async function getTrackerCatalog(): Promise<TrackerCatalogResponse> {
  return request<TrackerCatalogResponse>("/tracker-catalog");
}

export async function getModelProviderPreflight(options?: {
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<ProviderDependencyPreflightResponse> {
  const search = new URLSearchParams();
  if (options?.refresh) {
    search.set("refresh", "true");
  }
  const suffix = search.size ? `?${search}` : "";
  return request<ProviderDependencyPreflightResponse>(
    `/models/provider-preflight${suffix}`,
    { signal: options?.signal },
  );
}

export async function getModelProviders(options?: {
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<ModelProvider[]> {
  const search = new URLSearchParams();
  if (options?.refresh) {
    search.set("refresh", "true");
  }
  const suffix = search.size ? `?${search}` : "";
  return request<ModelProvider[]>(`/model-providers${suffix}`, {
    signal: options?.signal,
  });
}

export async function getRuntimeProviderStatuses(options?: {
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<RuntimeProviderStatus[]> {
  const search = new URLSearchParams();
  if (options?.refresh) {
    search.set("refresh", "true");
  }
  const suffix = search.size ? `?${search}` : "";
  return request<RuntimeProviderStatus[]>(
    `/runtime-providers/status${suffix}`,
    {
      signal: options?.signal,
    },
  );
}

export async function getUltralyticsTrainingRegistrySummary(options?: {
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<UltralyticsTrainingRegistrySummarySnapshot> {
  const search = new URLSearchParams();
  if (options?.refresh) {
    search.set("refresh", "true");
  }
  const suffix = search.size ? `?${search}` : "";
  return request<UltralyticsTrainingRegistrySummarySnapshot>(
    `/models/ultralytics/training-registry/summary${suffix}`,
    { signal: options?.signal },
  );
}

export async function getUltralyticsTrainingRegistry(
  signal?: AbortSignal,
): Promise<UltralyticsTrainingRegistryResponse> {
  return request<UltralyticsTrainingRegistryResponse>(
    "/models/ultralytics/training-registry",
    { signal },
  );
}

export async function getTrainingProviders(
  signal?: AbortSignal,
): Promise<TrainingProvider[]> {
  return request<TrainingProvider[]>("/training/providers", { signal });
}

export async function getTrainingWorkspaceBootstrap(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingWorkspaceBootstrapResponse> {
  return request<TrainingWorkspaceBootstrapResponse>(
    `/projects/${projectId}/training/bootstrap`,
    { signal },
  );
}

export async function getTrainingProviderParameters(
  providerId: string,
  signal?: AbortSignal,
): Promise<UltralyticsTrainingRegistryResponse> {
  return request<UltralyticsTrainingRegistryResponse>(
    `/training/providers/${providerId}/parameters`,
    { signal },
  );
}

export async function getTrainingDrafts(
  projectId: string,
): Promise<TrainingDraft[]> {
  return request<TrainingDraft[]>(`/projects/${projectId}/training-drafts`);
}

export async function getTrainingDraftSummaries(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingDraftSummary[]> {
  return request<TrainingDraftSummary[]>(
    `/projects/${projectId}/training-draft-summaries`,
    { signal },
  );
}

export async function getTrainingDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/training-drafts/${draftId}`, { signal });
}

export async function createTrainingDraft(
  projectId: string,
  payload: {
    name: string;
    run_name?: string | null;
    notes?: string | null;
    dataset_version_id?: string | null;
    task?: string | null;
    catalog_model_id?: string | null;
    provider_id?: string | null;
    architecture?: string | null;
    initial_checkpoint_source?:
      "scratch" | "registered_model" | "managed_catalog";
    initial_checkpoint_model_id?: string | null;
    device?: string;
    precision?: string;
    random_seed?: number | null;
    tiling_config?: Record<string, unknown>;
    training_config?: Record<string, unknown>;
    tuning_config?: Record<string, unknown>;
    evaluation_config?: Record<string, unknown>;
    resource_limits?: Record<string, unknown>;
  },
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/projects/${projectId}/training-drafts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateTrainingDraft(
  draftId: string,
  payload: Record<string, unknown>,
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/training-drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteTrainingDraft(draftId: string): Promise<void> {
  await request<void>(`/training-drafts/${draftId}`, { method: "DELETE" });
}

export async function runTrainingPreflight(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<TrainingPreflight> {
  return request<TrainingPreflight>(
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
    tiling_config: Record<string, unknown>;
  },
): Promise<TrainingTilingEstimate> {
  return request<TrainingTilingEstimate>(
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
): Promise<TrainingRun> {
  return request<TrainingRun>(`/projects/${projectId}/training-runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getTrainingRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingRun[]> {
  const pollToken = Date.now();
  return request<TrainingRun[]>(
    `/projects/${projectId}/training-runs?poll=${pollToken}`,
    {
      signal,
      cache: "no-store",
    },
  );
}

export async function getTrainingRun(
  runId: string,
  signal?: AbortSignal,
): Promise<TrainingRun> {
  return request<TrainingRun>(`/training-runs/${runId}`, { signal });
}

export async function cancelTrainingRun(runId: string): Promise<TrainingRun> {
  return request<TrainingRun>(`/training-runs/${runId}/cancel`, {
    method: "POST",
  });
}

export async function getExperiments(
  projectId: string,
  signal?: AbortSignal,
): Promise<ExperimentRecord[]> {
  return request<ExperimentRecord[]>(`/projects/${projectId}/experiments`, {
    signal,
  });
}

export async function compareExperiments(
  experimentIds: string[],
): Promise<ExperimentCompareResponse> {
  return request<ExperimentCompareResponse>("/experiments/compare", {
    method: "POST",
    body: JSON.stringify({ experiment_ids: experimentIds }),
  });
}

export async function validateUltralyticsTrainingConfiguration(payload: {
  task: string;
  mode: string;
  expected_ultralytics_version?: string;
  parameters?: Record<string, unknown>;
  search_space?: UltralyticsTrainingSearchSpaceField[];
}): Promise<UltralyticsTrainingValidationResponse> {
  return request<UltralyticsTrainingValidationResponse>(
    "/models/ultralytics/training-registry/validate",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export interface ProviderModelRegistration {
  id: string;
  provider_id: string;
  task: string;
  original_filename: string;
  sha256: string;
  registered_at: string;
  project_id: string;
}

export async function registerProviderModel(
  projectId: string,
  providerId: string,
  file: File,
): Promise<ProviderModelRegistration> {
  const formData = new FormData();
  formData.append("file", file, file.name);
  return request<ProviderModelRegistration>(
    `/projects/${encodeURIComponent(projectId)}/provider-models/${encodeURIComponent(providerId)}/register`,
    { method: "POST", body: formData },
  );
}

export async function registerModel(
  projectId: string,
  payload: {
    file: File;
    purpose: "detector" | "assist";
    providerName?: string;
    displayName?: string;
    notes?: string;
  },
): Promise<ModelRegistration> {
  const formData = new FormData();
  formData.append("file", payload.file, payload.file.name);
  formData.append("purpose", payload.purpose);
  if (payload.providerName) {
    formData.append("provider_name", payload.providerName);
  }
  if (payload.displayName) formData.append("display_name", payload.displayName);
  if (payload.notes) formData.append("notes", payload.notes);
  return request<ModelRegistration>(`/projects/${projectId}/models/register`, {
    method: "POST",
    body: formData,
  });
}

export async function registerModelFromRun(
  projectId: string,
  payload: {
    training_run_id: string;
    display_name?: string;
    notes?: string;
  },
): Promise<ModelRegistration> {
  return request<ModelRegistration>(
    `/projects/${projectId}/models/register-from-run`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteModel(modelId: string): Promise<void> {
  await request<void>(`/models/${modelId}`, { method: "DELETE" });
}

export async function createInferenceJob(
  projectId: string,
  payload: {
    model_id: string;
    image_ids: string[];
    confidence_threshold?: number;
    iou_threshold?: number;
    device: string;
  },
): Promise<JobRecord> {
  return request<JobRecord>(`/projects/${projectId}/inference-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  // Job state changes continuously while a download is active. A unique
  // query value plus fetch cache bypass prevents desktop webviews from
  // reusing the first queued/zero-byte response.
  const pollToken = Date.now();
  return request<JobRecord>(`/jobs/${jobId}?poll=${pollToken}`, {
    signal,
    cache: "no-store",
  });
}

export async function retryJob(jobId: string): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}/retry`, { method: "POST" });
}

export async function cancelJob(jobId: string): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function getQualityControlRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<QualityControlRunRecord[]> {
  return request<QualityControlRunRecord[]>(
    `/projects/${projectId}/quality-control-runs`,
    { signal },
  );
}

export async function getDatasetVersionQualityControlRuns(
  versionId: string,
  signal?: AbortSignal,
): Promise<QualityControlRunRecord[]> {
  return request<QualityControlRunRecord[]>(
    `/dataset-versions/${versionId}/quality-control-runs`,
    { signal },
  );
}

export async function createQualityControlRun(
  projectId: string,
  payload: {
    rule_categories: QualityControlRuleCategory[];
    selected_rule_ids?: string[];
    thresholds: QualityControlThresholdConfig;
    created_by?: string;
  },
): Promise<QualityControlRunRecord> {
  return request<QualityControlRunRecord>(
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
    rule_categories: QualityControlRuleCategory[];
    selected_rule_ids?: string[];
    thresholds: QualityControlThresholdConfig;
    created_by?: string;
  },
): Promise<QualityControlRunRecord> {
  return request<QualityControlRunRecord>(
    `/dataset-versions/${versionId}/quality-control-runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getQualityControlRun(
  runId: string,
  signal?: AbortSignal,
): Promise<QualityControlRunRecord> {
  return request<QualityControlRunRecord>(`/quality-control-runs/${runId}`, {
    signal,
  });
}

export async function cancelQualityControlRun(
  runId: string,
): Promise<QualityControlRunRecord> {
  return request<QualityControlRunRecord>(
    `/quality-control-runs/${runId}/cancel`,
    { method: "POST" },
  );
}

export async function getQualityControlIssues(
  runId: string,
  filters: {
    page?: number;
    pageSize?: number;
    severity?: string;
    ruleId?: string;
    classId?: string;
    imageId?: string;
    status?: string;
  },
  signal?: AbortSignal,
): Promise<QualityControlIssuePage> {
  const search = new URLSearchParams();
  search.set("page", String(filters.page ?? 1));
  search.set("page_size", String(filters.pageSize ?? 50));
  if (filters.severity) search.set("severity", filters.severity);
  if (filters.ruleId) search.set("rule_id", filters.ruleId);
  if (filters.classId) search.set("class_id", filters.classId);
  if (filters.imageId) search.set("image_id", filters.imageId);
  if (filters.status) search.set("status", filters.status);
  return request<QualityControlIssuePage>(
    `/quality-control-runs/${runId}/issues?${search}`,
    { signal },
  );
}

export async function compareQualityControlRuns(
  runId: string,
  otherRunId: string,
  signal?: AbortSignal,
): Promise<QualityControlRunComparison> {
  const search = new URLSearchParams({ other_run_id: otherRunId });
  return request<QualityControlRunComparison>(
    `/quality-control-runs/${runId}/compare?${search}`,
    { signal },
  );
}

export async function acknowledgeQualityControlIssue(
  issueId: string,
  actor?: string,
): Promise<QualityControlIssue> {
  return request<QualityControlIssue>(
    `/quality-control-issues/${issueId}/acknowledge`,
    {
      method: "POST",
      body: JSON.stringify({ actor }),
    },
  );
}

export async function dismissQualityControlIssue(
  issueId: string,
  reason: string,
  actor?: string,
): Promise<QualityControlIssue> {
  return request<QualityControlIssue>(
    `/quality-control-issues/${issueId}/dismiss`,
    {
      method: "POST",
      body: JSON.stringify({ reason, actor }),
    },
  );
}

export async function getReviewQueues(
  projectId: string,
  signal?: AbortSignal,
): Promise<ReviewQueueRecord[]> {
  return request<ReviewQueueRecord[]>(`/projects/${projectId}/review-queues`, {
    signal,
  });
}

export async function getDatasetVersionReviewQueues(
  versionId: string,
  signal?: AbortSignal,
): Promise<ReviewQueueRecord[]> {
  return request<ReviewQueueRecord[]>(
    `/dataset-versions/${versionId}/review-queues`,
    { signal },
  );
}

export async function createReviewQueue(
  projectId: string,
  payload: {
    source_quality_control_run_id?: string | null;
    signal_weights: ReviewScoreWeights;
    review_below_confidence?: number;
    created_by?: string;
  },
): Promise<ReviewQueueRecord> {
  return request<ReviewQueueRecord>(`/projects/${projectId}/review-queues`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createDatasetVersionReviewQueue(
  versionId: string,
  payload: {
    source_quality_control_run_id?: string | null;
    signal_weights: ReviewScoreWeights;
    review_below_confidence?: number;
    created_by?: string;
  },
): Promise<ReviewQueueRecord> {
  return request<ReviewQueueRecord>(
    `/dataset-versions/${versionId}/review-queues`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getReviewQueue(
  queueId: string,
  signal?: AbortSignal,
): Promise<ReviewQueueRecord> {
  return request<ReviewQueueRecord>(`/review-queues/${queueId}`, { signal });
}

export async function getReviewQueueItems(
  queueId: string,
  filters: {
    page?: number;
    pageSize?: number;
    labelClassId?: string;
    split?: string;
    qcSeverity?: string;
    reviewState?: string;
    modelId?: string;
  },
  signal?: AbortSignal,
): Promise<ReviewQueueItemPage> {
  const search = new URLSearchParams();
  search.set("page", String(filters.page ?? 1));
  search.set("page_size", String(filters.pageSize ?? 50));
  if (filters.labelClassId) search.set("label_class_id", filters.labelClassId);
  if (filters.split) search.set("split", filters.split);
  if (filters.qcSeverity) search.set("qc_severity", filters.qcSeverity);
  if (filters.reviewState) search.set("review_state", filters.reviewState);
  if (filters.modelId) search.set("model_id", filters.modelId);
  return request<ReviewQueueItemPage>(
    `/review-queues/${queueId}/items?${search}`,
    {
      signal,
    },
  );
}

export async function bulkTriageReviewQueueItems(
  queueId: string,
  payload: {
    item_ids: string[];
    action: ReviewQueueBulkAction;
    reason?: string;
    actor?: string;
    review_confirmed?: boolean;
    client_request_id?: string;
  },
): Promise<ReviewQueueBulkResponse> {
  return request<ReviewQueueBulkResponse>(
    `/review-queues/${queueId}/items/bulk`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function getReviewQueueEvents(
  queueId: string,
  itemId: string,
  page = 1,
  signal?: AbortSignal,
): Promise<ReviewQueueEventsPage> {
  return request<ReviewQueueEventsPage>(
    `/review-queues/${queueId}/items/${itemId}/events?page=${page}`,
    { signal },
  );
}

export async function addReviewQueueEvent(
  queueId: string,
  itemId: string,
  payload: ReviewQueueEventCreate,
): Promise<ReviewQueueEvent> {
  return request<ReviewQueueEvent>(
    `/review-queues/${queueId}/items/${itemId}/events`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function startReviewQueueItem(
  itemId: string,
  actor?: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/start`, {
    method: "POST",
    ...(actor ? { body: JSON.stringify({ actor }) } : {}),
  });
}

export async function completeReviewQueueItem(
  itemId: string,
  actor?: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/complete`, {
    method: "POST",
    ...(actor ? { body: JSON.stringify({ actor }) } : {}),
  });
}

export async function skipReviewQueueItem(
  itemId: string,
  reason: string,
  actor?: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason, ...(actor ? { actor } : {}) }),
  });
}

export async function returnReviewQueueItem(
  itemId: string,
  actor?: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/return`, {
    method: "POST",
    ...(actor ? { body: JSON.stringify({ actor }) } : {}),
  });
}

export async function regenerateReviewQueue(
  queueId: string,
): Promise<ReviewQueueRecord> {
  return request<ReviewQueueRecord>(`/review-queues/${queueId}/regenerate`, {
    method: "POST",
  });
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
  const search = new URLSearchParams();
  if (filters.modelId) search.set("model_id", filters.modelId);
  if (filters.labelClassId) search.set("label_class_id", filters.labelClassId);
  if (filters.minConfidence !== undefined) {
    search.set("min_confidence", String(filters.minConfidence));
  }
  if (filters.reviewStatus) search.set("review_status", filters.reviewStatus);
  const suffix = search.size ? `?${search}` : "";
  return request<PredictionListResponse>(
    `/images/${imageId}/prediction-proposals${suffix}`,
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
): Promise<{
  proposal: PredictionProposal;
  annotation: AnnotationRecord | null;
  mask_annotation?: AnnotationRecord | null;
}> {
  return request<{
    proposal: PredictionProposal;
    annotation: AnnotationRecord | null;
  }>(`/prediction-proposals/${proposalId}/accept`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function rejectPrediction(proposalId: string): Promise<{
  proposal: PredictionProposal;
  annotation: AnnotationRecord | null;
}> {
  return request<{
    proposal: PredictionProposal;
    annotation: AnnotationRecord | null;
  }>(`/prediction-proposals/${proposalId}/reject`, { method: "POST" });
}

export async function bulkReviewPredictions(payload: {
  label_class_id?: string;
  action: "accept" | "reject";
  proposal_ids: string[];
}): Promise<{
  reviewed_count: number;
  created_annotations: AnnotationRecord[];
}> {
  return request<{
    reviewed_count: number;
    created_annotations: AnnotationRecord[];
  }>("/prediction-proposals/bulk-review", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createAssistSession(
  imageId: string,
  payload: {
    model_id: string;
    device: string;
    source_prediction_id?: string;
  },
): Promise<AssistSession> {
  return request<AssistSession>(`/images/${imageId}/assist-sessions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function brushAssistSession(
  sessionId: string,
  payload: {
    mode: "add" | "subtract";
    brush_radius: number;
    strokes: Array<{ points: Array<{ x: number; y: number }> }>;
  },
): Promise<AssistSession> {
  return request<AssistSession>(`/assist-sessions/${sessionId}/brush`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function boxAssistSession(
  sessionId: string,
  payload: { x_min: number; y_min: number; x_max: number; y_max: number },
): Promise<AssistSession> {
  return request<AssistSession>(`/assist-sessions/${sessionId}/box`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function resetAssistSession(
  sessionId: string,
): Promise<AssistSession> {
  return request<AssistSession>(`/assist-sessions/${sessionId}/reset`, {
    method: "POST",
  });
}

export async function acceptAssistSession(
  sessionId: string,
  payload: { label_class_id: string },
): Promise<{ session_id: string; annotation: AnnotationRecord }> {
  return request<{ session_id: string; annotation: AnnotationRecord }>(
    `/assist-sessions/${sessionId}/accept`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteAssistSession(sessionId: string): Promise<void> {
  await request<void>(`/assist-sessions/${sessionId}`, { method: "DELETE" });
}
