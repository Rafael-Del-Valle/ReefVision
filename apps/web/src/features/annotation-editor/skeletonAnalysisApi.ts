import { getApiBaseUrl } from "../../runtime";

export interface SkeletonPixel {
  x: number;
  y: number;
}

export interface SkeletonReadiness {
  schema_version: "skeleton-readiness-0001";
  mask_annotation_id: string;
  image_id: string;
  mask_revision: number;
  geometry_kind: string;
  mask_status: string;
  connectivity: 8;
  total_foreground_pixels: number;
  component_count: number;
  single_component: boolean;
  ready_for_skeletonization: boolean;
  blocking_reason:
    "mask_not_verified" | "empty_mask" | "multiple_components" | null;
  resolution_actions: (
    "repair_gap" | "delete_artifact" | "classify_separate_object"
  )[];
  automatic_bridge_applied: false;
}

export interface SkeletonGraphNode {
  id: string;
  kind: "endpoint" | "junction" | "isolated" | "cycle_anchor";
  x: number;
  y: number;
  source_pixel_count: number;
  external_connection_count: number;
}

export interface SkeletonGraphEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  path_pixel_count: number;
  boundary_to_boundary_length_pixels: number;
  node_to_node_length_pixels: number;
  length_physical: number | null;
  is_cycle: boolean;
}

export interface SkeletonBranchAngle {
  junction_id: string;
  first_branch_id: string;
  second_branch_id: string;
  angle_degrees: number;
}

export interface SkeletonAnalysisResult {
  schema_version: "skeleton-analysis-0001";
  mask_annotation_id: string;
  image_id: string;
  mask_revision: number;
  algorithm: "zhang_suen";
  algorithm_version: "0001";
  connectivity: 8;
  automatic_bridge_applied: false;
  raw_skeleton_pixel_count: number;
  raw_skeleton_pixels: SkeletonPixel[];
  raw_skeleton_component_count: number;
  graph_nodes: SkeletonGraphNode[];
  graph_edges: SkeletonGraphEdge[];
  topology_preserved: boolean;
  endpoint_count: number;
  junction_pixel_count: number;
  junction_cluster_count: number;
  terminal_spur_max_length_pixels: number;
  spur_pruning_applied: boolean;
  removed_spur_count: number;
  pruned_skeleton_pixel_count: number;
  pruned_skeleton_pixels: SkeletonPixel[];
  pruned_graph_nodes: SkeletonGraphNode[];
  pruned_graph_edges: SkeletonGraphEdge[];
  raw_branch_count: number;
  pruned_branch_count: number;
  raw_total_linear_extension_pixels: number;
  pruned_total_linear_extension_pixels: number;
  raw_total_linear_extension_physical: number | null;
  pruned_total_linear_extension_physical: number | null;
  raw_longest_path_pixels: number;
  pruned_longest_path_pixels: number;
  raw_longest_path_physical: number | null;
  pruned_longest_path_physical: number | null;
  raw_branch_angles: SkeletonBranchAngle[];
  pruned_branch_angles: SkeletonBranchAngle[];
  calibrated: boolean;
  physical_unit: string | null;
  distance_per_pixel: number | null;
  calibration_source: string | null;
  calibration_confidence: number | null;
  perspective_corrected: boolean;
  length_calibration_method:
    "pixel_only" | "scalar_distance_per_pixel" | "reference_plane_homography";
  reference_plane_only: boolean | null;
  final_skeleton_source: "automatic_pruned" | "human_corrected";
  human_correction_applied: boolean;
  final_skeleton_pixels: SkeletonPixel[];
  final_graph_nodes: SkeletonGraphNode[];
  final_graph_edges: SkeletonGraphEdge[];
  final_branch_count: number;
  final_total_linear_extension_pixels: number;
  final_total_linear_extension_physical: number | null;
  final_longest_path_pixels: number;
  final_longest_path_physical: number | null;
  final_branch_angles: SkeletonBranchAngle[];
}

export interface SkeletonAnalysisRevision {
  id: string;
  analysis_series_id: string;
  analysis_revision: number;
  supersedes_analysis_id: string | null;
  mask_annotation_id: string;
  image_id: string;
  mask_revision: number;
  current_mask_revision: number;
  source_kind: "automatic" | "human_corrected";
  algorithm: string;
  algorithm_version: string;
  terminal_spur_max_length_pixels: number;
  input_mask_sha256: string;
  calibration_sha256: string | null;
  parameters_sha256: string;
  result_sha256: string;
  result: SkeletonAnalysisResult;
  correction: Record<string, unknown>;
  review_status: "unreviewed" | "approved" | "needs_correction" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_by: string;
  created_at: string;
  is_latest_revision: boolean;
  stale_mask: boolean;
  stale_calibration: boolean;
  stale: boolean;
}

export interface SkeletonExport {
  analysis_id: string;
  analysis_revision: number;
  package_name: string;
  archive_name: string;
  archive_size_bytes: number;
  archive_sha256: string;
  manifest_sha256: string;
  verification_status: "verified";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Skeleton analysis request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getSkeletonReadiness(
  maskId: string,
  signal?: AbortSignal,
): Promise<SkeletonReadiness> {
  return request<SkeletonReadiness>(
    `/mask-annotations/${encodeURIComponent(maskId)}/structure-readiness`,
    { signal, cache: "no-store" },
  );
}

export function listSkeletonAnalyses(
  maskId: string,
  signal?: AbortSignal,
): Promise<SkeletonAnalysisRevision[]> {
  return request<SkeletonAnalysisRevision[]>(
    `/mask-annotations/${encodeURIComponent(maskId)}/skeleton-analyses`,
    { signal, cache: "no-store" },
  );
}

export function createSkeletonAnalysis(
  maskId: string,
  terminalSpurMaxLengthPixels: number,
): Promise<SkeletonAnalysisRevision> {
  return request<SkeletonAnalysisRevision>(
    `/mask-annotations/${encodeURIComponent(maskId)}/skeleton-analyses`,
    {
      method: "POST",
      body: JSON.stringify({
        terminal_spur_max_length_pixels: terminalSpurMaxLengthPixels,
      }),
    },
  );
}

export function reviewSkeletonAnalysis(
  analysisId: string,
  reviewStatus: "approved" | "needs_correction" | "rejected",
  note: string | null,
): Promise<SkeletonAnalysisRevision> {
  return request<SkeletonAnalysisRevision>(
    `/skeleton-analyses/${encodeURIComponent(analysisId)}/review`,
    {
      method: "POST",
      body: JSON.stringify({
        review_status: reviewStatus,
        note,
      }),
    },
  );
}

export function correctSkeletonAnalysis(
  analysisId: string,
  payload: {
    add_pixels: SkeletonPixel[];
    remove_pixels: SkeletonPixel[];
    reason_code: string;
    note?: string | null;
  },
): Promise<SkeletonAnalysisRevision> {
  return request<SkeletonAnalysisRevision>(
    `/skeleton-analyses/${encodeURIComponent(analysisId)}/corrections`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function exportSkeletonAnalysis(
  analysisId: string,
): Promise<SkeletonExport> {
  return request<SkeletonExport>(
    `/skeleton-analyses/${encodeURIComponent(analysisId)}/export`,
    { method: "POST" },
  );
}

export function skeletonExportDownloadUrl(analysisId: string): string {
  return `${getApiBaseUrl()}/skeleton-analyses/${encodeURIComponent(analysisId)}/export/download`;
}
