import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { getDatasetVersions } from "../phase456/api";
import {
  createCocoExport,
  getWorkflowDefinitions,
  getWorkflowTemplates,
  validateWorkflow,
} from "./api";
import { WorkflowDashboard } from "./WorkflowDashboard";
import {
  createPersistedWorkflow,
  createWorkflowRevision,
  getPersistedWorkflow,
  getWorkflowRun,
  listPersistedWorkflows,
  queueWorkflowRun,
} from "./workflowPersistenceApi";

vi.mock("../phase456/api", () => ({
  getDatasetVersions: vi.fn(),
}));

vi.mock("./api", () => ({
  createCocoExport: vi.fn(),
  getWorkflowDefinitions: vi.fn(),
  getWorkflowTemplates: vi.fn(),
  validateWorkflow: vi.fn(),
}));

vi.mock("./workflowPersistenceApi", () => ({
  createPersistedWorkflow: vi.fn(),
  createWorkflowRevision: vi.fn(),
  getPersistedWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  listPersistedWorkflows: vi.fn(),
  queueWorkflowRun: vi.fn(),
}));

const project: Project = {
  id: "project-1",
  name: "Workflow project",
  slug: "workflow-project",
  description: "Workflow test",
  storage_root: "projects/workflow-project",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const persistedDetail = {
  workflow: {
    id: "workflow-1",
    project_id: project.id,
    name: "Untitled workflow",
    description: null,
    status: "draft" as const,
    current_revision_number: 1,
    created_by: "local_user",
    created_at: "2026-08-18T00:00:00Z",
    updated_at: "2026-08-18T00:00:00Z",
  },
  current_revision: {
    id: "revision-1",
    workflow_id: "workflow-1",
    revision_number: 1,
    workflow_json: {
      name: "Untitled workflow",
      nodes: [{ id: "images", node_type: "image_input", configuration: {} }],
      edges: [],
    },
    workflow_checksum: "b".repeat(64),
    validation_json: {},
    created_by: "local_user",
    created_at: "2026-08-18T00:00:00Z",
  },
  validation: {
    project_id: project.id,
    name: "Untitled workflow",
    valid: true,
    workflow_checksum: "b".repeat(64),
    topological_order: ["images"],
    execution_stages: [{ stage_index: 0, node_ids: ["images"] }],
    issues: [],
  },
};

const queuedRun = {
  id: "run-12345678",
  workflow_id: "workflow-1",
  workflow_revision_id: "revision-2",
  project_id: project.id,
  job_id: "job-workflow-1",
  status: "queued" as const,
  stage: "queued",
  current_node_id: null,
  input_json: {},
  result_json: {},
  node_state_json: {},
  error_message: null,
  created_at: "2026-08-18T00:00:00Z",
  started_at: null,
  completed_at: null,
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkflowDashboard project={project} />
    </QueryClientProvider>,
  );
}

describe("WorkflowDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getDatasetVersions).mockResolvedValue([
      {
        id: "version-1",
        version_number: 1,
        name: "Frozen coral dataset",
        status: "complete",
        image_count: 10,
        annotation_count: 200,
      },
    ]);
    vi.mocked(getWorkflowDefinitions).mockResolvedValue([
      {
        node_type: "image_input",
        display_name: "Image input",
        inputs: [],
        outputs: [{ name: "images", data_type: "images", required: true }],
        requires_model: false,
        supported_model_tasks: [],
      },
      {
        node_type: "export",
        display_name: "Export",
        inputs: [{ name: "artifact", data_type: "artifact", required: true }],
        outputs: [
          { name: "archive", data_type: "export_archive", required: true },
        ],
        requires_model: false,
        supported_model_tasks: [],
      },
    ]);
    vi.mocked(getWorkflowTemplates).mockResolvedValue([]);
    vi.mocked(validateWorkflow).mockResolvedValue({
      project_id: project.id,
      name: "Untitled workflow",
      valid: true,
      workflow_checksum: "a".repeat(64),
      topological_order: ["images"],
      execution_stages: [{ stage_index: 0, node_ids: ["images"] }],
      issues: [],
    });
    vi.mocked(createCocoExport).mockResolvedValue({
      export: {
        id: "export-1",
        dataset_version_id: "version-1",
        format: "coco_instances",
      },
      job: { id: "job-1", status: "queued" },
    });
    vi.mocked(listPersistedWorkflows).mockResolvedValue([]);
    vi.mocked(getPersistedWorkflow).mockResolvedValue(persistedDetail);
    vi.mocked(createPersistedWorkflow).mockResolvedValue(persistedDetail);
    vi.mocked(createWorkflowRevision).mockResolvedValue({
      ...persistedDetail,
      workflow: {
        ...persistedDetail.workflow,
        current_revision_number: 2,
      },
      current_revision: {
        ...persistedDetail.current_revision,
        id: "revision-2",
        revision_number: 2,
      },
    });
    vi.mocked(queueWorkflowRun).mockResolvedValue({
      run: queuedRun,
      job: {
        id: "job-workflow-1",
        status: "queued",
        job_type: "workflow_run",
        progress_current: 0,
        progress_total: 1,
      },
    });
    vi.mocked(getWorkflowRun).mockResolvedValue(queuedRun);
  });

  it("validates a graph and queues a COCO export", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByRole("option", { name: /frozen coral dataset/i });
    await user.click(screen.getByRole("button", { name: /export coco/i }));
    await waitFor(() =>
      expect(createCocoExport).toHaveBeenCalledWith("version-1"),
    );
    expect(await screen.findByText(/job job-1/i)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /validate workflow/i }),
    );
    await waitFor(() => expect(validateWorkflow).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/workflow is structurally valid/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/stage 1/i)).toBeInTheDocument();
  });

  it("persists the current graph then launches an immutable workflow revision", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByText(/save revisions and run the graph/i);
    await user.click(screen.getByRole("button", { name: /^save workflow$/i }));
    await waitFor(() =>
      expect(createPersistedWorkflow).toHaveBeenCalledWith(
        project.id,
        expect.objectContaining({
          name: "Untitled workflow",
          status: "draft",
          workflow: expect.objectContaining({
            nodes: [
              expect.objectContaining({
                id: "images",
                node_type: "image_input",
              }),
            ],
          }),
        }),
      ),
    );
    expect(await screen.findByText(/saved untitled workflow revision 1/i)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /save revision and run/i }),
    );
    await waitFor(() =>
      expect(createWorkflowRevision).toHaveBeenCalledWith(
        "workflow-1",
        expect.objectContaining({ name: "Untitled workflow" }),
      ),
    );
    await waitFor(() =>
      expect(queueWorkflowRun).toHaveBeenCalledWith("workflow-1", {
        workflow_revision_id: "revision-2",
        inputs: {},
        use_cache: true,
      }),
    );
    expect(await screen.findByText(/run run-1234 queued/i)).toBeInTheDocument();
  });
});
