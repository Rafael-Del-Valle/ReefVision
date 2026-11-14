import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as runtime from "../../runtime";

import type { TrainingRun } from "../../api/client";
import { TrainingRunDetail } from "./TrainingRunDetail";

const run: TrainingRun = {
  id: "run-1",
  project_id: "project-1",
  draft_id: "draft-1",
  dataset_version_id: "version-1",
  dataset_manifest_sha256: "a".repeat(64),
  split_manifest_sha256: "b".repeat(64),
  task: "detect",
  catalog_model_id: "yolo11",
  provider_id: "ultralytics",
  architecture: "yolo11n.yaml",
  initial_checkpoint_source: "managed_catalog",
  initial_checkpoint_model_id: null,
  resolved_model_asset_id: "catalog_model:yolo11",
  resolved_model_checksum: "c".repeat(64),
  parameter_registry_version: "1",
  selected_preset: "recommended",
  installation_state: "Ready",
  device: "cpu",
  precision: "fp32",
  run_name: "Coral detector",
  notes: null,
  random_seed: 17,
  tiling_config: {},
  training_config: { epochs: 3 },
  tuning_config: {},
  evaluation_config: {},
  resource_limits: {},
  preflight_report: {},
  draft_snapshot: { training_config: { epochs: 3 }, random_seed: 17 },
  status: "completed",
  stage: "completed",
  progress_epoch: 3,
  progress_total_epochs: 3,
  metrics: { "metrics/mAP50-95(B)": 0.41 },
  metrics_history: {
    epoch: [1, 2, 3],
    "metrics/mAP50-95(B)": [0.31, 0.52, 0.41],
    "train/box_loss": [1.2, 0.9, 0.8],
  },
  warnings: [],
  artifact_manifest: {
    artifacts: [
      {
        name: "results.csv",
        category: "metrics",
        relative_path: "runs/results.csv",
        size_bytes: 120,
        previewable: false,
      },
      {
        name: "best.pt",
        category: "checkpoint",
        relative_path: "runs/weights/best.pt",
        size_bytes: 2048,
        previewable: false,
      },
      {
        name: "last.pt",
        category: "checkpoint",
        relative_path: "runs/weights/last.pt",
        size_bytes: 2048,
        previewable: false,
      },
    ],
  },
  logs_path: null,
  result_checkpoint_path: "runs/weights/best.pt",
  job_id: "job-1",
  error_message: null,
  created_at: "2026-08-26T00:00:00Z",
  started_at: "2026-08-26T00:00:01Z",
  completed_at: "2026-08-26T00:01:00Z",
  updated_at: "2026-08-26T00:01:00Z",
};

describe("TrainingRunDetail", () => {
  it("requests the live PowerShell monitor through the desktop runtime helper", async () => {
    vi.spyOn(runtime, "getRuntimeContext").mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:8000/api/v1",
      dataDir: "C:/ReefVision",
      desktopMode: true,
    });
    const openConsole = vi
      .spyOn(runtime, "openDesktopTrainingConsole")
      .mockResolvedValue(undefined);
    render(
      <TrainingRunDetail
        run={{ ...run, status: "training" }}
        registering={false}
        onCancel={vi.fn()}
        onRegister={vi.fn()}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Open Training Console" }),
    );
    await waitFor(() => expect(openConsole).toHaveBeenCalledWith("run-1"));
    vi.restoreAllMocks();
  });

  it("shows the actual best epoch, task metrics, checkpoints, artifacts, and provenance", () => {
    render(
      <TrainingRunDetail
        run={run}
        registering={false}
        onCancel={vi.fn()}
        onRegister={vi.fn()}
      />,
    );
    expect(screen.getByText("Best epoch").parentElement).toHaveTextContent("2");
    expect(
      screen.getByRole("img", { name: /mAP50-95\(B\).*3 epochs/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Best checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Last checkpoint")).toBeInTheDocument();
    expect(screen.getByText("results.csv")).toBeInTheDocument();
    expect(
      screen.getByText("Configuration and provenance"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Register best detector" }),
    ).toBeEnabled();
  });

  it("shows every available detection, segmentation, and validation metric", () => {
    render(
      <TrainingRunDetail
        run={{
          ...run,
          task: "segment",
          metrics_history: {
            epoch: [1, 2],
            "train/box_loss": [1.2, 0.9],
            "train/seg_loss": [1.1, 0.8],
            "train/cls_loss": [0.7, 0.5],
            "train/dfl_loss": [0.6, 0.4],
            "metrics/mAP50-95(M)": [0.2, 0.3],
            "val/box_loss": [1.0, 0.8],
            "val/seg_loss": [0.9, 0.7],
            "val/cls_loss": [0.6, 0.4],
            "val/dfl_loss": [0.5, 0.3],
          },
        }}
        registering={false}
        onCancel={vi.fn()}
        onRegister={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("img", { name: /train box loss across 2 epochs/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /train seg loss across 2 epochs/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /train cls loss across 2 epochs/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /train dfl loss across 2 epochs/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /val seg loss across 2 epochs/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /val dfl loss across 2 epochs/i }),
    ).toBeInTheDocument();
  });

  it("shows ReefPose losses, best checkpoint state, device, and resume action", async () => {
    const onResume = vi.fn();
    render(
      <TrainingRunDetail
        run={{
          ...run,
          task: "pose",
          provider_id: "reefpose",
          architecture: "reefpose-s",
          status: "cancelled",
          stage: "cancelled",
          device: "cuda",
          precision: "amp",
          progress_epoch: 2,
          metrics_history: {
            epoch: [1, 2, 3],
            train_loss: [2.1, 1.4, 1.2],
            validation_loss: [2.0, 1.1, 1.5],
            selection_loss: [2.0, 1.1, 1.5],
            learning_rate: [0.0003, 0.0002, 0.0001],
          },
          artifact_manifest: {
            ...run.artifact_manifest,
            resume_checkpoint_path: "projects/project-1/runs/run-1/last.pt",
          },
        }}
        registering={false}
        onCancel={vi.fn()}
        onRegister={vi.fn()}
        onResume={onResume}
      />,
    );

    expect(screen.getByText("Best epoch").parentElement).toHaveTextContent("2");
    expect(
      screen.getAllByText("Device / precision")[0].parentElement,
    ).toHaveTextContent("cuda / amp");
    expect(
      screen.getByRole("img", { name: /validation loss across 3 epochs/i }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Resume from checkpoint" }),
    );
    expect(onResume).toHaveBeenCalledTimes(1);
  });
});
