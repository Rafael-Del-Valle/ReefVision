import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocalMeshPreview } from "./LocalMeshPreview";
import { previewLocalMeshFile } from "./workflowGraphApi";

vi.mock("./workflowGraphApi", () => ({
  previewLocalMeshFile: vi.fn(),
}));
vi.mock("./MeshArtifactViewer", () => ({
  MeshArtifactViewer: () => <p>Saved preview rendered</p>,
}));

beforeEach(() => {
  vi.mocked(previewLocalMeshFile).mockReset();
});

describe("LocalMeshPreview", () => {
  it("requires a file and retains explicitly unverified evidence", async () => {
    vi.mocked(previewLocalMeshFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    render(<LocalMeshPreview projectId="reef-project" />);
    const button = screen.getByRole("button", { name: "Preview mesh" });
    expect(button).toBeDisabled();
    const file = new File(["v 0 0 0"], "reef.obj", {
      type: "text/plain",
    });
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [file] },
    });
    fireEvent.change(
      screen.getByLabelText("Calibration evidence (unverified)"),
      {
        target: { value: "Ruler visible, awaiting review" },
      },
    );
    fireEvent.click(button);
    expect(
      await screen.findByText("Saved preview rendered"),
    ).toBeInTheDocument();
    expect(previewLocalMeshFile).toHaveBeenCalledWith(
      "reef-project",
      file,
      expect.objectContaining({
        meters_per_unit: 0.01,
        calibration_method: "ruler",
        calibration_evidence: "Ruler visible, awaiting review",
        relative_scale_uncertainty: null,
      }),
    );
    expect(screen.getByText(/Standalone preview only/)).toBeInTheDocument();
  });

  it("reports an import failure without displaying fabricated geometry", async () => {
    vi.mocked(previewLocalMeshFile).mockRejectedValue(
      new Error("Malformed PLY"),
    );
    render(<LocalMeshPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [new File(["bad"], "reef.ply")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview mesh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Malformed PLY");
    expect(
      screen.queryByText("Saved preview rendered"),
    ).not.toBeInTheDocument();
  });
  it("discards late results after a file or calibration change", async () => {
    const deferred: {
      resolve?: (value: Record<string, unknown>) => void;
    } = {};
    vi.mocked(previewLocalMeshFile).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deferred.resolve = resolve;
        }),
    );
    render(<LocalMeshPreview projectId="reef-project" />);
    const fileInput = screen.getByLabelText("Mesh file");
    const button = screen.getByRole("button", { name: "Preview mesh" });
    const original = new File(["old"], "old.obj");
    const replacement = new File(["new"], "new.obj");
    fireEvent.change(fileInput, { target: { files: [original] } });
    fireEvent.click(button);
    expect(button).toBeDisabled();

    fireEvent.change(fileInput, { target: { files: [replacement] } });
    fireEvent.change(
      screen.getByLabelText("Calibration evidence (unverified)"),
      {
        target: { value: "New ruler evidence awaiting review" },
      },
    );
    expect(button).toBeEnabled();
    await act(async () => {
      deferred.resolve?.({ measurement_status: "caller_supplied_unverified" });
    });
    expect(
      screen.queryByText("Saved preview rendered"),
    ).not.toBeInTheDocument();

    vi.mocked(previewLocalMeshFile).mockResolvedValue({
      measurement_status: "caller_supplied_unverified",
    });
    fireEvent.click(button);
    expect(
      await screen.findByText("Saved preview rendered"),
    ).toBeInTheDocument();
    expect(previewLocalMeshFile).toHaveBeenLastCalledWith(
      "reef-project",
      replacement,
      expect.objectContaining({
        calibration_evidence: "New ruler evidence awaiting review",
      }),
    );
  });

  it("isolates provisional geometry and pending results across project changes", async () => {
    const deferred: {
      resolve?: (value: Record<string, unknown>) => void;
    } = {};
    vi.mocked(previewLocalMeshFile).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deferred.resolve = resolve;
        }),
    );
    const { rerender } = render(
      <LocalMeshPreview projectId="original-project" />,
    );
    const original = new File(["old"], "old.obj");
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [original] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview mesh" }));
    expect(previewLocalMeshFile).toHaveBeenCalledWith(
      "original-project",
      original,
      expect.any(Object),
    );

    rerender(<LocalMeshPreview projectId="new-project" />);
    expect(screen.getByRole("button", { name: "Preview mesh" })).toBeDisabled();
    await act(async () => {
      deferred.resolve?.({ measurement_status: "caller_supplied_unverified" });
    });
    expect(
      screen.queryByText("Saved preview rendered"),
    ).not.toBeInTheDocument();

    const replacement = new File(["new"], "new.ply");
    vi.mocked(previewLocalMeshFile).mockResolvedValueOnce({
      measurement_status: "caller_supplied_unverified",
    });
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [replacement] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview mesh" }));
    expect(
      await screen.findByText("Saved preview rendered"),
    ).toBeInTheDocument();
    expect(previewLocalMeshFile).toHaveBeenLastCalledWith(
      "new-project",
      replacement,
      expect.objectContaining({ calibration_evidence: "" }),
    );
  });
});
