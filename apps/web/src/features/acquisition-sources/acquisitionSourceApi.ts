import { request } from "../../api/client";
import type { FieldClock } from "../field-capture/fieldCaptureApi";

export type SourceConfiguration =
  | { kind: "recorded"; batch_id: string; manifest_sha256: string }
  | {
      kind: "simulated";
      seed: number;
      start_at_utc: string;
      period_seconds: number;
    }
  | { kind: "camera"; camera_index: number };

export type AcquisitionStateAction =
  "pause" | "resume" | "approve_camera" | "revoke_camera";

export interface AcquisitionSource {
  id: string;
  project_id: string;
  label: string;
  configuration: SourceConfiguration;
  source_sha256: string;
  cursor: number;
  state: "ready" | "paused" | "disconnected" | "exhausted";
  revision: number;
  last_error: string | null;
  next_retry_at: string | null;
  local_consent_until: string | null;
}

export interface AcquisitionReceipt {
  content_sha256: string;
  receipt: {
    id: string;
    project_id: string;
    source_id: string;
    source_kind: SourceConfiguration["kind"];
    source_sha256: string;
    ordinal: number;
    dispatch: { kind: "manual" | "schedule"; occurrence_id: string | null };
    time: {
      origin: "field_source" | "synthetic_clock" | "local_host_read";
      clock: FieldClock;
      captured_at_utc: string | null;
      uncertainty_seconds: number | null;
      host_received_at_utc: string | null;
      host_read_elapsed_seconds: number | null;
    };
    media: {
      field_batch_id: string;
      field_batch_sha256: string;
      field_observation_id: string;
      original_observation_id: string;
      filename: string;
      kind: "image" | "video";
      sha256: string;
      size_bytes: number;
    };
    synthetic_reading: { value: number; unit: string } | null;
    recorded_at_utc: string;
  };
}

interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

const root = (projectId: string) =>
  "/projects/" + encodeURIComponent(projectId) + "/acquisition-sources";
const sourcePath = (projectId: string, sourceId: string) =>
  root(projectId) + "/" + encodeURIComponent(sourceId);

export const listAcquisitionSources = (
  projectId: string,
  page: number,
  signal?: AbortSignal,
) =>
  request<Page<AcquisitionSource>>(root(projectId) + "?page=" + page, {
    signal,
  });

export const createAcquisitionSource = (
  projectId: string,
  label: string,
  configuration: SourceConfiguration,
) =>
  request<AcquisitionSource>(root(projectId), {
    method: "POST",
    body: JSON.stringify({ label, configuration }),
  });

export const getAcquisitionSource = (
  projectId: string,
  sourceId: string,
  signal?: AbortSignal,
) => request<AcquisitionSource>(sourcePath(projectId, sourceId), { signal });

export const changeAcquisitionSource = (
  projectId: string,
  source: AcquisitionSource,
  action: AcquisitionStateAction,
) =>
  request<AcquisitionSource>(sourcePath(projectId, source.id) + "/state", {
    method: "PATCH",
    body: JSON.stringify({ revision: source.revision, action }),
  });

export const captureAcquisition = (
  projectId: string,
  source: AcquisitionSource,
  captureKey: string,
  confirmCamera: boolean,
) =>
  request<AcquisitionReceipt>(sourcePath(projectId, source.id) + "/captures", {
    method: "POST",
    body: JSON.stringify({
      source_sha256: source.source_sha256,
      capture_key: captureKey,
      confirm_camera: confirmCamera,
    }),
  });

export const listAcquisitionCaptures = (
  projectId: string,
  sourceId: string,
  page: number,
  signal?: AbortSignal,
) =>
  request<Page<AcquisitionReceipt>>(
    sourcePath(projectId, sourceId) + "/captures?page=" + page,
    { signal },
  );

export const getAcquisitionCapture = (
  projectId: string,
  sourceId: string,
  captureId: string,
) =>
  request<AcquisitionReceipt>(
    sourcePath(projectId, sourceId) +
      "/captures/" +
      encodeURIComponent(captureId),
  );
