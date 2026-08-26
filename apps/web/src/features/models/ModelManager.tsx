import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  cancelJob,
  deleteModel,
  getJob,
  getModelProviderPreflight,
  getModelHubBootstrap,
  getProjectModelCatalog,
  getRuntimeProviderStatuses,
  getUltralyticsTrainingRegistrySummary,
  installCatalogModel,
  removeCatalogModel,
  type ModelCatalogEntry,
  type ModelCatalogResponse,
  type ModelProvider,
  type JobRecord,
  registerModel,
  type ModelRegistration,
  type ProviderDependencyStatus,
  type Project,
  type RuntimeProviderStatus,
  type UltralyticsTrainingRegistrySummarySnapshot,
  verifyCatalogModel,
} from "../../api/client";

function ModelRow({
  model,
  onDelete,
}: {
  model: ModelRegistration;
  onDelete: (modelId: string) => void;
}) {
  const labelEntries = useMemo(() => {
    const labels = Array.isArray(model.class_map_json.labels)
      ? (model.class_map_json.labels as string[])
      : [];
    const mapping =
      typeof model.class_map_json.mapping === "object" &&
      model.class_map_json.mapping !== null
        ? (model.class_map_json.mapping as Record<string, string | null>)
        : {};
    return labels.map((label) => ({
      label,
      mapped: mapping[label] ?? null,
    }));
  }, [model.class_map_json]);

  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{model.display_name}</h4>
          <p>
            {model.purpose} | {model.framework} | {model.task}
          </p>
        </div>
        <div className="image-card-topline">
          <span className="count-chip">{model.source_filename}</span>
          <span className="count-chip secondary-chip">
            {Math.round(model.file_size_bytes / 1024)} KB
          </span>
        </div>
        <small>Provider: {model.provider_name}</small>
        <small>Checksum: {model.sha256.slice(0, 12)}...</small>
        {labelEntries.length > 0 && (
          <div className="annotation-selection-list">
            {labelEntries.map((entry) => (
              <div key={entry.label} className="annotation-selection-row">
                <strong>{entry.label}</strong>
                <span>{entry.mapped ? "Mapped" : "Unmapped"}</span>
              </div>
            ))}
          </div>
        )}
        {model.notes && <p>{model.notes}</p>}
        <div className="image-card-actions">
          <button
            type="button"
            className="danger-ghost"
            onClick={() => onDelete(model.id)}
          >
            Remove model
          </button>
        </div>
      </div>
    </article>
  );
}

function formatBytes(value: number | null): string {
  if (value == null) return "Not declared";
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function CatalogModelCard({
  model,
  job,
  onInstall,
  onCancel,
  onVerify,
  onRemove,
  onSelect,
  onViewReason,
  verificationResult,
}: {
  model: ModelCatalogEntry;
  job?: JobRecord;
  onInstall?: (model: ModelCatalogEntry) => void;
  onCancel?: (jobId: string) => void;
  onVerify?: (model: ModelCatalogEntry) => void;
  onRemove?: (model: ModelCatalogEntry) => void;
  onSelect?: (model: ModelCatalogEntry) => void;
  onViewReason?: (model: ModelCatalogEntry) => void;
  verificationResult?: {
    state: "verifying" | "passed" | "failed";
    message: string;
  };
}) {
  const state = model.installation_state;
  const architecture = model.architecture ?? model.architecture_family;
  const runtimes = model.supported_runtimes ?? model.supported_runtime ?? [];
  const license = model.license_summary ?? model.model_weight_license;
  const progressTotal = job?.progress_total ?? model.expected_size ?? 0;
  const progressCurrent = job?.progress_current ?? 0;
  const progress =
    progressTotal > 0
      ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100))
      : 0;
  const active = ["Downloading", "Verifying", "Installing"].includes(state);
  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{model.display_name}</h4>
          <p>
            {model.category.replaceAll("_", " ")} | {model.installation_state}
          </p>
        </div>
        <small>
          {architecture} | {model.task.replaceAll("_", " ")}
        </small>
        <small>
          Provider {model.provider} {model.provider_version}
        </small>
        <small>Runtime: {runtimes.join(", ") || "Not declared"}</small>
        {model.checkpoint_identifier && (
          <small>Checkpoint: {model.checkpoint_identifier}</small>
        )}
        {model.installed_path && (
          <small>Location: {model.installed_path}</small>
        )}
        <small>
          Devices: {model.supported_devices.join(", ") || "Not declared"}
        </small>
        <p>{model.display_summary}</p>
        {model.installation_reason && (
          <p className="annotation-helper">{model.installation_reason}</p>
        )}
        {verificationResult && (
          <p
            className={
              verificationResult.state === "failed"
                ? "form-error"
                : "annotation-helper"
            }
            role={verificationResult.state === "failed" ? "alert" : undefined}
            aria-live="polite"
          >
            {verificationResult.state === "verifying"
              ? "Verifying checkpoint integrity..."
              : verificationResult.state === "passed"
                ? `Verification passed: ${verificationResult.message}`
                : `Verification failed: ${verificationResult.message}`}
          </p>
        )}
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Trainable</strong>
            <span>{model.trainable ? "Yes" : "No"}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mode</strong>
            <span>{model.trainable ? "Trainable" : "Inference only"}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Download</strong>
            <span>{formatBytes(model.expected_size)}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Recommended VRAM</strong>
            <span>
              {model.recommended_vram == null
                ? "Not declared"
                : `${model.recommended_vram} GB`}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>License</strong>
            <span>{license}</span>
          </div>
        </div>
        {active && (
          <div>
            <progress value={progressCurrent} max={progressTotal || 1} />
            <small aria-live="polite">
              {state}: {progress}% (
              {job?.result_json?.progress_unit === "files"
                ? `${progressCurrent} / ${progressTotal} files`
                : `${formatBytes(progressCurrent)} / ${formatBytes(progressTotal)}`}
              )
            </small>
          </div>
        )}
        <div className="image-card-actions">
          {(state === "Not Installed" || state === "Provider Required") &&
            onInstall && (
              <button type="button" onClick={() => onInstall(model)}>
                {state === "Provider Required"
                  ? "Install Provider and Model"
                  : "Install"}
              </button>
            )}
          {state === "Update Available" && onInstall && (
            <button type="button" onClick={() => onInstall(model)}>
              Update
            </button>
          )}
          {state === "Ready" && (
            <>
              {model.trainable && onSelect && (
                <button type="button" onClick={() => onSelect(model)}>
                  Select
                </button>
              )}
              {onVerify && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onVerify(model)}
                  disabled={verificationResult?.state === "verifying"}
                >
                  {verificationResult?.state === "verifying"
                    ? "Verifying..."
                    : verificationResult?.state === "passed"
                      ? "Verify again"
                      : "Verify"}
                </button>
              )}
              {onRemove && (
                <button
                  type="button"
                  className="danger-ghost"
                  onClick={() => onRemove(model)}
                >
                  Remove
                </button>
              )}
            </>
          )}
          {active && job && onCancel && (
            <button
              type="button"
              className="danger-ghost"
              onClick={() => onCancel(job.id)}
            >
              Cancel
            </button>
          )}
          {state === "Corrupted" && onInstall && onRemove && (
            <>
              <button type="button" onClick={() => onInstall(model)}>
                Repair
              </button>
              <button
                type="button"
                className="danger-ghost"
                onClick={() => onRemove(model)}
              >
                Remove
              </button>
            </>
          )}
          {(state === "Unavailable" || state === "Incompatible") &&
            onViewReason && (
              <button
                type="button"
                className="secondary"
                onClick={() => onViewReason(model)}
              >
                View Reason
              </button>
            )}
          {state === "Blocked" && onInstall && onViewReason && (
            <>
              <button type="button" onClick={() => onInstall(model)}>
                Retry
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => onViewReason(model)}
              >
                View Reason
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

function formatCheckedAt(
  value: string | number | null | undefined,
): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value === "number" && value <= 0) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function cachedCatalogKey(projectId: string): string {
  return `reefvision:model-catalog:${projectId}`;
}

