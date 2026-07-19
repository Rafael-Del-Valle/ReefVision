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

vi.mock("../phase456/api", () => ({
  getDatasetVersions: vi.fn(),
}));

vi.mock("./api", () => ({
  createCocoExport: vi.fn(),
  getWorkflowDefinitions: vi.fn(),
  getWorkflowTemplates: vi.fn(),
  validateWorkflow: vi.fn(),
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

    await user.click(screen.getByRole("button", { name: /validate workflow/i }));
    await waitFor(() => expect(validateWorkflow).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/workflow is structurally valid/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/stage 1/i)).toBeInTheDocument();
  });
});
