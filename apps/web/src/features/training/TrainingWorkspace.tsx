import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  cancelTrainingRun,
  compareExperiments,
  createTrainingDraft,
  createTrainingRun,
  deleteTrainingDraft,
  estimateTrainingTiling,
  getDatasetVersions,
  getExperiments,
  getModels,
  getTrainingDraft,
  getTrainingProviderParameters,
  getTrainingRuns,
  getTrainingWorkspaceBootstrap,
  registerModelFromRun,
  runTrainingPreflight,
  type ModelCatalogEntry,
  type ModelCatalogTask,
  type ModelRegistration,
  type Project,
  type TrainingDraft,
  type TrainingDraftSummary,
  type TrainingPreflight,
  type TrainingRun,
  type TuningTrial,
  updateTrainingDraft,
} from "../../api/client";
import { TaskCapabilityMatrix } from "./TaskCapabilityMatrix";
import { SegmentationEvaluationPanel } from "./SegmentationEvaluationPanel";
import { TrainingRunDetail } from "./TrainingRunDetail";
import { trainingRunsContainActive } from "./trainingRunState";

type TrainingSection =
  | "new_run"
  | "dataset_splits"
  | "tiling"
  | "hyperparameters"
  | "tune"
  | "runs"
  | "experiments"
  | "models";

const sections: Array<{ id: TrainingSection; label: string }> = [
  { id: "new_run", label: "New Run" },
  { id: "dataset_splits", label: "Dataset & Splits" },
  { id: "tiling", label: "Tiling" },
  { id: "hyperparameters", label: "Hyperparameters" },
  { id: "tune", label: "Tune" },
  { id: "runs", label: "Runs" },
  { id: "experiments", label: "Experiments" },
  { id: "models", label: "Models" },
];

const taskLabels: Record<ModelCatalogTask, string> = {
  pose: "Pose",
  classify: "Classification",
  detect: "Object detection",
  segment: "Instance segmentation",
  semantic_segment: "Semantic segmentation",
  open_vocabulary_detect: "Open-vocabulary detection",
  example_guided_detect: "Example-guided detection",
  assist_segmentation: "Interactive masking",
  video_propagation: "Video mask propagation",
  track: "Multi-object tracking",
  caption: "Captioning",
  phrase_grounding: "Phrase grounding",
  relative_depth: "Relative monocular depth",
  metric_video_depth: "Metric video depth",
};

