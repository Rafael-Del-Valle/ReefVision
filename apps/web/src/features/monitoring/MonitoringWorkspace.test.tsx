import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listEventSummaries } from "../ecology/EventSummaryPanel";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  createMonitoringAssessment,
  createMonitoringRule,
  getMonitoringAssessment,
  getMonitoringRule,
  listMonitoringAlerts,
  listMonitoringAssessments,
  listMonitoringReviews,
  listMonitoringRules,
  reviewMonitoringAlert,
  type MonitoringAlert,
  type MonitoringAssessment,
  type MonitoringReview,
  type MonitoringRule,
} from "./monitoringApi";
import { MonitoringWorkspace } from "./MonitoringWorkspace";

vi.mock("../ecology/EventSummaryPanel", () => ({
  listEventSummaries: vi.fn(),
}));
vi.mock("../workflow-graphs/workflowGraphApi", () => ({
  saveWorkflowGraph: vi.fn(),
}));
vi.mock("./monitoringApi", () => ({
  listMonitoringRules: vi.fn(),
  getMonitoringRule: vi.fn(),
  createMonitoringRule: vi.fn(),
  listMonitoringAssessments: vi.fn(),
  getMonitoringAssessment: vi.fn(),
  createMonitoringAssessment: vi.fn(),
  listMonitoringAlerts: vi.fn(),
  listMonitoringReviews: vi.fn(),
  reviewMonitoringAlert: vi.fn(),
}));

const projectId = "local-project";
const start = "2026-10-09T13:00:00Z";
const end = "2026-10-09T13:05:00Z";
const hash = (value: string) => value.repeat(64);
const rule: MonitoringRule = {
  id: "rule-one",
  project_id: projectId,
  label: "Hourly temperature",
  protocol: "minute-temperature",
  metric: "water_temperature",
  unit: "degC",
  kind: "environmental",
  parameters: { cadence_seconds: 60, upper_limit: 21, source_kind: "observed" },
  rule_sha256: hash("f"),
  created_at: start,
};
const assessment: MonitoringAssessment = {
  id: "assessment-one",
  project_id: projectId,
  rule_id: rule.id,
  window_start: start,
  window_end: end,
  evidence_sha256: hash("b"),
  result_sha256: hash("c"),
  created_at: end,
  source_status: "current",
  stale_reasons: [],
  result: {
    schema_version: "monitoring-assessment-0001",
    protocol: rule.protocol,
    metric: rule.metric,
    unit: rule.unit,
    kind: rule.kind,
    estimate: 20.5,
    effort: { expected_slots: 5, observed_slots: 4, accepted_observations: 4 },
    source_refs: [
      {
        kind: "scientific_record",
        id: "source-one",
        sha256: hash("d"),
        observed_at: start,
      },
    ],
    exclusions: [],
    findings: [
      {
        kind: "upper_limit",
        finding_key: "upper-one",
        detail: "Upper limit exceeded",
        value: 22,
        threshold: 21,
      },
    ],
  },
};
const finding: MonitoringAlert = {
  id: "alert-one",
  project_id: projectId,
  assessment_id: assessment.id,
  kind: "upper_limit",
  finding_key: "upper-one",
  proposal: assessment.result.findings[0],
  proposal_sha256: hash("a"),
  created_at: end,
  status: "proposed",
  review_revision: 0,
  latest_review: null,
  source_status: "current",
};
const review: MonitoringReview = {
  id: "review-one",
  project_id: projectId,
  alert_id: finding.id,
  reviewer: "Local reviewer",
  decision: "confirmed",
  reason: "Checked the original logger",
  revision: 1,
  reviewed_at: end,
};

function pageOf<T>(items: T[]) {
  return { items, total: items.length, limit: 50, offset: 0 };
}

function renderMonitoring() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MonitoringWorkspace projectId={projectId} />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: true }), {
    target: { value },
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listMonitoringRules).mockResolvedValue(pageOf([]));
  vi.mocked(listMonitoringAssessments).mockResolvedValue(pageOf([]));
  vi.mocked(listMonitoringAlerts).mockResolvedValue(pageOf([finding]));
  vi.mocked(listMonitoringReviews).mockResolvedValue(pageOf([]));
  vi.mocked(getMonitoringRule).mockResolvedValue(rule);
  vi.mocked(getMonitoringAssessment).mockResolvedValue(assessment);
  vi.mocked(createMonitoringRule).mockResolvedValue(rule);
  vi.mocked(createMonitoringAssessment).mockResolvedValue(assessment);
});

