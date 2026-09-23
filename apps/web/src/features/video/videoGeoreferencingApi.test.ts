import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearVideoGeoreferencingCalibration,
  getVideoGeoreferencingCalibration,
  getVideoGeoreferencingReadiness,
  importVideo,
  setVideoGeoreferencingCalibration,
} from "./videoApi";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("video georeferencing API", () => {
  it("sends SRT, AirData, offset, and evidence in the video multipart import", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const video = new File(["video"], "clip.mp4", { type: "video/mp4" });
    const srt = new File(["1"], "clip.srt", { type: "application/x-subrip" });
    const airdata = new File(["time(millisecond)"], "flight.csv", {
      type: "text/csv",
    });

    await importVideo("project-1", video, {
      telemetryFile: srt,
      airdataFile: airdata,
      airdataTimeOffsetSeconds: 6.19,
      airdataTimeOffsetEvidence: "  source-only SRT/AirData alignment  ",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);

    const form = init.body as FormData;
    expect((form.get("file") as File).name).toBe("clip.mp4");
    expect((form.get("telemetry_file") as File).name).toBe("clip.srt");
    expect((form.get("airdata_file") as File).name).toBe("flight.csv");
    expect(form.get("airdata_time_offset_s")).toBe("6.19");
    expect(form.get("airdata_time_offset_evidence")).toBe(
      "source-only SRT/AirData alignment",
    );
  });

  it("fetches authoritative georeferencing readiness without caches", async () => {
    const response = {
      schema_version: "video-georeferencing-readiness-0001",
      video_id: "video-1",
      project_id: "project-1",
      ready: false,
      state: "missing_calibration",
      issues: [
        {
          code: "missing_calibration",
          message: "Video georeferencing camera calibration has not been configured",
        },
      ],
      srt_available: true,
      airdata_available: false,
      airdata_alignment_valid: true,
      surface_reference_configured: true,
      calibration_available: false,
      calibration_valid: false,
      calibration_checksum_sha256: null,
      sampled_frame_indices: [0, 75, 150, 224, 299],
      synchronized_frame_count: 0,
      sampled_frame_count: 5,
      maximum_sync_error_s: null,
      zoom_compatible: null,
      max_allowed_sync_error_s: 0.1,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    await expect(
      getVideoGeoreferencingReadiness("video-1", signal),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/videos\/video-1\/georeferencing-readiness$/),
      expect.objectContaining({ cache: "no-store", signal }),
    );
  });

  it("returns null when no selected calibration exists", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getVideoGeoreferencingCalibration("video-1"),
    ).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/videos\/video-1\/georeferencing-calibration$/),
      expect.objectContaining({}),
    );
  });

  it("sets a typed full georeferencing calibration", async () => {
    const payload = {
      width_px: 3840,
      height_px: 2160,
      fx_px: 2969.4,
      fy_px: 2970.3,
      cx_px: 1968.5,
      cy_px: 1116.9,
      distortion_coefficients: [0.26049, -0.83362, 0.00045, -0.00025, 0.73529],
      digital_zoom_ratio: 1,
      camera_mode: "DJI Mavic 3T RGB wide",
      source: "camera_calibration_DJIM3T_RGBwide.json",
      evidence: "WhaleDrone checkerboard camera calibration",
    };
    const response = {
      schema_version: "video-georeferencing-calibration-0001",
      video_id: "video-1",
      ...payload,
      checksum_sha256: "a".repeat(64),
      calibration_revision: 1,
      calibration_updated_at: "2026-09-23T00:00:00Z",
      video_revision: 2,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      setVideoGeoreferencingCalibration("video-1", payload),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/videos\/video-1\/georeferencing-calibration$/),
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  it("clears the selected calibration", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      clearVideoGeoreferencingCalibration("video-1"),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/videos\/video-1\/georeferencing-calibration$/),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
