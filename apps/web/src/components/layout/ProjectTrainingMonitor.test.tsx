import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/client";
import * as runtime from "../../runtime";
import { ProjectTrainingMonitor } from "./ProjectTrainingMonitor";

vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getTrainingRuns: vi.fn(),
  cancelTrainingRun: vi.fn(),
}));

const activeRun = {
  id: "run-active",
  project_id: "project-1",
  draft_id: "draft-1",
  dataset_version_id: "version-1",
  dataset_manifest_sha256: "a".repeat(64),
  split_manifest_sha256: "b".repeat(64),
  task: "detect",
  catalog_model_id: "yolo11n",
  provider_id: "ultralytics",
  architecture: "yolo11n.yaml",
  initial_checkpoint_source: "managed_catalog",
  initial_checkpoint_model_id: null,
  resolved_model_asset_id: null,
  resolved_model_checksum: null,
  parameter_registry_version: null,
  selected_preset: null,
  installation_state: "Ready",
  device: "cuda",
  precision: "amp",
  run_name: "Swiftia detector",
  notes: null,
  random_seed: 11,
  tiling_config: {},
  training_config: { epochs: 10 },
  tuning_config: {},
  evaluation_config: {},
  resource_limits: {},
  preflight_report: {},
  draft_snapshot: {},
  status: "training",
  stage: "training",
  progress_epoch: 2,
  progress_total_epochs: 10,
  metrics: {
    "metrics/mAP50(B)": 0.8123,
    "metrics/precision(B)": 0.902,
  },
  metrics_history: {},
  warnings: [],
  artifact_manifest: {},
  logs_path: null,
  result_checkpoint_path: null,
  job_id: "job-1",
  error_message: null,
  created_at: "2026-10-05T20:00:00Z",
  started_at: "2026-10-05T20:01:00Z",
  completed_at: null,
  updated_at: "2026-10-05T20:02:00Z",
} as api.TrainingRun;

const completedRun = {
  ...activeRun,
  id: "run-completed",
  run_name: "Swiftia detector completed",
  status: "completed",
  stage: "completed",
  progress_epoch: 10,
  progress_total_epochs: 10,
  result_checkpoint_path: "runs/swiftia/best.pt",
  created_at: "2026-10-04T20:00:00Z",
  completed_at: "2026-10-04T21:00:00Z",
} as api.TrainingRun;

