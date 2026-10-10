import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  deleteModel,
  getModelProviderPreflight,
  getModelHubBootstrap,
  getProjectModelCatalog,
  getRuntimeProviderStatuses,
  getUltralyticsTrainingRegistrySummary,
  type ModelCatalogEntry,
  type ModelCatalogResponse,
  type ModelProvider,
  registerModel,
  registerProviderModel,
  type ModelRegistration,
  type ProviderDependencyStatus,
  type Project,
  type RuntimeProviderStatus,
  type UltralyticsTrainingRegistrySummarySnapshot,
} from "../../api/client";

const optionalModelProviders = [
  { id: "grounding_dino", label: "Grounding DINO", extension: ".zip" },
  { id: "sam2", label: "SAM2", extension: ".zip" },
  { id: "smolvlm", label: "SmolVLM", extension: ".zip" },
  { id: "scale_label_ocr", label: "Scale label OCR", extension: ".zip" },
  {
    id: "video_depth_anything",
    label: "Metric Video Depth Anything",
    extension: ".pth",
  },
];

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
        <small title={model.sha256}>
          Checksum: {model.sha256.slice(0, 12)}...
        </small>
        <small>Project: {model.project_id}</small>
        <small>Registered: {new Date(model.created_at).toLocaleString()}</small>
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

