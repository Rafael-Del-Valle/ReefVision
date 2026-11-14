import { request } from "../../api/client";

export type LinkStatus = "current" | "stale" | "unlinked" | "superseded";

export interface PoseLink {
  id: string;
  link_id: string;
  revision: number;
  action: "link" | "correct" | "unlink";
  status: LinkStatus;
  stale_reason: string | null;
  organism_key: string;
  association_run_id: string;
  animal_identity_id: string;
  frame_start: number;
  frame_end: number;
  source_sha256: string;
  reviewer: string;
  reason: string;
  created_at: string;
  source: {
    video_id: string;
    pose_schema_revision: number;
    identity_run_revision: number;
    observations: {
      id: string;
      frame_index: number;
      source_video_track_id: string;
    }[];
    measurements: { id: string; run_id: string; name: string }[];
    events: {
      id: string;
      run_id: string;
      measurement_series_id: string;
      start_frame: number;
      end_frame: number;
    }[];
  };
}

export interface Review {
  confirm: true;
  reviewer: string;
  reason: string;
}

export interface PoseLinkInput extends Review {
  organism_revision_id: string;
  association_run_id: string;
  animal_identity_id: string;
  expected_identity_run_revision: number;
  expected_pose_schema_sha256: string;
  frame_start: number;
  frame_end: number;
  measurement_series_ids: string[];
  event_revision_ids: string[];
}

function base(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/ecology/pose-links`;
}

export function listPoseOrganismLinks(
  projectId: string,
  organism: string,
  offset: number,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({
    organism_key: organism,
    offset: String(offset),
  });
  return request<{ items: PoseLink[]; total: number; limit: number }>(
    `${base(projectId)}?${params}`,
    { signal },
  );
}

export function getPoseOrganismLinkHistory(
  projectId: string,
  linkId: string,
  signal?: AbortSignal,
) {
  return request<PoseLink[]>(`${base(projectId)}/${linkId}`, { signal });
}

export function savePoseOrganismLink(
  projectId: string,
  payload: PoseLinkInput,
  link?: PoseLink,
) {
  const path = link
    ? `${base(projectId)}/${link.link_id}/corrections`
    : base(projectId);
  return request<PoseLink>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      link ? { ...payload, expected_revision: link.revision } : payload,
    ),
  });
}

export function unlinkPoseOrganism(
  projectId: string,
  link: PoseLink,
  payload: Review,
) {
  return request<PoseLink>(`${base(projectId)}/${link.link_id}/unlink`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, expected_revision: link.revision }),
  });
}
