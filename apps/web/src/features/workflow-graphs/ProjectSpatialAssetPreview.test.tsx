import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectSpatialAssetPreview } from "./ProjectSpatialAssetPreview";
import {
  createSpatialAssetMetadataRevision,
  importProjectSpatialAsset,
  listSpatialAssetMetadataRevisions,
  listProjectSpatialAssets,
  previewProjectSpatialAsset,
} from "./workflowGraphApi";
import type { SpatialSourceAsset } from "./workflowGraphApi";

vi.mock("./workflowGraphApi", () => ({
  createSpatialAssetMetadataRevision: vi.fn(),
  importProjectSpatialAsset: vi.fn(),
  listSpatialAssetMetadataRevisions: vi.fn(),
  listProjectSpatialAssets: vi.fn(),
  previewProjectSpatialAsset: vi.fn(),
}));
vi.mock("./MeshArtifactViewer", () => ({
  MeshArtifactViewer: () => <p>Unreviewed mesh artifact</p>,
}));
vi.mock("./PointCloudArtifactViewer", () => ({
  PointCloudArtifactViewer: () => <p>Unreviewed cloud artifact</p>,
}));

const asset: SpatialSourceAsset = {
  id: "asset-1",
  project_id: "reef-project",
  original_filename: "colony.ply",
  source_format: "ply",
  source_kind: "mesh_or_point_cloud",
  sha256: "b".repeat(64),
  size_bytes: 256,
  created_at: "2026-10-28T00:00:00Z",
  measurement_status: "source_unreviewed",
  calibration_verified: false,
  specimen_identity_verified: false,
  parse_job_id: "parse-job-1",
  parse_status: "succeeded",
  parse_summary: {
    schema_version: "spatial-source-parse-0001",
    source_kind_resolved: "mesh",
    vertex_count: 3,
    face_count: 1,
    point_count: null,
    geometry_sha256: "d".repeat(64),
    qc_warnings: [
      "open_mesh_surface_not_enclosed",
      "physical_calibration_not_applied",
      "structural_parse_unreviewed",
    ],
    calibration_applied: false,
    calibration_verified: false,
    specimen_identity_verified: false,
  },
};

beforeEach(() => {
  vi.mocked(createSpatialAssetMetadataRevision).mockReset();
  vi.mocked(listProjectSpatialAssets).mockReset();
  vi.mocked(listSpatialAssetMetadataRevisions).mockReset();
  vi.mocked(importProjectSpatialAsset).mockReset();
  vi.mocked(previewProjectSpatialAsset).mockReset();
  vi.mocked(listProjectSpatialAssets).mockResolvedValue([asset]);
  vi.mocked(listSpatialAssetMetadataRevisions).mockResolvedValue([]);
  vi.mocked(createSpatialAssetMetadataRevision).mockResolvedValue({
    id: "metadata-1",
    project_id: "reef-project",
    spatial_source_asset_id: "asset-1",
    previous_revision_id: null,
    revision: 1,
    source_sha256: asset.sha256,
    coordinate_unit: "millimeter",
    meters_per_unit: 0.001,
    coordinate_frame_id: "survey-frame-A",
    transform_to_project_frame: null,
    calibration_evidence: "Unverified ruler reconstruction scale",
    review_state: "unreviewed",
    reviewed_by_identity: null,
    review_note: null,
    created_by_identity: "local_user",
    content_sha256: "c".repeat(64),
    created_at: "2026-11-15T00:00:00Z",
    reviewer_authenticated: false,
    calibration_verified: false,
    transform_verified: false,
  });
  vi.mocked(previewProjectSpatialAsset).mockResolvedValue({
    measurement_status: "caller_supplied_unverified",
  });
});

