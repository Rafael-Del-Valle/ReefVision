import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import type { VideoAssetRecord } from "../video/videoApi";

export interface AudioPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface AudioRecording {
  id: string;
  project_id: string;
  original_asset_id: string;
  original_project_id: string;
  original_filename: string;
  sha256: string;
  size_bytes: number;
  sample_rate_hz: number;
  sample_count: number;
  channel_count: number;
  bits_per_sample: number;
  created_at: string;
}

export interface Waveform {
  asset_id: string;
  source_sha256: string;
  channel: number;
  sample_rate_hz: number;
  sample_count: number;
  peaks: Array<{
    start_sample: number;
    end_sample: number;
    minimum: number;
    maximum: number;
  }>;
}

export interface AudioProposalCreate {
  start_sample: number;
  end_sample: number;
  channel: number;
  label: string;
  notes?: string;
  source_sha256: string;
}

export type AudioDecision = "accepted" | "dismissed" | "uncertain";

export interface AudioReview {
  id: string;
  project_id: string;
  proposal_id: string;
  reviewer: string;
  decision: AudioDecision;
  reason: string;
  revision: number;
  reviewed_at: string;
}

export interface AudioProposal extends AudioProposalCreate {
  id: string;
  project_id: string;
  asset_id: string;
  author: string;
  created_at: string;
  proposal_sha256: string;
  status: "proposed" | AudioDecision;
  review_revision: number;
  latest_review: AudioReview | null;
}

interface ClockEvidence {
  sample: number;
  source_sha256: string;
  uncertainty_us: number;
  evidence: string;
}

export type AudioAnchorCreate = ClockEvidence &
  (
    | { kind: "utc"; utc: string }
    | {
        kind: "video";
        video_id: string;
        video_sha256: string;
        video_time_us: number;
      }
  );

export type AudioAnchor = AudioAnchorCreate & {
  id: string;
  project_id: string;
  asset_id: string;
  anchor_sha256: string;
  author: string;
  created_at: string;
};

export interface AudioAlignment {
  status: "withheld" | "utc" | "video";
  reason: string | null;
  start_utc: string | null;
  end_utc: string | null;
  start_video_us: number | null;
  end_video_us: number | null;
  uncertainty_us: number | null;
}

export interface AudioReport {
  id: string;
  project_id: string;
  asset_id: string;
  report_sha256: string;
  created_at: string;
  snapshot: {
    schema_version: "reefvision-bioacoustic-report-1";
    method: "sample-clock-offset-v1";
    source: AudioRecording;
    anchor: AudioAnchor | null;
    clock_conflicts: string[];
    entries: Array<{ proposal: AudioProposal; alignment: AudioAlignment }>;
  };
}

export function recordingsPath(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/bioacoustics/assets`;
}

export function recordingPath(audio: AudioRecording) {
  return `${recordingsPath(audio.project_id)}/${encodeURIComponent(audio.id)}`;
}

export function originalAudioUrl(audio: AudioRecording) {
  return `${getApiBaseUrl()}${recordingPath(audio)}/content`;
}

export function createAudioRecording(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<AudioRecording>(recordingsPath(projectId), {
    method: "POST",
    body: form,
  });
}

export function audioPage<T>(
  path: string,
  offset: number,
  signal: AbortSignal,
) {
  return request<AudioPage<T>>(`${path}?offset=${offset}&limit=50`, { signal });
}

export function waveform(
  audio: AudioRecording,
  channel: number,
  signal: AbortSignal,
) {
  return request<Waveform>(
    `${recordingPath(audio)}/waveform?channel=${channel}&bins=512`,
    { signal },
  );
}

export function audioPost<T>(path: string, body: object) {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export function audioVideos(projectId: string, signal: AbortSignal) {
  return request<VideoAssetRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/videos`,
    { signal },
  );
}

export async function downloadAudioReport(
  audio: AudioRecording,
  report: AudioReport,
) {
  const response = await fetch(
    `${getApiBaseUrl()}${recordingPath(audio)}/reports/${encodeURIComponent(report.id)}/export`,
    {
      signal: AbortSignal.timeout(30_000),
    },
  );
  if (!response.ok)
    throw new Error(`Audio report download failed (HTTP ${response.status}).`);
  const data = await response.blob();
  const exported = JSON.parse(await data.text()) as AudioReport;
  if (
    exported.id !== report.id ||
    exported.project_id !== audio.project_id ||
    exported.asset_id !== audio.id ||
    exported.report_sha256 !== report.report_sha256
  ) {
    throw new Error(
      "The download does not match the selected bioacoustic report.",
    );
  }
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `bioacoustics-${report.report_sha256}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
