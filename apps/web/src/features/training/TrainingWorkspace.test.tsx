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
