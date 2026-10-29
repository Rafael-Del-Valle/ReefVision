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
  importProjectSpatialAsset,
  listProjectSpatialAssets,
  previewProjectSpatialAsset,
} from "./workflowGraphApi";
import type { SpatialSourceAsset } from "./workflowGraphApi";

vi.mock("./workflowGraphApi", () => ({
  importProjectSpatialAsset: vi.fn(),
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
};

beforeEach(() => {
  vi.mocked(listProjectSpatialAssets).mockReset();
  vi.mocked(importProjectSpatialAsset).mockReset();
  vi.mocked(previewProjectSpatialAsset).mockReset();
  vi.mocked(listProjectSpatialAssets).mockResolvedValue([asset]);
  vi.mocked(previewProjectSpatialAsset).mockResolvedValue({
    measurement_status: "caller_supplied_unverified",
  });
});

describe("ProjectSpatialAssetPreview", () => {
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
