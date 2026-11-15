import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { EcologyAnalysisPanel } from "./EcologyAnalysisPanel";
import { listEcologyAnalyses, saveEcologyAnalysis } from "./ecologyAnalysisApi";

vi.mock("./ecologyAnalysisApi", () => ({
  listEcologyAnalyses: vi.fn(async () => ({ items: [], total: 0 })),
  saveEcologyAnalysis: vi.fn(),
  ecologyAnalysisDownload: vi.fn(),
}));

it("requires explicit review and saves source selections with exclusion reasons", async () => {
  vi.mocked(saveEcologyAnalysis).mockRejectedValue(
    new Error("Missing followed-up visit"),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <EcologyAnalysisPanel
        projectId="project-1"
        registry={{
          identities: [],
          identity_history: [],
          image_evidence_links: [],
          annotation_evidence_links: [],
          calibration_evidence_links: [
            {
              id: "visit-1",
              annotation_evidence_id: "a",
              calibration_sha256: "a",
            },
            {
              id: "visit-2",
              annotation_evidence_id: "b",
              calibration_sha256: "b",
            },
          ],
          snapshot_sha256: "x",
          design_change_count: 0,
        }}
        images={[]}
        classes={[]}
      />
    </QueryClientProvider>,
  );
  expect(listEcologyAnalyses).toHaveBeenCalled();
  const save = screen.getByRole("button", { name: "Review and save analysis" });
  expect(save).toBeDisabled();
  for (const checkbox of screen.getAllByRole("checkbox", { name: /Visit/ })) {
    fireEvent.click(checkbox);
  }
  fireEvent.change(screen.getByLabelText("Exclude visit-2"), {
    target: { value: "Occluded colony" },
  });
  fireEvent.change(screen.getByLabelText("Reviewed by"), {
    target: { value: "Scientist" },
  });
  fireEvent.change(screen.getByLabelText("Review notes"), {
    target: { value: "Checked specimen and calibration on both dates." },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /confirm/i }));
  fireEvent.click(save);
  await waitFor(() =>
    expect(saveEcologyAnalysis).toHaveBeenCalledWith(
      "project-1",
      expect.objectContaining({
        reviewed_by: "Scientist",
        confirm_reviewed_selection: true,
        selection: {
          kind: "growth",
          metric: "mask_projected_area",
          sources: [
            { calibration_evidence_id: "visit-1" },
            {
              calibration_evidence_id: "visit-2",
              exclusion_reason: "Occluded colony",
            },
          ],
        },
      }),
    ),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Missing followed-up visit",
  );
});
