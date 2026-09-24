import { act, renderHook, waitFor } from "@testing-library/react";

import { describe, expect, it, vi } from "vitest";

import {
  GeographicMovementAnalyticsApiError,
  type GeographicTrackAnalytics,
} from "./videoGeographicMovementAnalyticsApi";

import { useGeographicMovementAnalytics } from "./useGeographicMovementAnalytics";

function analytics(trackId: string, count = 0): GeographicTrackAnalytics {
  return {
    track_id: trackId,
    video_asset_id: "video-1",
    observation_count: count,
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
}

function deferred<T>() {
  let resolve!: (value: T) => void;

  const promise = new Promise<T>((res) => {
    resolve = res;
  });

  return {
    promise,
    resolve,
  };
}

describe("useGeographicMovementAnalytics", () => {
  it("remains idle without a selected track", () => {
    const load = vi.fn(async () => analytics("unused"));

    const { result, unmount } = renderHook(() =>
      useGeographicMovementAnalytics(null, load),
    );

    expect(result.current.state.status).toBe("idle");
    expect(load).not.toHaveBeenCalled();

    unmount();
  });

  it("loads the selected track and preserves zero observations as success", async () => {
    const load = vi.fn(async (trackId: string) => analytics(trackId, 0));

    const { result, unmount } = renderHook(() =>
      useGeographicMovementAnalytics("track-A", load),
    );

    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        status: "success",
        trackId: "track-A",
        data: {
          observation_count: 0,
        },
      });
    });

    expect(load).toHaveBeenCalledTimes(1);

    unmount();
  });

  it("does not refetch during rerenders with the same selected track", async () => {
    const load = vi.fn(async (trackId: string) => analytics(trackId, 2));

    const { result, rerender, unmount } = renderHook(
      ({ trackId, frameIndex }) => {
        void frameIndex;

        return useGeographicMovementAnalytics(trackId, load);
      },
      {
        initialProps: {
          trackId: "track-A",
          frameIndex: 10,
        },
      },
    );

    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });

    rerender({
      trackId: "track-A",
      frameIndex: 20,
    });

    rerender({
      trackId: "track-A",
      frameIndex: 30,
    });

    expect(load).toHaveBeenCalledTimes(1);

    unmount();
  });

  it("prevents a late Track A response from replacing Track B", async () => {
    const requestA = deferred<GeographicTrackAnalytics>();
    const requestB = deferred<GeographicTrackAnalytics>();

    const load = vi.fn((trackId: string) =>
      trackId === "track-A" ? requestA.promise : requestB.promise,
    );

    const { result, rerender, unmount } = renderHook(
      ({ trackId }) => useGeographicMovementAnalytics(trackId, load),
      {
        initialProps: {
          trackId: "track-A",
        },
      },
    );

    rerender({
      trackId: "track-B",
    });

    expect(result.current.state).toMatchObject({
      status: "loading",
      trackId: "track-B",
      data: null,
    });

    await act(async () => {
      requestB.resolve(analytics("track-B", 3));
    });

    expect(result.current.state).toMatchObject({
      status: "success",
      trackId: "track-B",
      data: {
        track_id: "track-B",
        observation_count: 3,
      },
    });

    await act(async () => {
      requestA.resolve(analytics("track-A", 9));
    });

    expect(result.current.state).toMatchObject({
      status: "success",
      trackId: "track-B",
      data: {
        track_id: "track-B",
        observation_count: 3,
      },
    });

    unmount();
  });

  it("returns to idle when the selected track is cleared", async () => {
    const load = vi.fn(async (trackId: string) => analytics(trackId));

    const { result, rerender, unmount } = renderHook(
      ({ trackId }: { trackId: string | null }) =>
        useGeographicMovementAnalytics(trackId, load),
      {
        initialProps: {
          trackId: "track-A" as string | null,
        },
      },
    );

    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });

    rerender({
      trackId: null,
    });

    expect(result.current.state).toMatchObject({
      status: "idle",
      trackId: null,
      data: null,
    });

    unmount();
  });

  it("exposes backend validation errors without stale data", async () => {
    const load = vi.fn(async (): Promise<GeographicTrackAnalytics> => {
      throw new GeographicMovementAnalyticsApiError(400, "Unsupported CRS.");
    });

    const { result, unmount } = renderHook(() =>
      useGeographicMovementAnalytics("track-A", load),
    );

    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        status: "error",
        trackId: "track-A",
        data: null,
        error: "Unsupported CRS.",
        errorStatus: 400,
      });
    });

    unmount();
  });

  it("supports explicit reload without requiring reselection", async () => {
    const load = vi.fn(async (trackId: string) => analytics(trackId));

    const { result, unmount } = renderHook(() =>
      useGeographicMovementAnalytics("track-A", load),
    );

    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });

    act(() => {
      result.current.reload();
    });

    await waitFor(() => {
      expect(load).toHaveBeenCalledTimes(2);
    });

    unmount();
  });
});
