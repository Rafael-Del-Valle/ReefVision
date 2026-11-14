import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ModelRegistration } from "../../api/client";
import type { PoseTrainingDataset } from "../video/poseActiveLearningApi";
import { PoseEvaluationComparisonPanel } from "./PoseEvaluationComparisonPanel";

const model = (id: string, provider: string): ModelRegistration => ({
  id,
  project_id: "project-1",
  purpose: "detector",
  display_name: `${provider} fish`,
  source_filename: `${id}.pt`,
  managed_path: `models/${id}.pt`,
  sha256: id.padEnd(64, "a"),
  file_size_bytes: 100,
  framework: provider,
  task: "pose",
  provider_name: provider,
  provider_version: "1",
  class_map_json: {},
  input_size_json: null,
  metadata_json: {
    source_pose_schema_id: "schema-1",
    source_pose_schema_revision: 2,
    source_pose_schema_content_hash: "s".repeat(64),
  },
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const dataset: PoseTrainingDataset = {
  id: "dataset-1",
  project_id: "project-1",
  source_round_id: "round-1",
  name: "Held-out fish",
  status: "complete",
  schema_version: "pose-training-dataset-0001",
  pose_schema_id: "schema-1",
  pose_schema_revision: 2,
  pose_schema_content_hash: "s".repeat(64),
  source_selection_sha256: "x".repeat(64),
  source_retraining_manifest_sha256: "y".repeat(64),
  manifest_json: {},
  manifest_sha256: "m".repeat(64),
  item_count: 12,
  created_by: "scientist",
  created_at: "2026-01-01T00:00:00Z",
};

afterEach(() => vi.restoreAllMocks());

describe("PoseEvaluationComparisonPanel", () => {
  it("submits multiple compatible providers and renders persisted comparison metrics", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.includes("pose-evaluation-comparisons") &&
          init?.method === "POST"
        ) {
          const payload = JSON.parse(String(init.body));
          expect(payload.model_ids).toEqual(["model-r", "model-u"]);
          expect(payload.evaluation_dataset_id).toBe("dataset-1");
          return new Response(
            JSON.stringify({
              id: "job-1",
              project_id: "project-1",
              job_type: "pose_evaluation",
              status: "queued",
              progress_current: 0,
              progress_total: 24,
              request_json: payload,
              result_json: { stage: "queued" },
              error_message: null,
              created_at: "2026-01-01T00:00:00Z",
              started_at: null,
              completed_at: null,
            }),
            { status: 202, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(
          JSON.stringify({
            items: [
              {
                id: "job-complete",
                project_id: "project-1",
                job_type: "pose_evaluation",
                status: "succeeded",
                progress_current: 24,
                progress_total: 24,
                request_json: { evaluation_dataset_id: "dataset-1" },
                result_json: {
                  stage: "completed",
                  report_sha256: "r".repeat(64),
                  models: [
                    {
                      model_id: "model-r",
                      display_name: "reefpose fish",
                      provider_name: "reefpose",
                      metrics: {
                        nme: 0.12,
                        mean_euclidean_error: 2.5,
                        pck: { "0.1": 0.75 },
                        oks: 0.61,
                        visibility: { precision: 0.9, recall: 0.8 },
                        per_landmark: {
                          snout: {
                            name: "Snout",
                            nme: 0.1,
                            mean_euclidean_error: 2,
                            localization_coverage: 1,
                          },
                        },
                        normalized_error_distribution: {
                          bin_edges: [0.05, 0.1],
                          bin_counts: [3, 1],
                          overflow_count: 0,
                        },
                        calibration: {
                          expected_calibration_error: 0.08,
                          reliability_bins: [
                            {
                              mean_confidence: 0.8,
                              accuracy: 0.75,
                              sample_count: 4,
                            },
                          ],
                        },
                      },
                      performance: {
                        inference_latency_ms: 4,
                        images_per_second: 250,
                      },
                      metric_availability: {
                        nme: { available: true, reason: null },
                        euclidean_error: { available: true, reason: null },
                        pck: { available: true, reason: null },
                        oks: { available: true, reason: null },
                        calibration: { available: true, reason: null },
                        visibility: {
                          available: false,
                          reason: "Provider visibility semantics unavailable",
                        },
                      },
                    },
                  ],
                  exclusions: [
                    {
                      model_id: "model-s",
                      provider_name: "sleap_nn",
                      code: "provider_runtime_unavailable",
                      reason: "Pinned SLEAP runtime unavailable",
                    },
                  ],
                  warnings: ["Synthetic engineering fixture"],
                },
                error_message: null,
                created_at: "2026-01-01T00:00:00Z",
                started_at: "2026-01-01T00:00:01Z",
                completed_at: "2026-01-01T00:00:02Z",
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <PoseEvaluationComparisonPanel
          projectId="project-1"
          models={[
            model("model-r", "reefpose"),
            model("model-u", "ultralytics"),
          ]}
          datasets={[dataset]}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("NME: 0.12")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Normalized error distribution/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Calibration ECE: 0.08")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Confidence reliability/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Per-landmark error chart/ }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/Provider visibility semantics unavailable/).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("table", { name: /Per-landmark performance/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: /Comparative pose metrics/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/throughput: 250 images\/s/)).toBeInTheDocument();
    expect(
      screen.getByText(/Pinned SLEAP runtime unavailable/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Held-out evaluation dataset"), {
      target: { value: "dataset-1" },
    });
    for (const checkbox of screen.getAllByRole("checkbox"))
      fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "Start comparison" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });
});
