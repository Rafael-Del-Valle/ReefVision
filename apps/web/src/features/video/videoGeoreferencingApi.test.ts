import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearVideoGeoreferencingCalibration,
  getVideoGeoreferencingCalibration,
  setVideoGeoreferencingCalibration,
} from "./videoApi";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("video georeferencing API", () => {
  it("returns null when no selected calibration exists", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getVideoGeoreferencingCalibration("video-1")).resolves.toBeNull();
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
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("clears the selected calibration", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(clearVideoGeoreferencingCalibration("video-1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/videos\/video-1\/georeferencing-calibration$/),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
