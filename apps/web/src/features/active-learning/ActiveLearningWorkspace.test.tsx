import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import * as clientApi from "../../api/client";
import { ActiveLearningWorkspace } from "./ActiveLearningWorkspace";
import * as activeApi from "./activeLearningApi";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );
  return {
    ...actual,
    getDatasetVersions: vi.fn(),
    getModels: vi.fn(),
  };
});

vi.mock("./activeLearningApi", async () => {
  const actual = await vi.importActual<typeof import("./activeLearningApi")>(
    "./activeLearningApi",
  );
  return {
    ...actual,
    getActiveLearningRounds: vi.fn(),
    getActiveLearningFeedback: vi.fn(),
  };
});

vi.mock("../advanced-providers/AdvancedProviderWorkspace", () => ({
  AdvancedProviderWorkspace: () => <div>Advanced providers</div>,
}));

vi.mock("../interoperability/InteroperabilityWorkspace", () => ({
  InteroperabilityWorkspace: () => <div>Interoperability</div>,
}));

vi.mock("../workflow-graphs/WorkflowGraphWorkspace", () => ({
  WorkflowGraphWorkspace: () => <div>Workflow graphs</div>,
}));

const project: Project = {
  id: "project-1",
  name: "Coral active learning",
  slug: "coral-active-learning",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-08-08T00:00:00Z",
  updated_at: "2026-08-08T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ActiveLearningWorkspace project={project} />
    </QueryClientProvider>,
  );
}

describe("ActiveLearningWorkspace", () => {
  beforeEach(() => {
    vi.mocked(clientApi.getDatasetVersions).mockResolvedValue([]);
    vi.mocked(clientApi.getModels).mockResolvedValue([]);
    vi.mocked(activeApi.getActiveLearningRounds).mockResolvedValue([
      {
        id: "round-1",
        project_id: project.id,
        dataset_version_id: null,
        review_queue_id: "queue-1234567890",
        name: "Uncertain coral round",
        strategy: "uncertainty",
        status: "complete",
        requested_size: 1,
        selected_count: 1,
        model_ids_json: [],
        strategy_config_json: {},
        selection_manifest_json: {
          items: [
            {
              image_id: "image-1234567890",
              queue_item_id: "queue-item-1",
              rank_position: 1,
              score: 0.91,
              input_checksum: "a".repeat(64),
              reason_summary: "Low model confidence made this image uncertain.",
              score_breakdown: [{ signal: "low_mean_confidence" }],
              signal_values: { low_mean_confidence: 0.85 },
            },
          ],
        },
        selection_sha256: "b".repeat(64),
        feedback_summary_json: {
          feedback_dataset_version_id: "dataset-1234567890",
        },
        created_by: "local_user",
        created_at: "2026-08-08T00:00:00Z",
        completed_at: "2026-08-08T01:00:00Z",
      },
    ]);
    vi.mocked(activeApi.getActiveLearningFeedback).mockResolvedValue({
      round_id: "round-1",
      status: "complete",
      selected_count: 1,
      pending_count: 0,
      in_progress_count: 0,
      completed_count: 1,
      skipped_count: 0,
      completion_fraction: 1,
      prediction_review_counts: { detection_accepted: 1 },
      feedback_dataset_version_id: "dataset-1234567890",
      feedback_manifest_sha256: "c".repeat(64),
    });
  });

  it("shows strategy guidance, acquisition reasons, and feedback dataset lineage", async () => {
    renderWorkspace();

    expect(await screen.findByText("Active learning")).toBeInTheDocument();
    expect(screen.getByText("Input dataset")).toBeInTheDocument();
    expect(screen.getByText("Model filter")).toBeInTheDocument();
    expect(screen.getByText("Why these images?")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Low model confidence made this image uncertain.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Feedback dataset")).toBeInTheDocument();
    expect(screen.getByText("Dataset manifest")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Complete round + snapshot feedback",
      }),
    ).toBeDisabled();
  });
});
