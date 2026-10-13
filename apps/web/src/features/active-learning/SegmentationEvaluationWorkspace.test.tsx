import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DatasetVersionRecord,
  ModelRegistration,
  Project,
} from "../../api/client";
import * as clientApi from "../../api/client";
import { SegmentationEvaluationWorkspace } from "./SegmentationEvaluationWorkspace";
import * as evaluationApi from "./segmentationEvaluationApi";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );
  return { ...actual, getDatasetVersions: vi.fn(), getModels: vi.fn() };
});

vi.mock("./segmentationEvaluationApi", async () => {
  const actual = await vi.importActual<
    typeof import("./segmentationEvaluationApi")
  >("./segmentationEvaluationApi");
  return {
    ...actual,
    queueSegmentationEvaluation: vi.fn(),
    getSegmentationEvaluation: vi.fn(),
    promoteSegmentationCandidate: vi.fn(),
    rollbackSegmentationDeployment: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Coral scientific evaluations",
  slug: "coral-evaluations",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const dataset = {
  id: "dataset-1",
  name: "Verified coral holdout",
  version_number: 2,
  status: "complete",
} as DatasetVersionRecord;

const candidate = {
  id: "candidate-1",
  purpose: "segmenter",
  task: "segment",
  display_name: "Locally trained segmenter",
} as ModelRegistration;

const evaluation = {
  id: "evaluation-1",
  status: "completed",
  task: "segment" as const,
  dataset_version_id: dataset.id,
  manifest_sha256: "a".repeat(64),
  split: "validation" as const,
  candidate_model_id: candidate.id,
  candidate_job_id: "inference-1",
  candidate_checksum: "b".repeat(64),
  incumbent_model_id: null,
  incumbent_job_id: null,
  incumbent_checksum: null,
  candidate_metrics: {
    mask_map50: 0.83,
    precision: 0.9,
    recall: 0.85,
    mean_absolute_count_error: 1.2,
    count_bias_per_image: 0.2,
    mean_matched_mask_iou: 0.79,
  },
  incumbent_metrics: null,
  promotion_eligible: true,
  blockers: [],
  warning: "Mask AP50 is not detector box AP.",
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SegmentationEvaluationWorkspace project={project} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SegmentationEvaluationWorkspace", () => {
  beforeEach(() => {
    vi.mocked(clientApi.getDatasetVersions).mockResolvedValue([dataset]);
    vi.mocked(clientApi.getModels).mockResolvedValue([candidate]);
    vi.mocked(evaluationApi.queueSegmentationEvaluation).mockResolvedValue({
      id: evaluation.id,
      job_type: "segmentation_learning_evaluation",
      status: "waiting",
      progress_current: 0,
      progress_total: 1,
      error_message: null,
    });
    vi.mocked(evaluationApi.getSegmentationEvaluation).mockResolvedValue(
      evaluation,
    );
    vi.mocked(evaluationApi.promoteSegmentationCandidate).mockResolvedValue({
      id: "deployment-1",
      status: "succeeded",
      task: "segment",
      action: "promote",
      active_model_id: candidate.id,
      previous_model_id: null,
      approved_by: "Reviewer",
      reason: "Verified mask evidence accepted",
    });
    vi.mocked(evaluationApi.rollbackSegmentationDeployment).mockResolvedValue({
      id: "rollback-1",
      status: "succeeded",
      task: "segment",
      action: "rollback",
      active_model_id: null,
      previous_model_id: candidate.id,
      approved_by: "Reviewer",
      reason: "Restore previous segmenter",
    });
  });

  it("queues a segmentation-only holdout without implicitly deploying a model", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitFor(() =>
      expect(screen.getByLabelText("Candidate segmentation model")).toHaveTextContent(
        "Locally trained segmenter",
      ),
    );
    await user.selectOptions(
      screen.getByLabelText("Verified immutable dataset version"),
      dataset.id,
    );
    await user.selectOptions(
      screen.getByLabelText("Candidate segmentation model"),
      candidate.id,
    );
    await user.click(
      screen.getByRole("button", { name: "Queue held-out evaluation" }),
    );
    await waitFor(() => {
      expect(evaluationApi.queueSegmentationEvaluation).toHaveBeenCalledWith(
        project.id,
        expect.objectContaining({
          dataset_version_id: dataset.id,
          candidate_model_id: candidate.id,
          incumbent_model_id: null,
          split: "validation",
          minimum_images: 2,
          minimum_masks: 2,
        }),
      );
    });
    expect(evaluationApi.promoteSegmentationCandidate).not.toHaveBeenCalled();
    expect(evaluationApi.rollbackSegmentationDeployment).not.toHaveBeenCalled();
  });

  it("requires explicit operator evidence before audited promotion and rollback", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(
      screen.getByLabelText(
        "Existing evaluation ID (restore after restarting)",
      ),
      evaluation.id,
    );
    expect(await screen.findByText("0.830")).toBeInTheDocument();
    const promote = screen.getByRole("button", {
      name: "Promote segmentation candidate",
    });
    expect(promote).toBeDisabled();

    await user.type(
      screen.getByLabelText("Operator/reviewer identity"),
      "Reviewer",
    );
    await user.type(
      screen.getByLabelText(
        "Scientific reason for this action (at least 10 characters)",
      ),
      "Verified mask evidence accepted",
    );
    await user.click(
      screen.getByLabelText(
        "Confirm that this project has no active segmenter",
      ),
    );
    expect(promote).toBeDisabled();
    await user.click(
      screen.getByLabelText(
        "I reviewed the actual mask metrics and explicitly approve activating this candidate",
      ),
    );
    expect(promote).toBeEnabled();
    await user.click(promote);
    await waitFor(() => {
      expect(evaluationApi.promoteSegmentationCandidate).toHaveBeenCalledWith(
        project.id,
        evaluation.id,
        {
          expected_active_model_id: null,
          approved_by: "Reviewer",
          reason: "Verified mask evidence accepted",
        },
      );
    });
    const rollback = screen.getByRole("button", {
      name: "Rollback segmentation deployment",
    });
    expect(rollback).toBeDisabled();
    await user.click(
      screen.getByLabelText(
        "I explicitly approve reversing this segmentation deployment",
      ),
    );
    await user.click(rollback);
    await waitFor(() => {
      expect(evaluationApi.rollbackSegmentationDeployment).toHaveBeenCalledWith(
        project.id,
        "deployment-1",
        expect.objectContaining({
          expected_active_model_id: candidate.id,
          approved_by: "Reviewer",
        }),
      );
    });
  });

  it("never enables promotion for an ineligible or unfinished evaluation", async () => {
    vi.mocked(evaluationApi.getSegmentationEvaluation).mockResolvedValue({
      ...evaluation,
      status: "waiting",
      promotion_eligible: false,
      candidate_metrics: null,
      blockers: ["Inference still running"],
    });
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(
      screen.getByLabelText(
        "Existing evaluation ID (restore after restarting)",
      ),
      evaluation.id,
    );
    await screen.findByText("Inference still running");
    await user.type(
      screen.getByLabelText("Operator/reviewer identity"),
      "Reviewer",
    );
    await user.type(
      screen.getByLabelText(
        "Scientific reason for this action (at least 10 characters)",
      ),
      "Checkpoint not approved",
    );
    await user.click(
      screen.getByLabelText(
        "Confirm that this project has no active segmenter",
      ),
    );
    await user.click(
      screen.getByLabelText(
        "I reviewed the actual mask metrics and explicitly approve activating this candidate",
      ),
    );
    expect(
      screen.getByRole("button", { name: "Promote segmentation candidate" }),
    ).toBeDisabled();
    expect(evaluationApi.promoteSegmentationCandidate).not.toHaveBeenCalled();
  });
});
