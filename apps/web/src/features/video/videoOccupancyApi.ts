import { getApiBaseUrl } from "../../runtime";

export interface VideoOccupancyCell {
  row: number;
  column: number;
  x_min_pixels: number;
  y_min_pixels: number;
  x_max_pixels: number;
  y_max_pixels: number;
  observation_count: number;
  observation_fraction: number;
  occupied_frame_count: number;
  occupied_frame_fraction: number;
  unique_track_count: number;
  dwell_seconds: number;
}

export interface VideoTrackOccupancySummary {
  track_id: string;
  track_number: number;
  label_class_id: string;
  observation_count: number;
  dwell_seconds: number;
  occupied_cell_count: number;
  most_occupied_row: number | null;
  most_occupied_column: number | null;
  most_occupied_fraction: number | null;
}

export interface VideoOccupancyAnalytics {
  schema_version: "video-occupancy-0001";
  video_id: string;
  track_ids: string[];
  start_frame: number;
  end_frame: number;
  grid_rows: number;
  grid_columns: number;
  video_width_pixels: number;
  video_height_pixels: number;
  trajectory_policy: "configured_track_interpolation";
  frames_with_tracks: number;
  track_frame_observations: number;
  total_track_seconds: number;
  cells: VideoOccupancyCell[];
  per_track: VideoTrackOccupancySummary[];
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `Occupancy analytics failed with HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function getVideoOccupancy(
  videoId: string,
  payload: {
    track_ids: string[];
    grid_rows: number;
    grid_columns: number;
    start_frame?: number;
    end_frame?: number;
  },
): Promise<VideoOccupancyAnalytics> {
  const response = await fetch(
    `${getApiBaseUrl()}/videos/${encodeURIComponent(videoId)}/occupancy-analytics`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as VideoOccupancyAnalytics;
}
