import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/client";
import { TrainingWorkspace } from "./TrainingWorkspace";

vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getTrainingWorkspaceBootstrap: vi.fn(),
  getTrainingDraft: vi.fn(),
  getTrainingRuns: vi.fn(),
  getDatasetVersions: vi.fn(),
  getModels: vi.fn(),
  getExperiments: vi.fn(),
  registerModelFromRun: vi.fn(),
  runTrainingPreflight: vi.fn(),
  createTrainingRun: vi.fn(),
  updateTrainingDraft: vi.fn(),
}));

const project = { id: "project-1", slug: "coral" } as api.Project;
const preflight = {
  status: "ready",
  warnings: [],
  blockers: [],
  dataset: { warnings: [] },
  leakage_audit: { blockers: [] },
} as unknown as api.TrainingPreflight;
const draft = {
  id: "draft-1",
  project_id: project.id,
  name: "Draft 1",
  run_name: "Coral",
  task: "detect",
  architecture: "yolo11n.yaml",
  provider_id: "ultralytics",
  initial_checkpoint_source: "scratch",
  dataset_version_id: "version-1",
  random_seed: 11,
  dataset_manifest_sha256: "a".repeat(64),
  split_manifest_sha256: "b".repeat(64),
  training_config: { epochs: 3 },
  tiling_config: {},
  tuning_config: {},
  evaluation_config: {},
  resource_limits: {},
  validation_state: preflight,
} as unknown as api.TrainingDraft;
const run = {
  ...draft,
  id: "run-1",
  draft_id: draft.id,
  status: "training",
  stage: "training",
  progress_epoch: 0,
  progress_total_epochs: 3,
  metrics: {},
  metrics_history: {},
  warnings: [],
  artifact_manifest: {},
  preflight_report: {},
  draft_snapshot: {},
  created_at: "2026-09-12T00:00:00Z",
} as unknown as api.TrainingRun;
let queryClient: QueryClient;

function renderWorkspace() {
  return render(
    <QueryClientProvider client={queryClient}>
      <TrainingWorkspace project={project} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
    providers: [],
    catalog: { models: [] },
    draft_summaries: [draft],
    selected_draft: draft,
  } as unknown as api.TrainingWorkspaceBootstrapResponse);
  vi.mocked(api.getTrainingDraft).mockResolvedValue(draft);
  vi.mocked(api.getTrainingRuns).mockResolvedValue([]);
  vi.mocked(api.getDatasetVersions).mockResolvedValue([]);
  vi.mocked(api.getModels).mockResolvedValue([]);
  vi.mocked(api.getExperiments).mockResolvedValue([]);
  vi.mocked(api.runTrainingPreflight).mockResolvedValue(preflight);
  vi.mocked(api.createTrainingRun).mockResolvedValue(run);
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  vi.useRealTimers();
});

