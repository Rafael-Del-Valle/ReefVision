import { afterEach, describe, expect, it, vi } from "vitest";

import { previewLocalPointCloudFile } from "./workflowGraphApi";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "/api/v1",
}));

const calibration = {
  meters_per_unit: 0.01,
  calibration_method: "ruler" as const,
  calibration_evidence: "Ruler in frame; awaiting human verification",
  relative_scale_uncertainty: 0.1,
};

const ply = [
  "ply",
  "format ascii 1.0",
  "element vertex 2",
  "property float x",
  "property float y",
  "property float z",
  "property uchar red",
  "property uchar green",
  "property uchar blue",
  "end_header",
  "0 0 0 255 0 0",
  "1 2 3 0 255 0",
  "",
].join("\n");

function localFile(name: string, bytes: Uint8Array): File {
  return {
    name,
    size: bytes.length,
    arrayBuffer: async () => Uint8Array.from(bytes).buffer,
  } as File;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("previewLocalPointCloudFile", () => {
  it("submits exact ASCII PLY text, provisional calibration and project identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        measurement_status: "caller_supplied_unverified",
        surface_area_m2: null,
        branch_length_m: null,
        provenance: { calibration_verified: false },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await previewLocalPointCloudFile(
      "project 1",
      localFile("coral.PLY", new TextEncoder().encode(ply)),
      { ...calibration, coordinate_frame_id: "transect-7" },
    );
    expect(result.surface_area_m2).toBeNull();
    expect(result.branch_length_m).toBeNull();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "/api/v1/projects/project%201/spatial/point-cloud-preview",
    );
    const body = JSON.parse(String(init.body));
    expect(body.ply_text).toBe(ply);
    expect(body.source_label).toBe("coral.PLY");
    expect(body.calibration_evidence).toBe(calibration.calibration_evidence);
    expect(body.relative_scale_uncertainty).toBe(0.1);
    expect(body.coordinate_frame_id).toBe("transect-7");
    expect(body.points).toBeUndefined();
  });

  it("passes bounded original source indices to the shared scientific chord engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        measurement_status: "caller_supplied_unverified",
        selected_point_chords: [
          { point_indices: [0, 1], chord_distance_m: 0.01 },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = localFile("reef.ply", new TextEncoder().encode(ply));
    const result = await previewLocalPointCloudFile(
      "project",
      file,
      calibration,
      [[0, 1]],
    );
    expect(result.measurement_status).toBe("caller_supplied_unverified");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.point_index_pairs).toEqual([[0, 1]]);
    expect(body.ply_text).toBe(ply);
  });

  it("opts into bounded chord endpoint display without changing scientific inputs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ measurement_status: "caller_supplied_unverified" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = localFile("reef.ply", new TextEncoder().encode(ply));
    await previewLocalPointCloudFile(
      "project",
      file,
      calibration,
      [[0, 1]],
      true,
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.preserve_measured_chord_endpoints_in_preview).toBe(true);
    expect(body.point_index_pairs).toEqual([[0, 1]]);
    expect(body.ply_text).toBe(ply);
    expect(body.calibration_evidence).toBe(calibration.calibration_evidence);
  });

  it("rejects invalid source point pairs before any network request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const file = localFile("reef.ply", new TextEncoder().encode(ply));
    const invalid: Array<Array<[number, number]>> = [
      [[0, 0]],
      [[-1, 1]],
      [[0, 2000]],
      [[0.5, 1]],
      [[Number.NaN, 1]],
      Array.from({ length: 33 }, (): [number, number] => [0, 1]),
    ];
    for (const pairs of invalid) {
      await expect(
        previewLocalPointCloudFile("project", file, calibration, pairs),
      ).rejects.toThrow("Point chord indices");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects invalid file, calibration and non-ASCII bytes before network use", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const valid = localFile("cloud.ply", new TextEncoder().encode(ply));
    await expect(
      previewLocalPointCloudFile(
        "p",
        localFile("cloud.obj", new Uint8Array([1])),
        calibration,
      ),
    ).rejects.toThrow("ASCII PLY");
    await expect(
      previewLocalPointCloudFile(
        "p",
        localFile("cloud.ply", new Uint8Array()),
        calibration,
      ),
    ).rejects.toThrow("empty");
    await expect(
      previewLocalPointCloudFile(
        "p",
        { name: "cloud.ply", size: 256_001 } as File,
        calibration,
      ),
    ).rejects.toThrow("oversized");
    await expect(
      previewLocalPointCloudFile("p", valid, {
        ...calibration,
        meters_per_unit: 0,
      }),
    ).rejects.toThrow("positive scale");
    await expect(
      previewLocalPointCloudFile("p", valid, {
        ...calibration,
        calibration_evidence: " ",
      }),
    ).rejects.toThrow("calibration evidence");
    for (const uncertainty of [-0.1, 1.1, Number.NaN, Infinity]) {
      await expect(
        previewLocalPointCloudFile("p", valid, {
          ...calibration,
          relative_scale_uncertainty: uncertainty,
        }),
      ).rejects.toThrow("Relative scale uncertainty");
    }
    for (const invalidFrame of [
      "",
      "survey with spaces",
      "survey/1",
      "x".repeat(129),
    ]) {
      await expect(
        previewLocalPointCloudFile("p", valid, {
          ...calibration,
          coordinate_frame_id: invalidFrame,
        }),
      ).rejects.toThrow("Point-cloud source frame ID");
    }
    await expect(
      previewLocalPointCloudFile(
        "p",
        localFile("bad.ply", new Uint8Array([0xff])),
        calibration,
      ),
    ).rejects.toThrow();
    await expect(
      previewLocalPointCloudFile(
        "p",
        localFile("bad.ply", new Uint8Array([0xc3, 0xa9])),
        calibration,
      ),
    ).rejects.toThrow("Only ASCII PLY");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
