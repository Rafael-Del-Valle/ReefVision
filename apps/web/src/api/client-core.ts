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
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  label_class_count: number;
  active_label_class_count: number;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  template: "blank" | "octocoral";
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

export type ModelPurpose =
  "detector" | "segmenter" | "semantic_segmenter" | "classifier" | "assist";

export interface ModelRegistration {
  id: string;
  project_id: string;
  purpose: ModelPurpose;
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
  "pretrained_catalog" | "my_trained_models" | "imported_custom_models";

export type ModelCatalogTask =
  | "detect"
  | "segment"
  | "semantic_segment"
  | "classify"
  | "open_vocabulary_detect"
  | "example_guided_detect"
  | "assist_segmentation"
  | "video_propagation"
  | "track"
  | "caption"
  | "phrase_grounding";

export type ModelCatalogInstallationState =
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
  | "builtin_architecture"
  | "managed_catalog_model"
  | "registered_model"
  | "planned_unavailable";

export type ModelCatalogWorkflow =
  "training" | "prompt_assist" | "smart_mask" | "video" | "model_hub";

export interface ModelCatalogEntry {
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
  pretrained: boolean;
  scratch_only: boolean;
  source_type: string;
  local_path: string | null;
  managed_path: string | null;
  catalog_revision: string;
  checksum: string | null;
  size_bytes: number | null;
  installation_state: ModelCatalogInstallationState;
  installation_reason: string | null;
  metadata_verified: boolean;
  provider_ready: boolean;
  provider_state: string;
  provider_failure_reason: string | null;
  capabilities: Record<string, boolean>;
  latest_acceptance_status: string | null;
  compatibility_reasons: string[];
  selection_kind: ModelCatalogSelectionKind;
  registration_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ModelCatalogProviderFilter {
  id: string;
  display_name: string;
}

export interface ModelCatalogArchitectureFilter {
  id: string;
  display_name: string;
}

export interface ModelCatalogFilters {
  providers: ModelCatalogProviderFilter[];
  architectures: ModelCatalogArchitectureFilter[];
}

export interface ModelCatalogPagination {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface ModelCatalogResponse {
  entries: ModelCatalogEntry[];
  pagination: ModelCatalogPagination;
  filters: ModelCatalogFilters;
}

export interface ModelCatalogQuery {
  page?: number;
  pageSize?: number;
  search?: string;
  category?: string;
  task?: string;
  provider?: string;
  architecture?: string;
  trainable?: boolean;
  inference?: boolean;
  videoCompatibility?: boolean;
  promptAssistCompatibility?: boolean;
  tilingCompatibility?: boolean;
  tuningCompatibility?: boolean;
  scratchOnly?: boolean;
  installationState?: string;
}

export interface ModelCatalogInstallResponse {
  catalog_id: string;
  entry: ModelCatalogEntry;
  job: JobRecord;
}

export interface ModelCatalogWorkflowEligibilityItem {
  catalog_id: string;
  workflow: ModelCatalogWorkflow;
  eligible: boolean;
  reasons: string[];
}

export interface ModelCatalogWorkflowEligibilityResponse {
  workflow: ModelCatalogWorkflow;
  items: ModelCatalogWorkflowEligibilityItem[];
}

export interface ModelCatalogInstallStatusResponse {
  entry: ModelCatalogEntry;
  job: JobRecord | null;
}

export interface ModelCatalogProviderSummary {
  provider_id: string;
  display_name: string;
  ready_count: number;
  blocked_count: number;
  unavailable_count: number;
  total_count: number;
}

export interface RuntimeProviderStatus {
  provider_id: string;
  display_name: string;
  installation_state: ModelCatalogInstallationState;
  available: boolean;
  reason: string | null;
  executable_path: string | null;
  package_version: string | null;
  checked_at: string;
}

export interface TrainingProviderCapability {
  capability_id: string;
  label: string;
  available: boolean;
  reason: string | null;
}

export interface TrainingProvider {
  provider_id: string;
  display_name: string;
  provider_version: string;
  installed: boolean;
  ready: boolean;
  trainable: boolean;
  capabilities: TrainingProviderCapability[];
  supported_tasks: string[];
  supported_devices: string[];
  dependency_state: string;
  dependency_message: string | null;
}

export interface TrainingDraftSummary {
  id: string;
  name: string;
  task: string;
  provider_id: string;
  updated_at: string;
}

export interface TrainingDraft {
  id: string;
  project_id: string;
  name: string;
  task: string;
  provider_id: string;
  configuration_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TrainingWorkspaceProviderStatus {
  provider_id: string;
  display_name: string;
  installation_state: string;
  available: boolean;
  reason: string | null;
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
  revision: number;
  generation_key: string | null;
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
  revision: number;
  generation_key: string | null;
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
  promoted_dataset_version_id: string | null;
  promoted_cycle_id: string | null;
  promoted_at: string | null;
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
  selection_reasons_json: string[];
  manual_state: string;
  fragment_key: string | null;
  near_duplicate_key: string | null;
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

export interface DatasetVersionItem {
  id: string;
  dataset_version_id: string;
  image_id: string;
  image_sha256: string;
  original_filename: string;
  width_px: number;
  height_px: number;
  image_annotation_status: AnnotationStatus;
  split: DatasetSplit;
  group_key: string | null;
  annotation_snapshot_json: Array<Record<string, unknown>>;
  per_class_counts_json: Record<string, number>;
  annotation_count: number;
  snapshot_sha256: string;
  created_at: string;
}

export type DatasetExportFormat =
  | "yolo_detection"
  | "yolo_segmentation"
  | "semantic_masks"
  | "classification_multiclass"
  | "classification_binary_state";

export interface ExportRecord {
  id: string;
  project_id: string;
  dataset_version_id: string;
  job_id: string | null;
  format: DatasetExportFormat;
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

export interface TrainingRunSummary {
  id: string;
  project_id: string;
  dataset_version_id: string | null;
  job_id: string | null;
  run_name: string;
  task: string;
  provider_id: string;
  architecture: string | null;
  status: string;
  stage: string;
  progress_current_epoch: number;
  progress_total_epochs: number;
  best_fitness: number | null;
  metrics_json: Record<string, number>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface TrainingRunDetail extends TrainingRunSummary {
  initial_checkpoint_source: string;
  initial_checkpoint_model_id: string | null;
  initial_checkpoint_catalog_id: string | null;
  resolved_model_asset_id: string | null;
  resolved_model_checksum: string | null;
  device: string;
  precision: string;
  notes: string | null;
  random_seed: number | null;
  tiling_config_json: Record<string, unknown>;
  training_config_json: Record<string, unknown>;
  tuning_config_json: Record<string, unknown>;
  evaluation_config_json: Record<string, unknown>;
  resource_limits_json: Record<string, unknown>;
  preflight_report_json: Record<string, unknown>;
  draft_snapshot_json: Record<string, unknown>;
  warnings_json: string[];
  error_message: string | null;
  metrics_history_json: Array<Record<string, number>>;
  artifact_manifest_json: Record<string, unknown>;
  result_checkpoint_path: string | null;
  logs_path: string | null;
  dataset_manifest_sha256: string | null;
  split_manifest_sha256: string | null;
}

export interface TrainingDraftSummary {
  id: string;
  project_id: string;
  name: string;
  task: string;
  provider_id: string;
  configuration_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TrainingDraft {
  id: string;
  project_id: string;
  name: string;
  task: string;
  provider_id: string;
  configuration_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TrainingDatasetPreflight {
  project_id: string;
  dataset_version_id: string;
  dataset_version_number: number;
  dataset_version_name: string;
  dataset_version_status: string;
  dataset_manifest_sha256: string;
  split_manifest_sha256: string;
  image_count: number;
  annotation_count: number;
  box_annotation_count: number;
  polygon_mask_annotation_count: number;
  raster_mask_annotation_count: number;
  image_counts_by_split: Record<string, number>;
  annotation_counts_by_split: Record<string, number>;
  box_annotation_counts_by_split: Record<string, number>;
  polygon_mask_annotation_counts_by_split: Record<string, number>;
  raster_mask_annotation_counts_by_split: Record<string, number>;
  class_counts: Array<{
    label_class_id: string;
    class_index: number;
    class_name: string;
    annotation_count: number;
  }>;
  warnings: string[];
  blockers: string[];
}

export interface TrainingDraftResponse {
  draft: TrainingDraft;
  preflight: TrainingDatasetPreflight | null;
}

export interface TrainingRunCreatePayload {
  draft_id?: string;
  dataset_version_id: string;
  task: string;
  provider_id: string;
  run_name: string;
  architecture?: string | null;
  initial_checkpoint_source: string;
  initial_checkpoint_model_id?: string | null;
  initial_checkpoint_catalog_id?: string | null;
  resolved_model_asset_id?: string | null;
  resolved_model_checksum?: string | null;
  device: string;
  precision: string;
  random_seed?: number | null;
  tiling_config: Record<string, unknown>;
  training_config: Record<string, unknown>;
  tuning_config: Record<string, unknown>;
  evaluation_config: Record<string, unknown>;
  resource_limits: Record<string, unknown>;
  notes?: string | null;
}

export interface TrainingProviderCapabilityResponse {
  task: string;
  provider_id: string;
  ready: boolean;
  trainable: boolean;
  supported_devices: string[];
  capabilities: string[];
  blocker: string | null;
  warnings: string[];
}

export interface TrainingProviderResponse {
  provider_id: string;
  display_name: string;
  provider_version: string;
  installed: boolean;
  ready: boolean;
  trainable: boolean;
  capabilities: string[];
  supported_tasks: string[];
  supported_devices: string[];
  blocker: string | null;
  warnings: string[];
}

export interface TrainingEnvironmentPreflight {
  device: string;
  device_available: boolean;
  requested_precision: string;
  precision_supported: boolean;
  estimated_vram_mb: number | null;
  available_vram_mb: number | null;
  estimated_ram_mb: number | null;
  available_ram_mb: number | null;
  provider_ready: boolean;
  warnings: string[];
  blockers: string[];
}

export interface TrainingParameterMetadata {
  name: string;
  label: string;
  description: string;
  value_type: string;
  default_value: unknown;
  minimum: number | null;
  maximum: number | null;
  options: unknown[];
  required: boolean;
  advanced: boolean;
  task_scope: string[];
  provider_scope: string[];
}

export interface TrainingParameterRegistry {
  schema_version: string;
  parameters: TrainingParameterMetadata[];
}

export interface TrainingParameterValidation {
  valid: boolean;
  normalized_parameters: Record<string, unknown>;
  warnings: string[];
  blockers: string[];
}

export interface TrainingSearchSpaceValidation {
  valid: boolean;
  normalized_search_space: Record<string, unknown>;
  warnings: string[];
  blockers: string[];
}

export interface TrainingDeviceOption {
  id: string;
  label: string;
  available: boolean;
  reason: string | null;
  memory_total_mb: number | null;
  memory_free_mb: number | null;
}

export interface TrainingDevicesResponse {
  devices: TrainingDeviceOption[];
}

export interface ExperimentRecord {
  id: string;
  project_id: string;
  training_run_id: string;
  dataset_version_id: string | null;
  task: string;
  provider_id: string;
  architecture: string | null;
  summary_metrics_json: Record<string, number>;
  comparison_warnings_json: string[];
  artifact_manifest_json: Record<string, unknown>;
  package_versions_json: Record<string, string>;
  created_at: string;
}

export interface TrainingExperimentComparison {
  base_experiment_id: string;
  compare_experiment_id: string;
  metric_deltas: Record<string, number>;
  compatibility_warnings: string[];
}

export interface UltralyticsTrainingRegistryEntry {
  name: string;
  display_name: string;
  source: string;
  scratch: boolean;
  task: string;
}

export interface UltralyticsTrainingRegistrySummarySnapshot {
  ultralytics_version: string | null;
  entries: UltralyticsTrainingRegistryEntry[];
  detector_names: string[];
  segmenter_names: string[];
  classifier_names: string[];
  warnings: string[];
}

export interface TrainingWorkspaceStatusResponse {
  parameter_registry: TrainingParameterRegistry;
  providers: TrainingProviderResponse[];
  devices: TrainingDevicesResponse;
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

export interface PredictionProposal {
  id: string;
  image_id: string;
  label_class_id: string | null;
  model_id: string;
  inference_job_id: string | null;
  confidence: number;
  review_status: string;
  geometry_kind: string;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  polygon_json: Array<{ x: number; y: number }>;
  raster_mask_path: string | null;
  raster_mask_sha256: string | null;
  raster_width_px: number | null;
  raster_height_px: number | null;
  raster_area_pixels: number | null;
  raster_pixel_value: number | null;
  predicted_class_name: string | null;
  predicted_class_index: number | null;
  class_mapping_status: string;
  source_geometry_json: Record<string, unknown>;
  accepted_geometry_json: Record<string, unknown>;
  accepted_annotation_id: string | null;
  accepted_mask_annotation_id: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface PredictionListResponse {
  proposals: PredictionProposal[];
  total: number;
}

export interface AssistSession {
  id: string;
  image_id: string;
  model_id: string;
  device: string;
  status: string;
  source_prediction_id: string | null;
  mask_path: string;
  mask_sha256: string;
  width_px: number;
  height_px: number;
  area_pixels: number;
  created_at: string;
  updated_at: string;
}

export interface AnnotationAssistCatalogEntry {
  catalog_id: string;
  display_name: string;
  display_summary: string;
  provider_id: string;
  architecture: string;
  variant: string;
  task: string;
  availability: string;
  installation_state: string;
  compatibility_reasons: string[];
  local_path: string | null;
  managed_path: string | null;
}

export interface AnnotationAssistCatalogResponse {
  entries: AnnotationAssistCatalogEntry[];
}

export interface ProviderDependencyStatus {
  provider_id: string;
  package_name: string;
  installed: boolean;
  version: string | null;
  reason: string | null;
}

export interface ProviderDependencyPreflightResponse {
  ready: boolean;
  dependencies: ProviderDependencyStatus[];
  warnings: string[];
  blockers: string[];
}

export interface ModelInstallationStatus {
  job_id: string;
  catalog_id: string;
  state: string;
  progress_current: number;
  progress_total: number;
  error_message: string | null;
  result_json: Record<string, unknown> | null;
}

export interface SemanticTrainingRequest {
  dataset_version_id: string;
  provider_id: string;
  run_name: string;
  device: string;
  precision: string;
  notes?: string | null;
}

export interface SemanticTrainingResponse {
  run: TrainingRunDetail;
  job: JobRecord;
}

export interface SemanticModelRegistrationRequest {
  training_run_id: string;
  display_name?: string | null;
  notes?: string | null;
}

export interface SemanticPredictionRequest {
  model_id: string;
  device: string;
}

export interface SemanticPredictionResponse {
  job: JobRecord;
}

export interface SystemProviderDependencySummary {
  provider_id: string;
  display_name: string;
  installation_state: string;
  available: boolean;
  reason: string | null;
  package_version: string | null;
}

export interface SystemRuntimeSummary {
  python_version: string;
  platform: string;
  cpu_count: number | null;
  total_memory_bytes: number | null;
  cuda_available: boolean;
  cuda_device_count: number;
}

export interface SystemModelCatalogSummary {
  total_models: number;
  ready_models: number;
  blocked_models: number;
  unavailable_models: number;
  update_available_models: number;
}

export interface SystemProjectSummary {
  project_count: number;
  image_count: number;
  annotation_count: number;
  model_count: number;
  dataset_version_count: number;
  training_run_count: number;
}

export interface SystemCompatibilitySummary {
  schema_status: string;
  compatible_for_read_write: boolean;
  pending_revisions: string[];
  warnings: string[];
  blockers: string[];
}

export interface SystemOverviewResponse {
  version: SystemVersionResponse;
  runtime: SystemRuntimeSummary;
  providers: SystemProviderDependencySummary[];
  model_catalog: SystemModelCatalogSummary;
  projects: SystemProjectSummary;
  compatibility: SystemCompatibilitySummary;
}

export interface ImageImportSource {
  filename: string;
  relative_path?: string | null;
  local_path?: string | null;
  sha256?: string | null;
  file_size_bytes?: number | null;
}

export interface ImageImportRequest {
  sources: ImageImportSource[];
}

export interface ImportItem {
  source: string;
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
  return `${getApiBaseUrl()}/images/${imageId}/thumbnail`;
}

export function imageContentUrl(imageId: string): string {
  return `${getApiBaseUrl()}/images/${imageId}/content`;
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

export async function getLabelClassUsage(
  classId: string,
  signal?: AbortSignal,
): Promise<LabelClassUsage> {
  return request<LabelClassUsage>(`/classes/${classId}/usage`, { signal });
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

export async function mergeLabelClass(
  sourceClassId: string,
  targetClassId: string,
): Promise<LabelClassMergeResponse> {
  return request<LabelClassMergeResponse>(`/classes/${sourceClassId}/merge`, {
    method: "POST",
    body: JSON.stringify({ target_class_id: targetClassId }),
  });
}

export async function previewClassReassignment(
  sourceClassId: string,
  payload: {
    target_class_id?: string | null;
    operation_type: ClassOperationType;
    requested_by_identity?: string;
    notes?: string | null;
  },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
    `/classes/${sourceClassId}/reassign/preview`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function executeClassReassignment(
  sourceClassId: string,
  payload: {
    target_class_id?: string | null;
    operation_type: ClassOperationType;
    preview_checksum: string;
    requested_by_identity?: string;
    notes?: string | null;
  },
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(`/classes/${sourceClassId}/reassign`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function rollbackClassOperation(
  operationId: string,
): Promise<ClassOperationRecord> {
  return request<ClassOperationRecord>(
    `/class-operations/${operationId}/rollback`,
    {
      method: "POST",
    },
  );
}

export async function deleteLabelClass(classId: string): Promise<void> {
  await request<void>(`/classes/${classId}`, { method: "DELETE" });
}

export async function getClassVisibility(
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

export async function updateUserClassVisibility(
  projectId: string,
  layerType: ClassVisibilityLayerType,
  payload: ClassVisibilityUpdatePayload,
): Promise<ClassVisibilityBundle> {
  return request<ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility/user/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function clearUserClassVisibility(
  projectId: string,
  layerType: ClassVisibilityLayerType,
): Promise<ClassVisibilityBundle> {
  return request<ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility/user/${layerType}`,
    { method: "DELETE" },
  );
}

export async function updateProjectDefaultClassVisibility(
  projectId: string,
  layerType: ClassVisibilityLayerType,
  payload: ClassVisibilityUpdatePayload,
): Promise<ClassVisibilityBundle> {
  return request<ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility/project-default/${layerType}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function clearProjectDefaultClassVisibility(
  projectId: string,
  layerType: ClassVisibilityLayerType,
): Promise<ClassVisibilityBundle> {
  return request<ClassVisibilityBundle>(
    `/projects/${projectId}/class-visibility/project-default/${layerType}`,
    { method: "DELETE" },
  );
}

export async function getImages(
  projectId: string,
  filters: ImageFilters,
  signal?: AbortSignal,
): Promise<{
  items: ProjectImageListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}> {
  const search = new URLSearchParams();
  search.set("page", String(filters.page ?? 1));
  search.set("page_size", String(filters.pageSize ?? 25));
  if (filters.filename) search.set("filename", filters.filename);
  if (filters.annotationStatus)
    search.set("annotation_status", filters.annotationStatus);
  if (filters.groupKey) search.set("group_key", filters.groupKey);
  return request(`/projects/${projectId}/images?${search}`, { signal });
}

export async function getAnnotationSession(
  imageId: string,
  signal?: AbortSignal,
): Promise<AnnotationSession> {
  return request<AnnotationSession>(`/images/${imageId}/annotation-session`, {
    signal,
  });
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

export async function importImages(
  projectId: string,
  files: File[],
): Promise<ImageImportReport> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  return request<ImageImportReport>(`/projects/${projectId}/imports/images`, {
    method: "POST",
    body: formData,
  });
}

export async function importImagesFromPaths(
  projectId: string,
  sources: ImageImportSource[],
): Promise<ImageImportReport> {
  return request<ImageImportReport>(
    `/projects/${projectId}/imports/image-paths`,
    {
      method: "POST",
      body: JSON.stringify({ sources }),
    },
  );
}

export async function getProjectJobs(
  projectId: string,
  signal?: AbortSignal,
): Promise<JobRecord[]> {
  return request<JobRecord[]>(`/projects/${projectId}/jobs`, { signal });
}

export async function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}?poll=${Date.now()}`, {
    signal,
    cache: "no-store",
  });
}

export async function cancelJob(jobId: string): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function getModels(
  projectId: string,
  signal?: AbortSignal,
): Promise<ModelRegistration[]> {
  return request<ModelRegistration[]>(`/projects/${projectId}/models`, {
    signal,
  });
}

export async function registerModel(
  projectId: string,
  formData: FormData,
): Promise<ModelRegistration> {
  return request<ModelRegistration>(`/projects/${projectId}/models`, {
    method: "POST",
    body: formData,
  });
}

export async function registerModelFromRun(
  projectId: string,
  payload: {
    training_run_id: string;
    display_name?: string | null;
    notes?: string | null;
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
  imageId: string,
  payload: { model_id: string; confidence_threshold: number; device: string },
): Promise<JobRecord> {
  return request<JobRecord>(`/images/${imageId}/inference-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createSegmentationInferenceJob(
  imageId: string,
  payload: { model_id: string; confidence_threshold: number; device: string },
): Promise<JobRecord> {
  return request<JobRecord>(`/images/${imageId}/segmentation-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createSemanticSegmentationInferenceJob(
  imageId: string,
  payload: { model_id: string; device: string },
): Promise<JobRecord> {
  return request<JobRecord>(`/images/${imageId}/semantic-segmentation-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getModelCatalog(
  query: ModelCatalogQuery,
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  const search = new URLSearchParams();
  search.set("page", String(query.page ?? 1));
  search.set("page_size", String(query.pageSize ?? 50));
  if (query.search) search.set("search", query.search);
  if (query.category) search.set("category", query.category);
  if (query.task) search.set("task", query.task);
  if (query.provider) search.set("provider", query.provider);
  if (query.architecture) search.set("architecture", query.architecture);
  if (query.trainable !== undefined)
    search.set("trainable", String(query.trainable));
  if (query.inference !== undefined)
    search.set("inference", String(query.inference));
  if (query.videoCompatibility !== undefined)
    search.set("video_compatibility", String(query.videoCompatibility));
  if (query.promptAssistCompatibility !== undefined)
    search.set(
      "prompt_assist_compatibility",
      String(query.promptAssistCompatibility),
    );
  if (query.tilingCompatibility !== undefined)
    search.set("tiling_compatibility", String(query.tilingCompatibility));
  if (query.tuningCompatibility !== undefined)
    search.set("tuning_compatibility", String(query.tuningCompatibility));
  if (query.scratchOnly !== undefined)
    search.set("scratch_only", String(query.scratchOnly));
  if (query.installationState)
    search.set("installation_state", query.installationState);
  return request<ModelCatalogResponse>(`/model-catalog?${search}`, { signal });
}

export async function installModelCatalogEntry(
  catalogId: string,
): Promise<ModelCatalogInstallResponse> {
  return request<ModelCatalogInstallResponse>(
    `/model-catalog/${catalogId}/install`,
    {
      method: "POST",
    },
  );
}

export async function removeModelCatalogEntry(
  catalogId: string,
): Promise<void> {
  await request<void>(`/model-catalog/${catalogId}`, { method: "DELETE" });
}

export async function getModelCatalogInstallStatus(
  catalogId: string,
  signal?: AbortSignal,
): Promise<ModelCatalogInstallStatusResponse> {
  return request<ModelCatalogInstallStatusResponse>(
    `/model-catalog/${catalogId}/install-status`,
    { signal },
  );
}

export async function getModelCatalogWorkflowEligibility(
  workflow: ModelCatalogWorkflow,
  signal?: AbortSignal,
): Promise<ModelCatalogWorkflowEligibilityResponse> {
  return request<ModelCatalogWorkflowEligibilityResponse>(
    `/model-catalog/workflows/${workflow}/eligibility`,
    { signal },
  );
}

export async function getModelCatalogProviderSummary(
  signal?: AbortSignal,
): Promise<ModelCatalogProviderSummary[]> {
  return request<ModelCatalogProviderSummary[]>(
    "/model-catalog/provider-summary",
    {
      signal,
    },
  );
}

export async function getProviderRuntimeStatus(
  signal?: AbortSignal,
): Promise<RuntimeProviderStatus[]> {
  return request<RuntimeProviderStatus[]>(
    "/model-catalog/provider-runtime-status",
    {
      signal,
    },
  );
}

export async function getTrainingProviders(
  signal?: AbortSignal,
): Promise<TrainingProvider[]> {
  return request<TrainingProvider[]>("/training/providers", { signal });
}

export async function getTrainingWorkspaceStatus(
  signal?: AbortSignal,
): Promise<TrainingWorkspaceStatusResponse> {
  return request<TrainingWorkspaceStatusResponse>(
    "/training/workspace-status",
    {
      signal,
    },
  );
}

export async function getTrainingWorkspaceBootstrap(
  projectId: string,
  selectedDraftId?: string,
  signal?: AbortSignal,
): Promise<TrainingWorkspaceBootstrapResponse> {
  const search = new URLSearchParams();
  if (selectedDraftId) search.set("selected_draft_id", selectedDraftId);
  const suffix = search.size ? `?${search}` : "";
  return request<TrainingWorkspaceBootstrapResponse>(
    `/projects/${projectId}/training-workspace-bootstrap${suffix}`,
    { signal },
  );
}

export async function getTrainingDevices(
  signal?: AbortSignal,
): Promise<TrainingDevicesResponse> {
  return request<TrainingDevicesResponse>("/training/devices", { signal });
}

export async function getTrainingParameterRegistry(
  signal?: AbortSignal,
): Promise<TrainingParameterRegistry> {
  return request<TrainingParameterRegistry>("/training/parameters", { signal });
}

export async function validateTrainingParameters(payload: {
  task: string;
  provider_id: string;
  parameters: Record<string, unknown>;
}): Promise<TrainingParameterValidation> {
  return request<TrainingParameterValidation>("/training/parameters/validate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function validateTrainingSearchSpace(payload: {
  task: string;
  provider_id: string;
  search_space: Record<string, unknown>;
}): Promise<TrainingSearchSpaceValidation> {
  return request<TrainingSearchSpaceValidation>(
    "/training/search-space/validate",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function validateUltralyticsTraining(payload: {
  mode: string;
  parameters: Record<string, unknown>;
  search_space: Array<Record<string, unknown>>;
}): Promise<UltralyticsTrainingValidationResponse> {
  return request<UltralyticsTrainingValidationResponse>(
    "/training/ultralytics/validate",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function preflightTrainingDataset(
  projectId: string,
  versionId: string,
  task: string = "detect",
  signal?: AbortSignal,
): Promise<TrainingDatasetPreflight> {
  const search = new URLSearchParams({
    dataset_version_id: versionId,
    task,
  });
  return request<TrainingDatasetPreflight>(
    `/projects/${projectId}/training/preflight?${search}`,
    { signal },
  );
}

export async function preflightTrainingEnvironment(payload: {
  provider_id: string;
  task: string;
  device: string;
  precision: string;
  parameters: Record<string, unknown>;
}): Promise<TrainingEnvironmentPreflight> {
  return request<TrainingEnvironmentPreflight>(
    "/training/environment-preflight",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getTrainingDrafts(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingDraftSummary[]> {
  return request<TrainingDraftSummary[]>(
    `/projects/${projectId}/training-drafts`,
    {
      signal,
    },
  );
}

export async function getTrainingDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/training-drafts/${draftId}`, { signal });
}

export async function saveTrainingDraft(
  projectId: string,
  payload: {
    name: string;
    task: string;
    provider_id: string;
    configuration_json: Record<string, unknown>;
  },
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/projects/${projectId}/training-drafts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateTrainingDraft(
  draftId: string,
  payload: Partial<{
    name: string;
    task: string;
    provider_id: string;
    configuration_json: Record<string, unknown>;
  }>,
): Promise<TrainingDraft> {
  return request<TrainingDraft>(`/training-drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteTrainingDraft(draftId: string): Promise<void> {
  await request<void>(`/training-drafts/${draftId}`, { method: "DELETE" });
}

export async function createTrainingRun(
  projectId: string,
  payload: TrainingRunCreatePayload,
): Promise<TrainingRunDetail> {
  return request<TrainingRunDetail>(`/projects/${projectId}/training-runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getTrainingRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<TrainingRunSummary[]> {
  return request<TrainingRunSummary[]>(`/projects/${projectId}/training-runs`, {
    signal,
  });
}

export async function getTrainingRun(
  runId: string,
  signal?: AbortSignal,
): Promise<TrainingRunDetail> {
  return request<TrainingRunDetail>(`/training-runs/${runId}`, { signal });
}

export async function cancelTrainingRun(
  runId: string,
): Promise<TrainingRunDetail> {
  return request<TrainingRunDetail>(`/training-runs/${runId}/cancel`, {
    method: "POST",
  });
}

export async function getTrainingRunLogs(
  runId: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(
    `${getApiBaseUrl()}/training-runs/${runId}/logs`,
    {
      signal,
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(`Unable to load logs (HTTP ${response.status})`);
  }
  return response.text();
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
  baseExperimentId: string,
  compareExperimentId: string,
): Promise<TrainingExperimentComparison> {
  const search = new URLSearchParams({
    compare_experiment_id: compareExperimentId,
  });
  return request<TrainingExperimentComparison>(
    `/experiments/${baseExperimentId}/compare?${search}`,
  );
}

export async function getDatasetVersions(
  projectId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionRecord[]> {
  return request<DatasetVersionRecord[]>(
    `/projects/${projectId}/dataset-versions`,
    {
      signal,
    },
  );
}

export async function previewDatasetVersion(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<DatasetVersionPreview> {
  return request<DatasetVersionPreview>(
    `/projects/${projectId}/dataset-versions/preview`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function createDatasetVersion(
  projectId: string,
  payload: Record<string, unknown>,
): Promise<DatasetVersionRecord> {
  return request<DatasetVersionRecord>(
    `/projects/${projectId}/dataset-versions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getDatasetVersionItems(
  versionId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionItem[]> {
  return request<DatasetVersionItem[]>(`/dataset-versions/${versionId}/items`, {
    signal,
  });
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

export async function compareDatasetVersions(
  versionId: string,
  otherVersionId: string,
  signal?: AbortSignal,
): Promise<DatasetVersionComparison> {
  const search = new URLSearchParams({ other_version_id: otherVersionId });
  return request<DatasetVersionComparison>(
    `/dataset-versions/${versionId}/compare?${search}`,
    { signal },
  );
}

export async function createDatasetExport(
  versionId: string,
  format: DatasetExportFormat,
): Promise<DatasetExportCreateResponse> {
  return request<DatasetExportCreateResponse>(
    `/dataset-versions/${versionId}/exports`,
    {
      method: "POST",
      body: JSON.stringify({ format }),
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

export async function getExport(
  exportId: string,
  signal?: AbortSignal,
): Promise<ExportRecord> {
  return request<ExportRecord>(`/exports/${exportId}`, { signal });
}

export function exportDownloadUrl(exportId: string): string {
  return `${getApiBaseUrl()}/exports/${exportId}/download`;
}

export function exportManifestUrl(exportId: string): string {
  return `${getApiBaseUrl()}/exports/${exportId}/manifest`;
}

export async function startQualityControlRun(
  projectId: string,
  payload: {
    dataset_version_id?: string | null;
    rule_categories: QualityControlRuleCategory[];
    selected_rule_ids: string[];
    thresholds: QualityControlThresholdConfig;
    created_by?: string;
  },
): Promise<{ run: QualityControlRunRecord; job: JobRecord }> {
  return request<{ run: QualityControlRunRecord; job: JobRecord }>(
    `/projects/${projectId}/quality-control-runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getQualityControlRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<QualityControlRunRecord[]> {
  return request<QualityControlRunRecord[]>(
    `/projects/${projectId}/quality-control-runs`,
    {
      signal,
    },
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
    queue_kind?: "priority" | "active_learning";
    max_items?: number;
    min_priority_score?: number;
    diversity_weight?: number;
    max_items_per_group?: number | null;
    include_reviewed?: boolean;
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
    queue_kind?: "priority" | "active_learning";
    max_items?: number;
    min_priority_score?: number;
    diversity_weight?: number;
    max_items_per_group?: number | null;
    include_reviewed?: boolean;
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

export async function startReviewQueueItem(
  itemId: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/start`, {
    method: "POST",
  });
}

export async function completeReviewQueueItem(
  itemId: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/complete`, {
    method: "POST",
  });
}

export async function skipReviewQueueItem(
  itemId: string,
  reason: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function returnReviewQueueItem(
  itemId: string,
): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/review-queue-items/${itemId}/return`, {
    method: "POST",
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
  },
): Promise<{
  proposal: PredictionProposal;
  annotation: AnnotationRecord | null;
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