describe("TrainingWorkspace launch", () => {
  it("persists an explicit optimizer learning rate and clears the override on Auto", async () => {
    vi.mocked(api.updateTrainingDraft).mockImplementation(
      async (_id, patch) =>
        ({
          ...draft,
          ...patch,
        }) as api.TrainingDraft,
    );
    renderWorkspace();
    fireEvent.click(
      await screen.findByRole("tab", { name: "Hyperparameters" }),
    );
    expect(
      await screen.findByLabelText("Initial learning rate (lr0)"),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Optimizer"), {
      target: { value: "AdamW" },
    });
    fireEvent.change(screen.getByLabelText("Initial learning rate (lr0)"), {
      target: { value: "0.0025" },
    });
    await waitFor(() =>
      expect(api.updateTrainingDraft).toHaveBeenCalledWith(draft.id, {
        training_config: { epochs: 3, optimizer: "AdamW", lr0: 0.0025 },
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "New Run" }));
    fireEvent.click(screen.getByRole("tab", { name: "Hyperparameters" }));
    expect(screen.getByLabelText("Initial learning rate (lr0)")).toHaveValue(
      0.0025,
    );
    fireEvent.change(screen.getByLabelText("Optimizer"), {
      target: { value: "auto" },
    });
    await waitFor(() =>
      expect(api.updateTrainingDraft).toHaveBeenCalledWith(draft.id, {
        training_config: { epochs: 3, optimizer: "auto" },
      }),
    );
    expect(screen.getByLabelText("Initial learning rate (lr0)")).toBeDisabled();
  });

  it("selects an available architecture with explicit random initialization and no checkpoint", async () => {
    const architecture = {
      catalog_id: "ultralytics/yolo11/detect/n",
      category: "architecture",
      task: "detect",
      provider: "ultralytics",
      architecture_family: "YOLO11",
      architecture_reference: "yolo11n.yaml",
      display_name: "YOLO11 Nano",
      installation_state: "Available",
      selection_kind: "builtin_architecture",
      trainable: true,
      resolved_model_id: null,
    } as api.ModelCatalogEntry;
    vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
      providers: [],
      catalog: { models: [architecture] },
      draft_summaries: [draft],
      selected_draft: draft,
    } as unknown as api.TrainingWorkspaceBootstrapResponse);
    vi.mocked(api.updateTrainingDraft).mockResolvedValue({
      ...draft,
      catalog_model_id: architecture.catalog_id,
    });
    renderWorkspace();
    fireEvent.change(await screen.findByLabelText("Model size or preset"), {
      target: { value: architecture.catalog_id },
    });
    await waitFor(() =>
      expect(api.updateTrainingDraft).toHaveBeenCalledWith(
        draft.id,
        expect.objectContaining({
          architecture: "yolo11n.yaml",
          initial_checkpoint_source: "scratch",
          initial_checkpoint_model_id: null,
        }),
      ),
    );
    expect(
      screen.getByText(/Random initialization.*No trained weights/),
    ).toBeInTheDocument();
  });

  it("shows missing-provider architectures instead of an empty task selector", async () => {
    const architecture = {
      catalog_id: "ultralytics/yolo11/detect/n",
      category: "architecture",
      task: "detect",
      provider: "ultralytics",
      architecture_family: "YOLO11",
      architecture_reference: "yolo11n.yaml",
      display_name: "YOLO11 Nano",
      installation_state: "Provider Required",
      installation_reason:
        "The compatible provider runtime is required for training.",
      selection_kind: "builtin_architecture",
      trainable: true,
      resolved_model_id: null,
    } as api.ModelCatalogEntry;
    vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
      providers: [],
      catalog: { models: [architecture] },
      draft_summaries: [draft],
      selected_draft: {
        ...draft,
        task: "",
        architecture: "",
        catalog_model_id: null,
      },
    } as unknown as api.TrainingWorkspaceBootstrapResponse);
    vi.mocked(api.updateTrainingDraft).mockResolvedValue({
      ...draft,
      catalog_model_id: architecture.catalog_id,
    });

    renderWorkspace();
    const preset = await screen.findByLabelText("Model size or preset");
    expect(preset).toHaveValue("");
    expect(
      screen.getByRole("option", { name: /YOLO11 Nano.*Provider Required/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Architectures labeled Provider Required/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No supported training architectures/),
    ).not.toBeInTheDocument();

    fireEvent.change(preset, { target: { value: architecture.catalog_id } });
    await waitFor(() =>
      expect(api.updateTrainingDraft).toHaveBeenCalledWith(
        draft.id,
        expect.objectContaining({
          catalog_model_id: architecture.catalog_id,
          task: "detect",
          architecture: "yolo11n.yaml",
          initial_checkpoint_source: "scratch",
        }),
      ),
    );
  });

  it("distinguishes an empty catalog from provider-required architectures", async () => {
    renderWorkspace();
    expect(
      await screen.findByText(
        /No training architectures were returned by the model catalog/,
      ),
    ).toBeInTheDocument();
  });

  it("rechecks stale blocked validation and only launches after a fresh ready preflight", async () => {
    vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
      providers: [],
      catalog: { models: [] },
      draft_summaries: [draft],
      selected_draft: {
        ...draft,
        validation_state: { ...preflight, status: "blocked" },
      },
    } as unknown as api.TrainingWorkspaceBootstrapResponse);
    let resolvePreflight!: (value: api.TrainingPreflight) => void;
    vi.mocked(api.runTrainingPreflight).mockReturnValue(
      new Promise((resolve) => {
        resolvePreflight = resolve;
      }),
    );
    renderWorkspace();
    fireEvent.click(
      await screen.findByRole("button", { name: "Start training" }),
    );
    await waitFor(() =>
      expect(api.runTrainingPreflight).toHaveBeenCalledOnce(),
    );
    expect(api.createTrainingRun).not.toHaveBeenCalled();
    await act(async () => resolvePreflight(preflight));
    await waitFor(() =>
      expect(api.createTrainingRun).toHaveBeenCalledWith(project.id, {
        draft_id: draft.id,
      }),
    );
  });

  it("shows a fresh preflight blocker without creating a run", async () => {
    vi.mocked(api.runTrainingPreflight).mockResolvedValue({
      ...preflight,
      status: "blocked",
      blockers: ["Architecture unavailable"],
    });
    renderWorkspace();
    fireEvent.click(
      await screen.findByRole("button", { name: "Start training" }),
    );
    await screen.findAllByText("Architecture unavailable");
    expect(api.createTrainingRun).not.toHaveBeenCalled();
  });

  it("waits for autosave before enabling launch and keeps failed saves blocked", async () => {
    let rejectSave!: (reason: Error) => void;
    vi.mocked(api.updateTrainingDraft).mockReturnValue(
      new Promise((_, reject) => {
        rejectSave = reject;
      }),
    );
    renderWorkspace();
    const button = await screen.findByRole("button", {
      name: "Start training",
    });
    fireEvent.change(screen.getByLabelText("Run name"), {
      target: { value: "Changed" },
    });
    expect(button).toBeDisabled();
    await waitFor(() => expect(api.updateTrainingDraft).toHaveBeenCalledOnce());
    expect(button).toBeDisabled();
    await act(async () => rejectSave(new Error("Draft save failed")));
    await waitFor(() =>
      expect(screen.getByTestId("training-draft-save-state")).toHaveTextContent(
        "Draft save failed",
      ),
    );
    expect(button).toBeDisabled();
    vi.mocked(api.updateTrainingDraft).mockResolvedValue({
      ...draft,
      run_name: "Retried",
    });
    fireEvent.change(screen.getByLabelText("Run name"), {
      target: { value: "Retried" },
    });
    await waitFor(() => expect(button).toBeEnabled());
  });
});