const sizeSortOrder = [
  "nano",
  "n",
  "small",
  "s",
  "medium",
  "m",
  "large",
  "l",
  "x",
  "xlarge",
  "default",
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function asPreflight(value: unknown): TrainingPreflight | null {
  return value && typeof value === "object"
    ? (value as TrainingPreflight)
    : null;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function metricLabel(key: string): string {
  return key.replaceAll("/", " ").replaceAll("_", " ");
}

function taskLabel(task: string | null): string {
  if (!task) {
    return "Unselected";
  }
  return taskLabels[task as ModelCatalogTask] ?? task;
}

function fileSizeLabel(sizeBytes: number | null): string {
  if (
    typeof sizeBytes !== "number" ||
    !Number.isFinite(sizeBytes) ||
    sizeBytes <= 0
  ) {
    return "Managed by provider";
  }
  if (sizeBytes >= 1024 * 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  }
  if (sizeBytes >= 1024 * 1024) {
    return `${Math.round(sizeBytes / (1024 * 1024))} MB`;
  }
  return `${Math.round(sizeBytes / 1024)} KB`;
}

function catalogSizeSortValue(model: ModelCatalogEntry): number {
  const token = (model.model_size ?? "").trim().toLowerCase();
  const knownIndex = sizeSortOrder.indexOf(token);
  if (knownIndex >= 0) {
    return knownIndex;
  }
  return sizeSortOrder.length + model.display_name.toLowerCase().charCodeAt(0);
}

function saveStateLabel(
  state: "saved" | "unsaved" | "saving" | "error",
  message: string | null,
): string {
  if (message) {
    return message;
  }
  switch (state) {
    case "unsaved":
      return "Unsaved changes";
    case "saving":
      return "Saving...";
    case "error":
      return "Save failed";
    default:
      return "Saved";
  }
}

function toDraftSummary(draft: TrainingDraft): TrainingDraftSummary {
  const validationState = asRecord(draft.validation_state);
  const warnings = validationState.warnings;
  const blockers = validationState.blockers;
  return {
    id: draft.id,
    project_id: draft.project_id,
    name: draft.name,
    run_name: draft.run_name,
    dataset_version_id: draft.dataset_version_id,
    task: draft.task,
    catalog_model_id: draft.catalog_model_id,
    provider_id: draft.provider_id,
    architecture: draft.architecture,
    initial_checkpoint_source: draft.initial_checkpoint_source,
    validation_status:
      typeof validationState.status === "string"
        ? (validationState.status as TrainingDraftSummary["validation_status"])
        : null,
    warning_count: Array.isArray(warnings) ? warnings.length : 0,
    blocker_count: Array.isArray(blockers) ? blockers.length : 0,
    created_at: draft.created_at,
    updated_at: draft.updated_at,
  };
}

function toTrainingPreflightPayload(
  draft: TrainingDraft,
): Record<string, unknown> {
  return {
    name: draft.name,
    run_name: draft.run_name,
    notes: draft.notes,
    dataset_version_id: draft.dataset_version_id,
    task: draft.task,
    catalog_model_id: draft.catalog_model_id,
    provider_id: draft.provider_id,
    architecture: draft.architecture,
    initial_checkpoint_source: draft.initial_checkpoint_source,
    initial_checkpoint_model_id: draft.initial_checkpoint_model_id,
    device: draft.device,
    precision: draft.precision,
    random_seed: draft.random_seed,
    tiling_config: draft.tiling_config,
    training_config: draft.training_config,
    tuning_config: draft.tuning_config,
    evaluation_config: draft.evaluation_config,
    resource_limits: draft.resource_limits,
  };
}

function applyDraftPatch(
  draft: TrainingDraft,
  patch: Record<string, unknown>,
): TrainingDraft {
  return {
    ...draft,
    ...patch,
    updated_at: new Date().toISOString(),
  };
}

function applyDraftSummaryPatch(
  draft: TrainingDraftSummary,
  patch: Record<string, unknown>,
): TrainingDraftSummary {
  return {
    ...draft,
    name: typeof patch.name === "string" ? patch.name : draft.name,
    run_name:
      typeof patch.run_name === "string" || patch.run_name === null
        ? (patch.run_name as string | null)
        : draft.run_name,
    dataset_version_id:
      typeof patch.dataset_version_id === "string" ||
      patch.dataset_version_id === null
        ? (patch.dataset_version_id as string | null)
        : draft.dataset_version_id,
    task:
      typeof patch.task === "string" || patch.task === null
        ? (patch.task as string | null)
        : draft.task,
    catalog_model_id:
      typeof patch.catalog_model_id === "string" ||
      patch.catalog_model_id === null
        ? (patch.catalog_model_id as string | null)
        : draft.catalog_model_id,
    provider_id:
      typeof patch.provider_id === "string" || patch.provider_id === null
        ? (patch.provider_id as string | null)
        : draft.provider_id,
    architecture:
      typeof patch.architecture === "string" || patch.architecture === null
        ? (patch.architecture as string | null)
        : draft.architecture,
    initial_checkpoint_source:
      typeof patch.initial_checkpoint_source === "string"
        ? patch.initial_checkpoint_source
        : draft.initial_checkpoint_source,
    updated_at: new Date().toISOString(),
  };
}

export function TrainingWorkspace({
  project,
  initialCatalogModelId,
  onCatalogSelectionConsumed,
}: {
  project: Project;
  initialCatalogModelId?: string | null;
  onCatalogSelectionConsumed?: () => void;
}) {
  const queryClient = useQueryClient();
  const [activeSection, setActiveSection] =
    useState<TrainingSection>("new_run");
  const [selectedDraftId, setSelectedDraftId] = useState<string>("");
  const [tilingEstimate, setTilingEstimate] = useState<{
    tile_count: number;
    positive_tile_count: number;
    background_tile_count: number;
    estimated_storage_bytes: number;
    warnings: string[];
    preview_tiles: Array<{
      image_id: string;
      split: string;
      x: number;
      y: number;
      width: number;
      height: number;
      retained_annotation_count: number;
    }>;
  } | null>(null);
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runStatusFilter, setRunStatusFilter] = useState("");
  const [runSort, setRunSort] = useState("newest");
  const [compareWarnings, setCompareWarnings] = useState<string[]>([]);
  const [draftSaveState, setDraftSaveState] = useState<
    "saved" | "unsaved" | "saving" | "error"
  >("saved");
  const [draftSaveMessage, setDraftSaveMessage] = useState<string | null>(null);
  const draftSaveTimerRef = useRef<number | null>(null);
  const pendingDraftPatchRef = useRef<Record<string, unknown>>({});
  const pendingDraftIdRef = useRef<string | null>(null);
  const lastSaveTokenRef = useRef(0);
  const consumedCatalogSelectionRef = useRef<string | null>(null);
  const previousRunStatusesRef = useRef(new Map<string, string>());

  const workspaceBootstrap = useQuery({
    queryKey: ["training_workspace_bootstrap", project.id],
    queryFn: ({ signal }) => getTrainingWorkspaceBootstrap(project.id, signal),
    staleTime: 60_000,
  });
  const drafts = useQuery<TrainingDraftSummary[]>({
    queryKey: ["training_draft_summaries", project.id],
    queryFn: async (): Promise<TrainingDraftSummary[]> => [],
    enabled: false,
  });
  const providers = workspaceBootstrap.data?.providers ?? [];
  const modelCatalog = workspaceBootstrap.data?.catalog ?? null;
  const versions = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
    enabled: selectedDraftId.length > 0,
  });
  const models = useQuery({
    queryKey: ["models", project.id, "detector"],
    queryFn: ({ signal }) => getModels(project.id, "detector", signal),
    enabled: activeSection === "models" || activeSection === "runs",
  });
  const runs = useQuery({
    queryKey: ["training_runs", project.id],
    queryFn: ({ signal }) => getTrainingRuns(project.id, signal),
    refetchOnMount: "always",
    refetchInterval: (query) =>
      trainingRunsContainActive(query.state.data as TrainingRun[] | undefined)
        ? 2000
        : false,
  });
  const experiments = useQuery({
    queryKey: ["experiments", project.id],
    queryFn: ({ signal }) => getExperiments(project.id, signal),
    enabled: activeSection === "experiments",
  });

  useEffect(() => {
    if (!runs.data) return;
    const previous = previousRunStatusesRef.current;
    const hasNewCompletion = runs.data.some(
      (run) =>
        run.status === "completed" && previous.get(run.id) !== "completed",
    );
    previousRunStatusesRef.current = new Map(
      runs.data.map((run) => [run.id, run.status]),
    );
    if (hasNewCompletion) {
      void queryClient.invalidateQueries({
        queryKey: ["experiments", project.id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["models", project.id, "detector"],
      });
    }
  }, [project.id, queryClient, runs.data]);

  const selectedDraftQuery = useQuery({
    queryKey: ["training_draft", selectedDraftId],
    queryFn: ({ signal }) => getTrainingDraft(selectedDraftId, signal),
    enabled: selectedDraftId.length > 0,
    staleTime: 60_000,
  });

  const selectedDraft = selectedDraftQuery.data ?? null;
  const trainingCatalogEntries = useMemo(
    () => (modelCatalog?.models ?? []).filter((item) => item.trainable),
    [modelCatalog?.models],
  );
  const catalogEntryById = useMemo(
    () =>
      new Map(trainingCatalogEntries.map((item) => [item.catalog_id, item])),
    [trainingCatalogEntries],
  );
  const selectedCatalogEntry =
    (selectedDraft?.catalog_model_id
      ? (catalogEntryById.get(selectedDraft.catalog_model_id) ?? null)
      : null) ?? null;
  const architectureTrainingEntries = useMemo(
    () =>
      trainingCatalogEntries.filter(
        (item) =>
          item.category === "architecture" &&
          ["detect", "segment"].includes(item.task) &&
          !item.advanced_only,
      ),
    [trainingCatalogEntries],
  );
  // Keep missing-provider architectures visible so users can diagnose the runtime.
  // The server still blocks training until provider preflight succeeds.
  const selectableArchitectureEntries = useMemo(
    () =>
      architectureTrainingEntries.filter((item) =>
        ["Ready", "Available", "Provider Required"].includes(
          item.installation_state,
        ),
      ),
    [architectureTrainingEntries],
  );
  const myTrainedEntries = useMemo(
    () =>
      trainingCatalogEntries.filter(
        (item) =>
          item.category === "my_trained_models" &&
          (item.installation_state === "Ready" ||
            item.installation_state === "Available"),
      ),
    [trainingCatalogEntries],
  );
  const importedCustomEntries = useMemo(
    () =>
      trainingCatalogEntries.filter(
        (item) =>
          item.category === "imported_custom_models" &&
          (item.installation_state === "Ready" ||
            item.installation_state === "Available"),
      ),
    [trainingCatalogEntries],
  );
  const taskOptions = useMemo(
    () =>
      Array.from(
        new Set(selectableArchitectureEntries.map((item) => item.task)),
      ).sort((left, right) => taskLabel(left).localeCompare(taskLabel(right))),
    [selectableArchitectureEntries],
  );
  const selectedTaskForCatalog =
    selectedCatalogEntry?.category === "architecture"
      ? selectedCatalogEntry.task
      : (taskOptions[0] ?? "detect");
  const architectureFamilies = useMemo(
    () =>
      Array.from(
        new Set(
          selectableArchitectureEntries
            .filter((item) => item.task === selectedTaskForCatalog)
            .map((item) => item.architecture_family),
        ),
      ),
    [selectableArchitectureEntries, selectedTaskForCatalog],
  );
  const selectedArchitectureFamily =
    selectedCatalogEntry?.category === "architecture" &&
    selectedCatalogEntry.task === selectedTaskForCatalog
      ? selectedCatalogEntry.architecture_family
      : (architectureFamilies[0] ?? "");
  const presetOptions = useMemo(
    () =>
      selectableArchitectureEntries
        .filter(
          (item) =>
            item.task === selectedTaskForCatalog &&
            item.architecture_family === selectedArchitectureFamily,
        )
        .sort((left, right) => {
          const delta =
            catalogSizeSortValue(left) - catalogSizeSortValue(right);
          return delta || left.display_name.localeCompare(right.display_name);
        }),
    [
      selectableArchitectureEntries,
      selectedArchitectureFamily,
      selectedTaskForCatalog,
      taskOptions,
    ],
  );
  const selectedProvider =
    providers.find(
      (item) =>
        item.provider_id ===
        (selectedCatalogEntry?.provider ??
          selectedDraft?.provider_id ??
          providers[0]?.provider_id),
    ) ?? null;
  const selectedVersion =
    versions.data?.find(
      (item) => item.id === selectedDraft?.dataset_version_id,
    ) ?? null;
  const preflight = asPreflight(selectedDraft?.validation_state);

  const providerParameters = useQuery({
    queryKey: ["training_provider_parameters", selectedProvider?.provider_id],
    queryFn: ({ signal }) =>
      getTrainingProviderParameters(
        selectedProvider?.provider_id as string,
        signal,
      ),
    enabled:
      activeSection === "hyperparameters" &&
      selectedProvider?.provider_id === "ultralytics" &&
      selectedDraft !== null,
  });

  useEffect(() => {
    if (workspaceBootstrap.data?.draft_summaries) {
      queryClient.setQueryData(
        ["training_draft_summaries", project.id],
        workspaceBootstrap.data.draft_summaries,
      );
    }
    if (workspaceBootstrap.data?.selected_draft) {
      queryClient.setQueryData(
        ["training_draft", workspaceBootstrap.data.selected_draft.id],
        workspaceBootstrap.data.selected_draft,
      );
    }
  }, [project.id, queryClient, workspaceBootstrap.data]);

  useEffect(() => {
    const initialDraftId =
      workspaceBootstrap.data?.selected_draft?.id ?? drafts.data?.[0]?.id ?? "";
    if (initialDraftId && !selectedDraftId) {
      setSelectedDraftId(initialDraftId);
    }
  }, [
    drafts.data,
    selectedDraftId,
    workspaceBootstrap.data?.selected_draft?.id,
  ]);

  const createDraftMutation = useMutation({
    mutationFn: (catalogModelId?: string) =>
      createTrainingDraft(project.id, {
        name: `Draft ${drafts.data?.length ? drafts.data.length + 1 : 1}`,
        run_name: `${project.slug}-train`,
        catalog_model_id: catalogModelId ?? null,
      }),
    onSuccess: async (created) => {
      setSelectedDraftId(created.id);
      queryClient.setQueryData(["training_draft", created.id], created);
      queryClient.setQueryData<TrainingDraftSummary[]>(
        ["training_draft_summaries", project.id],
        (current) => [toDraftSummary(created), ...(current ?? [])],
      );
      setDraftSaveState("saved");
      setDraftSaveMessage(null);
      setActiveSection("new_run");
    },
  });

  const applyTuningMutation = useMutation({
    mutationFn: ({ run, trial }: { run: TrainingRun; trial: TuningTrial }) =>
      createTrainingDraft(project.id, {
        name: `${run.run_name} best trial`,
        run_name: `${run.run_name}-best-${trial.trial_number}`,
        notes: `Derived from tuning run ${run.id}, best trial ${trial.trial_number}.`,
        dataset_version_id: run.dataset_version_id,
        task: run.task,
        catalog_model_id: run.catalog_model_id,
        provider_id: run.provider_id,
        architecture: run.architecture,
        initial_checkpoint_source: run.initial_checkpoint_source as
          "scratch" | "registered_model" | "managed_catalog",
        initial_checkpoint_model_id: run.initial_checkpoint_model_id,
        device: run.device,
        precision: run.precision,
        random_seed: run.random_seed,
        tiling_config: run.tiling_config,
        training_config: { ...run.training_config, ...trial.hyperparameters },
        tuning_config: {
          mode: "disabled",
          derived_from_tuning_run_id: run.id,
          derived_from_trial_number: trial.trial_number,
        },
        evaluation_config: run.evaluation_config,
        resource_limits: run.resource_limits,
      }),
    onSuccess: (created) => {
      setSelectedDraftId(created.id);
      queryClient.setQueryData(["training_draft", created.id], created);
      queryClient.setQueryData<TrainingDraftSummary[]>(
        ["training_draft_summaries", project.id],
        (current) => [toDraftSummary(created), ...(current ?? [])],
      );
      setActiveSection("new_run");
    },
  });

  const updateDraftMutation = useMutation({
    mutationFn: ({
      draftId,
      patch,
    }: {
      draftId: string;
      patch: Record<string, unknown>;
    }) => updateTrainingDraft(draftId, patch),
  });

  const deleteDraftMutation = useMutation({
    mutationFn: (draftId: string) => deleteTrainingDraft(draftId),
    onSuccess: async (_, draftId) => {
      if (draftSaveTimerRef.current !== null) {
        window.clearTimeout(draftSaveTimerRef.current);
        draftSaveTimerRef.current = null;
      }
      pendingDraftPatchRef.current = {};
      pendingDraftIdRef.current = null;
      setSelectedDraftId("");
      queryClient.removeQueries({ queryKey: ["training_draft"] });
      queryClient.setQueryData<TrainingDraftSummary[]>(
        ["training_draft_summaries", project.id],
        (current) => current?.filter((draft) => draft.id !== draftId) ?? [],
      );
    },
  });

  const estimateTilingMutation = useMutation({
    mutationFn: () =>
      estimateTrainingTiling(project.id, {
        dataset_version_id: selectedDraft?.dataset_version_id as string,
        tiling_config: asRecord(selectedDraft?.tiling_config),
      }),
    onSuccess: (result) => setTilingEstimate(result),
  });

  const launchRunMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDraft) {
        throw new Error("Select a training draft before launching a run.");
      }
      const preflightResult = await runTrainingPreflight(
        project.id,
        toTrainingPreflightPayload(selectedDraft),
      );
      const updatedDraft: TrainingDraft = {
        ...selectedDraft,
        validation_state: preflightResult,
      };
      queryClient.setQueryData(
        ["training_draft", selectedDraft.id],
        updatedDraft,
      );
      queryClient.setQueryData<TrainingDraftSummary[]>(
        ["training_draft_summaries", project.id],
        (current) =>
          current?.map((draft) =>
            draft.id === selectedDraft.id
              ? toDraftSummary(updatedDraft)
              : draft,
          ) ?? [],
      );
      if (preflightResult.status === "blocked") {
        throw new Error(
          preflightResult.blockers[0] ?? "Training preflight failed.",
        );
      }
      return createTrainingRun(project.id, { draft_id: selectedDraft.id });
    },
    onSuccess: async () => {
      setActiveSection("runs");
      await queryClient.invalidateQueries({
        queryKey: ["training_runs", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["experiments", project.id],
      });
    },
  });

  const cancelRunMutation = useMutation({
    mutationFn: (runId: string) => cancelTrainingRun(runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["training_runs", project.id],
      });
    },
  });

  const compareExperimentsMutation = useMutation({
    mutationFn: () => compareExperiments(compareSelection),
    onSuccess: (result) => setCompareWarnings(result.warnings),
  });

  const registerRunModelMutation = useMutation({
    mutationFn: ({
      runId,
      displayName,
      notes,
    }: {
      runId: string;
      displayName?: string;
      notes?: string;
    }) =>
      registerModelFromRun(project.id, {
        training_run_id: runId,
        display_name: displayName,
        notes,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["models", project.id, "detector"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["training_workspace_bootstrap", project.id],
      });
    },
  });

  async function flushPendingDraftSave() {
    const draftId = pendingDraftIdRef.current;
    const patch = pendingDraftPatchRef.current;
    if (!draftId || Object.keys(patch).length === 0) {
      return;
    }
    pendingDraftPatchRef.current = {};
    if (draftSaveTimerRef.current !== null) {
      window.clearTimeout(draftSaveTimerRef.current);
      draftSaveTimerRef.current = null;
    }
    const saveToken = ++lastSaveTokenRef.current;
    setDraftSaveState("saving");
    setDraftSaveMessage(null);
    try {
      const saved = await updateDraftMutation.mutateAsync({ draftId, patch });
      queryClient.setQueryData(["training_draft", draftId], saved);
      queryClient.setQueryData<TrainingDraftSummary[]>(
        ["training_draft_summaries", project.id],
        (current) =>
          current?.map((draft) =>
            draft.id === draftId ? toDraftSummary(saved) : draft,
          ) ?? [],
      );
      if (
        pendingDraftIdRef.current === draftId &&
        Object.keys(pendingDraftPatchRef.current).length > 0
      ) {
        setDraftSaveState("unsaved");
        scheduleDraftSave();
        return;
      }
      if (lastSaveTokenRef.current === saveToken) {
        setDraftSaveState("saved");
        setDraftSaveMessage(null);
      }
    } catch (error) {
      pendingDraftPatchRef.current = {
        ...patch,
        ...pendingDraftPatchRef.current,
      };
      setDraftSaveState("error");
      setDraftSaveMessage(
        error instanceof Error ? error.message : "Draft save failed",
      );
    }
  }

  function scheduleDraftSave() {
    if (draftSaveTimerRef.current !== null) {
      window.clearTimeout(draftSaveTimerRef.current);
    }
    draftSaveTimerRef.current = window.setTimeout(() => {
      void flushPendingDraftSave();
    }, 350);
  }

  function patchDraft(patch: Record<string, unknown>) {
    if (!selectedDraft) {
      return;
    }
    if (
      pendingDraftIdRef.current &&
      pendingDraftIdRef.current !== selectedDraft.id
    ) {
      void flushPendingDraftSave();
    }
    pendingDraftIdRef.current = selectedDraft.id;
    pendingDraftPatchRef.current = {
      ...pendingDraftPatchRef.current,
      ...patch,
    };
    queryClient.setQueryData<TrainingDraft>(
      ["training_draft", selectedDraft.id],
      (current) => (current ? applyDraftPatch(current, patch) : current),
    );
    queryClient.setQueryData<TrainingDraftSummary[]>(
      ["training_draft_summaries", project.id],
      (current) =>
        current?.map((draft) =>
          draft.id === selectedDraft.id
            ? applyDraftSummaryPatch(draft, patch)
            : draft,
        ) ?? [],
    );
    setDraftSaveState("unsaved");
    setDraftSaveMessage(null);
    scheduleDraftSave();
  }

  function applyCatalogSelection(entry: ModelCatalogEntry) {
    patchDraft({
      catalog_model_id: entry.catalog_id,
      task: entry.task,
      provider_id: entry.provider,
      architecture: entry.architecture_reference,
      initial_checkpoint_source:
        entry.selection_kind === "registered_model"
          ? "registered_model"
          : "scratch",
      initial_checkpoint_model_id: entry.resolved_model_id,
    });
  }

  useEffect(() => {
    if (
      !initialCatalogModelId ||
      consumedCatalogSelectionRef.current === initialCatalogModelId ||
      !modelCatalog
    ) {
      return;
    }
    const entry = catalogEntryById.get(initialCatalogModelId);
    if (!entry || !["Ready", "Available"].includes(entry.installation_state))
      return;
    consumedCatalogSelectionRef.current = initialCatalogModelId;
    if (selectedDraft) {
      applyCatalogSelection(entry);
      setActiveSection("new_run");
      onCatalogSelectionConsumed?.();
      return;
    }
    createDraftMutation.mutate(initialCatalogModelId, {
      onSuccess: () => onCatalogSelectionConsumed?.(),
    });
  }, [
    catalogEntryById,
    initialCatalogModelId,
    modelCatalog,
    onCatalogSelectionConsumed,
    selectedDraft,
  ]);

  function selectTaskPreset(task: ModelCatalogTask) {
    const nextEntry =
      selectableArchitectureEntries.find((item) => item.task === task) ?? null;
    if (nextEntry) {
      applyCatalogSelection(nextEntry);
    }
  }

  function selectArchitecturePreset(architectureFamily: string) {
    const nextEntry =
      presetOptions.find(
        (item) => item.architecture_family === architectureFamily,
      ) ??
      selectableArchitectureEntries.find(
        (item) =>
          item.task === selectedTaskForCatalog &&
          item.architecture_family === architectureFamily,
      ) ??
      null;
    if (nextEntry) {
      applyCatalogSelection(nextEntry);
    }
  }

  function patchConfig(
    configKey:
      | "tiling_config"
      | "training_config"
      | "tuning_config"
      | "evaluation_config"
      | "resource_limits",
    key: string,
    value: unknown,
  ) {
    if (!selectedDraft) {
      return;
    }
    const current = asRecord(selectedDraft[configKey]);
    patchDraft({ [configKey]: { ...current, [key]: value } });
  }

  const visibleRuns = useMemo(() => {
    const filtered = (runs.data ?? []).filter(
      (run) => !runStatusFilter || run.status === runStatusFilter,
    );
    return [...filtered].sort((left, right) => {
      const delta =
        new Date(right.created_at).getTime() -
        new Date(left.created_at).getTime();
      return runSort === "oldest" ? -delta : delta;
    });
  }, [runSort, runStatusFilter, runs.data]);
  const selectedRun =
    visibleRuns.find((run) => run.id === selectedRunId) ??
    visibleRuns[0] ??
    null;

  const registeredRunModels = useMemo(() => {
    const mapped = new Map<string, ModelRegistration>();
    models.data?.forEach((model) => {
      const runId = stringValue(
        asRecord(model.metadata_json).source_training_run_id,
      );
      if (runId) {
        mapped.set(runId, model);
      }
    });
    return mapped;
  }, [models.data]);

  useEffect(
    () => () => {
      if (draftSaveTimerRef.current !== null) {
        window.clearTimeout(draftSaveTimerRef.current);
      }
    },
    [],
  );

  return (
    <section className="gallery-panel training-panel">
      <div className="section-heading gallery-heading">
        <div>
          <p className="eyebrow">Pinned-provider workflow</p>
          <h3>Training</h3>
          <span>Drafts, preflight, runs, and experiments in one workspace</span>
        </div>
        <div className="training-toolbar">
          <button
            type="button"
            onClick={() => createDraftMutation.mutate(undefined)}
            disabled={createDraftMutation.isPending}
          >
            {createDraftMutation.isPending ? "Creating..." : "New draft"}
          </button>
          {selectedDraft && (
            <button
              type="button"
              className="danger-ghost"
              onClick={() => deleteDraftMutation.mutate(selectedDraft.id)}
              disabled={deleteDraftMutation.isPending}
            >
              Delete draft
            </button>
          )}
          {selectedDraftId && (
            <span
              className="status-chip"
              data-testid="training-draft-save-state"
            >
              {saveStateLabel(draftSaveState, draftSaveMessage)}
            </span>
          )}
        </div>
      </div>

      <div className="training-layout">
        <aside className="training-nav">
          <label className="training-draft-picker">
            Active draft
            <select
              value={selectedDraftId}
              onChange={(event) => setSelectedDraftId(event.target.value)}
            >
              <option value="" disabled>
                {drafts.data?.length ? "Select a draft" : "No drafts yet"}
              </option>
              {drafts.data?.map((draft) => (
                <option key={draft.id} value={draft.id}>
                  {draft.name}
                </option>
              ))}
            </select>
          </label>
          <div
            className="training-section-list"
            role="tablist"
            aria-label="Training sections"
          >
            {sections.map((section) => (
              <button
                key={section.id}
                type="button"
                role="tab"
                aria-selected={activeSection === section.id}
                className={
                  activeSection === section.id ? "active" : "secondary"
                }
                onClick={() => setActiveSection(section.id)}
              >
                {section.label}
              </button>
            ))}
          </div>
          {selectedProvider?.warning && (
            <p className="system-subtle">{selectedProvider.warning}</p>
          )}
        </aside>

        <div className="training-content">
          {selectedDraftId &&
            !selectedDraft &&
            selectedDraftQuery.isPending && (
              <div className="empty-state">
                <h4>Loading training draft</h4>
                <p>
                  Fetching the selected draft configuration and validation
                  state.
                </p>
              </div>
            )}
          {selectedDraftId && selectedDraftQuery.error && (
            <div className="empty-state">
              <h4>Training draft unavailable</h4>
              <p>{selectedDraftQuery.error.message}</p>
            </div>
          )}
          {!selectedDraft && !selectedDraftId && (
            <div className="empty-state">
              <h4>No training draft selected</h4>
              <p>
                Create a draft to start configuring an immutable training run.
              </p>
            </div>
          )}

          {selectedDraft && (
            <>
              <div className="training-summary-bar">
                <div className="status-chip">
                  Preflight: {preflight?.status ?? "not ready"}
                </div>
                <div className="status-chip">
                  Task:{" "}
                  {taskLabel(selectedCatalogEntry?.task ?? selectedDraft.task)}
                </div>
                <div className="status-chip">
                  Dataset: {selectedVersion?.name ?? "Unselected"}
                </div>
                <div className="status-chip">
                  Model:{" "}
                  {selectedCatalogEntry?.display_name ??
                    selectedDraft.selected_preset ??
                    selectedDraft.architecture ??
                    "Unselected"}
                </div>
              </div>

              {activeSection === "new_run" && (
                <div className="training-card-grid">
                  <TaskCapabilityMatrix />
                  <article className="system-card">
                    <h4>Run identity</h4>
                    <label>
                      Draft name
                      <input
                        value={selectedDraft.name}
                        onChange={(event) =>
                          patchDraft({ name: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Run name
                      <input
                        value={selectedDraft.run_name ?? ""}
                        onChange={(event) =>
                          patchDraft({ run_name: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Notes
                      <textarea
                        value={selectedDraft.notes ?? ""}
                        onChange={(event) =>
                          patchDraft({ notes: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Random seed
                      <input
                        type="number"
                        value={selectedDraft.random_seed ?? 11}
                        onChange={(event) =>
                          patchDraft({
                            random_seed: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                  </article>

                  <article className="system-card">
                    <h4>Task-first model selection</h4>
                    <p className="annotation-helper">
                      {selectedDraft.initial_checkpoint_source ===
                      "registered_model"
                        ? "Registered model initialization — uses your selected local checkpoint."
                        : "Random initialization — No trained weights are used."}
                    </p>
                    {workspaceBootstrap.isPending && !modelCatalog && (
                      <p className="system-subtle">
                        Loading the validated model catalog...
                      </p>
                    )}
                    {workspaceBootstrap.error && !modelCatalog && (
                      <p className="form-error">
                        {workspaceBootstrap.error.message}
                      </p>
                    )}
                    {taskOptions.length > 0 ? (
                      <>
                        <label>
                          Task
                          <select
                            value={selectedTaskForCatalog}
                            onChange={(event) =>
                              selectTaskPreset(
                                event.target.value as ModelCatalogTask,
                              )
                            }
                          >
                            {taskOptions.map((task) => (
                              <option key={task} value={task}>
                                {taskLabel(task)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Architecture
                          <select
                            value={selectedArchitectureFamily}
                            onChange={(event) =>
                              selectArchitecturePreset(event.target.value)
                            }
                          >
                            {architectureFamilies.map((family) => (
                              <option key={family} value={family}>
                                {family}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Model size or preset
                          <select
                            value={
                              selectedCatalogEntry?.category === "architecture"
                                ? selectedCatalogEntry.catalog_id
                                : ""
                            }
                            onChange={(event) => {
                              const next = catalogEntryById.get(
                                event.target.value,
                              );
                              if (next) {
                                applyCatalogSelection(next);
                              }
                            }}
                          >
                            <option value="" disabled>
                              Select a model size or preset
                            </option>
                            {presetOptions.map((entry) => (
                              <option
                                key={entry.catalog_id}
                                value={entry.catalog_id}
                              >
                                {entry.display_name} |{" "}
                                {entry.installation_state}
                              </option>
                            ))}
                          </select>
                        </label>
                        {selectableArchitectureEntries.some(
                          (entry) =>
                            entry.installation_state === "Provider Required",
                        ) && (
                          <p className="form-error">
                            Architectures labeled Provider Required are visible
                            for diagnosis, but cannot train until the matching
                            provider is installed in ReefVision's backend. Check
                            provider availability in Model Hub or repair the
                            desktop installation. Scratch training does not
                            require pretrained weights or model registration.
                          </p>
                        )}
                      </>
                    ) : (
                      !workspaceBootstrap.isPending &&
                      !workspaceBootstrap.error && (
                        <p className="form-error">
                          No training architectures were returned by the model
                          catalog. Check the catalog and provider diagnostics in
                          Model Hub.
                        </p>
                      )
                    )}

                    {selectedCatalogEntry && (
                      <div className="annotation-selection-list">
                        <div className="annotation-selection-row">
                          <strong>Selected model</strong>
                          <span>{selectedCatalogEntry.display_name}</span>
                        </div>
                        <div className="annotation-selection-row">
                          <strong>Provider</strong>
                          <span>
                            {selectedCatalogEntry.provider} |{" "}
                            {selectedCatalogEntry.provider_version}
                          </span>
                        </div>
                        <div className="annotation-selection-row">
                          <strong>State</strong>
                          <span>{selectedCatalogEntry.installation_state}</span>
                        </div>
                        <div className="annotation-selection-row">
                          <strong>Disk</strong>
                          <span>
                            {fileSizeLabel(
                              selectedCatalogEntry.expected_file_size,
                            )}
                          </span>
                        </div>
                        <div className="annotation-selection-row">
                          <strong>Recommended VRAM</strong>
                          <span>
                            {selectedCatalogEntry.minimum_recommended_vram_gb ??
                              "n/a"}{" "}
                            GB
                          </span>
                        </div>
                        <div className="annotation-selection-row">
                          <strong>Trainable</strong>
                          <span>
                            {selectedCatalogEntry.trainable
                              ? "Yes"
                              : "Inference only"}
                          </span>
                        </div>
                      </div>
                    )}

                    {myTrainedEntries.length > 0 && (
                      <label>
                        My trained models
                        <select
                          value={
                            selectedCatalogEntry?.category ===
                            "my_trained_models"
                              ? selectedCatalogEntry.catalog_id
                              : ""
                          }
                          onChange={(event) => {
                            const next = catalogEntryById.get(
                              event.target.value,
                            );
                            if (next) {
                              applyCatalogSelection(next);
                            }
                          }}
                        >
                          <option value="">Keep current catalog preset</option>
                          {myTrainedEntries.map((entry) => (
                            <option
                              key={entry.catalog_id}
                              value={entry.catalog_id}
                            >
                              {entry.display_name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}

                    <details>
                      <summary>Registered model initialization</summary>
                      {importedCustomEntries.length > 0 ? (
                        <label>
                          Registered checkpoint
                          <select
                            value={
                              selectedCatalogEntry?.category ===
                              "imported_custom_models"
                                ? selectedCatalogEntry.catalog_id
                                : ""
                            }
                            onChange={(event) => {
                              const next = catalogEntryById.get(
                                event.target.value,
                              );
                              if (next) {
                                applyCatalogSelection(next);
                              }
                            }}
                          >
                            <option value="">
                              Select imported custom model
                            </option>
                            {importedCustomEntries.map((entry) => (
                              <option
                                key={entry.catalog_id}
                                value={entry.catalog_id}
                              >
                                {entry.display_name}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : (
                        <p className="system-subtle">
                          No compatible trained models are registered for this
                          project.
                        </p>
                      )}
                      <p className="system-subtle">
                        Selecting a registered model uses that checkpoint for
                        initialization and preserves its provenance. Selecting
                        an architecture starts from random initialization.
                      </p>
                    </details>
                  </article>

                  <article className="system-card">
                    <h4>Review and start</h4>
                    <label>
                      Device
                      <select
                        value={selectedDraft.device}
                        onChange={(event) =>
                          patchDraft({ device: event.target.value })
                        }
                      >
                        <option value="auto">Auto</option>
                        <option value="cpu">CPU</option>
                        <option value="cuda">CUDA</option>
                      </select>
                    </label>
                    <label>
                      Precision
                      <select
                        value={selectedDraft.precision}
                        onChange={(event) =>
                          patchDraft({ precision: event.target.value })
                        }
                      >
                        <option value="fp32">FP32</option>
                        <option value="amp">AMP</option>
                      </select>
                    </label>
                    <div
                      className="annotation-selection-list"
                      aria-label="Training configuration review"
                    >
                      <div className="annotation-selection-row">
                        <strong>Dataset</strong>
                        <span>
                          {selectedVersion?.name ??
                            "Select an immutable dataset version"}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Task</strong>
                        <span>
                          {taskLabel(
                            selectedCatalogEntry?.task ?? selectedDraft.task,
                          )}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Model</strong>
                        <span>
                          {selectedCatalogEntry?.display_name ??
                            selectedDraft.architecture ??
                            "Select a model"}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Epochs</strong>
                        <span>
                          {String(
                            asRecord(selectedDraft.training_config).epochs ??
                              "Provider default",
                          )}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Image size</strong>
                        <span>
                          {String(
                            asRecord(selectedDraft.training_config).imgsz ??
                              "Provider default",
                          )}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Batch</strong>
                        <span>
                          {String(
                            asRecord(selectedDraft.training_config).batch ??
                              "Provider default",
                          )}
                        </span>
                      </div>
                      <div className="annotation-selection-row">
                        <strong>Seed</strong>
                        <span>
                          {selectedDraft.random_seed ?? "Provider default"}
                        </span>
                      </div>
                    </div>
                    <details>
                      <summary>Hardware and resource assessment</summary>
                      {preflight?.resource_snapshot &&
                      Object.keys(preflight.resource_snapshot).length > 0 ? (
                        <dl className="training-provenance-list">
                          {Object.entries(preflight.resource_snapshot).map(
                            ([key, value]) => (
                              <div key={key}>
                                <dt>{metricLabel(key)}</dt>
                                <dd>
                                  {typeof value === "object"
                                    ? JSON.stringify(value)
                                    : String(value)}
                                </dd>
                              </div>
                            ),
                          )}
                        </dl>
                      ) : (
                        <p className="system-subtle">
                          Run preflight to inspect available hardware.
                          ReefVision does not make an exact VRAM-fit guarantee.
                        </p>
                      )}
                    </details>
                    <button
                      type="button"
                      onClick={() => launchRunMutation.mutate()}
                      disabled={
                        launchRunMutation.isPending ||
                        draftSaveState !== "saved"
                      }
                    >
                      {launchRunMutation.isPending
                        ? "Queueing..."
                        : "Start training"}
                    </button>
                    {launchRunMutation.error && (
                      <p className="form-error">
                        {launchRunMutation.error.message}
                      </p>
                    )}
                  </article>
                </div>
              )}

              {activeSection === "dataset_splits" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <h4>Immutable dataset version</h4>
                    <label>
                      Dataset version
                      <select
                        value={selectedDraft.dataset_version_id ?? ""}
                        onChange={(event) =>
                          patchDraft({
                            dataset_version_id: event.target.value || null,
                          })
                        }
                      >
                        <option value="">Select dataset version</option>
                        {versions.data?.map((version) => (
                          <option key={version.id} value={version.id}>
                            v{version.version_number} - {version.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {selectedVersion && (
                      <dl className="training-kv-grid">
                        <div>
                          <dt>Version ID</dt>
                          <dd>{selectedVersion.id}</dd>
                        </div>
                        <div>
                          <dt>Manifest checksum</dt>
                          <dd>{selectedVersion.manifest_sha256}</dd>
                        </div>
                        <div>
                          <dt>Image count</dt>
                          <dd>{selectedVersion.image_count}</dd>
                        </div>
                        <div>
                          <dt>Annotation count</dt>
                          <dd>{selectedVersion.annotation_count}</dd>
                        </div>
                        <div>
                          <dt>Split method</dt>
                          <dd>{selectedVersion.resolved_split_method}</dd>
                        </div>
                        <div>
                          <dt>Warnings</dt>
                          <dd>{selectedVersion.warnings_json.length}</dd>
                        </div>
                      </dl>
                    )}
                  </article>

                  <article className="system-card">
                    <h4>Preflight dataset audit</h4>
                    <dl className="training-kv-grid">
                      <div>
                        <dt>Split checksum</dt>
                        <dd>
                          {preflight?.dataset.split_manifest_sha256 ?? "N/A"}
                        </dd>
                      </div>
                      <div>
                        <dt>Group count</dt>
                        <dd>{preflight?.dataset.group_count ?? 0}</dd>
                      </div>
                      <div>
                        <dt>Image leakage</dt>
                        <dd>
                          {preflight?.leakage_audit.image_leak_count ?? 0}
                        </dd>
                      </div>
                      <div>
                        <dt>Group leakage</dt>
                        <dd>
                          {preflight?.leakage_audit.group_leak_count ?? 0}
                        </dd>
                      </div>
                    </dl>
                    {(preflight?.dataset.warnings.length ?? 0) > 0 && (
                      <ul className="system-details">
                        {preflight?.dataset.warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    )}
                    {(preflight?.leakage_audit.blockers.length ?? 0) > 0 && (
                      <ul className="system-details form-error">
                        {preflight?.leakage_audit.blockers.map((blocker) => (
                          <li key={blocker}>{blocker}</li>
                        ))}
                      </ul>
                    )}
                  </article>
                </div>
              )}

              {activeSection === "tiling" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <h4>Tiling configuration</h4>
                    <label>
                      Mode
                      <select
                        value={String(
                          asRecord(selectedDraft.tiling_config).mode ?? "none",
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tiling_config",
                            "mode",
                            event.target.value,
                          )
                        }
                      >
                        <option value="none">No tiling baseline</option>
                        <option value="square">Square tiles</option>
                        <option value="rectangular">Rectangular tiles</option>
                      </select>
                    </label>
                    <label>
                      Tile width
                      <input
                        type="number"
                        value={numberValue(
                          asRecord(selectedDraft.tiling_config).tile_width,
                          640,
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tiling_config",
                            "tile_width",
                            Number(event.target.value),
                          )
                        }
                      />
                    </label>
                    <label>
                      Tile height
                      <input
                        type="number"
                        value={numberValue(
                          asRecord(selectedDraft.tiling_config).tile_height,
                          640,
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tiling_config",
                            "tile_height",
                            Number(event.target.value),
                          )
                        }
                      />
                    </label>
                    <label>
                      Horizontal overlap
                      <input
                        type="number"
                        value={numberValue(
                          asRecord(selectedDraft.tiling_config).overlap_x,
                          0,
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tiling_config",
                            "overlap_x",
                            Number(event.target.value),
                          )
                        }
                      />
                    </label>
                    <label>
                      Vertical overlap
                      <input
                        type="number"
                        value={numberValue(
                          asRecord(selectedDraft.tiling_config).overlap_y,
                          0,
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tiling_config",
                            "overlap_y",
                            Number(event.target.value),
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => estimateTilingMutation.mutate()}
                      disabled={
                        estimateTilingMutation.isPending ||
                        !selectedDraft.dataset_version_id
                      }
                    >
                      {estimateTilingMutation.isPending
                        ? "Estimating..."
                        : "Estimate tiles"}
                    </button>
                  </article>

                  <article className="system-card">
                    <h4>Estimate</h4>
                    {!tilingEstimate && (
                      <p className="system-subtle">
                        Run the estimator to preview tile counts and
                        representative tiles.
                      </p>
                    )}
                    {tilingEstimate && (
                      <>
                        <dl className="training-kv-grid">
                          <div>
                            <dt>Total tiles</dt>
                            <dd>{tilingEstimate.tile_count}</dd>
                          </div>
                          <div>
                            <dt>Positive tiles</dt>
                            <dd>{tilingEstimate.positive_tile_count}</dd>
                          </div>
                          <div>
                            <dt>Background tiles</dt>
                            <dd>{tilingEstimate.background_tile_count}</dd>
                          </div>
                          <div>
                            <dt>Estimated storage</dt>
                            <dd>
                              {Math.round(
                                tilingEstimate.estimated_storage_bytes /
                                  (1024 * 1024),
                              )}{" "}
                              MB
                            </dd>
                          </div>
                        </dl>
                        {tilingEstimate.warnings.length > 0 && (
                          <ul className="system-details">
                            {tilingEstimate.warnings.map((warning) => (
                              <li key={warning}>{warning}</li>
                            ))}
                          </ul>
                        )}
                        <div className="training-preview-list">
                          {tilingEstimate.preview_tiles.map((tile) => (
                            <div
                              key={`${tile.image_id}-${tile.x}-${tile.y}`}
                              className="system-record-card"
                            >
                              <strong>{tile.image_id}</strong>
                              <span>
                                {tile.width}x{tile.height} at ({tile.x},{" "}
                                {tile.y})
                              </span>
                              <small>
                                {tile.split} | retained annotations:{" "}
                                {tile.retained_annotation_count}
                              </small>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </article>
                </div>
              )}

              {activeSection === "hyperparameters" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <h4>Guided controls</h4>
                    <div className="training-form-grid">
                      <label>
                        Epochs
                        <input
                          type="number"
                          value={numberValue(
                            asRecord(selectedDraft.training_config).epochs,
                            50,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "epochs",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Patience
                        <input
                          type="number"
                          value={numberValue(
                            asRecord(selectedDraft.training_config).patience,
                            20,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "patience",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Batch
                        <input
                          type="number"
                          value={numberValue(
                            asRecord(selectedDraft.training_config).batch,
                            8,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "batch",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Image size
                        <input
                          type="number"
                          value={numberValue(
                            asRecord(selectedDraft.training_config).imgsz,
                            640,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "imgsz",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Optimizer
                        <select
                          value={String(
                            asRecord(selectedDraft.training_config).optimizer ??
                              "auto",
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "optimizer",
                              event.target.value,
                            )
                          }
                        >
                          <option value="auto">Auto</option>
                          <option value="SGD">SGD</option>
                          <option value="Adam">Adam</option>
                          <option value="AdamW">AdamW</option>
                        </select>
                      </label>
                      <label>
                        Workers
                        <input
                          type="number"
                          value={numberValue(
                            asRecord(selectedDraft.training_config).workers,
                            2,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "training_config",
                              "workers",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                    </div>
                  </article>

                  <article className="system-card">
                    <h4>Expert registry</h4>
                    {providerParameters.isPending && (
                      <p>Loading pinned registry...</p>
                    )}
                    {providerParameters.error && (
                      <p className="form-error">
                        {providerParameters.error.message}
                      </p>
                    )}
                    {providerParameters.data && (
                      <>
                        <p className="system-subtle">
                          The expert view is generated from the installed pinned
                          Ultralytics version, and launch validation uses the
                          same backend registry.
                        </p>
                        <div className="training-registry-list">
                          {providerParameters.data.parameters
                            .filter(
                              (item) =>
                                item.supported_tasks.includes("detect") &&
                                item.supported_modes.includes("train") &&
                                item.reefvision_supported,
                            )
                            .slice(0, 12)
                            .map((item) => (
                              <div
                                key={item.name}
                                className="system-record-card"
                              >
                                <strong>{item.display_name}</strong>
                                <span>{item.name}</span>
                                <small>
                                  default {String(item.default_value)} |{" "}
                                  {item.value_type}
                                </small>
                              </div>
                            ))}
                        </div>
                      </>
                    )}
                  </article>
                </div>
              )}

              {activeSection === "tune" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <p className="eyebrow">
                      Dataset → Model → Search Space → Trial Settings → Tune
                    </p>
                    <h4>Tuning strategy</h4>
                    <label>
                      Mode
                      <select
                        value={String(
                          asRecord(selectedDraft.tuning_config).mode ??
                            "disabled",
                        )}
                        onChange={(event) =>
                          patchConfig(
                            "tuning_config",
                            "mode",
                            event.target.value,
                          )
                        }
                      >
                        <option value="disabled">Disabled</option>
                        <option value="random">Random search</option>
                      </select>
                    </label>
                    <div className="training-form-grid">
                      <label>
                        Maximum trials
                        <input
                          type="number"
                          min="1"
                          max="1000"
                          value={numberValue(
                            asRecord(selectedDraft.tuning_config).max_trials,
                            20,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "tuning_config",
                              "max_trials",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Epochs per trial
                        <input
                          type="number"
                          min="1"
                          max="1000"
                          value={numberValue(
                            asRecord(selectedDraft.tuning_config)
                              .epochs_per_trial,
                            10,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "tuning_config",
                              "epochs_per_trial",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Patience (trials)
                        <input
                          type="number"
                          min="0"
                          max="1000"
                          value={numberValue(
                            asRecord(selectedDraft.tuning_config).patience,
                            10,
                          )}
                          onChange={(event) =>
                            patchConfig(
                              "tuning_config",
                              "patience",
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label>
                        Seed
                        <input
                          type="number"
                          value={selectedDraft.random_seed ?? 0}
                          onChange={(event) =>
                            patchDraft({
                              random_seed: Number(event.target.value),
                            })
                          }
                        />
                      </label>
                    </div>
                    <div className="editor-message">
                      <strong>Fitness being optimized</strong>
                      <p>
                        Ultralytics detection fitness uses the provider-recorded
                        fitness value (normally weighted toward mAP50–95). The
                        exact definition is persisted with results.
                      </p>
                    </div>
                  </article>
                  <article className="system-card">
                    <h4>Search space</h4>
                    <p className="system-subtle">
                      Recommended provider-supported ranges are persisted
                      exactly at launch. Custom range editing is available in
                      the effective tuning JSON below.
                    </p>
                    <pre className="json-block">
                      {JSON.stringify(
                        asRecord(selectedDraft.tuning_config).search_space ?? {
                          lr0: { min: 0.00001, max: 0.1, enabled: true },
                          momentum: { min: 0.6, max: 0.98, enabled: true },
                          weight_decay: { min: 0, max: 0.001, enabled: true },
                          mosaic: { min: 0, max: 1, enabled: true },
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </article>
                </div>
              )}

              {activeSection === "runs" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">History</p>
                        <h4>Active and completed runs</h4>
                      </div>
                      <span>{visibleRuns.length} shown</span>
                    </div>
                    <div className="training-run-filters">
                      <label>
                        Status
                        <select
                          value={runStatusFilter}
                          onChange={(event) =>
                            setRunStatusFilter(event.target.value)
                          }
                        >
                          <option value="">All states</option>
                          <option value="queued">Queued</option>
                          <option value="training">Training</option>
                          <option value="tuning">Tuning</option>
                          <option value="completed">Completed</option>
                          <option value="failed">Failed</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                      </label>
                      <label>
                        Order
                        <select
                          value={runSort}
                          onChange={(event) => setRunSort(event.target.value)}
                        >
                          <option value="newest">Newest first</option>
                          <option value="oldest">Oldest first</option>
                        </select>
                      </label>
                    </div>
                    {!runs.data?.length && (
                      <p className="system-subtle">
                        No training runs have been launched yet.
                      </p>
                    )}
                    <div className="training-run-list">
                      {visibleRuns.map((run) => (
                        <button
                          key={run.id}
                          type="button"
                          className={`system-record-card training-run-card ${selectedRun?.id === run.id ? "selected" : ""}`}
                          onClick={() => setSelectedRunId(run.id)}
                        >
                          <div className="section-heading">
                            <div>
                              <strong>{run.run_name}</strong>
                              <p className="system-subtle">
                                {run.provider_id} | {run.architecture}
                              </p>
                            </div>
                            <span className="status-chip">
                              {run.status} / {run.stage}
                            </span>
                          </div>
                          <small>
                            Progress {run.progress_epoch}/
                            {run.progress_total_epochs}
                          </small>
                          <progress
                            value={run.progress_epoch}
                            max={Math.max(run.progress_total_epochs, 1)}
                            aria-label={`${run.run_name} progress`}
                          />
                          {run.error_message && (
                            <p className="form-error">{run.error_message}</p>
                          )}
                        </button>
                      ))}
                    </div>
                  </article>
                  {selectedRun ? (
                    <TrainingRunDetail
                      run={selectedRun}
                      registeredName={
                        registeredRunModels.get(selectedRun.id)?.display_name
                      }
                      registering={
                        registerRunModelMutation.isPending &&
                        registerRunModelMutation.variables?.runId ===
                          selectedRun.id
                      }
                      onCancel={() => {
                        if (
                          window.confirm(
                            `Cancel training run ${selectedRun.run_name}? Safely written artifacts will be retained.`,
                          )
                        )
                          cancelRunMutation.mutate(selectedRun.id);
                      }}
                      onRegister={() =>
                        registerRunModelMutation.mutate({
                          runId: selectedRun.id,
                          displayName: `${selectedRun.run_name} best`,
                          notes: selectedRun.notes ?? undefined,
                        })
                      }
                      onApplyBest={(trial) =>
                        applyTuningMutation.mutate({ run: selectedRun, trial })
                      }
                    />
                  ) : (
                    <article className="system-card">
                      <h4>Run detail</h4>
                      <p className="system-subtle">
                        Select a run to inspect progress, metrics, checkpoints,
                        artifacts, and provenance.
                      </p>
                    </article>
                  )}
                </div>
              )}

              {activeSection === "experiments" && (
                <div className="training-card-grid">
                  <article className="system-card">
                    <h4>Experiments</h4>
                    {!experiments.data?.length && (
                      <p className="system-subtle">
                        Completed runs create experiments for comparison.
                      </p>
                    )}
                    <div className="training-run-list">
                      {experiments.data?.map((experiment) => (
                        <label
                          key={experiment.id}
                          className="system-record-card training-compare-card"
                        >
                          <input
                            type="checkbox"
                            checked={compareSelection.includes(experiment.id)}
                            onChange={(event) => {
                              setCompareSelection((current) =>
                                event.target.checked
                                  ? [...current, experiment.id].slice(-4)
                                  : current.filter(
                                      (item) => item !== experiment.id,
                                    ),
                              );
                            }}
                          />
                          <strong>{experiment.architecture}</strong>
                          <small>{experiment.provider_id}</small>
                          {Object.entries(experiment.summary_metrics_json)
                            .slice(0, 4)
                            .map(([key, value]) => (
                              <span key={key}>
                                {metricLabel(key)}: {String(value)}
                              </span>
                            ))}
                        </label>
                      ))}
                    </div>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => compareExperimentsMutation.mutate()}
                      disabled={compareSelection.length < 2}
                    >
                      Compare selected experiments
                    </button>
                    {compareWarnings.length > 0 && (
                      <ul className="system-details">
                        {compareWarnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    )}
                  </article>
                </div>
              )}

              {activeSection === "models" && (
                <div className="training-card-grid">
                  <SegmentationEvaluationPanel project={project} />
                  <article className="system-card">
                    <h4>Run artifacts</h4>
                    <p className="system-subtle">
                      Completed runs keep their best checkpoint paths and
                      experiment lineage here. Registration is explicit, so a
                      completed run stays separate from the active model
                      registry until you choose to register it.
                    </p>
                    <div className="training-run-list">
                      {runs.data
                        ?.filter((run) => run.result_checkpoint_path)
                        .map((run) => (
                          <div key={run.id} className="system-record-card">
                            <strong>{run.run_name}</strong>
                            <small>{run.result_checkpoint_path}</small>
                            <span>
                              Dataset checksum:{" "}
                              {run.dataset_manifest_sha256.slice(0, 12)}...
                            </span>
                            <span>Status: {run.status}</span>
                            {registeredRunModels.get(run.id) ? (
                              <span>
                                Registered as{" "}
                                {registeredRunModels.get(run.id)?.display_name}
                              </span>
                            ) : (
                              <button
                                type="button"
                                className="secondary"
                                onClick={() =>
                                  registerRunModelMutation.mutate({
                                    runId: run.id,
                                    displayName: `${run.run_name} best`,
                                    notes: run.notes ?? undefined,
                                  })
                                }
                                disabled={
                                  run.status !== "completed" ||
                                  registerRunModelMutation.isPending
                                }
                              >
                                {registerRunModelMutation.isPending &&
                                registerRunModelMutation.variables?.runId ===
                                  run.id
                                  ? "Registering..."
                                  : "Register as detector model"}
                              </button>
                            )}
                          </div>
                        ))}
                    </div>
                  </article>

                  <article className="system-card">
                    <h4>Registered detector models</h4>
                    <div className="training-run-list">
                      {models.data?.map((model) => (
                        <div key={model.id} className="system-record-card">
                          <strong>{model.display_name}</strong>
                          <small>{model.provider_name}</small>
                          <span>{model.source_filename}</span>
                        </div>
                      ))}
                    </div>
                  </article>
                </div>
              )}

              {(preflight?.warnings.length ?? 0) > 0 && (
                <div className="system-card">
                  <h4>Preflight warnings</h4>
                  <ul className="system-details">
                    {preflight?.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(preflight?.blockers.length ?? 0) > 0 && (
                <div className="system-card">
                  <h4>Launch blockers</h4>
                  <ul className="system-details form-error">
                    {preflight?.blockers.map((blocker) => (
                      <li key={blocker}>{blocker}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