function loadCachedCatalog(projectId: string): ModelCatalogResponse | null {
  try {
    const raw = window.localStorage.getItem(cachedCatalogKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ModelCatalogResponse;
    return Array.isArray(parsed.models) && parsed.models.length > 0
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function jobState(job: JobRecord): ModelCatalogEntry["installation_state"] {
  const stage = String(job.result_json?.stage ?? "downloading");
  if (stage === "verifying") return "Verifying";
  if (stage === "finalizing" || stage === "provider_preflight")
    return "Installing";
  return "Downloading";
}

export function ModelManager({
  project,
  onSelectCatalogModel,
}: {
  project: Project;
  onSelectCatalogModel?: (catalogId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [purpose, setPurpose] = useState<"detector" | "assist">("detector");
  const [providerName, setProviderName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [notes, setNotes] = useState("");
  const [cachedCatalog, setCachedCatalog] =
    useState<ModelCatalogResponse | null>(() => loadCachedCatalog(project.id));
  const [confirmationModel, setConfirmationModel] =
    useState<ModelCatalogEntry | null>(null);
  const [reasonModel, setReasonModel] = useState<ModelCatalogEntry | null>(
    null,
  );
  const [installJobs, setInstallJobs] = useState<Record<string, JobRecord>>({});
  const [operationMessage, setOperationMessage] = useState<string | null>(null);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogFilter, setCatalogFilter] = useState<
    "all" | "ready" | "installable" | "training" | "segmentation" | "assist"
  >("all");
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [verificationResults, setVerificationResults] = useState<
    Record<
      string,
      {
        state: "verifying" | "passed" | "failed";
        message: string;
      }
    >
  >({});

  const catalogQuery = useQuery({
    queryKey: ["model_catalog", project.id, "model_hub"],
    queryFn: ({ signal }) =>
      getProjectModelCatalog(
        project.id,
        { workflow: "model_hub", includeUnavailable: true },
        signal,
      ),
    staleTime: 60_000,
    retry: false,
  });

  const modelHubBootstrap = useQuery({
    queryKey: ["model_hub_bootstrap", project.id],
    queryFn: ({ signal }) => getModelHubBootstrap(project.id, signal),
    staleTime: 60_000,
  });
  const providerPreflight = useQuery({
    queryKey: ["model-provider-preflight", project.id],
    queryFn: ({ signal }) =>
      getModelProviderPreflight({ refresh: true, signal }),
    enabled: modelHubBootstrap.isSuccess,
    placeholderData: (previous) =>
      previous ?? modelHubBootstrap.data?.provider_preflight ?? undefined,
  });
  const runtimeStatuses = useQuery({
    queryKey: ["runtime-provider-statuses", project.id],
    queryFn: ({ signal }) =>
      getRuntimeProviderStatuses({ refresh: true, signal }),
    enabled: modelHubBootstrap.isSuccess,
    placeholderData: (previous) =>
      previous ?? modelHubBootstrap.data?.runtime_statuses,
  });
  const trainingCompatibility = useQuery({
    queryKey: ["ultralytics-training-registry-summary", project.id],
    queryFn: ({ signal }) =>
      getUltralyticsTrainingRegistrySummary({ refresh: true, signal }),
    enabled: modelHubBootstrap.isSuccess,
    placeholderData: (previous) =>
      previous ?? modelHubBootstrap.data?.training_compatibility ?? undefined,
  });
  const models = modelHubBootstrap.data?.models ?? [];
  const modelCatalog =
    catalogQuery.data ??
    cachedCatalog ??
    modelHubBootstrap.data?.catalog ??
    null;
  const providerCatalog = modelHubBootstrap.data?.providers ?? [];
  const registerableProviders = useMemo(
    () =>
      providerCatalog.filter(
        (item) =>
          item.registerable && item.default_registration_purpose === purpose,
      ),
    [providerCatalog, purpose],
  );
  const preflightByName = useMemo(
    () =>
      new Map(
        (providerPreflight.data?.providers ?? []).map((item) => [
          item.provider_name,
          item,
        ]),
      ),
    [providerPreflight.data?.providers],
  );
  const selectedProvider =
    registerableProviders.find((item) => item.provider_id === providerName) ??
    registerableProviders[0] ??
    null;
  const selectedProviderPreflight = selectedProvider
    ? (preflightByName.get(selectedProvider.provider_id) ?? null)
    : null;
  const pretrainedCatalogModels = useMemo(
    () =>
      (modelCatalog?.models ?? []).filter(
        (item) => item.category === "pretrained_catalog",
      ),
    [modelCatalog?.models],
  );
  const trainedCatalogModels = useMemo(
    () =>
      (modelCatalog?.models ?? []).filter(
        (item) => item.category === "my_trained_models",
      ),
    [modelCatalog?.models],
  );
  const importedCatalogModels = useMemo(
    () =>
      (modelCatalog?.models ?? []).filter(
        (item) => item.category === "imported_custom_models",
      ),
    [modelCatalog?.models],
  );

  const catalogSummary = useMemo(() => {
    const entries = pretrainedCatalogModels;
    return {
      ready: entries.filter((item) => item.installation_state === "Ready")
        .length,
      installable: entries.filter((item) =>
        ["Not Installed", "Provider Required", "Update Available"].includes(
          item.installation_state,
        ),
      ).length,
      active: entries.filter((item) =>
        ["Downloading", "Verifying", "Installing"].includes(
          item.installation_state,
        ),
      ).length,
      attention: entries.filter((item) =>
        ["Blocked", "Corrupted", "Incompatible"].includes(
          item.installation_state,
        ),
      ).length,
    };
  }, [pretrainedCatalogModels]);

  const filteredPretrainedCatalogModels = useMemo(() => {
    const query = catalogSearch.trim().toLocaleLowerCase();
    return pretrainedCatalogModels.filter((model) => {
      if (!showUnavailable && model.installation_state === "Unavailable") {
        return false;
      }

      const matchesSearch =
        !query ||
        [
          model.display_name,
          model.display_summary,
          model.architecture,
          model.architecture_family,
          model.provider,
          model.provider_id,
          model.task,
          model.variant,
        ]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
          .includes(query);

      if (!matchesSearch) return false;

      if (catalogFilter === "ready") {
        return model.installation_state === "Ready";
      }
      if (catalogFilter === "installable") {
        return [
          "Not Installed",
          "Provider Required",
          "Update Available",
        ].includes(model.installation_state);
      }
      if (catalogFilter === "training") {
        return model.trainable;
      }
      if (catalogFilter === "segmentation") {
        return [
          "segment",
          "semantic_segment",
          "assist_segmentation",
          "video_propagation",
        ].includes(model.task);
      }
      if (catalogFilter === "assist") {
        return (
          model.prompt_assist_compatibility ||
          ["assist_segmentation", "open_vocabulary_detect", "caption"].includes(
            model.task,
          )
        );
      }
      return true;
    });
  }, [catalogFilter, catalogSearch, pretrainedCatalogModels, showUnavailable]);

  function jumpToModelSection(sectionId: string) {
    document.getElementById(sectionId)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  function openCatalogFilter(
    filter:
      "all" | "ready" | "installable" | "training" | "segmentation" | "assist",
  ) {
    setCatalogFilter(filter);
    jumpToModelSection("model-ai-catalog");
  }

  useEffect(() => {
    if (!catalogQuery.data?.models.length) return;
    setCachedCatalog(catalogQuery.data);
    window.localStorage.setItem(
      cachedCatalogKey(project.id),
      JSON.stringify(catalogQuery.data),
    );
  }, [catalogQuery.data, project.id]);

  const activeJobEntries = useMemo(() => {
    const entries = new Map<string, string>();
    for (const model of modelCatalog?.models ?? []) {
      const localJob = installJobs[model.catalog_id];
      const jobId = localJob?.id ?? model.installation_job_id;
      const status = localJob?.status;
      if (
        jobId &&
        (!status || ["queued", "running", "cancel_requested"].includes(status))
      ) {
        entries.set(model.catalog_id, jobId);
      }
    }
    return Array.from(entries.entries());
  }, [installJobs, modelCatalog?.models]);
  const activeJobSignature = activeJobEntries
    .map(([catalogId, jobId]) => `${catalogId}:${jobId}`)
    .join("|");

  useEffect(() => {
    if (!activeJobSignature) return;
    let stopped = false;
    let inFlight = false;
    const refresh = async () => {
      // Never stack polling requests. Overlapping responses can arrive out
      // of order and make a live progress bar appear frozen or move backward.
      if (stopped || inFlight) return;
      inFlight = true;
      try {
        const updates = await Promise.all(
          activeJobEntries.map(
            async ([catalogId, jobId]) =>
              [catalogId, await getJob(jobId)] as const,
          ),
        );
        if (stopped) return;
        setInstallJobs((current) => {
          const next = { ...current };
          for (const [catalogId, job] of updates) {
            const previous = next[catalogId];
            const terminal = ![
              "queued",
              "running",
              "cancel_requested",
            ].includes(job.status);
            if (
              terminal ||
              !previous ||
              previous.id !== job.id ||
              job.progress_current >= previous.progress_current
            ) {
              next[catalogId] = job;
            }
          }
          return next;
        });
        if (
          updates.some(
            ([, job]) =>
              !["queued", "running", "cancel_requested"].includes(job.status),
          )
        ) {
          void queryClient.invalidateQueries({
            queryKey: ["model_catalog", project.id],
          });
          void queryClient.invalidateQueries({
            queryKey: ["model_hub_bootstrap", project.id],
          });
        }
      } catch (error) {
        if (!stopped) {
          console.error("Failed to refresh model-install progress", error);
        }
      } finally {
        inFlight = false;
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 500);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [activeJobSignature, project.id, queryClient]);

  useEffect(() => {
    if (selectedProvider && selectedProvider.provider_id === providerName) {
      return;
    }
    setProviderName(registerableProviders[0]?.provider_id ?? "");
  }, [providerName, registerableProviders, selectedProvider]);

  const registerMutation = useMutation({
    mutationFn: () => {
      if (!file) {
        throw new Error("Choose a model checkpoint file first");
      }
      if (selectedProviderPreflight && !selectedProviderPreflight.ready) {
        throw new Error(
          selectedProviderPreflight.issues[0] ??
            `${selectedProviderPreflight.display_name} dependencies are not ready`,
        );
      }
      return registerModel(project.id, {
        file,
        purpose,
        providerName: selectedProvider?.provider_id,
        displayName: displayName.trim() || undefined,
        notes: notes.trim() || undefined,
      });
    },
    onSuccess: async () => {
      setFile(null);
      setDisplayName("");
      setNotes("");
      await queryClient.invalidateQueries({
        queryKey: ["model_hub_bootstrap", project.id],
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (modelId: string) => deleteModel(modelId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["model_hub_bootstrap", project.id],
      });
    },
  });

  const installMutation = useMutation({
    mutationFn: async (model: ModelCatalogEntry) => ({
      model,
      job: await installCatalogModel(project.id, model.catalog_id),
    }),
    onSuccess: ({ model, job }) => {
      setConfirmationModel(null);
      setVerificationResults((current) => {
        const next = { ...current };
        delete next[model.catalog_id];
        return next;
      });
      setOperationMessage(`Installation started for ${model.display_name}.`);
      setInstallJobs((current) => ({ ...current, [model.catalog_id]: job }));
      void queryClient.invalidateQueries({
        queryKey: ["model_catalog", project.id],
      });
    },
  });

  const cancelInstallMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (job) => {
      setOperationMessage(
        "Cancellation requested. Partial downloads will be removed safely.",
      );
      setInstallJobs((current) => {
        const next = { ...current };
        for (const [catalogId, currentJob] of Object.entries(next)) {
          if (currentJob.id === job.id) next[catalogId] = job;
        }
        return next;
      });
    },
  });

  const verifyMutation = useMutation({
    mutationFn: async (model: ModelCatalogEntry) => ({
      model,
      result: await verifyCatalogModel(project.id, model.catalog_id),
    }),
    onMutate: (model) => {
      setVerificationResults((current) => ({
        ...current,
        [model.catalog_id]: {
          state: "verifying",
          message:
            "Checking the installed checkpoint against its pinned checksum.",
        },
      }));
      setOperationMessage(`Verifying ${model.display_name}...`);
    },
    onSuccess: ({ model, result }) => {
      const message = result.verified
        ? result.actual_checksum
          ? `SHA-256 ${result.actual_checksum.slice(0, 12)}… matches the trusted model.`
          : "The installed checkpoint matches the trusted model."
        : (result.reason ??
          "The installed checkpoint did not pass verification.");

      setVerificationResults((current) => ({
        ...current,
        [model.catalog_id]: {
          state: result.verified ? "passed" : "failed",
          message,
        },
      }));
      setOperationMessage(
        result.verified
          ? `${model.display_name} verification passed.`
          : `${model.display_name} verification failed.`,
      );
      void queryClient.invalidateQueries({
        queryKey: ["model_catalog", project.id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["model_hub_bootstrap", project.id],
      });
    },
    onError: (error, model) => {
      setVerificationResults((current) => ({
        ...current,
        [model.catalog_id]: {
          state: "failed",
          message: error.message,
        },
      }));
      setOperationMessage(`${model.display_name} verification failed.`);
    },
  });

  const removeCatalogMutation = useMutation({
    mutationFn: async (model: ModelCatalogEntry) => ({
      model,
      result: await removeCatalogModel(project.id, model.catalog_id),
    }),
    onSuccess: ({ model }) => {
      setVerificationResults((current) => {
        const next = { ...current };
        delete next[model.catalog_id];
        return next;
      });
      setOperationMessage(
        "Managed catalog model removed. The definition remains available.",
      );
      void queryClient.invalidateQueries({
        queryKey: ["model_catalog", project.id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["training_workspace_bootstrap", project.id],
      });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    registerMutation.mutate();
  }

  const catalogCountLabel = modelCatalog
    ? `${modelCatalog.models.length} catalog entries`
    : catalogQuery.isPending
      ? "Loading catalog..."
      : "Catalog unavailable";
  const providerPreflightCheckedAt =
    formatCheckedAt(providerPreflight.dataUpdatedAt) ??
    formatCheckedAt(modelHubBootstrap.data?.provider_preflight_checked_at);
  const runtimeStatusesCheckedAt =
    formatCheckedAt(runtimeStatuses.dataUpdatedAt) ??
    formatCheckedAt(modelHubBootstrap.data?.runtime_statuses_checked_at);
  const trainingCompatibilityCheckedAt =
    formatCheckedAt(trainingCompatibility.dataUpdatedAt) ??
    formatCheckedAt(modelHubBootstrap.data?.training_compatibility_checked_at);
  const catalogErrorDetails =
    catalogQuery.error instanceof ApiRequestError
      ? catalogQuery.error.details
      : null;
  const operationError =
    installMutation.error ??
    cancelInstallMutation.error ??
    verifyMutation.error ??
    removeCatalogMutation.error;

  return (
    <section className="gallery-panel model-ai-workspace">
      <div className="section-heading gallery-heading model-ai-header">
        <div>
          <p className="eyebrow">Models & AI</p>
          <h3>AI workspace</h3>
          <span>
            Find, install, verify, and manage models without digging through
            provider internals.
          </span>
        </div>
        <div className="image-card-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => {
              void queryClient.invalidateQueries({
                queryKey: ["model_hub_bootstrap", project.id],
              });
              void queryClient.invalidateQueries({
                queryKey: ["model_catalog", project.id],
              });
              void providerPreflight.refetch();
              void runtimeStatuses.refetch();
              void trainingCompatibility.refetch();
            }}
            disabled={modelHubBootstrap.isPending || catalogQuery.isPending}
          >
            Refresh all
          </button>
        </div>
      </div>

      <div
        className="model-ai-overview-grid"
        aria-label="Models and AI overview"
      >
        <button
          type="button"
          className="model-ai-overview-card"
          onClick={() => openCatalogFilter("installable")}
        >
          <span className="model-ai-overview-label">Available to install</span>
          <strong>{catalogSummary.installable}</strong>
          <small>Browse models that can be added now</small>
        </button>
        <button
          type="button"
          className="model-ai-overview-card"
          onClick={() => openCatalogFilter("ready")}
        >
          <span className="model-ai-overview-label">Installed & ready</span>
          <strong>{catalogSummary.ready}</strong>
          <small>See models that ReefVision can use now</small>
        </button>
        <button
          type="button"
          className="model-ai-overview-card"
          onClick={() => openCatalogFilter("assist")}
        >
          <span className="model-ai-overview-label">AI assist</span>
          <strong>Find tools</strong>
          <small>Segmentation, prompting, vision-language, and OCR</small>
        </button>
        <button
          type="button"
          className="model-ai-overview-card"
          onClick={() => jumpToModelSection("model-ai-advanced")}
        >
          <span className="model-ai-overview-label">System status</span>
          <strong>
            {catalogSummary.active > 0
              ? `${catalogSummary.active} active`
              : catalogSummary.attention > 0
                ? `${catalogSummary.attention} needs attention`
                : "Healthy"}
          </strong>
          <small>Provider, runtime, and compatibility diagnostics</small>
        </button>
      </div>

      <nav className="model-ai-jumpbar" aria-label="Models and AI navigation">
        <button type="button" onClick={() => openCatalogFilter("all")}>
          Browse models
        </button>
        <button type="button" onClick={() => openCatalogFilter("ready")}>
          Installed
        </button>
        <button
          type="button"
          onClick={() => jumpToModelSection("model-ai-project-models")}
        >
          My models
        </button>
        <button
          type="button"
          onClick={() => jumpToModelSection("model-ai-custom-models")}
        >
          Custom imports
        </button>
        <button
          type="button"
          onClick={() => jumpToModelSection("model-ai-advanced")}
        >
          Advanced
        </button>
      </nav>

      <p className="model-ai-catalog-count">{catalogCountLabel}</p>

      <section
        id="model-ai-catalog"
        className="gallery-panel model-ai-catalog-section"
      >
        <div className="section-heading gallery-heading">
          <div>
            <p className="eyebrow">Model catalog</p>
            <h3>Validated presets</h3>
            <span>Search by task or choose what you want ReefVision to do</span>
          </div>
          <button
            type="button"
            className="secondary"
            onClick={() =>
              void queryClient.invalidateQueries({
                queryKey: ["model_catalog", project.id],
              })
            }
            disabled={catalogQuery.isFetching}
          >
            Refresh catalog
          </button>
        </div>
        {catalogQuery.isPending && !modelCatalog && (
          <p>Loading model catalog...</p>
        )}
        {catalogQuery.error && (
          <div className="empty-state gallery-empty" role="alert">
            <h4>Model catalog failed to load</h4>
            <p className="form-error">{catalogQuery.error.message}</p>
            {typeof catalogErrorDetails?.expected_path === "string" && (
              <small>
                Expected location: {catalogErrorDetails.expected_path}
              </small>
            )}
            {typeof catalogErrorDetails?.recovery_action === "string" && (
              <p>{catalogErrorDetails.recovery_action}</p>
            )}
            {modelCatalog && (
              <small>Showing the last validated cached catalog.</small>
            )}
            <button type="button" onClick={() => void catalogQuery.refetch()}>
              Retry
            </button>
          </div>
        )}
        {modelCatalog && modelCatalog.rejected_entries > 0 && (
          <details className="form-error">
            <summary>
              Catalog loaded, but {modelCatalog.rejected_entries} entries were
              rejected
            </summary>
            {modelCatalog.validation_warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </details>
        )}
        {operationMessage && (
          <p className="annotation-helper" aria-live="polite">
            {operationMessage}
          </p>
        )}
        {operationError && (
          <p className="form-error">{operationError.message}</p>
        )}

        <div className="model-ai-catalog-toolbar">
          <label className="model-ai-search">
            <span>Search models</span>
            <input
              type="search"
              value={catalogSearch}
              placeholder="Search model, task, architecture, or provider"
              onChange={(event) => setCatalogSearch(event.target.value)}
            />
          </label>

          <div
            className="model-ai-filter-tabs"
            aria-label="Filter model catalog"
          >
            {(
              [
                ["all", "All"],
                ["ready", "Installed"],
                ["installable", "Available"],
                ["training", "Training"],
                ["segmentation", "Segmentation"],
                ["assist", "AI assist"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="secondary"
                aria-pressed={catalogFilter === value}
                onClick={() => setCatalogFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>

          <label className="model-ai-unavailable-toggle">
            <input
              type="checkbox"
              checked={showUnavailable}
              onChange={(event) => setShowUnavailable(event.target.checked)}
            />
            Show unavailable / future models
          </label>
        </div>

        <p className="system-subtle">
          Showing {filteredPretrainedCatalogModels.length} of{" "}
          {pretrainedCatalogModels.length} pretrained models.
        </p>

        {filteredPretrainedCatalogModels.length === 0 && (
          <div className="empty-state gallery-empty">
            <h4>No models match these filters</h4>
            <p>Try another search or switch back to All.</p>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setCatalogSearch("");
                setCatalogFilter("all");
              }}
            >
              Clear filters
            </button>
          </div>
        )}

        <div className="image-grid model-ai-model-grid">
          {filteredPretrainedCatalogModels.map((model) => {
            const job = installJobs[model.catalog_id];
            const displayedModel =
              job &&
              ["queued", "running", "cancel_requested"].includes(job.status)
                ? {
                    ...model,
                    installation_state: jobState(job),
                    installation_job_id: job.id,
                  }
                : model;
            return (
              <CatalogModelCard
                key={model.catalog_id}
                model={displayedModel}
                job={job}
                onInstall={setConfirmationModel}
                onCancel={(jobId) => cancelInstallMutation.mutate(jobId)}
                onVerify={(item) => verifyMutation.mutate(item)}
                onRemove={(item) => {
                  if (
                    window.confirm(
                      `Remove the managed ${item.display_name} checkpoint?`,
                    )
                  ) {
                    removeCatalogMutation.mutate(item);
                  }
                }}
                onSelect={(item) => {
                  setOperationMessage(
                    `${item.display_name} selected for a new training draft.`,
                  );
                  void queryClient.invalidateQueries({
                    queryKey: ["training_workspace_bootstrap", project.id],
                  });
                  onSelectCatalogModel?.(item.catalog_id);
                }}
                onViewReason={setReasonModel}
                verificationResult={verificationResults[model.catalog_id]}
              />
            );
          })}
        </div>
        {confirmationModel && (
          <div className="modal-backdrop" role="presentation">
            <section
              className="modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="model-install-title"
            >
              <p className="eyebrow">Confirm managed installation</p>
              <h3 id="model-install-title">{confirmationModel.display_name}</h3>
              <p>{confirmationModel.license_summary}</p>
              <div className="annotation-selection-list">
                <div className="annotation-selection-row">
                  <strong>Download</strong>
                  <span>{formatBytes(confirmationModel.expected_size)}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>RAM / VRAM</strong>
                  <span>
                    {confirmationModel.recommended_ram ?? "n/a"} GB /{" "}
                    {confirmationModel.recommended_vram ?? "n/a"} GB
                  </span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Provider pack</strong>
                  <span>
                    {confirmationModel.provider_pack_id ??
                      "Bundled base runtime"}
                  </span>
                </div>
              </div>
              <p className="annotation-helper">
                ReefVision will download from the declared trusted source,
                verify the pinned SHA-256, and store the finalized checkpoint in
                application data.
              </p>
              <div className="image-card-actions">
                <button
                  type="button"
                  onClick={() => installMutation.mutate(confirmationModel)}
                  disabled={installMutation.isPending}
                >
                  {installMutation.isPending
                    ? "Starting..."
                    : "Confirm Install"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setConfirmationModel(null)}
                >
                  Cancel
                </button>
              </div>
            </section>
          </div>
        )}
        {reasonModel && (
          <div className="modal-backdrop" role="presentation">
            <section
              className="modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="model-reason-title"
            >
              <h3 id="model-reason-title">{reasonModel.display_name}</h3>
              <p>
                {reasonModel.installation_reason ??
                  "No additional reason was provided."}
              </p>
              {reasonModel.known_limitations.map((limitation) => (
                <p key={limitation} className="annotation-helper">
                  {limitation}
                </p>
              ))}
              <button type="button" onClick={() => setReasonModel(null)}>
                Close
              </button>
            </section>
          </div>
        )}
      </section>

      <section id="model-ai-project-models" className="gallery-panel">
        <div className="section-heading gallery-heading">
          <div>
            <p className="eyebrow">My Trained Models</p>
            <h3>Project-trained checkpoints</h3>
            <span>One-click selection through the managed registry</span>
          </div>
        </div>
        {!trainedCatalogModels.length && (
          <p className="system-subtle">
            Completed training runs will appear here after you register them.
          </p>
        )}
        <div className="image-grid">
          {trainedCatalogModels.map((model) => (
            <CatalogModelCard key={model.catalog_id} model={model} />
          ))}
        </div>
      </section>

      <section id="model-ai-custom-models" className="gallery-panel">
        <div className="section-heading gallery-heading">
          <div>
            <p className="eyebrow">Imported Custom Models</p>
            <h3>Advanced project imports</h3>
            <span>
              Custom checkpoints stay outside the normal pretrained flow
            </span>
          </div>
        </div>
        {!importedCatalogModels.length && (
          <p className="system-subtle">
            Import a custom checkpoint from the advanced workflow to surface it
            here.
          </p>
        )}
        <div className="image-grid">
          {importedCatalogModels.map((model) => (
            <CatalogModelCard key={model.catalog_id} model={model} />
          ))}
        </div>
      </section>

      <details
        id="model-ai-advanced"
        className="gallery-panel model-ai-advanced-shell"
      >
        <summary>
          <span>
            <strong>Advanced diagnostics & provider setup</strong>
            <small>
              Runtime health, provider dependencies, and compatibility details
            </small>
          </span>
        </summary>
        <div className="model-ai-advanced-content">
          <section className="gallery-panel">
            <div className="section-heading gallery-heading">
              <div>
                <p className="eyebrow">Provider hub</p>
                <h3>Model provider catalog</h3>
                <span>Ready, blocked, and future provider families</span>
              </div>
            </div>
            {modelHubBootstrap.isPending && providerCatalog.length === 0 && (
              <p>Loading provider catalog...</p>
            )}
            {modelHubBootstrap.error && providerCatalog.length === 0 && (
              <p className="form-error">{modelHubBootstrap.error.message}</p>
            )}
            <div className="image-grid">
              {providerCatalog.map((provider) => (
                <ProviderCatalogCard
                  key={provider.provider_id}
                  provider={provider}
                  dependencyStatus={
                    preflightByName.get(provider.provider_id) ?? undefined
                  }
                />
              ))}
            </div>
          </section>

          <section className="gallery-panel">
            <div className="section-heading gallery-heading">
              <div>
                <p className="eyebrow">Runtime status</p>
                <h3>Execution backends</h3>
                <span>
                  {runtimeStatusesCheckedAt
                    ? `Showing latest check from ${runtimeStatusesCheckedAt}`
                    : "Architecture and runtime are tracked separately"}
                </span>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => void runtimeStatuses.refetch()}
                disabled={runtimeStatuses.isFetching}
              >
                Refresh runtime status
              </button>
            </div>
            {runtimeStatuses.isPending && !runtimeStatuses.data && (
              <p>Checking runtime backends...</p>
            )}
            {runtimeStatuses.error && (
              <p className="form-error">{runtimeStatuses.error.message}</p>
            )}
            <div className="image-grid">
              {runtimeStatuses.data?.map((runtime) => (
                <RuntimeProviderCard
                  key={runtime.runtime_id}
                  runtime={runtime}
                />
              ))}
            </div>
          </section>

          <section className="gallery-panel">
            <div className="section-heading gallery-heading">
              <div>
                <p className="eyebrow">Dependency preflight</p>
                <h3>Implemented provider readiness</h3>
                <span>
                  {providerPreflightCheckedAt
                    ? `Showing latest check from ${providerPreflightCheckedAt}`
                    : "Explicit local checkpoints only"}
                </span>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => void providerPreflight.refetch()}
                disabled={providerPreflight.isFetching}
              >
                Refresh dependencies
              </button>
            </div>
            {providerPreflight.isPending && !providerPreflight.data && (
              <p>Checking provider dependencies...</p>
            )}
            {providerPreflight.error && (
              <p className="form-error">{providerPreflight.error.message}</p>
            )}
            <div className="image-grid">
              {providerPreflight.data?.providers.map((provider) => (
                <ProviderReadinessCard
                  key={provider.provider_name}
                  provider={provider}
                />
              ))}
            </div>
          </section>

          <section className="gallery-panel">
            <div className="section-heading gallery-heading">
              <div>
                <p className="eyebrow">Training compatibility</p>
                <h3>Pinned Ultralytics registry</h3>
                <span>
                  {trainingCompatibilityCheckedAt
                    ? `Showing latest compatibility snapshot from ${trainingCompatibilityCheckedAt}`
                    : "Read-only compatibility map for future training workflows"}
                </span>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => void trainingCompatibility.refetch()}
                disabled={trainingCompatibility.isFetching}
              >
                Refresh compatibility
              </button>
            </div>
            {trainingCompatibility.isPending && !trainingCompatibility.data && (
              <p>Loading pinned Ultralytics training compatibility...</p>
            )}
            {trainingCompatibility.error && (
              <p className="form-error">
                {trainingCompatibility.error.message}
              </p>
            )}
            {trainingCompatibility.data && (
              <UltralyticsTrainingCompatibility
                registry={trainingCompatibility.data}
              />
            )}
          </section>
        </div>
      </details>

      <details
        id="model-ai-import"
        className="gallery-panel model-ai-import-shell"
      >
        <summary>Advanced · Import custom checkpoint</summary>
        <form className="new-class-form" onSubmit={submit}>
          <h3>Import a local checkpoint</h3>
          <label>
            Purpose
            <select
              value={purpose}
              onChange={(event) =>
                setPurpose(event.target.value as "detector" | "assist")
              }
            >
              <option value="detector">Detector</option>
              <option value="assist">Assist / Smart Mask</option>
            </select>
          </label>
          <label>
            Provider
            <select
              value={selectedProvider?.provider_id ?? ""}
              onChange={(event) => setProviderName(event.target.value)}
              disabled={registerableProviders.length === 0}
            >
              {registerableProviders.length === 0 && (
                <option value="">
                  No registerable providers for this purpose
                </option>
              )}
              {registerableProviders.map((provider) => (
                <option key={provider.provider_id} value={provider.provider_id}>
                  {provider.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Display name
            <input
              value={displayName}
              placeholder="Optional friendly name"
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>
          <label>
            Notes
            <textarea
              value={notes}
              placeholder="Checkpoint source, class map notes, hardware notes"
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
          <label>
            Checkpoint file
            <input
              type="file"
              accept=".pt,.pth"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <p className="annotation-helper">
            Imported custom models remain part of the advanced workflow. The
            normal pretrained selector comes from the validated Model Catalog
            instead.
          </p>
          {selectedProvider && (
            <p className="annotation-helper">
              Selected provider: {selectedProvider.display_name}. Supported
              tasks: {selectedProvider.supported_tasks.join(", ")}. Runtime:{" "}
              {selectedProvider.supported_execution_runtimes.join(", ")}.
            </p>
          )}
          {selectedProviderPreflight && !selectedProviderPreflight.ready && (
            <p className="form-error">
              {selectedProviderPreflight.display_name} is not ready:{" "}
              {selectedProviderPreflight.issues.join(" ")}
            </p>
          )}
          <button
            type="submit"
            disabled={
              registerMutation.isPending ||
              !selectedProvider ||
              Boolean(
                selectedProviderPreflight && !selectedProviderPreflight.ready,
              )
            }
          >
            {registerMutation.isPending
              ? "Importing..."
              : "Import custom model"}
          </button>
          {registerMutation.error && (
            <p className="form-error">{registerMutation.error.message}</p>
          )}
        </form>
      </details>

      {modelHubBootstrap.isPending && models.length === 0 && (
        <p>Loading registered models...</p>
      )}
      {modelHubBootstrap.error && models.length === 0 && (
        <p className="form-error">{modelHubBootstrap.error.message}</p>
      )}
      {!modelHubBootstrap.isPending && models.length === 0 && (
        <div className="empty-state gallery-empty">
          <h4>No models registered</h4>
          <p>
            Register a detector for batch proposals or an assist model for Smart
            Mask sessions.
          </p>
        </div>
      )}
      <div className="image-grid">
        {models.map((model) => (
          <ModelRow
            key={model.id}
            model={model}
            onDelete={(modelId) => deleteMutation.mutate(modelId)}
          />
        ))}
      </div>
      {deleteMutation.error && (
        <p className="form-error">{deleteMutation.error.message}</p>
      )}
    </section>
  );
}

function ProviderCatalogCard({
  provider,
  dependencyStatus,
}: {
  provider: ModelProvider;
  dependencyStatus?: ProviderDependencyStatus;
}) {
  const capabilityFlags = [
    provider.capabilities.image_detection ? "Image detect" : null,
    provider.capabilities.text_prompt_detection ? "Text prompt" : null,
    provider.capabilities.image_example_detection ? "Example object" : null,
    provider.capabilities.box_prompting ? "Box prompt" : null,
    provider.capabilities.brush_prompting ? "Brush prompt" : null,
    provider.capabilities.video_propagation ? "Video" : null,
    provider.capabilities.multi_object_tracking ? "Tracking" : null,
  ].filter(Boolean);

  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{provider.display_name}</h4>
          <p>
            {provider.availability_status} |{" "}
            {provider.registerable ? "Registerable" : "Catalog only"}
          </p>
        </div>
        <small>Provider ID: {provider.provider_id}</small>
        <small>
          Tasks: {provider.supported_tasks.join(", ") || "Not declared"}
        </small>
        <small>
          Runtimes:{" "}
          {provider.supported_execution_runtimes.join(", ") || "Not declared"}
        </small>
        <small>
          CPU {provider.cpu_support ? "yes" : "no"} | CUDA{" "}
          {provider.cuda_support ? "yes" : "no"} | Desktop{" "}
          {provider.capabilities.packaged_desktop_operation ? "yes" : "no"}
        </small>
        {provider.availability_reason && (
          <p className="annotation-helper">{provider.availability_reason}</p>
        )}
        {dependencyStatus && (
          <small>
            Pinned dependency state:{" "}
            {dependencyStatus.ready ? "ready" : dependencyStatus.status}
          </small>
        )}
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Capabilities</strong>
            <span>{capabilityFlags.join(", ") || "None surfaced yet"}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Families</strong>
            <span>
              {provider.supported_model_families.slice(0, 2).join("; ") ||
                "Not declared"}
            </span>
          </div>
        </div>
      </div>
    </article>
  );
}

function ProviderReadinessCard({
  provider,
}: {
  provider: ProviderDependencyStatus;
}) {
  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{provider.display_name}</h4>
          <p>
            {provider.purpose} | {provider.ready ? "Ready" : "Needs attention"}
          </p>
        </div>
        <small>
          Python {provider.current_python} | tested {provider.tested_python}
        </small>
        <small>
          Platform {provider.current_platform} | tested{" "}
          {provider.tested_platform}
        </small>
        {provider.tested_cuda && (
          <small>
            CUDA {provider.current_cuda ?? "unknown"} | tested{" "}
            {provider.tested_cuda}
          </small>
        )}
        <small>Requirements: {provider.requirements_file}</small>
        <small>
          Downloads{" "}
          {provider.automatic_downloads_disabled ? "disabled" : "enabled"} |
          local checkpoint{" "}
          {provider.explicit_checkpoint_required ? "required" : "optional"}
        </small>
        {provider.issues.length > 0 && (
          <div className="annotation-selection-list">
            {provider.issues.map((issue) => (
              <div key={issue} className="annotation-selection-row">
                <strong>Issue</strong>
                <span>{issue}</span>
              </div>
            ))}
          </div>
        )}
        <div className="annotation-selection-list">
          {provider.packages.map((item) => (
            <div
              key={item.distribution_name}
              className="annotation-selection-row"
            >
              <strong>{item.distribution_name}</strong>
              <span>
                {item.installed_version ?? "missing"} / {item.required_version}
              </span>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function RuntimeProviderCard({ runtime }: { runtime: RuntimeProviderStatus }) {
  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{runtime.display_name}</h4>
          <p>
            {runtime.available ? "Available" : "Unavailable"} | {runtime.status}
          </p>
        </div>
        <small>
          Package: {runtime.package_name ?? "n/a"}{" "}
          {runtime.package_version ?? "missing"}
        </small>
        <small>
          CPU {runtime.supports_cpu ? "yes" : "no"} | CUDA{" "}
          {runtime.supports_cuda ? "yes" : "no"}
        </small>
        <div className="annotation-selection-list">
          {runtime.notes.map((note) => (
            <div key={note} className="annotation-selection-row">
              <strong>Note</strong>
              <span>{note}</span>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function UltralyticsTrainingCompatibility({
  registry,
}: {
  registry: UltralyticsTrainingRegistrySummarySnapshot;
}) {
  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>Ultralytics {registry.provider_version}</h4>
          <p>
            Detect and segment parameter registry for the pinned desktop build
          </p>
        </div>
        <small>
          Installed package {registry.ultralytics_version ?? "missing"} |{" "}
          {registry.pinned_version_matches_installed
            ? "pinned version match"
            : "installed version mismatch"}
        </small>
        <small>
          Supported tasks {registry.supported_tasks.join(", ")} | modes{" "}
          {registry.supported_modes.join(", ")}
        </small>
        <small>
          Full training execution is still in progress. This release adds the
          versioned registry and strict argument validation foundation first.
        </small>
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Total parameters</strong>
            <span>{registry.summary.parameter_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>ReefVision-supported</strong>
            <span>{registry.summary.reefvision_supported_parameter_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Tunable parameters</strong>
            <span>{registry.summary.tunable_parameter_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Native tune defaults</strong>
            <span>{registry.summary.native_tune_parameter_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Fixed-only parameters</strong>
            <span>{registry.summary.fixed_only_parameter_count}</span>
          </div>
        </div>
        <p className="annotation-helper">
          Detailed parameter schemas now load in the Training workspace only
          after you choose a compatible provider and open hyperparameters.
        </p>
      </div>
    </article>
  );
}