function renderMonitor() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProjectTrainingMonitor projectId="project-1" />
    </QueryClientProvider>,
  );

  return queryClient;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getTrainingRuns).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProjectTrainingMonitor", () => {
  it("opens the active run in a desktop PowerShell monitor", async () => {
    vi.spyOn(runtime, "getRuntimeContext").mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:8000/api/v1",
      dataDir: "C:/ReefVision",
      desktopMode: true,
    });
    const open = vi
      .spyOn(runtime, "openDesktopTrainingConsole")
      .mockResolvedValue(undefined);
    vi.mocked(api.getTrainingRuns).mockResolvedValue([activeRun]);

    renderMonitor();
    await screen.findByText("Swiftia detector");
    await userEvent.click(
      screen.getByRole("button", { name: "Open Training Console" }),
    );
    await waitFor(() => expect(open).toHaveBeenCalledWith("run-active"));
  });

  it("serializes rapid console clicks and allows retry after a launcher error", async () => {
    vi.spyOn(runtime, "getRuntimeContext").mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:8000/api/v1",
      dataDir: "C:/ReefVision",
      desktopMode: true,
    });
    let rejectFirst: (error: Error) => void = () => {
      throw new Error("The first console launch was never started");
    };
    const open = vi
      .spyOn(runtime, "openDesktopTrainingConsole")
      .mockImplementationOnce(
        () =>
          new Promise<void>((_resolve, reject) => {
            rejectFirst = reject;
          }),
      )
      .mockResolvedValueOnce(undefined);
    vi.mocked(api.getTrainingRuns).mockResolvedValue([activeRun]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    // Dispatch both clicks before React flushes the disabled-button state.
    // A synchronous guard must prevent launching two PowerShell processes.
    act(() => {
      const button = screen.getByRole("button", {
        name: "Open Training Console",
      });
      button.click();
      button.click();
    });
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith("run-active");

    await act(async () => {
      rejectFirst(new Error("PowerShell unavailable"));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "PowerShell unavailable",
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Open Training Console" }),
    );
    await waitFor(() => expect(open).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["completed", "failed"] as const)(
    "opens the read-only PowerShell monitor for %s runs",
    async (status) => {
      vi.spyOn(runtime, "getRuntimeContext").mockReturnValue({
        apiBaseUrl: "http://127.0.0.1:8000/api/v1",
        dataDir: "C:/ReefVision",
        desktopMode: true,
      });
      const open = vi
        .spyOn(runtime, "openDesktopTrainingConsole")
        .mockResolvedValue(undefined);
      vi.mocked(api.getTrainingRuns).mockResolvedValue([
        { ...completedRun, status },
      ]);

      renderMonitor();
      await screen.findByText("Swiftia detector completed");
      expect(
        screen.queryByRole("button", { name: "Cancel run" }),
      ).not.toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: "Open Training Console" }),
      );
      await waitFor(() => expect(open).toHaveBeenCalledWith("run-completed"));
    },
  );

  it("does not offer a PowerShell launcher in browser mode", async () => {
    vi.spyOn(runtime, "getRuntimeContext").mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:8000/api/v1",
      dataDir: "C:/ReefVision",
      desktopMode: false,
    });
    vi.mocked(api.getTrainingRuns).mockResolvedValue([completedRun]);

    renderMonitor();
    await screen.findByText("Swiftia detector completed");
    expect(
      screen.queryByRole("button", { name: "Open Training Console" }),
    ).not.toBeInTheDocument();
  });

  it("shows active canonical training progress, metrics, and provenance", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([activeRun]);

    renderMonitor();

    expect(await screen.findByText("Swiftia detector")).toBeInTheDocument();
    expect(screen.getByText("1 active")).toBeInTheDocument();
    expect(screen.getByText("2/10")).toBeInTheDocument();
    expect(screen.getByText("cuda")).toBeInTheDocument();
    expect(screen.getByText("0.8123")).toBeInTheDocument();
    expect(screen.getByText("aaaaaaaaaa")).toBeInTheDocument();

    expect(
      screen.getByRole("progressbar", {
        name: "Swiftia detector progress",
      }),
    ).toHaveAttribute("value", "2");
  });

  it("shows real box, cls and dfl losses from epoch history before other metrics", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([
      {
        ...activeRun,
        metrics: {
          "metrics/mAP50(B)": 0.8123,
          "metrics/precision(B)": 0.902,
          "train/box_loss": 0.5, // Stale summary must not replace epoch 2.
          "train/cls_loss": 9.9,
          "train/dfl_loss": Number.NaN,
        },
        metrics_history: {
          "train/box_loss": [0.8, 0.6],
          "train/cls_loss": [1.5, 1.2],
          "train/dfl_loss": [1.1, 0.9],
        },
      },
    ]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    expect(screen.getByText("train box loss")).toBeInTheDocument();
    expect(screen.getByText("train cls loss")).toBeInTheDocument();
    expect(screen.getByText("train dfl loss")).toBeInTheDocument();
    expect(screen.getByText("0.6")).toBeInTheDocument();
    expect(screen.getByText("1.2")).toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
    expect(screen.queryByText("9.9")).not.toBeInTheDocument();
    expect(screen.getByText("0.9")).toBeInTheDocument();
    expect(screen.getByText("0.8123")).toBeInTheDocument();
    expect(screen.getByText("0.902")).toBeInTheDocument();
  });

  it("does not report small nonzero training losses as measured zeros", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([
      {
        ...activeRun,
        metrics: {},
        metrics_history: {
          "train/box_loss": [0],
          "train/cls_loss": [0.000012],
          "train/dfl_loss": [0.00000025],
        },
      },
    ]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    const measuredValue = (name: string) =>
      screen.getByText(name).closest("div")?.querySelector("dd > span");
    expect(measuredValue("train box loss")).toHaveTextContent("0");
    expect(measuredValue("train cls loss")).toHaveTextContent("1.2e-5");
    expect(measuredValue("train dfl loss")).toHaveTextContent("2.5e-7");
    expect(api.cancelTrainingRun).not.toHaveBeenCalled();
  });

  it("keeps the last finite box, cls and dfl losses during partial epochs", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([
      {
        ...activeRun,
        metrics: { "train/box_loss": 0.99 },
        metrics_history: {
          "train/box_loss": [0.4, 0.25, Number.NaN],
          "train/cls_loss": [0.7, 0, Number.POSITIVE_INFINITY],
          "train/dfl_loss": [0.3, 0.12, Number.NaN],
          "train/seg_loss": [Number.NaN],
        },
      },
    ]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    expect(screen.getByText("train box loss")).toBeInTheDocument();
    expect(screen.getByText("train cls loss")).toBeInTheDocument();
    expect(screen.getByText("train dfl loss")).toBeInTheDocument();
    expect(screen.getByText("0.25")).toBeInTheDocument();
    expect(screen.queryByText("0.99")).not.toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("0.12")).toBeInTheDocument();
    expect(screen.queryByText("train seg loss")).not.toBeInTheDocument();
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
  });

  it("excludes negative standard YOLO losses while retaining valid prior samples and signed objectives", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([
      {
        ...activeRun,
        metrics: {
          "train/box_loss": -0.6,
          "train/cls_loss": -0.8,
          "train/seg_loss": 0.7,
          "VAL/CLS_LOSS": -0.5,
          "train/custom_signed_objective": -0.25,
        },
        metrics_history: {
          "train/box_loss": [0.4, -0.1],
          "train/cls_loss": [-0.8],
          "TRAIN/DFL_LOSS": [0.8, -0.2],
          "train/seg_loss": [-0.3],
        },
      },
    ]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    const boxRow = screen.getByText("train box loss").closest("div");
    expect(boxRow).toHaveTextContent("0.4");
    expect(boxRow).toHaveTextContent("prior sample");
    expect(screen.queryByText("train cls loss")).not.toBeInTheDocument();

    const dflRow = screen.getByText("TRAIN DFL LOSS").closest("div");
    expect(dflRow).toHaveTextContent("0.8");
    expect(dflRow).toHaveTextContent("prior sample");

    const segRow = screen.getByText("train seg loss").closest("div");
    expect(segRow).toHaveTextContent("0.7");
    expect(segRow).toHaveTextContent("summary fallback");
    expect(screen.queryByText("VAL CLS LOSS")).not.toBeInTheDocument();
    expect(
      screen.getByText("train custom signed objective").closest("div"),
    ).toHaveTextContent("-0.25");
    expect(api.cancelTrainingRun).not.toHaveBeenCalled();
  });

  it("labels stale loss samples and summary fallbacks without claiming current-epoch measurements", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([
      {
        ...activeRun,
        progress_epoch: 3,
        metrics: {
          "train/box_loss": 0.99,
          "train/cls_loss": 0.55,
          "metrics/mAP50(B)": 0.81,
        },
        metrics_history: {
          "train/box_loss": [0.75, 0.25, null],
          "train/cls_loss": [null, Number.NaN],
        },
      },
    ]);

    renderMonitor();
    await screen.findByText("Swiftia detector");

    const boxRow = screen.getByText("train box loss").closest("div");
    expect(boxRow).toHaveTextContent("0.25");
    expect(boxRow).toHaveTextContent(
      "history entry 2/3; prior sample; epoch association unverified",
    );
    expect(screen.queryByText("0.99")).not.toBeInTheDocument();

    const clsRow = screen.getByText("train cls loss").closest("div");
    expect(clsRow).toHaveTextContent("0.55");
    expect(clsRow).toHaveTextContent(
      "summary fallback; history unavailable; epoch association unverified",
    );

    const mapRow = screen.getByText("metrics mAP50(B)").closest("div");
    expect(mapRow).toHaveTextContent("0.81");
    expect(mapRow).toHaveTextContent("summary; epoch association unverified");
    // These are observation/source labels, not verified epoch associations;
    // monitoring never mutates the training run or its persisted loss history.
    expect(api.cancelTrainingRun).not.toHaveBeenCalled();
  });

  it("cancels through the existing training-run API and updates the shared cache", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([activeRun]);
    vi.mocked(api.cancelTrainingRun).mockResolvedValue({
      ...activeRun,
      status: "cancel_requested",
      stage: "training",
    });

    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderMonitor();

    await screen.findByText("Swiftia detector");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Cancel run",
      }),
    );

    await waitFor(() =>
      expect(api.cancelTrainingRun).toHaveBeenCalledWith("run-active"),
    );

    expect(await screen.findByText("cancel requested")).toBeInTheDocument();

    expect(
      screen.queryByRole("button", {
        name: "Cancel run",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps completed runs visible without presenting cancellation", async () => {
    vi.mocked(api.getTrainingRuns).mockResolvedValue([completedRun]);

    renderMonitor();

    expect(
      await screen.findByText("Swiftia detector completed"),
    ).toBeInTheDocument();

    expect(screen.getByText("No active runs")).toBeInTheDocument();
    expect(screen.getByText("10/10")).toBeInTheDocument();

    expect(
      screen.queryByRole("button", {
        name: "Cancel run",
      }),
    ).not.toBeInTheDocument();
  });

  it("shows an explicit empty state before the first training run", async () => {
    renderMonitor();

    expect(await screen.findByText("No training runs yet")).toBeInTheDocument();
  });
});