describe("monitoring workspace", () => {
  it("creates an environmental rule and assesses a literal UTC window using its hash", async () => {
    renderMonitoring();
    fireEvent.click(
      screen.getByRole("button", { name: "New monitoring rule" }),
    );
    fill("Rule name", rule.label);
    fill("Protocol", rule.protocol);
    fill("Metric", rule.metric);
    fill("Unit", rule.unit);
    fill("Cadence (seconds)", "60");
    fill("Upper limit", "21");
    fireEvent.click(
      screen.getByRole("button", { name: "Create monitoring rule" }),
    );
    await waitFor(() =>
      expect(createMonitoringRule).toHaveBeenCalledWith(projectId, {
        label: rule.label,
        protocol: rule.protocol,
        metric: rule.metric,
        unit: rule.unit,
        kind: "environmental",
        parameters: {
          cadence_seconds: 60,
          upper_limit: 21,
          source_kind: "observed",
        },
      }),
    );
    fill("Window start (UTC)", "2026-10-09T13:00");
    fill("Window end (UTC)", "2026-10-09T13:05");
    fireEvent.click(
      screen.getByRole("button", { name: "Assess monitoring window" }),
    );
    await waitFor(() =>
      expect(createMonitoringAssessment).toHaveBeenCalledWith(projectId, {
        rule_id: rule.id,
        rule_sha256: rule.rule_sha256,
        window_start: start,
        window_end: end,
      }),
    );
    const evidence = await screen.findByRole("region", {
      name: "Assessment evidence",
    });
    expect(within(evidence).getByText("20.5 degC")).toBeVisible();
    expect(within(evidence).getByText("observed slots")).toBeVisible();
    expect(await screen.findByText("Upper limit exceeded")).toBeVisible();
  });

  it("reopens attributed review history and saves a pinned assessment workflow", async () => {
    vi.mocked(listMonitoringAssessments).mockResolvedValue(
      pageOf([assessment]),
    );
    vi.mocked(listMonitoringRules).mockResolvedValue(pageOf([rule]));
    vi.mocked(reviewMonitoringAlert).mockImplementation(async () => {
      vi.mocked(listMonitoringReviews).mockResolvedValue(pageOf([review]));
      vi.mocked(listMonitoringAlerts).mockResolvedValue(
        pageOf([
          {
            ...finding,
            status: "confirmed",
            latest_review: review,
            review_revision: 1,
          },
        ]),
      );
      return review;
    });
    vi.mocked(saveWorkflowGraph).mockResolvedValue({
      name: "Monitoring assessment",
    } as Awaited<ReturnType<typeof saveWorkflowGraph>>);
    renderMonitoring();
    await screen.findByRole("option", { name: /water temperature.*degC/ });
    fill("Saved assessment", assessment.id);
    await screen.findByText("Upper limit exceeded");
    fireEvent.click(screen.getByRole("button", { name: "Review finding" }));
    fill("Review reason", review.reason);
    fireEvent.click(screen.getByRole("button", { name: "Confirm finding" }));
    await waitFor(() =>
      expect(reviewMonitoringAlert).toHaveBeenCalledWith(
        projectId,
        finding.id,
        0,
        "confirmed",
        review.reason,
      ),
    );
    const history = await screen.findByRole("region", {
      name: "Review history",
    });
    expect(await within(history).findByText(/Local reviewer/)).toBeVisible();
    expect(within(history).getByText(review.reason)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Save assessment workflow" }),
    );
    await waitFor(() =>
      expect(saveWorkflowGraph).toHaveBeenCalledWith(
        projectId,
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              node_type: "monitoring_assessment",
              parameters: {
                rule_id: rule.id,
                rule_sha256: rule.rule_sha256,
                assessment_id: assessment.id,
                assessment_sha256: assessment.result_sha256,
              },
            }),
          ]),
        }),
      ),
    );
  });

  it("selects reviewed biological summaries and preserves their protocol pin", async () => {
    const protocol = hash("e");
    vi.mocked(listEventSummaries).mockResolvedValue({
      total: 2,
      items: [
        {
          id: "summary-live",
          snapshot: {
            selection: { name: "Reviewed recording" },
            protocol_sha256: protocol,
          },
          stale_reasons: [],
        },
        {
          id: "summary-stale",
          snapshot: {
            selection: { name: "Superseded recording" },
            protocol_sha256: protocol,
          },
          stale_reasons: ["Invalidated source"],
        },
      ] as Awaited<ReturnType<typeof listEventSummaries>>["items"],
    });
    renderMonitoring();
    fireEvent.click(
      screen.getByRole("button", { name: "New monitoring rule" }),
    );
    fill("Source type", "biological");
    fill("Rule name", "Reviewed event cadence");
    const source = await screen.findByRole("checkbox", {
      name: "Reviewed recording",
    });
    fireEvent.click(source);
    expect(
      screen.getByRole("checkbox", { name: "Superseded recording" }),
    ).toBeDisabled();
    fill("Minimum effort (seconds)", "30");
    fireEvent.click(
      screen.getByRole("button", { name: "Create monitoring rule" }),
    );
    await waitFor(() =>
      expect(createMonitoringRule).toHaveBeenCalledWith(projectId, {
        label: "Reviewed event cadence",
        kind: "biological",
        protocol,
        metric: "confirmed_events_per_minute",
        unit: "events/min",
        parameters: {
          summary_ids: ["summary-live"],
          minimum_effort_seconds: 30,
        },
      }),
    );
  });
});
