import { afterEach, describe, expect, it, vi } from "vitest";

import {
  GeographicMovementAnalyticsApiError,
  getVideoTrackGeographicAnalytics,
  type GeographicTrackAnalytics,
} from "./videoGeographicMovementAnalyticsApi";

const emptyAnalytics: GeographicTrackAnalytics = {
  track_id: "track-1",
  video_asset_id: "video-1",
  observation_count: 0,
  segment_count: 0,
  first_frame_index: null,
  last_frame_index: null,
  first_frame_time_s: null,
  last_frame_time_s: null,
  elapsed_time_s: null,
  total_distance_m: 0,
  net_displacement_m: 0,
  mean_speed_m_s: null,
  max_segment_speed_m_s: null,
  start_location: null,
  end_location: null,
  segments: [],
};

function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
    },
    ...init,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("getVideoTrackGeographicAnalytics", () => {
  it("requests the geographic analytics endpoint with GET", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(emptyAnalytics));

    vi.stubGlobal("fetch", fetchMock);

    const result = await getVideoTrackGeographicAnalytics("track-1");

    expect(result).toEqual(emptyAnalytics);

    expect(fetchMock).toHaveBeenCalledTimes(1);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/video-tracks/track-1/geographic-analytics",
      {
        method: "GET",
        signal: undefined,
      },
    );
  });

  it("URL-encodes the track ID", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(emptyAnalytics));

    vi.stubGlobal("fetch", fetchMock);

    await getVideoTrackGeographicAnalytics("track/with spaces");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/video-tracks/track%2Fwith%20spaces/geographic-analytics",
      {
        method: "GET",
        signal: undefined,
      },
    );
  });

  it("forwards AbortSignal to fetch", async () => {
    const controller = new AbortController();

    const fetchMock = vi.fn(async () => jsonResponse(emptyAnalytics));

    vi.stubGlobal("fetch", fetchMock);

    await getVideoTrackGeographicAnalytics("track-1", controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/video-tracks/track-1/geographic-analytics",
      {
        method: "GET",
        signal: controller.signal,
      },
    );
  });

  it("preserves backend validation detail and HTTP status", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        {
          detail:
            "Geographic movement analytics currently support only EPSG:4326.",
        },
        {
          status: 400,
        },
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    let caught: unknown = null;

    try {
      await getVideoTrackGeographicAnalytics("track-1");
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(GeographicMovementAnalyticsApiError);

    const apiError = caught as GeographicMovementAnalyticsApiError;

    expect(apiError.status).toBe(400);

    expect(apiError.message).toBe(
      "Geographic movement analytics currently support only EPSG:4326.",
    );
  });

  it("keeps a zero-observation response as successful data", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(emptyAnalytics));

    vi.stubGlobal("fetch", fetchMock);

    const result = await getVideoTrackGeographicAnalytics("track-1");

    expect(result.observation_count).toBe(0);

    expect(result.segments).toEqual([]);
  });
});
