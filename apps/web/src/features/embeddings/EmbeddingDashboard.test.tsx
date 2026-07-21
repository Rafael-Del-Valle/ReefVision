import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  completeReviewQueueItem,
  getReviewQueueItems,
  getReviewQueues,
  skipReviewQueueItem,
  startReviewQueueItem,
  type Project,
  type ReviewQueueItem,
  type ReviewQueueRecord,
} from "../../api/client";
import { listProviderModels, type ProviderModelAsset } from "../providers/api";
import { cancelJob, getJob } from "../phase456/api";
import { EmbeddingDashboard } from "./EmbeddingDashboard";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );
  return {
    ...actual,
    completeReviewQueueItem: vi.fn(),
    getReviewQueueItems: vi.fn(),
    getReviewQueues: vi.fn(),
    skipReviewQueueItem: vi.fn(),
    startReviewQueueItem: vi.fn(),
  };
});

vi.mock("../providers/api", async () => {
  const actual =
    await vi.importActual<typeof import("../providers/api")>(
      "../providers/api",
    );
  return { ...actual, listProviderModels: vi.fn() };
});

vi.mock("../phase456/api", async () => {
  const actual =
    await vi.importActual<typeof import("../phase456/api")>("../phase456/api");
  return { ...actual, cancelJob: vi.fn(), getJob: vi.fn() };
});

const project: Project = {
  id: "project-1",
  name: "Active-learning project",
  slug: "active-learning-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-21T12:00:00Z",
  updated_at: "2026-07-21T12:00:00Z",
  archived_at: null,
  label_classes: [],
};

const embeddingAsset: ProviderModelAsset = {
  id: "asset-yolo11n",
  provider_id: "ultralytics",
  provider_version: "8.3.228",
  model_id: "ultralytics/yolo11/detect/n",
  architecture: "YOLO11",
  task: "detect",
  capabilities: { detection: true, inference: true, embeddings: true },
  checkpoint_path: "models/catalog-models/yolo11n.pt",
  checkpoint_path_kind: "managed",
  checkpoint_sha256: "b".repeat(64),
  checkpoint_size_bytes: 5_613_767,
  checkpoint_format: "pytorch_pt",
  source: "managed_catalog",
  revision: "ultralytics-assets-v8.3.0",
  required_packages: ["ultralytics"],
  optional_packages: [],
  supported_devices: ["cpu", "cuda"],
  preferred_device: "auto",
  estimated_vram_bytes: null,
  input_types: ["image"],
  output_types: ["boxes"],
  prompt_types: [],
  supports_training: true,
  supports_inference: true,
  supports_video: false,
  state: "unloaded",
  failure_reason: null,
  verification: { verified: true },
  last_health_check: {},
  last_health_check_at: null,
  last_successful_load_at: "2026-07-21T12:00:00Z",
  last_successful_inference_at: "2026-07-21T12:01:00Z",
  metadata: {},
  latest_acceptance_status: "passed",
  created_at: "2026-07-21T12:00:00Z",
  updated_at: "2026-07-21T12:01:00Z",
};

function queue(overrides: Partial<ReviewQueueRecord> = {}): ReviewQueueRecord {
  return {
    id: "queue-1",
    project_id: project.id,
    dataset_version_id: null,
    source_quality_control_run_id: null,
    regenerated_from_queue_id: null,
    scope_type: "project",
    status: "complete",
    revision: 4,
    generation_key: "generation-4",
    formula_id: "active_learning_diversity_v1",
    formula_version: "2.0.0",
    configuration_json: {
      active_learning: {
        embedding_provider_id: "ultralytics_backbone",
        embedding_model_id: embeddingAsset.model_id,
        embedding_model_checksum: embeddingAsset.checkpoint_sha256,
      },
    },
    input_checksums_json: {},
    summary_json: { cycle_id: "cycle-1" },
    item_count: 1,
    created_by: "local_user",
    created_at: "2026-07-21T12:00:00Z",
    completed_at: "2026-07-21T12:00:01Z",
    error_message: null,
    promoted_dataset_version_id: null,
    promoted_cycle_id: null,
    promoted_at: null,
    ...overrides,
  };
}

