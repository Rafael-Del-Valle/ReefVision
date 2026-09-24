import { describe, expect, it, vi } from "vitest";

import {
  GeographicMovementAnalyticsApiError,
  type GeographicTrackAnalytics,
} from "./videoGeographicMovementAnalyticsApi";

import {
  createGeographicMovementAnalyticsController,
  type GeographicMovementAnalyticsState,
} from "./videoGeographicMovementAnalyticsState";

function analytics(
  trackId: string,
  observationCount = 0,
): GeographicTrackAnalytics {
  return {
    track_id: trackId,
    video_asset_id: "video-1",
    observation_count: observationCount,
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
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return {
    promise,
    resolve,
    reject,
  };
}

describe("geographic movement analytics request state", () => {
  it("starts idle without a selected track", () => {
    const controller = createGeographicMovementAnalyticsController();

    expect(controller.getState()).toEqual({
      status: "idle",
      trackId: null,
      data: null,
      error: null,
      errorStatus: null,
    });

    controller.dispose();
  });

  it("transitions from loading to success", async () => {
    const pending = deferred<GeographicTrackAnalytics>();

    const load = vi.fn(() => pending.promise);

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    expect(controller.getState()).toMatchObject({
      status: "loading",
      trackId: "track-1",
      data: null,
    });

    pending.resolve(analytics("track-1", 2));

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "success",
        trackId: "track-1",
        data: {
          observation_count: 2,
        },
      });
    });

    expect(load).toHaveBeenCalledTimes(1);

    controller.dispose();
  });

  it("treats zero observations as successful data", async () => {
    const load = vi.fn(async () => analytics("track-1"));

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    await vi.waitFor(() => {
      expect(controller.getState().status).toBe("success");
    });

    expect(controller.getState()).toMatchObject({
      status: "success",
      data: {
        observation_count: 0,
        segments: [],
      },
      error: null,
    });

    controller.dispose();
  });

  it("preserves HTTP status and backend error detail", async () => {
    const load = vi.fn(async (): Promise<GeographicTrackAnalytics> => {
      throw new GeographicMovementAnalyticsApiError(
        400,
        "Only EPSG:4326 is supported.",
      );
    });

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "error",
        trackId: "track-1",
        data: null,
        error: "Only EPSG:4326 is supported.",
        errorStatus: 400,
      });
    });

    controller.dispose();
  });

  it("represents network errors without inventing HTTP status", async () => {
    const load = vi.fn(async (): Promise<GeographicTrackAnalytics> => {
      throw new Error("Network unavailable");
    });

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "error",
        error: "Network unavailable",
        errorStatus: null,
      });
    });

    controller.dispose();
  });

  it("ignores a late Track A response after Track B succeeds", async () => {
    const requestA = deferred<GeographicTrackAnalytics>();
    const requestB = deferred<GeographicTrackAnalytics>();

    const signals: AbortSignal[] = [];

    const load = vi.fn((trackId: string, signal?: AbortSignal) => {
      if (signal) {
        signals.push(signal);
      }

      return trackId === "track-A" ? requestA.promise : requestB.promise;
    });

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-A");
    controller.selectTrack("track-B");

    expect(signals[0].aborted).toBe(true);

    requestB.resolve(analytics("track-B", 3));

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "success",
        trackId: "track-B",
        data: {
          track_id: "track-B",
          observation_count: 3,
        },
      });
    });

    // Simulate a transport that resolves despite the abort.
    requestA.resolve(analytics("track-A", 9));

    await Promise.resolve();

    expect(controller.getState()).toMatchObject({
      status: "success",
      trackId: "track-B",
      data: {
        track_id: "track-B",
        observation_count: 3,
      },
    });

    controller.dispose();
  });

  it("does not show an error when a superseded request aborts", async () => {
    const requestA = deferred<GeographicTrackAnalytics>();
    const requestB = deferred<GeographicTrackAnalytics>();

    const load = vi.fn((trackId: string) =>
      trackId === "track-A" ? requestA.promise : requestB.promise,
    );

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-A");
    controller.selectTrack("track-B");

    const abortError = new Error("Request aborted");
    abortError.name = "AbortError";

    requestA.reject(abortError);
    requestB.resolve(analytics("track-B"));

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "success",
        trackId: "track-B",
        error: null,
      });
    });

    controller.dispose();
  });

  it("clears selection to idle and aborts the active request", async () => {
    const pending = deferred<GeographicTrackAnalytics>();

    let receivedSignal: AbortSignal | undefined;

    const load = vi.fn((_trackId: string, signal?: AbortSignal) => {
      receivedSignal = signal;
      return pending.promise;
    });

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");
    controller.selectTrack(null);

    expect(receivedSignal?.aborted).toBe(true);

    expect(controller.getState()).toMatchObject({
      status: "idle",
      trackId: null,
      data: null,
      error: null,
    });

    pending.resolve(analytics("track-1"));

    await Promise.resolve();

    expect(controller.getState().status).toBe("idle");

    controller.dispose();
  });

  it("does not refetch the same selected track without explicit reload", async () => {
    const load = vi.fn(async (trackId: string) => analytics(trackId));

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    await vi.waitFor(() => {
      expect(controller.getState().status).toBe("success");
    });

    controller.selectTrack("track-1");
    controller.selectTrack("track-1");

    expect(load).toHaveBeenCalledTimes(1);

    controller.reload();

    await vi.waitFor(() => {
      expect(load).toHaveBeenCalledTimes(2);
    });

    controller.dispose();
  });

  it("rejects a response belonging to a different track", async () => {
    const load = vi.fn(async () => analytics("wrong-track"));

    const controller = createGeographicMovementAnalyticsController(load);

    controller.selectTrack("track-1");

    await vi.waitFor(() => {
      expect(controller.getState()).toMatchObject({
        status: "error",
        trackId: "track-1",
        data: null,
        errorStatus: null,
      });
    });

    controller.dispose();
  });

  it("notifies subscribers and stops updates after disposal", async () => {
    const pending = deferred<GeographicTrackAnalytics>();

    const controller = createGeographicMovementAnalyticsController(
      () => pending.promise,
    );

    const updates: GeographicMovementAnalyticsState[] = [];

    controller.subscribe((state) => {
      updates.push(state);
    });

    controller.selectTrack("track-1");

    expect(updates).toHaveLength(1);
    expect(updates[0].status).toBe("loading");

    controller.dispose();

    pending.resolve(analytics("track-1"));

    await Promise.resolve();

    expect(updates).toHaveLength(1);
  });
});
