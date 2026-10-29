// Generated from ReefVision's backend geographic movement analytics contract.
// Task 16E: frontend contract + transport only.
// Do not calculate movement metrics in this module.

export interface GeographicCoordinate {
  latitude_deg: number;
  longitude_deg: number;
  crs: string;
}

export interface GeographicMovementSegment {
  track_id: string;
  video_asset_id: string;
  start_observation_id: string;
  end_observation_id: string;
  start_frame_index: number;
  end_frame_index: number;
  start_frame_time_s: number;
  end_frame_time_s: number;
  elapsed_time_s: number;
  start_location: GeographicCoordinate;
  end_location: GeographicCoordinate;
  distance_m: number;
  speed_m_s: number | null;
  /** WGS84 initial azimuth clockwise from true north; null for coincident positions. */
  initial_bearing_deg: number | null;
  cumulative_distance_m: number;
  speed_valid: boolean;
  invalid_reason: string | null;
}

export interface GeographicTrackAnalytics {
  track_id: string;
  video_asset_id: string;
  observation_count: number;
  segment_count: number;
  first_frame_index: number | null;
  last_frame_index: number | null;
  first_frame_time_s: number | null;
  last_frame_time_s: number | null;
  elapsed_time_s: number | null;
  total_distance_m: number;
  net_displacement_m: number;
  mean_speed_m_s: number | null;
  max_segment_speed_m_s: number | null;
  start_location: GeographicCoordinate | null;
  end_location: GeographicCoordinate | null;
  segments: GeographicMovementSegment[];
}

export class GeographicMovementAnalyticsApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "GeographicMovementAnalyticsApiError";
    this.status = status;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: unknown;
    };

    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail;
    }
  } catch {
    // Fall through to a status-based message.
  }

  return `Request failed with status ${response.status}`;
}

export async function getVideoTrackGeographicAnalytics(
  trackId: string,
  signal?: AbortSignal,
): Promise<GeographicTrackAnalytics> {
  const response = await fetch(
    `/api/v1/video-tracks/${encodeURIComponent(trackId)}/geographic-analytics`,
    {
      method: "GET",
      signal,
    },
  );

  if (!response.ok) {
    throw new GeographicMovementAnalyticsApiError(
      response.status,
      await readErrorDetail(response),
    );
  }

  return (await response.json()) as GeographicTrackAnalytics;
}