function item(
  reviewState: ReviewQueueItem["review_state"] = "pending",
): ReviewQueueItem {
  return {
    id: "item-1",
    review_queue_id: "queue-1",
    project_id: project.id,
    dataset_version_id: null,
    image_id: "image-1",
    split: null,
    review_state: reviewState,
    score: 0.91,
    rank_position: 1,
    highest_qc_severity: null,
    label_class_ids_json: [],
    model_ids_json: ["source-model-1"],
    related_issue_ids_json: [],
    signal_values_json: {},
    normalized_signals_json: {},
    weights_json: { uncertainty: 0.45, novelty: 0.45 },
    score_breakdown_json: [],
    input_checksum: "c".repeat(64),
    reason_summary: "High novelty and rare-class coverage.",
    selection_reasons_json: ["High novelty", "Rare class"],
    manual_state: "automatic",
    fragment_key: "fragment-a",
    near_duplicate_key: null,
    skip_reason: null,
    created_at: "2026-07-21T12:00:00Z",
    updated_at: "2026-07-21T12:00:00Z",
    started_at: null,
    completed_at: reviewState === "completed" ? "2026-07-21T12:10:00Z" : null,
    returned_at: null,
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(
  coverageReady = true,
  cycleOverrides: Record<string, unknown> = {},
) {
  const cycle = {
    id: "cycle-1",
    cycle_index: 2,
    name: "Second active-learning cycle",
    status: "review",
    selection_strategy: "blended",
    selected_count: 1,
    reviewed_count: 0,
    source_model_id: "source-model-1",
    candidate_model_id: null,
    promoted_model_id: null,
    dataset_version_id: null,
    training_run_id: null,
    review_queue_id: "queue-1",
    embedding_provider_id: "ultralytics_backbone",
    embedding_model_id: embeddingAsset.model_id,
    embedding_model_checksum: embeddingAsset.checkpoint_sha256,
    queue_revision: 4,
    accepted_annotation_ids: [],
    rejected_item_ids: [],
    warnings: ["Ensemble disagreement is deferred."],
    baseline_metrics: { map50: 0.4 },
    candidate_metrics: {},
    history: [],
    created_at: "2026-07-21T12:00:00Z",
    completed_at: null,
    ...cycleOverrides,
  };
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/embedding-coverage")) {
        return jsonResponse({
          total_image_count: 2,
          ready_image_count: coverageReady ? 2 : 0,
          missing_image_count: coverageReady ? 0 : 2,
          stale_image_count: 0,
          failed_image_count: 0,
          dimension: coverageReady ? 256 : null,
          warnings: [],
        });
      }
      if (url.endsWith(`/projects/${project.id}/active-learning-cycles`)) {
        return jsonResponse({ cycles: [cycle] });
      }
      if (url.endsWith(`/projects/${project.id}/training-runs`)) {
        return jsonResponse([
          {
            id: "run-1",
            run_name: "Cycle retraining",
            status: "completed",
            dataset_version_id: "dataset-version-1",
            metrics: { map50_95: 0.52 },
          },
          {
            id: "run-other",
            run_name: "Wrong dataset",
            status: "completed",
            dataset_version_id: "dataset-version-other",
            metrics: { map50_95: 0.8 },
          },
        ]);
      }
      if (url.endsWith(`/projects/${project.id}/models`)) {
        return jsonResponse([
          {
            id: "candidate-model-1",
            display_name: "Cycle candidate",
            task: "detect",
            provider_name: "ultralytics",
            metadata_json: { source_training_run_id: "run-1" },
          },
        ]);
      }
      if (url.endsWith(`/projects/${project.id}/embedding-jobs`)) {
        return jsonResponse({
          embedding_model_id: embeddingAsset.model_id,
          requested_image_count: 2,
          job: { id: "job-1", status: "pending" },
        });
      }
      if (url.endsWith(`/projects/${project.id}/active-learning-queues`)) {
        return jsonResponse(queue({ id: "queue-2", revision: 5 }));
      }
      if (url.endsWith("/active-learning-queues/queue-1/promote")) {
        return jsonResponse({
          queue_id: "queue-1",
          queue_revision: 4,
          dataset_version_id: "dataset-version-1",
          cycle_id: "cycle-1",
          promoted_at: "2026-07-21T12:15:00Z",
          idempotent_replay: false,
        });
      }
      if (url.endsWith("/active-learning-cycles/cycle-1/training")) {
        return jsonResponse({
          ...cycle,
          status: "evaluation",
          training_run_id: "run-1",
          candidate_model_id: "candidate-model-1",
        });
      }
      if (url.endsWith("/active-learning-cycles/cycle-1/evaluate")) {
        return jsonResponse({
          cycle: {
            ...cycle,
            status: "promoted",
            training_run_id: "run-1",
            candidate_model_id: "candidate-model-1",
            promoted_model_id: "candidate-model-1",
            baseline_metrics: { map50_95: 0.4 },
            candidate_metrics: { map50_95: 0.52 },
          },
          all_required_gates_passed: true,
          promoted: true,
          stopped: false,
          stop_reasons: [],
          comparison_compatible: true,
          compatibility_warnings: [],
        });
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method ?? "GET"}`);
    });
}

function renderDashboard(
  overrides: {
    queue?: ReviewQueueRecord;
    queueItem?: ReviewQueueItem;
    onOpenImage?: (value: ReviewQueueItem) => void;
    onLaunchTraining?: () => void;
  } = {},
) {
  const queueValue = overrides.queue ?? queue();
  const itemValue = overrides.queueItem ?? item();
  vi.mocked(getReviewQueues).mockResolvedValue([queueValue]);
  vi.mocked(getReviewQueueItems).mockResolvedValue({
    items: [itemValue],
    total: 1,
    page: 1,
    page_size: 500,
    pages: 1,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EmbeddingDashboard
        project={project}
        onOpenImage={overrides.onOpenImage}
        onLaunchTraining={overrides.onLaunchTraining}
      />
    </QueryClientProvider>,
  );
}

describe("EmbeddingDashboard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(listProviderModels).mockResolvedValue({
      items: [embeddingAsset],
      total: 1,
      limit: 200,
      offset: 0,
      duplicate_checksum_groups: [],
    });
    vi.mocked(startReviewQueueItem).mockResolvedValue(item("in_progress"));
    vi.mocked(completeReviewQueueItem).mockResolvedValue(item("completed"));
    vi.mocked(skipReviewQueueItem).mockResolvedValue(item("skipped"));
    vi.mocked(getJob).mockResolvedValue({
      id: "job-1",
      job_type: "generate_image_embeddings",
      status: "running",
      progress_current: 1,
      progress_total: 2,
      request_json: {},
      result_json: null,
      error_message: null,
    });
    vi.mocked(cancelJob).mockResolvedValue({
      id: "job-1",
      job_type: "generate_image_embeddings",
      status: "cancelled",
      progress_current: 1,
      progress_total: 2,
      request_json: {},
      result_json: null,
      error_message: null,
    });
  });

  it("shows persisted coverage, selection reasons, review state, and cycle provenance", async () => {
    installFetch();
    const onOpenImage = vi.fn();
    const user = userEvent.setup();
    renderDashboard({ onOpenImage });

    expect(await screen.findByText("1 recorded cycles")).toBeInTheDocument();
    expect(await screen.findByText("2 ready")).toBeInTheDocument();
    expect(screen.getByText(/256 dimensions/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/High novelty.*Rare class/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Revision 4/i)).toHaveLength(2);
    expect(screen.getByText(/1 unfinished/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create immutable dataset" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Source model: source-model-1/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ensemble disagreement is deferred/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Annotate" }));
    expect(onOpenImage).toHaveBeenCalledWith(
      expect.objectContaining({ id: "item-1" }),
    );
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() =>
      expect(startReviewQueueItem).toHaveBeenCalledWith("item-1"),
    );
  });

  it("starts and cancels embedding jobs and submits weighted queue controls", async () => {
    const fetchSpy = installFetch();
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByText("2 ready");
    await user.selectOptions(screen.getByLabelText("Device"), "cuda");
    await user.click(
      screen.getByRole("button", { name: "Generate missing embeddings" }),
    );
    await waitFor(() =>
      expect(getJob).toHaveBeenCalledWith("job-1", expect.anything()),
    );
    await user.click(
      await screen.findByRole("button", { name: "Cancel embedding job" }),
    );
    expect(cancelJob).toHaveBeenCalledWith("job-1");

    await user.clear(screen.getByLabelText(/Manual include image UUIDs/i));
    await user.type(
      screen.getByLabelText(/Manual include image UUIDs/i),
      "image-1",
    );
    await user.clear(screen.getByLabelText(/Manual exclude image UUIDs/i));
    await user.type(
      screen.getByLabelText(/Manual exclude image UUIDs/i),
      "image-2",
    );
    await user.click(
      screen.getByRole("button", { name: "Generate queue revision" }),
    );

    await waitFor(() => {
      const call = fetchSpy.mock.calls.find(([input]) =>
        String(input).endsWith(
          `/projects/${project.id}/active-learning-queues`,
        ),
      );
      expect(call).toBeDefined();
      const payload = JSON.parse(String(call?.[1]?.body));
      expect(payload).toMatchObject({
        embedding_provider_id: "ultralytics_backbone",
        embedding_model_id: embeddingAsset.model_id,
        uncertainty_weight: 0.45,
        novelty_weight: 0.45,
        max_items_per_group: 3,
        max_items_per_fragment: 3,
        class_balancing: true,
        manual_include_image_ids: ["image-1"],
        manual_exclude_image_ids: ["image-2"],
        suppress_exact_duplicates: true,
        suppress_near_duplicates: true,
        create_cycle: true,
      });
    });
  });

  it("promotes completed revisions once and exposes training only after promotion", async () => {
    const fetchSpy = installFetch();
    const onLaunchTraining = vi.fn();
    const user = userEvent.setup();
    const promotedQueue = queue({
      promoted_dataset_version_id: "dataset-version-1",
      promoted_cycle_id: "cycle-1",
      promoted_at: "2026-07-21T12:15:00Z",
    });
    const view = renderDashboard({
      queue: promotedQueue,
      queueItem: item("completed"),
      onLaunchTraining,
    });

    expect(await screen.findByText("Promoted")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create immutable dataset" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Launch training" }));
    expect(onLaunchTraining).toHaveBeenCalledOnce();

    view.unmount();
    vi.mocked(getReviewQueues).mockResolvedValue([queue()]);
    renderDashboard({ queueItem: item("completed") });
    const promote = await screen.findByRole("button", {
      name: "Create immutable dataset",
    });
    await waitFor(() => expect(promote).toBeEnabled());
    await user.click(promote);
    expect(
      await screen.findByText(/Dataset dataset-version-1 created/i),
    ).toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.filter(([input]) =>
        String(input).endsWith("/active-learning-queues/queue-1/promote"),
      ),
    ).toHaveLength(1);
  });

  it("links a compatible run and records a before-and-after comparison", async () => {
    const fetchSpy = installFetch(true, {
      status: "dataset_frozen",
      dataset_version_id: "dataset-version-1",
      reviewed_count: 1,
    });
    const user = userEvent.setup();
    renderDashboard({
      queue: queue({
        promoted_dataset_version_id: "dataset-version-1",
        promoted_cycle_id: "cycle-1",
        promoted_at: "2026-07-21T12:15:00Z",
      }),
      queueItem: item("completed"),
    });

    expect(
      await screen.findByText(/Attach training and compare models/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Cycle training run")).toHaveValue("run-1"),
    );
    expect(screen.queryByText("Wrong dataset")).not.toBeInTheDocument();
    await user.selectOptions(
      screen.getByLabelText("Cycle resulting model"),
      "candidate-model-1",
    );
    await user.click(
      screen.getByRole("button", { name: "Record training result" }),
    );
    expect(
      await screen.findByText(/Training run run-1 is linked/i),
    ).toBeInTheDocument();

    const trainingCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).endsWith("/active-learning-cycles/cycle-1/training"),
    );
    expect(JSON.parse(String(trainingCall?.[1]?.body))).toEqual({
      training_run_id: "run-1",
      candidate_model_id: "candidate-model-1",
    });

    await user.type(screen.getByLabelText("Baseline value"), "0.40");
    expect(screen.getByLabelText("Candidate value")).toHaveValue("0.52");
    await user.click(
      screen.getByRole("button", { name: "Compare before and after" }),
    );
    expect(
      await screen.findByText(
        /Compatible comparison recorded; candidate promoted/i,
      ),
    ).toBeInTheDocument();

    const evaluationCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).endsWith("/active-learning-cycles/cycle-1/evaluate"),
    );
    expect(JSON.parse(String(evaluationCall?.[1]?.body))).toMatchObject({
      baseline_metrics: { map50_95: 0.4 },
      candidate_metrics: { map50_95: 0.52 },
      candidate_model_id: "candidate-model-1",
      baseline_dataset_version_id: "dataset-version-1",
      candidate_dataset_version_id: "dataset-version-1",
      baseline_metric_schema_id: "reefvision-evaluation-v1",
      candidate_metric_schema_id: "reefvision-evaluation-v1",
    });
  });
});
