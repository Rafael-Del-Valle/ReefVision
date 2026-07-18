import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project, ReviewQueueRecord } from "../../api/client";
import { ReviewQueueDashboard } from "./ReviewQueueDashboard";

const api = vi.hoisted(() => ({
  completeReviewQueueItem: vi.fn(),
  createDatasetVersionReviewQueue: vi.fn(),
  createReviewQueue: vi.fn(),
  getDatasetVersionQualityControlRuns: vi.fn(),
  getDatasetVersionReviewQueues: vi.fn(),
  getDatasetVersions: vi.fn(),
  getQualityControlRuns: vi.fn(),
  getReviewQueueItems: vi.fn(),
  getReviewQueues: vi.fn(),
  regenerateReviewQueue: vi.fn(),
  returnReviewQueueItem: vi.fn(),
  skipReviewQueueItem: vi.fn(),
  startReviewQueueItem: vi.fn(),
}));

vi.mock("../../api/client", () => api);

const project: Project = {
  id: "project-1",
  name: "Active learning project",
  slug: "active-learning-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-18T12:00:00Z",
  updated_at: "2026-07-18T12:00:00Z",
  archived_at: null,
  label_classes: [],
};

const activeQueue: ReviewQueueRecord = {
  id: "queue-1",
  project_id: project.id,
  dataset_version_id: null,
  source_quality_control_run_id: null,
  regenerated_from_queue_id: null,
  scope_type: "project",
  status: "complete",
  formula_id: "active_learning_diversity_v1",
  formula_version: "1.0.0",
  configuration_json: {
    active_learning: {
      max_items: 25,
      min_priority_score: 20,
      diversity_weight: 0.6,
      max_items_per_group: 3,
      include_reviewed: true,
    },
  },
  input_checksums_json: {},
  summary_json: {
    candidate_count: 40,
    reviewed_excluded: 2,
    average_diversity_score: 0.75,
    average_selection_score: 68.5,
  },
  item_count: 25,
  created_by: "local_user",
  created_at: "2026-07-18T12:00:00Z",
  completed_at: "2026-07-18T12:00:01Z",
  error_message: null,
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReviewQueueDashboard project={project} onOpenImage={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("ReviewQueueDashboard active learning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getDatasetVersions.mockResolvedValue([]);
    api.getQualityControlRuns.mockResolvedValue([]);
    api.getDatasetVersionQualityControlRuns.mockResolvedValue([]);
    api.getReviewQueues.mockResolvedValue([]);
    api.getDatasetVersionReviewQueues.mockResolvedValue([]);
    api.getReviewQueueItems.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
      pages: 0,
    });
    api.createReviewQueue.mockResolvedValue(activeQueue);
  });

  it("keeps priority ranking as the default mode", async () => {
    renderDashboard();

    expect(await screen.findByLabelText("Queue type")).toHaveValue("priority");
    expect(
      screen.getByRole("button", { name: "Generate priority queue" }),
    ).toBeEnabled();
    expect(screen.queryByLabelText("Maximum images")).not.toBeInTheDocument();
  });

  it("submits diversity-aware batch settings through the shared route", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.selectOptions(await screen.findByLabelText("Queue type"), "active_learning");
    await user.clear(screen.getByLabelText("Maximum images"));
    await user.type(screen.getByLabelText("Maximum images"), "25");
    await user.clear(screen.getByLabelText("Minimum priority score"));
    await user.type(screen.getByLabelText("Minimum priority score"), "20");
    await user.clear(screen.getByLabelText("Diversity weight"));
    await user.type(screen.getByLabelText("Diversity weight"), "0.6");
    await user.type(screen.getByLabelText("Maximum per group"), "3");
    await user.click(screen.getByLabelText("Include images already marked reviewed"));
    await user.click(
      screen.getByRole("button", { name: "Generate active-learning batch" }),
    );

    await waitFor(() => expect(api.createReviewQueue).toHaveBeenCalledTimes(1));
    expect(api.createReviewQueue).toHaveBeenCalledWith(
      project.id,
      expect.objectContaining({
        queue_kind: "active_learning",
        max_items: 25,
        min_priority_score: 20,
        diversity_weight: 0.6,
        max_items_per_group: 3,
        include_reviewed: true,
      }),
    );
  });
});
