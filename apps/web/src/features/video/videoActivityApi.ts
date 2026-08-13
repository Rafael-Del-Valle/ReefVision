import { getApiBaseUrl } from "../../runtime";
import type { VideoSpatialCalibration } from "./videoScienceApi";

export interface VideoActivityInterval {
  start_frame: number;
  end_frame: number;
  start_time_seconds: number;
  end_time_seconds: number;
  duration_seconds: number;
  distance_pixels: number;
  distance: number;
  speed_pixels_per_second: number;
  speed_per_second: number;
  active: boolean;
}

export interface VideoActivityBout {
  state: "active" | "rest";
  start_frame: number;
  end_frame: number;
  start_time_seconds: number;
  end_time_seconds: number;
  duration_seconds: number;
  interval_count: number;
}

export interface VideoTrackActivity {
  schema_version: "video-track-activity-0001";
  track_id: string;
  video_id: string;
  track_number: number;
  label_class_id: string;
  trajectory_policy: "configured_track_interpolation";
  start_frame: number;
  end_frame: number;
  distance_unit: "mm" | "cm" | "m";
  speed_threshold_per_second: number;
  speed_threshold_pixels_per_second: number;
  minimum_active_bout_seconds: number;
  evaluated_seconds: number;
  active_seconds: number;
  rest_seconds: number;
  active_fraction: number;
  active_bout_count: number;
  rest_bout_count: number;
  mean_active_bout_seconds: number | null;
  maximum_active_bout_seconds: number | null;
  mean_rest_bout_seconds: number | null;
  mean_active_speed_per_second: number | null;
  maximum_speed_per_second: number | null;
  calibration: VideoSpatialCalibration;
  intervals: VideoActivityInterval[];
  bouts: VideoActivityBout[];
}

async function responseError(response: Response): Promise<string> {
  const fallback = `Activity analytics failed with HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function getVideoTrackActivity(
  trackId: string,
  payload: {
    speed_threshold_per_second: number;
    start_frame?: number;
    end_frame?: number;
    minimum_active_bout_seconds?: number;
  },
): Promise<VideoTrackActivity> {
  const response = await fetch(
    `${getApiBaseUrl()}/video-tracks/${encodeURIComponent(trackId)}/activity-analytics`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(await responseError(response));
  return (await response.json()) as VideoTrackActivity;
}
