import { afterEach, describe, expect, it, vi } from "vitest";

import {
  importProjectSpatialAsset,
  listProjectSpatialAssets,
  previewProjectSpatialAsset,
} from "./workflowGraphApi";
import type { SpatialSourceAsset } from "./workflowGraphApi";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "/api/v1",
}));

const asset: SpatialSourceAsset = {
  id: "asset-1",
  project_id: "project 1",
  original_filename: "colony.ply",
  source_format: "ply",
  source_kind: "mesh_or_point_cloud",
  sha256: "a".repeat(64),
  size_bytes: 12,
  created_at: "2026-10-28T00:00:00Z",
  measurement_status: "source_unreviewed",
  calibration_verified: false,
  specimen_identity_verified: false,
};

const calibration = {
  meters_per_unit: 0.01,
  calibration_method: "ruler" as const,
  calibration_evidence: "Unreviewed field ruler",
  relative_scale_uncertainty: 0.1,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project spatial source API", () => {
  it("lists only the selected project originals", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [asset],
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    expect(await listProjectSpatialAssets("project 1", controller.signal)).toEqual([asset]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/projects/project%201/spatial/assets",
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("imports an original as multipart without manually setting Content-Type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => asset,
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["ply"], "colony.ply");
    expect(await importProjectSpatialAsset("project 1", file)).toEqual(asset);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/projects/project%201/spatial/assets");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("binds both mesh and PLY cloud previews to immutable source bytes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ measurement_status: "caller_supplied_unverified" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    for (const kind of ["mesh", "point_cloud"] as const) {
      await previewProjectSpatialAsset("project 1", asset, kind, calibration);
    }
    const paths = ["mesh-preview", "point-cloud-preview"];
    fetchMock.mock.calls.forEach(([url, init], index) => {
      expect(url).toBe(`/api/v1/projects/project%201/spatial/${paths[index]}`);
      const payload = JSON.parse(String((init as RequestInit).body));
      expect(payload).toMatchObject({
        ...calibration,
        asset_id: asset.id,
        expected_source_payload_sha256: asset.sha256,
      });
      expect(payload).not.toHaveProperty("ply_text");
      expect(payload).not.toHaveProperty("obj_text");
      expect(payload).not.toHaveProperty("points");
    });
  });

  it("rejects invalid geometry modes and calibration before sending a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      previewProjectSpatialAsset(
        "p",
        { ...asset, source_format: "glb", source_kind: "mesh" },
        "point_cloud",
        calibration,
      ),
    ).rejects.toThrow("PLY");
    await expect(
      previewProjectSpatialAsset("p", asset, "mesh", {
        ...calibration,
        relative_scale_uncertainty: Number.NaN,
      }),
    ).rejects.toThrow("Relative scale uncertainty");
    await expect(
      importProjectSpatialAsset("p", new File(["x"], "image.jpg")),
    ).rejects.toThrow("OBJ, PLY, or GLB");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
