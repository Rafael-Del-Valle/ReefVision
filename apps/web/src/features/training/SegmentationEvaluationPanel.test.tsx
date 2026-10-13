import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getDatasetVersions,
  getJob,
  getModels,
  type Project,
} from "../../api/client";
import { SegmentationEvaluationPanel } from "./SegmentationEvaluationPanel";
import {
  listSegmentationDeploymentAudit,
  listSegmentationEvaluations,
  promoteSegmentationCandidate,
  queueSegmentationEvaluation,
  rollbackSegmentationDeployment,
} from "./segmentationEvaluationApi";

vi.mock("../../api/client", () => ({
  getDatasetVersions: vi.fn(),
  getModels: vi.fn(),
  getJob: vi.fn(),
}));

vi.mock("./segmentationEvaluationApi", () => ({
  listSegmentationDeploymentAudit: vi.fn(),
  listSegmentationEvaluations: vi.fn(),
  queueSegmentationEvaluation: vi.fn(),
  promoteSegmentationCandidate: vi.fn(),
  rollbackSegmentationDeployment: vi.fn(),
}));

const project = { id: "project-1" } as Project;

function model(id: string, active = false, deploymentId?: string) {
  return {
    id,
    purpose: "segmenter",
    task: "segment",
    display_name: id,
    metadata_json: {
      active_for_predictions: active,
      ...(deploymentId
        ? { active_segmentation_deployment_id: deploymentId }
        : {}),
    },
  };
}

