import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/client";
import { ProjectReviewInspector } from "./ProjectReviewInspector";

vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getReviewQueues: vi.fn(),
  getReviewQueueItems: vi.fn(),
}));

const queueOne = {
  id: "queue-1",
  project_id: "project-1",
  dataset_version_id: null,
  source_quality_control_run_id: "qc-1",
  regenerated_from_queue_id: null,
  scope_type: "project",
  status: "ready",
  formula_id: "review-ranking-v1",
  formula_version: "1",
  configuration_json: {},
  input_checksums_json: {},
  summary_json: {},
  item_count: 8,
  created_by: "researcher",
  created_at: "2026-10-05T20:00:00Z",
  completed_at: null,
  error_message: null,
} as api.ReviewQueueRecord;

const queueTwo = {
  ...queueOne,
  id: "queue-2",
  item_count: 4,
  created_at: "2026-10-05T21:00:00Z",
} as api.ReviewQueueRecord;

const reviewItem = {
  id: "review-item-1",
  review_queue_id: "queue-2",
  project_id: "project-1",
  dataset_version_id: null,
  image_id: "image-swiftia-001",
  split: "validation",
  review_state: "pending",
  score: 81.25,
  rank_position: 1,
  highest_qc_severity: "warning",
  label_class_ids_json: ["class-1"],
  model_ids_json: ["model-1"],
  related_issue_ids_json: ["issue-1"],
  signal_values_json: {},
  normalized_signals_json: {},
  weights_json: {},
  score_breakdown_json: [
    {
      signal_id: "low_mean_confidence",
      label: "Low mean confidence",
      raw_value: 0.3,
      normalized_value: 0.7,
      weight: 24,
      contribution: 16.8,
      description: "Low prediction confidence",
    },
  ],
  input_checksum: "c".repeat(64),
  reason_summary:
    "Low-confidence model proposals and an unresolved QC warning.",
  skip_reason: null,
  created_at: "2026-10-05T21:00:00Z",
  updated_at: "2026-10-05T21:00:00Z",
  started_at: null,
  completed_at: null,
  returned_at: null,
} as api.ReviewQueueItem;

function renderInspector({
  selectedQueueId = "queue-2",
  onOpenItem = vi.fn(),
}: {
  selectedQueueId?: string | null;
  onOpenItem?: (item: api.ReviewQueueItem) => void;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProjectReviewInspector
        projectId="project-1"
        selectedQueueId={selectedQueueId}
        onOpenItem={onOpenItem}
      />
    </QueryClientProvider>,
  );

  return { queryClient, onOpenItem };
}

beforeEach(() => {
  vi.clearAllMocks();

  vi.mocked(api.getReviewQueues).mockResolvedValue([queueOne, queueTwo]);

  vi.mocked(api.getReviewQueueItems).mockResolvedValue({
    items: [reviewItem],
    total: 1,
    page: 1,
    page_size: 25,
    pages: 1,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProjectReviewInspector", () => {
  it("uses the selected canonical review queue and shows ranked evidence", async () => {
    renderInspector();

    expect(await screen.findByText("Rank #1")).toBeInTheDocument();

    await waitFor(() =>
      expect(api.getReviewQueueItems).toHaveBeenCalledWith(
        "queue-2",
        {
          page: 1,
          pageSize: 25,
        },
        expect.any(AbortSignal),
      ),
    );

    expect(screen.getByText("Score 81.25")).toBeInTheDocument();
    expect(screen.getByText("QC warning")).toBeInTheDocument();

    expect(
      screen.getByText(
        "Low-confidence model proposals and an unresolved QC warning.",
      ),
    ).toBeInTheDocument();

    expect(screen.getByText("Low mean confidence")).toBeInTheDocument();
    expect(screen.getByText("+16.80")).toBeInTheDocument();
    expect(screen.getByText("1 pending on page")).toBeInTheDocument();
  });

  it("opens review evidence in the canonical annotation editor", async () => {
    const handlers = renderInspector();

    await screen.findByText("Rank #1");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Open in annotation editor",
      }),
    );

    expect(handlers.onOpenItem).toHaveBeenCalledWith(reviewItem);
  });

  it("falls back to the first project queue until dashboard selection is available", async () => {
    renderInspector({ selectedQueueId: null });

    await screen.findByText("Rank #1");

    await waitFor(() =>
      expect(api.getReviewQueueItems).toHaveBeenCalledWith(
        "queue-1",
        {
          page: 1,
          pageSize: 25,
        },
        expect.any(AbortSignal),
      ),
    );
  });

  it("shows the canonical empty state when no review queue exists", async () => {
    vi.mocked(api.getReviewQueues).mockResolvedValue([]);

    renderInspector({ selectedQueueId: null });

    expect(
      await screen.findByText("No review queue generated"),
    ).toBeInTheDocument();

    expect(api.getReviewQueueItems).not.toHaveBeenCalled();
  });
});
