import { afterEach, describe, expect, it, vi } from "vitest";

import { previewLocalMeshFile } from "./workflowGraphApi";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "/api/v1",
}));

const calibration = {
  meters_per_unit: 0.01,
  calibration_method: "ruler" as const,
  calibration_evidence: "Unreviewed physical ruler",
  relative_scale_uncertainty: 0.1,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("previewLocalMeshFile", () => {
  it("posts a bounded OBJ preview with explicitly unverified calibration", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        measurement_status: "caller_supplied_unverified",
        provenance: { calibration_verified: false },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = {
      name: "coral.obj",
      size: 32,
      text: async () => "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
    } as File;
    const result = await previewLocalMeshFile("project 1", file, {
      ...calibration,
      coordinate_frame_id: "transect-7",
    });
    expect(result.measurement_status).toBe("caller_supplied_unverified");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/projects/project%201/spatial/mesh-preview");
    const body = JSON.parse(String(init.body));
    expect(body.obj_text).toContain("f 1 2 3");
    expect(body.source_label).toBe("coral.obj");
    expect(body.calibration_evidence).toBe("Unreviewed physical ruler");
    expect(body.relative_scale_uncertainty).toBe(0.1);
    expect(body.coordinate_frame_id).toBe("transect-7");
  });

  it("encodes GLB bytes exactly without uploading or persisting an asset", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = {
      name: "mesh.GLB",
      size: 4,
      arrayBuffer: async () => new Uint8Array([0, 1, 254, 255]).buffer,
    } as File;
    await previewLocalMeshFile("p", file, calibration);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).glb_base64).toBe("AAH+/w==");
  });

  it("rejects invalid or oversized input before any network request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      previewLocalMeshFile(
        "p",
        { name: "image.jpg", size: 1 } as File,
        calibration,
      ),
    ).rejects.toThrow("OBJ, PLY, or GLB");
    await expect(
      previewLocalMeshFile(
        "p",
        { name: "oversized.ply", size: 256_001 } as File,
        calibration,
      ),
    ).rejects.toThrow("oversized");
    await expect(
      previewLocalMeshFile("p", { name: "coral.obj", size: 1 } as File, {
        ...calibration,
        meters_per_unit: 0,
      }),
    ).rejects.toThrow("positive scale");
    for (const uncertainty of [-0.01, 1.01, Number.NaN, Infinity]) {
      await expect(
        previewLocalMeshFile("p", { name: "coral.obj", size: 1 } as File, {
          ...calibration,
          relative_scale_uncertainty: uncertainty,
        }),
      ).rejects.toThrow("Relative scale uncertainty");
    }
    await expect(
      previewLocalMeshFile("p", { name: "coral.obj", size: 1 } as File, {
        ...calibration,
        meters_per_unit: 1_000_001,
      }),
    ).rejects.toThrow("positive scale");
    await expect(
      previewLocalMeshFile("p", { name: "coral.obj", size: 1 } as File, {
        ...calibration,
        calibration_evidence: "   ",
      }),
    ).rejects.toThrow("calibration evidence");
    for (const invalidFrame of [
      "",
      "survey with spaces",
      "survey/1",
      "x".repeat(129),
    ]) {
      await expect(
        previewLocalMeshFile("p", { name: "coral.obj", size: 1 } as File, {
          ...calibration,
          coordinate_frame_id: invalidFrame,
        }),
      ).rejects.toThrow("Mesh source frame ID");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
