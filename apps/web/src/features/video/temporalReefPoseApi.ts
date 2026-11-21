import { request } from "../../api/client";

export type TemporalSplit = "train" | "validation" | "test";
export type TemporalDevice = "auto" | "cpu" | "cuda";
export type TemporalContext = "causal" | "centered";

export interface TemporalTrack {
  id: string;
  video_id: string;
  video_name: string;
  track_number: number;
  revision: number;
  schema_hash: string;
  model_id?: string;
}

export interface TemporalSource {
  frame_track_id: string;
  reviewed_track_id?: string;
  confirm_same_animal?: boolean;
  identity_observation_run_id?: string;
  animal_identity_id?: string;
  group_key?: string;
  discontinuity_frames?: number[];
}

export type TemporalDatasetRequest = {
  name: string;
  sources: (TemporalSource & { split: TemporalSplit })[];
};

export type TemporalRunRequest =
  | {
      kind: "training";
      dataset_id: string;
      name: string;
      window_length?: number;
      context_mode?: TemporalContext;
      epochs?: number;
      batch_size?: number;
      learning_rate?: number;
      device?: TemporalDevice;
      channels?: number;
      max_gap_seconds?: number | null;
      seed?: number;
      loss?: "smooth_l1" | "mse";
    }
  | {
      kind: "inference";
      temporal_model_id: string;
      source: TemporalSource;
      chunk_size?: number;
      device?: TemporalDevice;
    }
  | {
      kind: "evaluation";
      dataset_id: string;
      temporal_model_id: string;
      chunk_size?: number;
      device?: TemporalDevice;
      movement_threshold_px_per_second?: number;
      bootstrap_samples?: number;
      anatomical_events?: TemporalAnatomicalEvents;
    };

export interface TemporalAnatomicalEvents {
  landmark_a_id: string;
  landmark_b_id: string;
  open_threshold_px: number;
  close_threshold_px: number;
  minimum_amplitude_px?: number;
  minimum_duration_seconds?: number;
  maximum_gap_seconds?: number;
  onset_tolerance_seconds?: number;
  offset_tolerance_seconds?: number;
}

export interface TemporalDataset {
  id: string;
  name: string;
  manifest_sha256?: string;
  schema_hash?: string;
  source_count?: number;
  split_counts?: Record<string, number>;
  frame_lineage_state?: string;
  landmarks?: { id: string; name: string }[];
  frame_model_sha256?: string;
}

export interface TemporalInputs {
  next_offset?: number | null;
  frame_tracks: TemporalTrack[];
  reviewed_tracks: TemporalTrack[];
  identities: {
    id: string;
    run_id: string;
    video_id: string;
    name: string;
    revision: number;
  }[];
  temporal_models: {
    id: string;
    name: string;
    sha256: string;
    frame_model_sha256: string;
    schema_hash: string;
    window_length: number;
    context_mode: TemporalContext;
  }[];
  frame_models: {
    id: string;
    name: string;
    sha256: string;
    schema_hash: string;
  }[];
}

export interface TemporalRun {
  id: string;
  kind: TemporalRunRequest["kind"];
  status: string;
  job_id: string | null;
  result: Record<string, unknown> | null;
  error?: string | null;
  configuration?: Record<string, unknown>;
  source_stale?: boolean;
  progress_current?: number;
  progress_total?: number;
  identity_run_id?: string | null;
  identity_id?: string | null;
  review_revision?: number;
}

export interface TemporalPoint {
  landmark_id: string;
  x: number | null;
  y: number | null;
  confidence: number | null;
  visibility: string;
}

export interface TemporalFrame {
  frame_index: number;
  timestamp_seconds: number;
  frame_points: TemporalPoint[] | null;
  refined_points: (TemporalPoint | null)[];
  future_frames: number;
  future_seconds: number;
  review_source?: string | null;
}

export type TemporalReviewSource = "frame" | "refined" | "rejected";
export type TemporalCorrection = { landmark_id: string; x: number; y: number };
type TemporalReview = {
  base_revision: number;
  confirmed: true;
  frames: {
    frame_index: number;
    source: TemporalReviewSource;
    corrections?: TemporalCorrection[];
  }[];
  note?: string;
};
export type TemporalReviewResponse = {
  id: string;
  revision: number;
  identity_run_id: string;
  identity_id: string;
  accepted_frame_count: number;
  source_stale: boolean;
};

const base = (project: string) => `/projects/${project}/temporal-reefpose`;
const write = (body: unknown) => ({
  method: "POST",
  body: JSON.stringify(body),
});
export const getTemporalInputs = (
  project: string,
  signal?: AbortSignal,
  offset = 0,
) =>
  request<TemporalInputs>(
    `${base(project)}/inputs?limit=100&offset=${offset}`,
    { signal },
  );
export const getTemporalDatasets = (
  project: string,
  signal?: AbortSignal,
  offset = 0,
) =>
  request<TemporalDataset[]>(
    `${base(project)}/datasets?limit=100&offset=${offset}`,
    { signal },
  );
export const freezeTemporalDataset = (
  project: string,
  value: TemporalDatasetRequest,
) => request<TemporalDataset>(`${base(project)}/datasets`, write(value));
export const getTemporalRuns = (project: string, signal?: AbortSignal) =>
  request<TemporalRun[]>(`${base(project)}/runs`, { signal });
export const beginTemporalRun = (project: string, value: TemporalRunRequest) =>
  request<TemporalRun>(`${base(project)}/runs`, write(value));
export const getTemporalFrames = (
  project: string,
  run: string,
  offset: number,
  signal?: AbortSignal,
) =>
  request<{
    items: TemporalFrame[];
    offset: number;
    limit: number;
    total: number;
  }>(`${base(project)}/runs/${run}/frames?offset=${offset}&limit=25`, {
    signal,
  });
export const reviewTemporalFrames = (
  project: string,
  run: string,
  value: TemporalReview,
) =>
  request<TemporalReviewResponse>(
    `${base(project)}/runs/${run}/reviews`,
    write(value),
  );
