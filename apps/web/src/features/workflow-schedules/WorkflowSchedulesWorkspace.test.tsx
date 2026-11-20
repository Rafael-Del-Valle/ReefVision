import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listSavedWorkflowGraphs } from "../workflow-graphs/workflowGraphApi";
import {
  cancelScheduleOccurrence,
  createWorkflowSchedule,
  listScheduleOccurrences,
  listWorkflowSchedules,
  updateWorkflowSchedule,
  type ScheduleOccurrence,
  type WorkflowSchedule,
} from "./workflowScheduleApi";
import { WorkflowSchedulesWorkspace } from "./WorkflowSchedulesWorkspace";

vi.mock("../workflow-graphs/workflowGraphApi", () => ({
  listSavedWorkflowGraphs: vi.fn(),
}));
vi.mock("./workflowScheduleApi", () => ({
  schedulePageSize: 20,
  listWorkflowSchedules: vi.fn(),
  listScheduleOccurrences: vi.fn(),
  createWorkflowSchedule: vi.fn(),
  updateWorkflowSchedule: vi.fn(),
  cancelScheduleOccurrence: vi.fn(),
}));

const graph = {
  id: "graph-id",
  project_id: "project-id",
  graph_key: "graph-key",
  name: "Frozen QC",
  schema_version: "1",
  revision: 3,
  graph_json: {},
  graph_sha256: "a".repeat(64),
  created_at: "2026-12-08T11:00:00Z",
  updated_at: "2026-12-08T11:00:00Z",
};
const schedule: WorkflowSchedule = {
  id: "schedule-id",
  project_id: "project-id",
  name: "Morning QC",
  purpose: "qc",
  workflow_graph_record_id: graph.id,
  graph_sha256: graph.graph_sha256,
  inputs: {},
  inputs_sha256: "b".repeat(64),
  interval_seconds: 60,
  next_due_at: "2026-12-08T14:03:07Z",
  enabled: true,
  revision: 2,
  minimum_free_bytes: 0,
  last_status: "waiting_previous_run",
  last_message: "Waiting for the previous review",
  created_at: "2026-12-08T11:00:00Z",
  updated_at: "2026-12-08T11:00:00Z",
};
const occurrence: ScheduleOccurrence = {
  id: "occurrence-id",
  project_id: schedule.project_id,
  schedule_id: schedule.id,
  scheduled_at: "2026-12-08T13:59:07Z",
  created_at: "2026-12-08T14:02:07Z",
  missed_intervals: 3,
  status: "waiting_for_review",
  detail: "Researcher review is required",
  workflow_run_id: "workflow-run",
  job_id: "job-id",
  graph_sha256: schedule.graph_sha256,
  inputs_sha256: schedule.inputs_sha256,
};

function renderWorkspace(onOpenWorkflowRun = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <WorkflowSchedulesWorkspace
        projectId={schedule.project_id}
        onOpenWorkflowRun={onOpenWorkflowRun}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listSavedWorkflowGraphs).mockResolvedValue([graph]);
  vi.mocked(listWorkflowSchedules).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(listScheduleOccurrences).mockResolvedValue({ items: [], total: 0 });
});

describe("workflow schedules", () => {
  it("creates a schedule with a selected immutable revision and literal UTC seconds", async () => {
    vi.mocked(createWorkflowSchedule).mockResolvedValue(schedule);
    renderWorkspace();
    await screen.findByRole("option", { name: "Frozen QC (revision 3)" });
    fireEvent.change(screen.getByLabelText("Schedule name"), {
      target: { value: "Morning QC" },
    });
    fireEvent.change(screen.getByLabelText("Purpose"), {
      target: { value: "qc" },
    });
    fireEvent.change(screen.getByLabelText("Saved workflow revision"), {
      target: { value: graph.id },
    });
    expect(screen.getByText(graph.graph_sha256)).toBeVisible();
    fireEvent.change(screen.getByLabelText("First due (UTC)"), {
      target: { value: "2026-12-08T14:03:07" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));
    await waitFor(() =>
      expect(createWorkflowSchedule).toHaveBeenCalledWith("project-id", {
        name: "Morning QC",
        purpose: "qc",
        workflow_graph_record_id: "graph-id",
        interval_seconds: 60,
        next_due_at: "2026-12-08T14:03:07Z",
        enabled: true,
        minimum_free_bytes: 0,
      }),
    );
  });

  it("shows delayed review evidence and requires separate confirmation to cancel", async () => {
    vi.mocked(listWorkflowSchedules).mockResolvedValue({
      items: [schedule],
      total: 1,
    });
    vi.mocked(listScheduleOccurrences).mockResolvedValue({
      items: [occurrence],
      total: 1,
    });
    vi.mocked(cancelScheduleOccurrence).mockResolvedValue({
      ...occurrence,
      status: "cancel_requested",
    });
    const open = vi.fn();
    renderWorkspace(open);
    fireEvent.click(await screen.findByRole("button", { name: "Morning QC" }));
    expect(
      await screen.findByText("Researcher review is required"),
    ).toBeVisible();
    expect(screen.getByText("Waiting for the previous review")).toBeVisible();
    expect(screen.getByText("3 coalesced intervals")).toBeVisible();
    expect(screen.getByText("job-id")).toBeVisible();
    expect(screen.getByText("workflow-run")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open workflow run" }));
    expect(open).toHaveBeenCalledWith("workflow-run", graph);

    fireEvent.click(screen.getByRole("button", { name: "Cancel occurrence" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "Cancel scheduled occurrence",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Cancel$/ }));
    expect(cancelScheduleOccurrence).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel occurrence" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Request cancellation",
      }),
    );
    await waitFor(() =>
      expect(cancelScheduleOccurrence).toHaveBeenCalledWith(
        "project-id",
        "schedule-id",
        "occurrence-id",
      ),
    );
  });

  it("pauses against the displayed revision and surfaces a stale write", async () => {
    vi.mocked(listWorkflowSchedules).mockResolvedValue({
      items: [schedule],
      total: 1,
    });
    vi.mocked(updateWorkflowSchedule).mockRejectedValue(
      new Error("Schedule changed. Reload it before saving."),
    );
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Morning QC" }));
    fireEvent.click(screen.getByRole("button", { name: "Pause schedule" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Schedule changed. Reload it before saving.",
    );
    expect(updateWorkflowSchedule).toHaveBeenCalledTimes(1);
    expect(updateWorkflowSchedule).toHaveBeenCalledWith(
      schedule.project_id,
      schedule.id,
      { expected_revision: 2, enabled: false },
    );
  });

  it("leaves graph, purpose, and the advancing due time untouched when changing a name", async () => {
    vi.mocked(listWorkflowSchedules).mockResolvedValue({
      items: [schedule],
      total: 1,
    });
    vi.mocked(updateWorkflowSchedule).mockResolvedValue({
      ...schedule,
      name: "Night QC",
    });
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Morning QC" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit schedule" }));
    expect(screen.getByLabelText("Saved workflow revision")).toBeDisabled();
    expect(screen.getByLabelText("Purpose")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Schedule name"), {
      target: { value: "Night QC" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save schedule changes" }),
    );
    await waitFor(() =>
      expect(updateWorkflowSchedule).toHaveBeenCalledWith(
        schedule.project_id,
        schedule.id,
        {
          name: "Night QC",
          enabled: true,
          interval_seconds: 60,
          minimum_free_bytes: 0,
          expected_revision: 2,
        },
      ),
    );
  });
});
