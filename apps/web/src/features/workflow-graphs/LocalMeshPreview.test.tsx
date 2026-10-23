import { fireEvent, render, screen } from "@testing-library/react";
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
    const file = new File(["v 0 0 0"], "reef.obj", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [file] },
    });
    fireEvent.change(screen.getByLabelText("Calibration evidence (unverified)"), {
      target: { value: "Ruler visible, awaiting review" },
    });
    fireEvent.click(button);
    expect(await screen.findByText("Saved preview rendered")).toBeInTheDocument();
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
    vi.mocked(previewLocalMeshFile).mockRejectedValue(new Error("Malformed PLY"));
    render(<LocalMeshPreview projectId="reef-project" />);
    fireEvent.change(screen.getByLabelText("Mesh file"), {
      target: { files: [new File(["bad"], "reef.ply")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview mesh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Malformed PLY");
    expect(screen.queryByText("Saved preview rendered")).not.toBeInTheDocument();
  });
});
