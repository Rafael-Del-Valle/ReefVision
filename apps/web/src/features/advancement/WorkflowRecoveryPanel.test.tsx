import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowRecoveryPanel } from "./WorkflowRecoveryPanel";
import {
  applyWorkflowArtifactCleanup,
  listPersistedWorkflows,
  listWorkflowRuns,
  previewWorkflowArtifactCleanup,
} from "./workflowPersistenceApi";

vi.mock("./Sam3WorkflowSetupPanel", () => ({
  Sam3WorkflowSetupPanel: () => <div data-testid="sam3-setup" />,
}));

vi.mock("./workflowPersistenceApi", () => ({
  listPersistedWorkflows: vi.fn(),
  listWorkflowRuns: vi.fn(),
  retryWorkflowRun: vi.fn(),
  previewWorkflowArtifactCleanup: vi.fn(),
  applyWorkflowArtifactCleanup: vi.fn(),
}));

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkflowRecoveryPanel projectId="project-1" />
    </QueryClientProvider>,
  );
}

const run = {
  id: "run-12345678",
  workflow_id: "workflow-1",
  workflow_revision_id: "revision-1",
  project_id: "project-1",
  job_id: "job-1",
  status: "succeeded" as const,
  stage: "completed",
  current_node_id: null,
  input_json: {},
  result_json: {},
  node_state_json: { export: { status: "succeeded" } },
  error_message: null,
  created_at: "2026-07-23T12:00:00Z",
  started_at: "2026-07-23T12:00:01Z",
  completed_at: "2026-07-23T12:00:10Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPersistedWorkflows).mockResolvedValue([
    {
      id: "workflow-1",
      project_id: "project-1",
      name: "Consensus workflow",
      description: null,
      status: "draft",
      current_revision_number: 1,
      created_by: "test",
      created_at: "2026-07-23T12:00:00Z",
      updated_at: "2026-07-23T12:00:00Z",
    },
  ]);
  vi.mocked(listWorkflowRuns).mockResolvedValue([run]);
  vi.mocked(previewWorkflowArtifactCleanup).mockResolvedValue({
    workflow_run_id: run.id,
    run_status: "succeeded",
    preview_checksum: "a".repeat(64),
    action_count: 1,
    eligible_action_count: 1,
    reclaimable_bytes: 1024,
    actions: [
      {
        action_id: "action-1",
        action_kind: "quarantine_file",
        artifact_id: "artifact-1",
        node_id: "export",
        port_name: "archive",
        managed_path: "projects/project-1/workflows/run-12345678/export.zip",
        size_bytes: 1024,
        file_sha256: "b".repeat(64),
        eligible: true,
        blockers: [],
      },
    ],
  });
  vi.mocked(applyWorkflowArtifactCleanup).mockResolvedValue({
    workflow_run_id: run.id,
    applied_action_count: 1,
    quarantined_file_count: 1,
    cleared_reference_count: 0,
    reclaimed_bytes: 1024,
    quarantine_paths: ["projects/project-1/workflow-quarantine/export.zip"],
  });
});

describe("WorkflowRecoveryPanel cleanup", () => {
  it("requires explicit selection after every preview", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("Run run-1234")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Preview artifact cleanup" }),
    );

    const checkbox = await screen.findByRole("checkbox", {
      name: /quarantine file/i,
    });
    expect(checkbox).not.toBeChecked();
    const applyButton = screen.getByRole("button", {
      name: "Apply 0 selected actions",
    });
    expect(applyButton).toBeDisabled();

    await user.click(checkbox);
    expect(
      screen.getByRole("button", { name: "Apply 1 selected actions" }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Apply 1 selected actions" }),
    );

    await waitFor(() =>
      expect(applyWorkflowArtifactCleanup).toHaveBeenCalledWith(run.id, {
        preview_checksum: "a".repeat(64),
        action_ids: ["action-1"],
      }),
    );
  });
});
