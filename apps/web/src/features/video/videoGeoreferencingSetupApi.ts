import { getApiBaseUrl } from "../../runtime";

export interface VideoGeoreferencingCalibrationPayload {
  width_px: number;
  height_px: number;
  fx_px: number;
  fy_px: number;
  cx_px: number;
  cy_px: number;
  distortion_coefficients: number[];
  digital_zoom_ratio: number;
  camera_mode: string;
  source: string;
  evidence: string;
}

export interface VideoGeoreferencingCalibration
  extends VideoGeoreferencingCalibrationPayload {
  schema_version: "video-georeferencing-calibration-0001";
  video_id: string;
  checksum_sha256: string;
  calibration_revision: number;
  calibration_updated_at: string;
  video_revision: number;
}

export interface VideoGeoreferencingRunResult {
  video_id: string;
  track_count: number;
  attempted_count: number;
  georeferenced_observation_count: number;
  failure_count: number;
  configuration_hash: string;
}

async function detail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function getVideoGeoreferencingCalibration(
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoGeoreferencingCalibration | null> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/georeferencing-calibration`,
    { signal, cache: "no-store" },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(await detail(response, `Calibration request failed (${response.status})`));
  }
  return (await response.json()) as VideoGeoreferencingCalibration;
}

export async function setVideoGeoreferencingCalibration(
  videoId: string,
  payload: VideoGeoreferencingCalibrationPayload,
): Promise<VideoGeoreferencingCalibration> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/georeferencing-calibration`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(await detail(response, `Calibration update failed (${response.status})`));
  }
  return (await response.json()) as VideoGeoreferencingCalibration;
}

export async function setProjectGeoreferencingSurface(
  projectId: string,
  height: number,
  evidence: string,
): Promise<void> {
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${encodeURIComponent(projectId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        georeference_height_offset_m: height,
        georeference_height_evidence: evidence,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await detail(response, `Surface reference update failed (${response.status})`));
  }
}

export async function startVideoGeoreferencing(
  videoId: string,
): Promise<VideoGeoreferencingRunResult> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/georeference-tracks`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(await detail(response, `Georeferencing failed (${response.status})`));
  }
  return (await response.json()) as VideoGeoreferencingRunResult;
}