function completedEvaluation(eligible: boolean, incumbentId: string | null) {
  return {
    id: "evaluation-1",
    project_id: project.id,
    job_type: "segmentation_learning_evaluation",
    status: "completed",
    progress_current: incumbentId ? 2 : 1,
    progress_total: incumbentId ? 2 : 1,
    request_json: {
      task: "segment",
      dataset_version_id: "version-1",
      manifest_sha256: "a".repeat(64),
      split: "validation",
      heldout_image_ids: ["image-1", "image-2"],
      candidate_model_id: "candidate",
      candidate_job_id: "candidate-inference-1",
      candidate_checksum: "b".repeat(64),
      incumbent_model_id: incumbentId,
      incumbent_checksum: incumbentId ? "c".repeat(64) : null,
    },
    result_json: {
      promotion_eligible: eligible,
      blockers: eligible ? [] : ["Candidate below mask AP50 floor"],
      candidate_metrics: {
        mask_map50: eligible ? 0.85 : 0.3,
        precision: 0.9,
        recall: 0.8,
        mean_absolute_count_error: 1.5,
        count_bias_per_image: 0.5,
        per_class: {
          "class-octocoral-open": {
            ground_truth_count: 8,
            precision: 0.9,
            recall: 0.8,
            ap50: 0.83,
          },
        },
      },
    },
  };
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SegmentationEvaluationPanel project={project} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getDatasetVersions).mockResolvedValue([
    {
      id: "version-1",
      name: "Verified octocoral masks",
      version_number: 1,
      status: "complete",
    },
  ] as unknown as Awaited<ReturnType<typeof getDatasetVersions>>);
  vi.mocked(listSegmentationEvaluations).mockResolvedValue([]);
  vi.mocked(listSegmentationDeploymentAudit).mockResolvedValue([]);
  vi.mocked(getModels).mockResolvedValue([
    model("candidate"),
  ] as unknown as Awaited<ReturnType<typeof getModels>>);
  vi.mocked(queueSegmentationEvaluation).mockResolvedValue({
    id: "evaluation-1",
    status: "waiting",
  } as unknown as Awaited<ReturnType<typeof queueSegmentationEvaluation>>);
  vi.mocked(getJob).mockResolvedValue(
    completedEvaluation(true, null) as unknown as Awaited<
      ReturnType<typeof getJob>
    >,
  );
  vi.mocked(promoteSegmentationCandidate).mockResolvedValue({
    id: "deploy-1",
    status: "succeeded",
    action: "promote",
    active_model_id: "candidate",
  } as unknown as Awaited<ReturnType<typeof promoteSegmentationCandidate>>);
  vi.mocked(rollbackSegmentationDeployment).mockResolvedValue({
    id: "rollback-1",
    status: "succeeded",
    action: "rollback",
    active_model_id: null,
  } as unknown as Awaited<ReturnType<typeof rollbackSegmentationDeployment>>);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("SegmentationEvaluationPanel", () => {
  it("displays persisted read-only scientific deployment audit history", async () => {
    vi.mocked(listSegmentationDeploymentAudit).mockResolvedValue([
      {
        id: "promotion-record-1",
        project_id: project.id,
        job_type: "segmentation_learning_deployment",
        status: "succeeded",
        request_json: {
          task: "segment",
          approved_by: "Scientist",
          reason: "Passed held-out octocoral mask verification",
        },
        result_json: { active_model_id: "candidate" },
      },
      {
        id: "rollback-record-1",
        project_id: project.id,
        job_type: "segmentation_learning_deployment_rollback",
        status: "succeeded",
        request_json: {
          task: "segment",
          approved_by: "Scientist",
          reason: "Reverted following quality review",
        },
        result_json: { restored_model_id: null },
      },
    ] as unknown as Awaited<
      ReturnType<typeof listSegmentationDeploymentAudit>
    >);
    renderPanel();
    const history = await screen.findByRole("region", {
      name: "Segmentation deployment audit history",
    });
    await waitFor(() => {
      expect(history).toHaveTextContent(
        "Passed held-out octocoral mask verification",
      );
      expect(history).toHaveTextContent("Reverted following quality review");
    });
    expect(history).toHaveTextContent("Promotion");
    expect(history).toHaveTextContent("Rollback");
    expect(history).toHaveTextContent("Scientist");
    expect(listSegmentationDeploymentAudit).toHaveBeenCalledWith(
      project.id,
      expect.anything(),
    );
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
    expect(rollbackSegmentationDeployment).not.toHaveBeenCalled();
  });

  it("does not display or promote another project's evaluation record", async () => {
    vi.mocked(listSegmentationEvaluations).mockResolvedValue([
      completedEvaluation(true, null),
    ] as unknown as Awaited<ReturnType<typeof listSegmentationEvaluations>>);
    vi.mocked(getJob).mockResolvedValue({
      ...completedEvaluation(true, null),
      project_id: "other-project",
    } as unknown as Awaited<ReturnType<typeof getJob>>);
    renderPanel();
    await screen.findByRole("option", { name: "completed: candidate" });
    fireEvent.change(screen.getByLabelText("Segmentation evaluation history"), {
      target: { value: "evaluation-1" },
    });
    expect(
      await screen.findByText("Evaluation does not belong to this project"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.850")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Promote evaluated segmenter" }),
    ).toBeDisabled();
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("blocks approval when the evaluated segmenter is no longer registered", async () => {
    vi.mocked(getModels).mockResolvedValue([
      model("unrelated-segmenter"),
    ] as unknown as Awaited<ReturnType<typeof getModels>>);
    vi.mocked(listSegmentationEvaluations).mockResolvedValue([
      completedEvaluation(true, null),
    ] as unknown as Awaited<ReturnType<typeof listSegmentationEvaluations>>);
    renderPanel();
    await screen.findByRole("option", { name: "completed: candidate" });
    fireEvent.change(screen.getByLabelText("Segmentation evaluation history"), {
      target: { value: "evaluation-1" },
    });
    expect(await screen.findByText("0.850")).toBeInTheDocument();
    expect(
      await screen.findByText(/evaluated segmentation candidate is no longer registered/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Promote evaluated segmenter" }),
    ).toBeDisabled();
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("shows the immutable mask holdout digest and per-class sample support", async () => {
    vi.mocked(listSegmentationEvaluations).mockResolvedValue([
      completedEvaluation(true, null),
    ] as unknown as Awaited<ReturnType<typeof listSegmentationEvaluations>>);
    renderPanel();
    await screen.findByRole("option", { name: "completed: candidate" });
    fireEvent.change(screen.getByLabelText("Segmentation evaluation history"), {
      target: { value: "evaluation-1" },
    });
    const provenance = await screen.findByText(
      "Scientific evaluation provenance and class support",
    );
    fireEvent.click(provenance);
    expect(
      await screen.findByText("candidate-inference-1"),
    ).toBeInTheDocument();
    expect(screen.getByText("class-octocoral-open")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("0.830")).toBeInTheDocument();
    expect(screen.getByText("Held-out images")).toBeInTheDocument();
    expect(
      screen.getByText("Candidate checkpoint SHA-256"),
    ).toBeInTheDocument();
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("loads prior project evaluation evidence without activating a model", async () => {
    vi.mocked(listSegmentationEvaluations).mockResolvedValue([
      completedEvaluation(true, null),
    ] as unknown as Awaited<ReturnType<typeof listSegmentationEvaluations>>);
    renderPanel();
    const history = screen.getByLabelText("Segmentation evaluation history");
    await screen.findByRole("option", { name: "completed: candidate" });
    fireEvent.change(history, { target: { value: "evaluation-1" } });
    expect(await screen.findByText("0.850")).toBeInTheDocument();
    expect(listSegmentationEvaluations).toHaveBeenCalledWith(
      project.id,
      expect.anything(),
    );
    expect(queueSegmentationEvaluation).not.toHaveBeenCalled();
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("requires valid sample sizes and passes chosen limits to scoring", async () => {
    renderPanel();
    await screen.findByRole("option", {
      name: "Verified octocoral masks (v1)",
    });
    fireEvent.change(screen.getByLabelText("Segmentation holdout dataset"), {
      target: { value: "version-1" },
    });
    fireEvent.change(screen.getByLabelText("Candidate segmenter"), {
      target: { value: "candidate" },
    });
    const queue = screen.getByRole("button", {
      name: "Queue held-out evaluation",
    });
    const images = screen.getByLabelText("Minimum held-out images");
    const masks = screen.getByLabelText("Minimum verified instance masks");
    fireEvent.change(images, { target: { value: "1" } });
    expect(queue).toBeDisabled();
    fireEvent.change(images, { target: { value: "12" } });
    fireEvent.change(masks, { target: { value: "40" } });
    expect(queue).toBeEnabled();
    fireEvent.click(queue);
    await waitFor(() => {
      expect(queueSegmentationEvaluation).toHaveBeenCalledWith(
        project.id,
        expect.objectContaining({
          minimum_images: 12,
          minimum_masks: 40,
        }),
      );
    });
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("queues isolated holdout evaluation without activating a model", async () => {
    renderPanel();
    await screen.findByRole("option", {
      name: "Verified octocoral masks (v1)",
    });
    fireEvent.change(screen.getByLabelText("Segmentation holdout dataset"), {
      target: { value: "version-1" },
    });
    fireEvent.change(screen.getByLabelText("Candidate segmenter"), {
      target: { value: "candidate" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Queue held-out evaluation" }),
    );
    await waitFor(() => {
      expect(queueSegmentationEvaluation).toHaveBeenCalledWith(
        project.id,
        expect.objectContaining({
          dataset_version_id: "version-1",
          candidate_model_id: "candidate",
          incumbent_model_id: null,
          split: "validation",
        }),
      );
    });
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
    expect(rollbackSegmentationDeployment).not.toHaveBeenCalled();
  });

  it("blocks promotion for failed scientific quality criteria", async () => {
    vi.mocked(getJob).mockResolvedValue(
      completedEvaluation(false, null) as unknown as Awaited<
        ReturnType<typeof getJob>
      >,
    );
    renderPanel();
    await screen.findByRole("option", {
      name: "Verified octocoral masks (v1)",
    });
    fireEvent.change(screen.getByLabelText("Segmentation holdout dataset"), {
      target: { value: "version-1" },
    });
    fireEvent.change(screen.getByLabelText("Candidate segmenter"), {
      target: { value: "candidate" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Queue held-out evaluation" }),
    );
    await screen.findByText("Candidate below mask AP50 floor");
    expect(
      screen.getByRole("button", { name: "Promote evaluated segmenter" }),
    ).toBeDisabled();
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });

  it("requires identity, reason and explicit confirmation for promotion", async () => {
    renderPanel();
    await screen.findByRole("option", {
      name: "Verified octocoral masks (v1)",
    });
    fireEvent.change(screen.getByLabelText("Segmentation holdout dataset"), {
      target: { value: "version-1" },
    });
    fireEvent.change(screen.getByLabelText("Candidate segmenter"), {
      target: { value: "candidate" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Queue held-out evaluation" }),
    );
    expect(await screen.findByText("0.850")).toBeInTheDocument();
    const promote = screen.getByRole("button", {
      name: "Promote evaluated segmenter",
    });
    expect(promote).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operator identity"), {
      target: { value: "Researcher" },
    });
    fireEvent.change(screen.getByLabelText("Reason (at least 10 characters)"), {
      target: { value: "Reviewed immutable mask holdout and approved" },
    });
    expect(promote).toBeEnabled();
    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.click(promote);
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
    fireEvent.click(promote);
    await waitFor(() => {
      expect(promoteSegmentationCandidate).toHaveBeenCalledWith(
        project.id,
        "evaluation-1",
        null,
        "Researcher",
        "Reviewed immutable mask holdout and approved",
      );
    });
  });

  it("uses the active deployment identity for an explicitly approved rollback", async () => {
    vi.mocked(getModels).mockResolvedValue([
      model("candidate"),
      model("incumbent", true, "deployment-7"),
    ] as unknown as Awaited<ReturnType<typeof getModels>>);
    renderPanel();
    await screen.findByText("incumbent");
    const rollback = screen.getByRole("button", {
      name: "Rollback segmentation deployment",
    });
    expect(rollback).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operator identity"), {
      target: { value: "Researcher" },
    });
    fireEvent.change(screen.getByLabelText("Reason (at least 10 characters)"), {
      target: { value: "Revert to prior verified segmentation deployment" },
    });
    fireEvent.click(rollback);
    await waitFor(() => {
      expect(rollbackSegmentationDeployment).toHaveBeenCalledWith(
        project.id,
        "deployment-7",
        "incumbent",
        "Researcher",
        "Revert to prior verified segmentation deployment",
      );
    });
    expect(promoteSegmentationCandidate).not.toHaveBeenCalled();
  });
});
