import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PairedGrowthContrast } from "./PairedGrowthContrast";
import { calculatePairedContrast } from "./pairedGrowthContrastApi";
import type { EcologyAnalysis } from "./ecologyAnalysisApi";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";

vi.mock("./pairedGrowthContrastApi", async (original) => ({
  ...(await original<typeof import("./pairedGrowthContrastApi")>()),
  calculatePairedContrast: vi.fn(),
}));
vi.mock("../workflow-graphs/workflowGraphApi", () => ({
  saveWorkflowGraph: vi.fn(),
}));

const source: EcologyAnalysis = {
  id: "growth-1",
  content_sha256: "a".repeat(64),
  source_id_map: {},
  supersedes_id: null,
  created_at: "2026-09-21T00:00:00Z",
  stale: false,
  stale_reason: null,
  snapshot: {
    reviewed_by: "Reviewer",
    review_note: "Reviewed fixture",
    method_version: "test",
    limitations: [],
    selection: {
      kind: "growth",
      metric: "box_width",
      sources: [],
      sampling_plan: [
        {
          experimental_unit_id: "Tank A",
          organism_keys: ["A1", "A2"],
          dates: ["2026-09-01", "2026-09-15", "2026-09-20"],
        },
        {
          experimental_unit_id: "Tank B",
          organism_keys: ["B1"],
          dates: ["2026-09-01", "2026-09-15"],
        },
      ],
    },
    result: {
      kind: "growth",
      observations: [],
      changes: [],
      population_summaries: [],
      exclusions: [],
    },
  },
};

function renderContrast(analysis = source) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PairedGrowthContrast projectId="project-1" analysis={analysis} />
    </QueryClientProvider>,
  );
}

it("binds a declared two-visit analysis to its frozen source and saves the same design for replay", async () => {
  renderContrast();
  fireEvent.click(screen.getByText("Repeated measures"));
  const calculate = screen.getByRole("button", {
    name: "Calculate paired contrast",
  });
  expect(calculate).toBeDisabled();
  expect(
    screen.queryByRole("option", { name: "2026-09-20" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Baseline UTC date"), {
    target: { value: "2026-09-01" },
  });
  fireEvent.change(screen.getByLabelText("Follow-up UTC date"), {
    target: { value: "2026-09-15" },
  });
  fireEvent.change(screen.getByLabelText("Independent unit type"), {
    target: { value: "tank" },
  });
  fireEvent.change(screen.getByLabelText("Declared estimand"), {
    target: { value: "Mean change in width across tanks" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Exclude a unit/ }));
  const design = {
    baseline_date: "2026-09-01",
    followup_date: "2026-09-15",
    experimental_unit_type: "tank",
    estimand: "Mean change in width across tanks",
    missingness_policy: "complete_unit" as const,
  };
  vi.mocked(calculatePairedContrast).mockResolvedValue({
    analysis_id: source.id,
    source_sha256: source.content_sha256,
    design,
    metric: "box_width",
    unit: "m",
    method_version: "paired-growth-contrast-0001",
    units: [],
    planned_unit_count: 2,
    included_unit_count: 2,
    mean_difference: 0.003,
    standard_error: 0.001,
    degrees_of_freedom: 1,
    interval_status: "available",
    confidence_interval_95: [-0.0097, 0.0157],
    assumptions: ["Independent units"],
    method_reference:
      "https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm",
    report_sha256: "b".repeat(64),
    source_exclusions: [],
  });
  fireEvent.click(calculate);
  expect(
    await screen.findByRole("heading", { name: "Paired contrast result" }),
  ).toBeVisible();
  expect(calculatePairedContrast).toHaveBeenCalledWith(
    "project-1",
    "growth-1",
    { ...design, source_sha256: source.content_sha256 },
    expect.any(AbortSignal),
  );
  vi.mocked(saveWorkflowGraph).mockResolvedValue({
    id: "graph-1",
    project_id: "project-1",
    graph_key: "g",
    name: "Paired growth contrast",
    schema_version: "1",
    revision: 1,
    graph_json: {},
    graph_sha256: "c".repeat(64),
    created_at: "",
    updated_at: "",
  });
  fireEvent.click(screen.getByRole("button", { name: "Save paired workflow" }));
  await waitFor(() =>
    expect(saveWorkflowGraph).toHaveBeenCalledWith(
      "project-1",
      expect.objectContaining({
        nodes: expect.arrayContaining([
          expect.objectContaining({
            node_type: "paired_growth_contrast",
            parameters: {
              analysis_id: source.id,
              source_sha256: source.content_sha256,
              ...design,
            },
          }),
        ]),
      }),
    ),
  );
  fireEvent.change(screen.getByLabelText("Baseline UTC date"), {
    target: { value: "2026-09-15" },
  });
  expect(calculate).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Save paired workflow" }),
  ).not.toBeInTheDocument();
});

it("explains why a previously saved analysis without a sampling plan cannot be paired", () => {
  renderContrast({
    ...source,
    snapshot: {
      ...source.snapshot,
      selection: { kind: "growth", metric: "box_width", sources: [] },
    },
  });
  fireEvent.click(screen.getByText("Repeated measures"));
  expect(
    screen.getByText(/Save a growth analysis with a sampling plan/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Calculate paired contrast" }),
  ).not.toBeInTheDocument();
});
