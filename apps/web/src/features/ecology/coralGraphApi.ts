import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import type {
  SkeletonGraphNode,
  SkeletonPixel,
} from "../annotation-editor/skeletonAnalysisApi";

export type GraphEditKind = "add" | "split" | "merge" | "remove" | "correct";
export type GapDisposition =
  "observed_attachment" | "occluded" | "unknown" | "separate_colony";
export interface GraphReview {
  identity_revision_id: string;
  analysis_id: string;
  base_revision_id?: string;
  decision: "accepted" | "rejected";
  observed_at: string;
  reviewer: string;
  reason: string;
  edit?: {
    kind: GraphEditKind;
    branch_ids: string[];
    points: SkeletonPixel[];
    snap_tolerance_px: number;
  };
  gaps?: {
    disposition: GapDisposition;
    points: SkeletonPixel[];
    reason: string;
  }[];
}

interface Branch {
  id: string;
  source_node_id: string;
  target_node_id: string;
  pixels: SkeletonPixel[];
  node_to_node_length_pixels: number;
  length_physical: number | null;
}
export interface GraphRecord {
  id: string;
  graph_id: string;
  revision: number;
  analysis_id: string;
  identity_revision_id: string;
  decision: GraphReview["decision"];
  reviewer: string;
  reason: string;
  current: boolean;
  stale_reasons: string[];
  snapshot: {
    organism_key: string;
    image_id: string;
    observed_at: string;
    nodes: Pick<SkeletonGraphNode, "id" | "x" | "y" | "kind">[];
    edges: Branch[];
    total_pixels: number;
    total_physical: number | null;
    calibration: { unit: string } | null;
    qc: string[];
    eligible_for_growth: boolean;
    supersession: {
      previous_branch_ids: string[];
      successor_branch_ids: string[];
    }[];
  };
}
export type MatchKind =
  "matched" | "ambiguous" | "missing" | "occluded" | "split" | "merge";
export interface Match {
  status: MatchKind;
  earlier_branch_ids: string[];
  later_branch_ids: string[];
  reason: string;
}
export interface CorrespondenceRecord {
  id: string;
  revision: number;
  earlier_graph_revision_id: string;
  later_graph_revision_id: string;
  reviewer: string;
  reason: string;
  stale_reasons: string[];
  snapshot: { matches: Match[] };
}
export interface CorrespondenceReview {
  earlier_graph_revision_id: string;
  later_graph_revision_id: string;
  base_revision_id?: string;
  matches: Match[];
  reviewer: string;
  reason: string;
}
interface Change {
  earlier_length: number;
  later_length: number;
  absolute_change: number;
  change_per_day: number;
}
export interface GrowthRecord {
  id: string;
  correspondence_revision_id: string;
  stale_reasons: string[];
  snapshot: {
    earlier_observed_at: string;
    later_observed_at: string;
    elapsed_days: number;
    organism_key: string;
    unit: string;
    total: Change | null;
    branches: (Match & { change: Change | null })[];
    limitations: string[];
  };
}

export function coralPath(projectId: string, tail: string) {
  return `/projects/${encodeURIComponent(projectId)}/ecology/${tail}`;
}
export function coralDownload(projectId: string, tail: string) {
  return getApiBaseUrl() + coralPath(projectId, tail);
}
export function listCoralGraphs(
  projectId: string,
  signal?: AbortSignal,
  maskId?: string,
) {
  return request<GraphRecord[]>(
    coralPath(
      projectId,
      "coral-graphs?limit=200" +
        (maskId ? "&mask_id=" + encodeURIComponent(maskId) : ""),
    ),
    { signal },
  );
}
export function reviewCoralGraph(projectId: string, review: GraphReview) {
  return request<GraphRecord>(coralPath(projectId, "coral-graphs"), {
    method: "POST",
    body: JSON.stringify(review),
  });
}
export function listCoralCorrespondence(
  projectId: string,
  signal?: AbortSignal,
) {
  return request<CorrespondenceRecord[]>(
    coralPath(projectId, "coral-correspondences"),
    { signal },
  );
}
export function reviewCoralCorrespondence(
  projectId: string,
  review: CorrespondenceReview,
) {
  return request<CorrespondenceRecord>(
    coralPath(projectId, "coral-correspondences"),
    { method: "POST", body: JSON.stringify(review) },
  );
}
export function listCoralGrowth(projectId: string, signal?: AbortSignal) {
  return request<GrowthRecord[]>(coralPath(projectId, "coral-growth"), {
    signal,
  });
}
export function saveCoralGrowth(projectId: string, correspondenceId: string) {
  return request<GrowthRecord>(coralPath(projectId, "coral-growth"), {
    method: "POST",
    body: JSON.stringify({ correspondence_revision_id: correspondenceId }),
  });
}
