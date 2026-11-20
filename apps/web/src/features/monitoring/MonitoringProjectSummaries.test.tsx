import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getProjectSummaries } from "../../api/client";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  createMonitoringSummary,
  getMonitoringSummary,
  listMonitoringAssessments,
  listMonitoringSummaries,
  type MonitoringAssessment,
  type MonitoringSummary,
} from "./monitoringApi";
import { MonitoringProjectSummaries } from "./MonitoringProjectSummaries";

vi.mock("../../api/client", () => ({ getProjectSummaries: vi.fn() }));
vi.mock("../workflow-graphs/workflowGraphApi", () => ({
  saveWorkflowGraph: vi.fn(),
}));
vi.mock("./monitoringApi", () => ({
  createMonitoringSummary: vi.fn(),
  downloadMonitoringSummary: vi.fn(),
  getMonitoringSummary: vi.fn(),
  listMonitoringAssessments: vi.fn(),
  listMonitoringSummaries: vi.fn(),
}));

const projectA = "reef-a";
const projectB = "reef-b";
const start = "2026-10-09T13:00:00Z";
const end = "2026-10-09T13:05:00Z";
const digest = "a".repeat(64);

function assessment(projectId: string): MonitoringAssessment {
  return {
    id: `assessment-${projectId}`,
    project_id: projectId,
    rule_id: `rule-${projectId}`,
    window_start: start,
    window_end: end,
    result_sha256: digest,
    evidence_sha256: "b".repeat(64),
    created_at: end,
    source_status: "current",
    stale_reasons: [],
    result: {
      schema_version: "monitoring-assessment-0001",
      kind: "environmental",
      protocol: "minute-temperature",
      metric: "water_temperature",
      unit: projectId === projectA ? "degC" : "degF",
      estimate: 21,
      effort: { expected_slots: 5, observed_slots: 4 },
      source_refs: [],
      exclusions: [],
      findings: [],
    },
  };
}

const summary: MonitoringSummary = {
  id: "summary-id",
  project_id: projectA,
  created_at: end,
  content_sha256: digest,
  snapshot: {
    schema_version: "monitoring-comparison-1.7",
    reference_project_id: projectA,
    rows: [projectA, projectB].map((project_id, index) => ({
      project_id,
      project_name: index === 0 ? "North reef" : "South reef",
      assessment_id: assessment(project_id).id,
      rule_id: `rule-${project_id}`,
      rule_sha256: digest,
      protocol: "minute-temperature",
      metric: "water_temperature",
      unit: index === 0 ? "degC" : "degF",
      window_start: start,
      window_end: end,
      kind: "environmental",
      status: index === 0 ? "included" : "excluded",
      reasons: index ? ["Units are incompatible."] : [],
      result_sha256: digest,
      evidence_sha256: "b".repeat(64),
      effort: { observed_slots: index ? 5 : 4 },
      values: {
        estimate: index ? 69.8 : 21,
        method: "Observed mean",
        source_refs: [],
        independent_units: [],
        exclusions: [],
        rule_parameters: {},
      },
      review: {
        proposed: 0,
        confirmed: index ? 0 : 1,
        dismissed: 0,
        alerts: [],
      },
    })),
  },
};

function renderSummaries() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MonitoringProjectSummaries projectId={projectA} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  const projects = [projectA, projectB].map((id, index) => ({
    id,
    name: index ? "South reef" : "North reef",
    archived_at: null,
  }));
  vi.mocked(getProjectSummaries).mockResolvedValue(
    projects as Awaited<ReturnType<typeof getProjectSummaries>>,
  );
  vi.mocked(listMonitoringAssessments).mockImplementation(async (id) => ({
    items: [assessment(id)],
    total: 1,
    limit: 50,
    offset: 0,
  }));
  vi.mocked(listMonitoringSummaries).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(createMonitoringSummary).mockResolvedValue(summary);
  vi.mocked(getMonitoringSummary).mockResolvedValue(summary);
});

describe("monitoring project summaries", () => {
  it("sends the reference first and keeps each project's unit, effort and reviewed state visible", async () => {
    renderSummaries();
    const compare = screen.getByRole("button", { name: "Compare projects" });
    expect(compare).toBeDisabled();
    await screen.findByRole("option", { name: /water temperature.*degC/ });
    fireEvent.change(screen.getByLabelText("Reference assessment"), {
      target: { value: assessment(projectA).id },
    });
    fireEvent.change(screen.getByLabelText("Comparison project 1"), {
      target: { value: projectB },
    });
    await screen.findByRole("option", { name: /water temperature.*degF/ });
    fireEvent.change(screen.getByLabelText("Comparison assessment 1"), {
      target: { value: assessment(projectB).id },
    });
    fireEvent.click(compare);
    await waitFor(() =>
      expect(createMonitoringSummary).toHaveBeenCalledWith(projectA, [
        { project_id: projectA, assessment_id: assessment(projectA).id },
        { project_id: projectB, assessment_id: assessment(projectB).id },
      ]),
    );
    const north = await screen.findByRole("article", { name: "North reef" });
    const south = screen.getByRole("article", { name: "South reef" });
    expect(within(north).getByText("Included")).toBeVisible();
    expect(within(north).getByText("degC")).toBeVisible();
    expect(within(north).getByText("4")).toBeVisible();
    expect(within(south).getByText("Excluded")).toBeVisible();
    expect(within(south).getByText("degF")).toBeVisible();
    expect(within(south).getByText("5")).toBeVisible();
    expect(within(south).getByText("Units are incompatible.")).toBeVisible();
  });

  it("reopens a persisted summary and saves the exact replay pin", async () => {
    vi.mocked(listMonitoringSummaries).mockResolvedValue({
      items: [summary],
      total: 1,
    });
    vi.mocked(saveWorkflowGraph).mockResolvedValue({
      name: "Monitoring project summary",
    } as Awaited<ReturnType<typeof saveWorkflowGraph>>);
    renderSummaries();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open project summary 2026-10-09 13:05:00 UTC",
      }),
    );
    await waitFor(() =>
      expect(getMonitoringSummary).toHaveBeenCalledWith(
        projectA,
        summary.id,
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Save summary workflow" }),
    );
    await waitFor(() =>
      expect(saveWorkflowGraph).toHaveBeenCalledWith(
        projectA,
        expect.objectContaining({
          nodes: expect.arrayContaining([
            {
              node_id: "summary",
              node_type: "monitoring_project_summary",
              parameters: { summary_id: summary.id, content_sha256: digest },
            },
          ]),
        }),
      ),
    );
  });
});
