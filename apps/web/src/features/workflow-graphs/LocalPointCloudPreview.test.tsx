import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocalPointCloudPreview } from "./LocalPointCloudPreview";
import { previewLocalPointCloudFile } from "./workflowGraphApi";

vi.mock("./workflowGraphApi", () => ({
  previewLocalPointCloudFile: vi.fn(),
}));
vi.mock("./PointCloudArtifactViewer", () => ({
  PointCloudArtifactViewer: () => <p>Provisional point-cloud viewer</p>,
}));

beforeEach(() => {
  vi.mocked(previewLocalPointCloudFile).mockReset();
});

describe("LocalPointCloudPreview", () => {
  it("shows a temporary viewer and passes unverified calibration evidence", async () => {
    vi.mocked(previewLocalPointCloudFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    render(<LocalPointCloudPreview projectId="reef-project" />);
    const button = screen.getByRole("button", { name: "Preview point cloud" });
    expect(button).toBeDisabled();
    const file = new File(["ply"], "reef.ply");
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [file] },
    });
    fireEvent.change(
      screen.getByLabelText("Point-cloud calibration evidence (unverified)"),
      { target: { value: "Unreviewed ruler in image" } },
    );
    fireEvent.change(
      screen.getByLabelText(
        "Point-cloud source coordinate frame ID (unverified, optional)",
      ),
      { target: { value: "transect-7" } },
    );
    fireEvent.click(button);
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    expect(previewLocalPointCloudFile).toHaveBeenCalledWith(
      "reef-project",
      file,
      expect.objectContaining({
        meters_per_unit: 0.01,
        calibration_method: "ruler",
        calibration_evidence: "Unreviewed ruler in image",
        coordinate_frame_id: "transect-7",
        relative_scale_uncertainty: null,
      }),
      undefined,
    );
    expect(screen.getByText(/Standalone preview only/)).toBeInTheDocument();
  });

  it("clears a stale preview when the source frame changes", async () => {
    vi.mocked(previewLocalPointCloudFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    render(<LocalPointCloudPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["ply"], "reef.ply")] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText(
        "Point-cloud source coordinate frame ID (unverified, optional)",
      ),
      { target: { value: "survey-2" } },
    );
    expect(
      screen.queryByText("Provisional point-cloud viewer"),
    ).not.toBeInTheDocument();
  });

  it("passes original source indices for provisional straight-line chords", async () => {
    vi.mocked(previewLocalPointCloudFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    render(<LocalPointCloudPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["ply"], "reef.ply")] },
    });
    fireEvent.change(screen.getByLabelText("Chord start source point index"), {
      target: { value: "0" },
    });
    fireEvent.change(screen.getByLabelText("Chord end source point index"), {
      target: { value: "1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    expect(previewLocalPointCloudFile).toHaveBeenCalledWith(
      "reef-project",
      expect.any(File),
      expect.objectContaining({ meters_per_unit: 0.01 }),
      [[0, 1]],
    );
    expect(
      screen.getByText(/not anatomical branch length/),
    ).toBeInTheDocument();
  });

  it("pins selected chord endpoints only after explicit display opt-in", async () => {
    vi.mocked(previewLocalPointCloudFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    render(<LocalPointCloudPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["ply"], "reef.ply")] },
    });
    fireEvent.change(screen.getByLabelText("Chord start source point index"), {
      target: { value: "100" },
    });
    fireEvent.change(screen.getByLabelText("Chord end source point index"), {
      target: { value: "511" },
    });
    const checkbox = screen.getByRole("checkbox", {
      name: /Keep selected chord endpoints visible/,
    });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    expect(previewLocalPointCloudFile).toHaveBeenCalledWith(
      "reef-project",
      expect.any(File),
      expect.objectContaining({ calibration_method: "ruler" }),
      [[100, 511]],
      true,
    );
    fireEvent.click(checkbox);
    expect(
      screen.queryByText("Provisional point-cloud viewer"),
    ).not.toBeInTheDocument();
  });

  it("requires both source indices before sending a chord request", async () => {
    render(<LocalPointCloudPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["ply"], "reef.ply")] },
    });
    fireEvent.change(screen.getByLabelText("Chord start source point index"), {
      target: { value: "0" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "both source point indices",
    );
    expect(previewLocalPointCloudFile).not.toHaveBeenCalled();
  });

  it("discards stale results when the file or calibration changes", async () => {
    const deferred: { resolve?: (value: Record<string, unknown>) => void } = {};
    vi.mocked(previewLocalPointCloudFile).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deferred.resolve = resolve;
        }),
    );
    render(<LocalPointCloudPreview projectId="reef-project" />);
    const input = screen.getByLabelText("Point-cloud file");
    const button = screen.getByRole("button", { name: "Preview point cloud" });
    fireEvent.change(input, {
      target: { files: [new File(["old"], "old.ply")] },
    });
    fireEvent.click(button);
    expect(button).toBeDisabled();
    fireEvent.change(
      screen.getByLabelText("Point-cloud calibration evidence (unverified)"),
      { target: { value: "New ruler evidence" } },
    );
    await act(async () => {
      deferred.resolve?.({ measurement_status: "caller_supplied_unverified" });
    });
    expect(
      screen.queryByText("Provisional point-cloud viewer"),
    ).not.toBeInTheDocument();
    expect(button).toBeEnabled();
    vi.mocked(previewLocalPointCloudFile).mockResolvedValueOnce({});
    fireEvent.click(button);
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    expect(previewLocalPointCloudFile).toHaveBeenLastCalledWith(
      "reef-project",
      expect.any(File),
      expect.objectContaining({ calibration_evidence: "New ruler evidence" }),
      undefined,
    );
  });

  it("isolates pending previews when the project changes", async () => {
    const deferred: { resolve?: (value: Record<string, unknown>) => void } = {};
    vi.mocked(previewLocalPointCloudFile).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deferred.resolve = resolve;
        }),
    );
    const { rerender } = render(
      <LocalPointCloudPreview projectId="original-project" />,
    );
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["old"], "old.ply")] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    rerender(<LocalPointCloudPreview projectId="new-project" />);
    expect(
      screen.getByRole("button", { name: "Preview point cloud" }),
    ).toBeDisabled();
    await act(async () => {
      deferred.resolve?.({ measurement_status: "caller_supplied_unverified" });
    });
    expect(
      screen.queryByText("Provisional point-cloud viewer"),
    ).not.toBeInTheDocument();
    vi.mocked(previewLocalPointCloudFile).mockResolvedValueOnce({});
    const replacement = new File(["new"], "new.ply");
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [replacement] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(
      await screen.findByText("Provisional point-cloud viewer"),
    ).toBeInTheDocument();
    expect(previewLocalPointCloudFile).toHaveBeenLastCalledWith(
      "new-project",
      replacement,
      expect.objectContaining({ calibration_evidence: "" }),
      undefined,
    );
  });

  it("shows errors without retaining old scientific preview geometry", async () => {
    vi.mocked(previewLocalPointCloudFile).mockRejectedValue(
      new Error("Point-cloud PLY must have one vertex-only element"),
    );
    render(<LocalPointCloudPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Point-cloud file"), {
      target: { files: [new File(["bad"], "bad.ply")] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview point cloud" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("vertex-only");
    expect(
      screen.queryByText("Provisional point-cloud viewer"),
    ).not.toBeInTheDocument();
  });
});