describe("ProjectSpatialAssetPreview", () => {
  it("shows bounded background parse status without claiming calibration", async () => {
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    await screen.findByRole("option", { name: /colony.ply/ });
    fireEvent.change(screen.getByLabelText("Project 3D source"), {
      target: { value: "asset-1" },
    });

    expect(
      await screen.findByText("Structural parse: Succeeded"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No physical calibration was applied/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/open mesh surface not enclosed/),
    ).toBeInTheDocument();
  });

  it("saves an immutable unit and coordinate-frame metadata revision", async () => {
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    await screen.findByRole("option", { name: /colony.ply/ });
    fireEvent.change(screen.getByLabelText("Project 3D source"), {
      target: { value: "asset-1" },
    });
    fireEvent.change(screen.getByLabelText("Source coordinate unit"), {
      target: { value: "millimeter" },
    });
    fireEvent.change(screen.getByLabelText("Source coordinate frame"), {
      target: { value: "survey-frame-A" },
    });
    fireEvent.change(screen.getByLabelText("Metadata calibration evidence"), {
      target: { value: "Unverified ruler reconstruction scale" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save metadata revision" }),
    );

    expect(
      await screen.findByText(/Metadata revision 1 saved/),
    ).toBeInTheDocument();
    expect(createSpatialAssetMetadataRevision).toHaveBeenCalledWith(
      "reef-project",
      "asset-1",
      expect.objectContaining({
        coordinate_unit: "millimeter",
        meters_per_unit: 0.001,
        coordinate_frame_id: "survey-frame-A",
        calibration_evidence: "Unverified ruler reconstruction scale",
        review_state: "unreviewed",
      }),
    );
  });

  it("selects an imported PLY and previews provisional point-cloud geometry", async () => {
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    await screen.findByRole("option", { name: /colony.ply/ });
    fireEvent.change(screen.getByLabelText("Project 3D source"), {
      target: { value: "asset-1" },
    });
    fireEvent.change(screen.getByLabelText("Preview geometry"), {
      target: { value: "point_cloud" },
    });
    fireEvent.change(screen.getByLabelText("Calibration method (unverified)"), {
      target: { value: "ruler" },
    });
    fireEvent.change(
      screen.getByLabelText("Calibration evidence (unverified)"),
      {
        target: { value: "Unreviewed ruler" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Preview imported source" }),
    );
    expect(
      await screen.findByText("Unreviewed cloud artifact"),
    ).toBeInTheDocument();
    expect(previewProjectSpatialAsset).toHaveBeenCalledWith(
      "reef-project",
      asset,
      "point_cloud",
      expect.objectContaining({
        meters_per_unit: 0.01,
        calibration_method: "ruler",
        calibration_evidence: "Unreviewed ruler",
        relative_scale_uncertainty: null,
      }),
    );
    expect(
      screen.getByText(/not calibration, biological identity, or review/),
    ).toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText("Meters per source unit (unverified)"),
      {
        target: { value: "0.02" },
      },
    );
    expect(
      screen.queryByText("Unreviewed cloud artifact"),
    ).not.toBeInTheDocument();
  });

  it("defaults to unknown calibration and invalidates results when method changes", async () => {
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    await screen.findByRole("option", { name: /colony.ply/ });
    fireEvent.change(screen.getByLabelText("Project 3D source"), {
      target: { value: "asset-1" },
    });
    fireEvent.change(
      screen.getByLabelText("Calibration evidence (unverified)"),
      {
        target: { value: "Unreviewed source metadata" },
      },
    );
    expect(
      screen.getByLabelText("Calibration method (unverified)"),
    ).toHaveValue("other");
    fireEvent.click(
      screen.getByRole("button", { name: "Preview imported source" }),
    );
    expect(
      await screen.findByText("Unreviewed mesh artifact"),
    ).toBeInTheDocument();
    expect(previewProjectSpatialAsset).toHaveBeenLastCalledWith(
      "reef-project",
      asset,
      "mesh",
      expect.objectContaining({ calibration_method: "other" }),
    );

    fireEvent.change(screen.getByLabelText("Calibration method (unverified)"), {
      target: { value: "instrument" },
    });
    expect(
      screen.queryByText("Unreviewed mesh artifact"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview imported source" }),
    );
    await waitFor(() =>
      expect(previewProjectSpatialAsset).toHaveBeenCalledTimes(2),
    );
    expect(previewProjectSpatialAsset).toHaveBeenLastCalledWith(
      "reef-project",
      asset,
      "mesh",
      expect.objectContaining({ calibration_method: "instrument" }),
    );
  });

  it("imports a new original and keeps scientific review explicitly pending", async () => {
    vi.mocked(listProjectSpatialAssets).mockResolvedValue([]);
    vi.mocked(importProjectSpatialAsset).mockResolvedValue(asset);
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    await waitFor(() => expect(listProjectSpatialAssets).toHaveBeenCalled());
    const file = new File(["ply"], "colony.ply");
    fireEvent.change(screen.getByLabelText("Import 3D original"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import original" }));
    expect(
      await screen.findByText(/human scientific review remains required/),
    ).toBeInTheDocument();
    expect(importProjectSpatialAsset).toHaveBeenCalledWith(
      "reef-project",
      file,
    );
    expect(screen.getByLabelText("Project 3D source")).toHaveValue("asset-1");
  });

  it("resets selection and measurement evidence when switching projects", async () => {
    vi.mocked(listProjectSpatialAssets)
      .mockResolvedValueOnce([asset])
      .mockResolvedValueOnce([]);
    const view = render(
      <ProjectSpatialAssetPreview projectId="reef-project" />,
    );
    await screen.findByRole("option", { name: /colony.ply/ });
    fireEvent.change(screen.getByLabelText("Project 3D source"), {
      target: { value: "asset-1" },
    });
    view.rerender(<ProjectSpatialAssetPreview projectId="other-project" />);
    await waitFor(() =>
      expect(listProjectSpatialAssets).toHaveBeenCalledWith(
        "other-project",
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByLabelText("Project 3D source")).toHaveValue("");
    expect(
      screen.queryByRole("option", { name: /colony.ply/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps project originals when an upload fails before listing finishes", async () => {
    let resolveList!: (records: SpatialSourceAsset[]) => void;
    vi.mocked(listProjectSpatialAssets).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveList = resolve;
        }),
    );
    vi.mocked(importProjectSpatialAsset).mockRejectedValue(
      new Error("Upload unavailable"),
    );
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    const file = new File(["ply"], "another.ply");
    fireEvent.change(screen.getByLabelText("Import 3D original"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import original" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Upload unavailable",
    );
    await act(async () => {
      resolveList([asset]);
    });
    expect(
      await screen.findByRole("option", { name: /colony.ply/ }),
    ).toBeInTheDocument();
  });

  it("preserves a completed import when an older empty asset list arrives", async () => {
    let resolveList!: (records: SpatialSourceAsset[]) => void;
    vi.mocked(listProjectSpatialAssets).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveList = resolve;
        }),
    );
    vi.mocked(importProjectSpatialAsset).mockResolvedValue(asset);
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    const file = new File(["ply"], "colony.ply");
    fireEvent.change(screen.getByLabelText("Import 3D original"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import original" }));
    expect(
      await screen.findByText(/human scientific review remains required/),
    ).toBeInTheDocument();
    await act(async () => {
      resolveList([]);
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Project 3D source")).toHaveValue("asset-1"),
    );
    expect(
      screen.getByRole("option", { name: /colony.ply/ }),
    ).toBeInTheDocument();
  });

  it("does not expose cross-project originals returned by a stale list", async () => {
    vi.mocked(listProjectSpatialAssets).mockResolvedValue([
      asset,
      { ...asset, id: "foreign-asset", project_id: "another-project" },
    ]);
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    expect(
      await screen.findByRole("option", { name: /colony.ply/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /foreign-/ }),
    ).not.toBeInTheDocument();
  });

  it("rejects imported originals whose response belongs to another project", async () => {
    vi.mocked(listProjectSpatialAssets).mockResolvedValue([]);
    vi.mocked(importProjectSpatialAsset).mockResolvedValue({
      ...asset,
      project_id: "foreign-project",
    });
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    const file = new File(["ply"], "colony.ply");
    fireEvent.change(screen.getByLabelText("Import 3D original"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import original" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid project ownership or unreviewed provenance",
    );
    expect(screen.getByLabelText("Project 3D source")).toHaveValue("");
    expect(
      screen.queryByRole("option", { name: /colony.ply/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/human scientific review remains required/),
    ).not.toBeInTheDocument();
  });

  it("rejects imported originals with invalid integrity digests", async () => {
    vi.mocked(listProjectSpatialAssets).mockResolvedValue([]);
    vi.mocked(importProjectSpatialAsset).mockResolvedValue({
      ...asset,
      sha256: "not-a-digest",
    });
    render(<ProjectSpatialAssetPreview projectId="reef-project" />);
    const file = new File(["ply"], "colony.ply");
    fireEvent.change(screen.getByLabelText("Import 3D original"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import original" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid project ownership or unreviewed provenance",
    );
    expect(screen.getByLabelText("Project 3D source")).toHaveValue("");
  });
});