describe("TrainingWorkspace progress freshness", () => {
  it("registers a completed pose run from Models without a draft", async () => {
    const completed = {
      ...run,
      draft_id: null,
      provider_id: "ultralytics",
      task: "pose",
      run_name: "Frozen pose run",
      status: "completed",
      stage: "completed",
      notes: "Reviewed landmarks",
      result_checkpoint_path: "training/pose/best.pt",
    } satisfies api.TrainingRun;
    vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
      providers: [],
      catalog: { models: [] },
      draft_summaries: [],
      selected_draft: null,
    } as unknown as api.TrainingWorkspaceBootstrapResponse);
    vi.mocked(api.getTrainingRuns).mockResolvedValue([completed]);
    vi.mocked(api.registerModelFromRun).mockResolvedValue({
      id: "pose-model-1",
    } as api.ModelRegistration);

    renderWorkspace();
    await screen.findByRole("heading", { name: "No training draft selected" });
    fireEvent.click(screen.getByRole("tab", { name: "Models" }));

    expect(
      await screen.findByRole("heading", { name: "Run artifacts" }),
    ).toBeVisible();
    expect(screen.queryByText("No training draft selected")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Register best pose model" }),
    );
    await waitFor(() =>
      expect(api.registerModelFromRun).toHaveBeenCalledWith(project.id, {
        training_run_id: completed.id,
        display_name: "Frozen pose run best",
        notes: "Reviewed landmarks",
      }),
    );
  });

  it.each(["Models", "Runs"] as const)(
    "shows a pose registration rejection in %s and clears it after successful retry",
    async (section) => {
      const completed = {
        ...run,
        draft_id: null,
        registered_model_id: null,
        provider_id: "ultralytics",
        task: "pose",
        run_name: "Restored pose training",
        status: "completed",
        stage: "completed",
        result_checkpoint_path: "training/restored/best.pt",
      } satisfies api.TrainingRun;
      const model = {
        id: "pose-model-1",
        project_id: project.id,
        purpose: "detector",
        display_name: "Restored pose training best",
        source_filename: "best.pt",
        managed_path: "models/best.pt",
        sha256: "a".repeat(64),
        file_size_bytes: 128,
        framework: "pytorch",
        task: "pose",
        provider_name: "ultralytics",
        provider_version: "1",
        class_map_json: {},
        input_size_json: null,
        metadata_json: { source_training_run_id: completed.id },
        notes: null,
        created_at: completed.created_at,
        updated_at: completed.created_at,
      } satisfies api.ModelRegistration;
      const reason =
        "Pose training split manifest checksum no longer matches the persisted training run";
      vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
        providers: [],
        catalog: { models: [] },
        draft_summaries: [],
        selected_draft: null,
      } as unknown as api.TrainingWorkspaceBootstrapResponse);
      vi.mocked(api.getTrainingRuns).mockResolvedValue([completed]);
      vi.mocked(api.registerModelFromRun)
        .mockRejectedValueOnce(new Error(reason))
        .mockImplementationOnce(async () => {
          vi.mocked(api.getModels).mockResolvedValue([model]);
          vi.mocked(api.getTrainingRuns).mockResolvedValue([
            { ...completed, registered_model_id: model.id },
          ]);
          return model;
        });
      renderWorkspace();
      await screen.findByRole("heading", {
        name: "No training draft selected",
      });
      fireEvent.click(screen.getByRole("tab", { name: section }));

      const register = await screen.findByRole("button", {
        name: "Register best pose model",
      });
      fireEvent.click(register);
      expect(
        await screen.findByText(reason, {
          selector: '[role="alert"]',
          exact: false,
        }),
      ).toBeVisible();
      expect(register).toBeEnabled();
      expect(api.registerModelFromRun).toHaveBeenCalledTimes(1);

      fireEvent.click(register);
      await screen.findByText(
        section === "Models"
          ? "Registered as Restored pose training best"
          : "Best model registered as Restored pose training best",
      );
      expect(
        screen.queryByText(reason, {
          selector: '[role="alert"]',
          exact: false,
        }),
      ).not.toBeInTheDocument();
      expect(api.registerModelFromRun).toHaveBeenCalledTimes(2);
      expect(api.registerModelFromRun).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ training_run_id: completed.id }),
      );
    },
  );

  it("labels completed mask and detector registrations by task with a draft open", async () => {
    const completed = ["detect", "segment", "semantic_segment"].map(
      (task) =>
        ({
          ...run,
          id: `${task}-run`,
          task,
          run_name: `${task} reference run`,
          status: "completed",
          stage: "completed",
          result_checkpoint_path: `training/${task}/best.pt`,
        }) satisfies api.TrainingRun,
    );
    vi.mocked(api.getTrainingRuns).mockResolvedValue(completed);
    renderWorkspace();
    await screen.findByLabelText("Run name");
    fireEvent.click(screen.getByRole("tab", { name: "Models" }));

    expect(
      await screen.findByRole("button", {
        name: "Register best detector",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "Register best segmenter",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "Register best semantic segmenter",
      }),
    ).toBeEnabled();
  });

  it("opens completed workflow runs and experiments in a project without a draft", async () => {
    const completedRun = {
      ...run,
      draft_id: null,
      registered_model_id: "model-1",
      provider_id: "reefpose",
      task: "pose",
      run_name: "Frozen workflow training",
      status: "completed",
      stage: "completed",
      progress_epoch: 3,
    } satisfies api.TrainingRun;
    vi.mocked(api.getTrainingWorkspaceBootstrap).mockResolvedValue({
      providers: [],
      catalog: { models: [] },
      draft_summaries: [],
      selected_draft: null,
    } as unknown as api.TrainingWorkspaceBootstrapResponse);
    vi.mocked(api.getTrainingRuns).mockResolvedValue([completedRun]);
    vi.mocked(api.getModels).mockResolvedValue([
      {
        id: "model-1",
        project_id: project.id,
        purpose: "detector",
        task: "pose",
        display_name: "Frozen ReefPose checkpoint",
        source_filename: "best.pt",
        managed_path: "models/best.pt",
        sha256: "a".repeat(64),
        file_size_bytes: 128,
        framework: "pytorch",
        provider_name: "reefpose",
        provider_version: "1",
        class_map_json: {},
        input_size_json: null,
        metadata_json: {
          source_training_run_id: "original-run-with-the-same-checkpoint",
        },
        notes: null,
        created_at: completedRun.created_at,
        updated_at: completedRun.created_at,
      },
    ]);
    vi.mocked(api.getExperiments).mockResolvedValue([
      {
        id: "experiment-1",
        training_run_id: completedRun.id,
        provider_id: "reefpose",
        architecture: "reefpose-s",
        summary_metrics_json: {},
      } as api.ExperimentRecord,
    ]);
    renderWorkspace();

    await screen.findByRole("heading", { name: "No training draft selected" });
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    await screen.findByRole("heading", { name: "Active and completed runs" });
    expect(
      await screen.findByText(
        "Best model registered as Frozen ReefPose checkpoint",
      ),
    ).toBeVisible();
    expect(screen.queryByText("No training draft selected")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Experiments" }));
    expect(
      await screen.findByRole("checkbox", { name: /reefpose-s/ }),
    ).toBeVisible();
    expect(screen.queryByText("No training draft selected")).toBeNull();
    expect(api.getModels).toHaveBeenCalledWith(
      project.id,
      undefined,
      expect.anything(),
    );
    expect(api.getTrainingDraft).not.toHaveBeenCalled();
  });

  it("polls active runs across sections, refreshes completion data, and stops at N/N", async () => {
    vi.useFakeTimers();
    vi.mocked(api.getTrainingRuns)
      .mockResolvedValueOnce([run])
      .mockResolvedValue([
        { ...run, status: "completed", stage: "completed", progress_epoch: 3 },
      ]);
    queryClient.setQueryData(["models", project.id, "detector"], []);
    queryClient.setQueryData(["experiments", project.id], []);
    renderWorkspace();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20);
    });
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.getByText("Progress 0/3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Experiments" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(api.getTrainingRuns).toHaveBeenCalledTimes(2);
    expect(api.getExperiments).toHaveBeenCalledOnce();
    expect(
      queryClient.getQueryState(["models", project.id, "detector"])
        ?.isInvalidated,
    ).toBe(true);
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.getByText("Progress 3/3")).toBeInTheDocument();
    const calls = vi.mocked(api.getTrainingRuns).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(api.getTrainingRuns).toHaveBeenCalledTimes(calls);
  });

  it("refetches completed cached runs when the workspace mounts again", async () => {
    queryClient.setQueryData(
      ["training_runs", project.id],
      [{ ...run, status: "completed" }],
    );
    const view = renderWorkspace();
    await waitFor(() => expect(api.getTrainingRuns).toHaveBeenCalledOnce());
    view.unmount();
    renderWorkspace();
    await waitFor(() => expect(api.getTrainingRuns).toHaveBeenCalledTimes(2));
  });
});