function CatalogModelCard({
  model,
  onSelect,
  onRegister,
}: {
  model: ModelCatalogEntry;
  onSelect?: (model: ModelCatalogEntry) => void;
  onRegister?: () => void;
}) {
  const architecture = model.category === "architecture";
  const registered = model.selection_kind === "registered_model";
  const canTrain =
    architecture &&
    (model.training_supported ?? model.trainable) &&
    model.installation_state === "Available";
  return (
    <article className="image-card">
      <div className="image-card-body">
        <div>
          <h4>{model.display_name}</h4>
          <p>
            {architecture
              ? "Architecture"
              : registered
                ? "Registered model"
                : "Optional provider"}{" "}
            |{" "}
            {architecture
              ? model.installation_state === "Ready"
                ? "Available"
                : model.installation_state
              : registered
                ? model.installation_state
                : "Model Required"}
          </p>
        </div>
        <small>
          {model.architecture_family} | {model.task.replaceAll("_", " ")}
        </small>
        <small>
          Provider: {model.provider} {model.provider_version}
        </small>
        {architecture && (
          <small>Configuration: {model.architecture_reference}</small>
        )}
        {registered && model.installed_path && (
          <small>Location: {model.installed_path}</small>
        )}
        {registered && model.installed_checksum && (
          <small>Checksum: {model.installed_checksum}</small>
        )}
        <p>{model.display_summary}</p>
        {architecture ? (
          <p className="annotation-helper">
            Train from random initialization using verified data. This
            architecture contains no trained weights.
          </p>
        ) : !registered ? (
          <p className="annotation-helper">
            Model required — register a compatible model to use this feature.
          </p>
        ) : (
          <p>
            Source:{" "}
            {model.category === "my_trained_models"
              ? "ReefVision training output"
              : "Researcher-registered checkpoint"}
          </p>
        )}
        {model.installation_reason && (
          <p className="annotation-helper">{model.installation_reason}</p>
        )}
        <small>
          Recommended VRAM:{" "}
          {model.recommended_vram == null
            ? "Not declared"
            : `${model.recommended_vram} GB`}
        </small>
        <small>License: {model.license_summary ?? model.package_license}</small>
        <div className="image-card-actions">
          {canTrain && onSelect && (
            <button type="button" onClick={() => onSelect(model)}>
              Train New Model
            </button>
          )}
          {!registered && !architecture && onRegister && (
            <button type="button" onClick={onRegister}>
              Register Existing Model
            </button>
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

export function ModelManager({
  project,
  onSelectCatalogModel,
  onTrainPoseArchitecture,
  onTrainClassificationArchitecture,
}: {
  project: Project;
  onSelectCatalogModel?: (catalogId: string) => void;
  onTrainPoseArchitecture?: (architecture: string) => void;
  onTrainClassificationArchitecture?: (architecture: string) => void;
}) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [providerFile, setProviderFile] = useState<File | null>(null);
  const [optionalProviderId, setOptionalProviderId] =
    useState("grounding_dino");
  const [purpose, setPurpose] = useState<"detector" | "assist">("detector");
  const [providerName, setProviderName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [notes, setNotes] = useState("");
  const [cachedCatalog, setCachedCatalog] =
    useState<ModelCatalogResponse | null>(() => loadCachedCatalog(project.id));
  const [operationMessage, setOperationMessage] = useState<string | null>(null);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogFilter, setCatalogFilter] = useState<
    "all" | "available" | "training" | "segmentation" | "assist"
  >("all");
  const [showUnavailable, setShowUnavailable] = useState(false);
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
  const architectureCatalogModels = useMemo(
    () =>
      (modelCatalog?.models ?? []).filter((item) =>
        ["architecture", "provider_requirement", "pretrained_catalog"].includes(
          item.category,
        ),
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

  const catalogSummary = {
    available: architectureCatalogModels.filter(
      (item) =>
        item.category === "architecture" &&
        item.installation_state === "Available",
    ).length,
    ready: trainedCatalogModels.length + importedCatalogModels.length,
  };

  const filteredArchitectureCatalogModels = useMemo(() => {
    const query = catalogSearch.trim().toLocaleLowerCase();
    return architectureCatalogModels.filter((model) => {
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

      if (catalogFilter === "available")
        return (
          model.category === "architecture" &&
          model.installation_state === "Available"
        );
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
  }, [
    catalogFilter,
    catalogSearch,
    architectureCatalogModels,
    showUnavailable,
  ]);

  function jumpToModelSection(sectionId: string) {
    document.getElementById(sectionId)?.scrollIntoView?.({
      behavior: "smooth",
      block: "start",
    });
  }

  function openCatalogFilter(
    filter: "all" | "available" | "training" | "segmentation" | "assist",
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
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["model_hub_bootstrap", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["project", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["projects"],
        }),
      ]);
    },
  });

  const registerProviderMutation = useMutation({
    mutationFn: () => {
      if (!providerFile)
        throw new Error("Choose a compatible local model file first");
      return registerProviderModel(
        project.id,
        optionalProviderId,
        providerFile,
      );
    },
    onSuccess: () => {
      setProviderFile(null);
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["model_catalog", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["model_hub_bootstrap", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["advanced-provider-model-catalog", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["reefvision-assistant-model-catalog", project.id],
        }),
        providerPreflight.refetch(),
      ]);
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
  return (
    <section className="gallery-panel model-ai-workspace">
      <div className="section-heading gallery-heading model-ai-header">
        <div>
          <p className="eyebrow">Models & AI</p>
          <h3>AI workspace</h3>
          <span>
            Train from supported architectures or register your own trained
            models. No model weights are bundled or downloaded.
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
          onClick={() => openCatalogFilter("available")}
        >
          <span className="model-ai-overview-label">
            Available architectures
          </span>
          <strong>{catalogSummary.available}</strong>
          <small>Choose a configuration for training</small>
        </button>
        <button
          type="button"
          className="model-ai-overview-card"
          onClick={() => jumpToModelSection("model-ai-project-models")}
        >
          <span className="model-ai-overview-label">Registered models</span>
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
          <strong>Provider status</strong>
          <small>Provider, runtime, and compatibility diagnostics</small>
        </button>
      </div>

      <nav className="model-ai-jumpbar" aria-label="Models and AI navigation">
        <button type="button" onClick={() => openCatalogFilter("all")}>
          Architectures
        </button>
        <button
          type="button"
          onClick={() => jumpToModelSection("model-ai-project-models")}
        >
          Registered Models
        </button>
        <button
          type="button"
          onClick={() => jumpToModelSection("model-ai-project-models")}
        >
          My models
        </button>
        <button
          type="button"
          onClick={() =>
            document
              .getElementById("model-registration")
              ?.setAttribute("open", "")
          }
        >
          Register Existing Model
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
            <h3>Architectures</h3>
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
                ["available", "Available"],
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
          Showing {filteredArchitectureCatalogModels.length} of{" "}
          {architectureCatalogModels.length} architectures and provider
          capabilities.
        </p>

        {filteredArchitectureCatalogModels.length === 0 && (
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
          {filteredArchitectureCatalogModels.map((model) => (
            <CatalogModelCard
              key={model.catalog_id}
              model={model}
              onSelect={
                onSelectCatalogModel
                  ? (item) => {
                      setOperationMessage(
                        `${item.display_name} selected for training from scratch.`,
                      );
                      if (item.task === "pose") {
                        if (item.architecture_reference)
                          onTrainPoseArchitecture?.(
                            item.architecture_reference,
                          );
                      } else if (item.task === "classify") {
                        if (item.architecture_reference)
                          onTrainClassificationArchitecture?.(
                            item.architecture_reference,
                          );
                      } else {
                        onSelectCatalogModel(item.catalog_id);
                      }
                    }
                  : undefined
              }
              onRegister={() => {
                if (
                  optionalModelProviders.some(
                    (provider) => provider.id === model.provider_id,
                  )
                ) {
                  setOptionalProviderId(model.provider_id);
                  setProviderFile(null);
                  document
                    .getElementById("optional-provider-registration")
                    ?.setAttribute("open", "");
                  jumpToModelSection("optional-provider-registration");
                  return;
                }
                const form = document.getElementById("model-registration");
                form?.setAttribute("open", "");
                jumpToModelSection("model-registration");
              }}
            />
          ))}
        </div>
      </section>

      <section id="model-ai-project-models" className="gallery-panel">
        <div className="section-heading gallery-heading">
          <div>
            <p className="eyebrow">My Trained Models</p>
            <h3>Registered Models</h3>
            <span>
              ReefVision training outputs with project and training-run
              provenance
            </span>
          </div>
        </div>
        {!trainedCatalogModels.length && (
          <p className="system-subtle">
            Registered training outputs appear here after a successful run.
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
            <h3>Researcher-registered checkpoints</h3>
            <span>
              Your compatible local models, with explicit source and schema
              binding
            </span>
          </div>
        </div>
        {!importedCatalogModels.length && (
          <p className="system-subtle">
            Register a compatible trained checkpoint to use it in this project.
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
        id="optional-provider-registration"
        className="gallery-panel model-ai-import-shell"
      >
        <summary>Register optional provider model</summary>
        <form
          className="new-class-form"
          onSubmit={(event) => {
            event.preventDefault();
            registerProviderMutation.mutate();
          }}
        >
          <h3>Optional provider model</h3>
          <p>
            Provide your own compatible trained model. Transformers bundles must
            contain the configuration, processor/tokenizer files and trained
            weights in a ZIP. Metric video depth accepts a local .pth
            checkpoint.
          </p>
          <p>
            This registration activates the local model for this provider across
            ReefVision projects. Existing model files are preserved.
          </p>
          <label>
            Optional model provider
            <select
              value={optionalProviderId}
              onChange={(event) => {
                setOptionalProviderId(event.target.value);
                setProviderFile(null);
                registerProviderMutation.reset();
              }}
            >
              {optionalModelProviders.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Provider model file
            <input
              key={optionalProviderId}
              type="file"
              accept={
                optionalModelProviders.find(
                  (provider) => provider.id === optionalProviderId,
                )?.extension
              }
              onChange={(event) =>
                setProviderFile(event.target.files?.[0] ?? null)
              }
            />
          </label>
          <button
            type="submit"
            disabled={!providerFile || registerProviderMutation.isPending}
          >
            {registerProviderMutation.isPending
              ? "Registering..."
              : "Register provider model"}
          </button>
          {registerProviderMutation.error && (
            <p className="form-error" role="alert">
              {registerProviderMutation.error.message}
            </p>
          )}
          {registerProviderMutation.data && (
            <div role="status">
              <p>
                Registered {registerProviderMutation.data.original_filename}
              </p>
              <p>
                Provider: {registerProviderMutation.data.provider_id} | Task:{" "}
                {registerProviderMutation.data.task}
              </p>
              <p>Project: {registerProviderMutation.data.project_id}</p>
              <p>
                Registered:{" "}
                {new Date(
                  registerProviderMutation.data.registered_at,
                ).toLocaleString()}
              </p>
              <code>{registerProviderMutation.data.sha256}</code>
            </div>
          )}
        </form>
      </details>

      <details
        id="model-registration"
        className="gallery-panel model-ai-import-shell"
      >
        <summary>Register Existing Model</summary>
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
            Register a local trained checkpoint. ReefVision preserves its
            source, checksum, provider and class mapping. Pose models and SLEAP
            bundles use the schema-aware registration in Pose Tracking.
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
              : "Register Existing Model"}
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
          Automatic weight downloads disabled | local checkpoint{" "}
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
          Training uses local architecture configurations or explicitly
          registered checkpoints.
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
