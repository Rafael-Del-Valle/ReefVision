import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { getJob, getProjectModelCatalog, type Project } from "../../api/client";
import {
  executeAdvancedProvider,
  getAdvancedProviderManifests,
  getSam2Models,
  installSam2Model,
  listAdvancedProviderImages,
  preflightAdvancedProvider,
} from "./advancedProvidersApi";

interface AdvancedProviderWorkspaceProps {
  project: Project;
}

const MANAGED_PROVIDER_CATALOG_IDS: Record<string, string> = {
  grounding_dino: "transformers/grounding_dino/tiny",
  sam2: "sam2/image/base",
  smolvlm: "transformers/smolvlm/256m-instruct",
};

function defaultPromptFields(
  providerId: string,
  task: string,
): Record<string, unknown> {
  if (providerId === "grounding_dino") {
    return {
      image_id: "",
      text_prompts: ["coral polyp"],
      confidence: 0.35,
      text_threshold: 0.25,
    };
  }
  if (providerId === "sam2") {
    return { image_id: "", box: [0, 0, 100, 100], sam2_variant: "small" };
  }
  if (providerId === "smolvlm") {
    return {
      image_id: "",
      prompt:
        task === "caption"
          ? "Describe the scientifically relevant visible content in this image."
          : "What scientifically relevant structures are visible in this image?",
      max_new_tokens: 128,
    };
  }
  if (providerId === "nnunet") {
    return {
      input_folder: "",
      output_folder: "",
      dataset: "Dataset001_MyDataset",
      configuration: "3d_fullres",
      folds: [0, 1, 2, 3, 4],
      timeout_seconds: 7200,
    };
  }
  return {};
}

export function AdvancedProviderWorkspace({
  project,
}: AdvancedProviderWorkspaceProps) {
  const [providerId, setProviderId] = useState("");
  const [task, setTask] = useState("");
  const [device, setDevice] = useState("auto");
  const [promptFields, setPromptFields] = useState<Record<string, unknown>>({});
  const [rawJson, setRawJson] = useState("{}");
  const [sam2Variant, setSam2Variant] = useState("small");
  const autoInstallAttempted = useRef(new Set<string>());
  const [sam2InstallJobId, setSam2InstallJobId] = useState<string | null>(null);
  const sam2Models = useQuery({
    queryKey: ["sam2-models", project.id],
    queryFn: ({ signal }) => getSam2Models(project.id, signal),
    enabled: providerId === "sam2",
    refetchInterval: sam2InstallJobId ? 2500 : false,
  });
  const sam2Install = useMutation({
    mutationFn: () => installSam2Model(project.id, sam2Variant),
    onSuccess: (job) => setSam2InstallJobId(job.id),
  });
  const sam2InstallJob = useQuery({
    queryKey: ["sam2-install-job", sam2InstallJobId],
    queryFn: () => getJob(sam2InstallJobId!),
    enabled: Boolean(sam2InstallJobId),
    refetchInterval: (query) =>
      ["succeeded", "failed", "cancelled"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1250,
  });
  const selectedSam2Model = sam2Models.data?.find(
    (item) => item.variant === sam2Variant,
  );
  const sam2Ready = Boolean(selectedSam2Model?.ready);

  useEffect(() => {
    if (
      providerId !== "sam2" ||
      !selectedSam2Model ||
      selectedSam2Model.installed ||
      sam2Install.isPending ||
      autoInstallAttempted.current.has(sam2Variant)
    )
      return;
    autoInstallAttempted.current.add(sam2Variant);
    sam2Install.mutate();
  }, [
    providerId,
    sam2Variant,
    selectedSam2Model,
    sam2Install.isPending,
    sam2Install.mutate,
  ]);

  const manifestsQuery = useQuery({
    queryKey: ["advanced-provider-manifests"],
    queryFn: ({ signal }) => getAdvancedProviderManifests(signal),
  });
  const imagesQuery = useQuery({
    queryKey: ["advanced-provider-images", project.id],
    queryFn: ({ signal }) => listAdvancedProviderImages(project.id, signal),
  });
  const modelCatalogQuery = useQuery({
    queryKey: ["advanced-provider-model-catalog", project.id],
    queryFn: ({ signal }) =>
      getProjectModelCatalog(
        project.id,
        { workflow: "model_hub", includeUnavailable: true },
        signal,
      ),
    staleTime: 30_000,
  });
  const selectedManifest = useMemo(
    () => manifestsQuery.data?.find((item) => item.provider_id === providerId),
    [manifestsQuery.data, providerId],
  );
  const managedCatalogId = MANAGED_PROVIDER_CATALOG_IDS[providerId] ?? null;
  const managedModel = useMemo(
    () =>
      managedCatalogId
        ? modelCatalogQuery.data?.models.find(
            (model) => model.catalog_id === managedCatalogId,
          )
        : undefined,
    [managedCatalogId, modelCatalogQuery.data?.models],
  );
  const managedModelReady =
    providerId === "sam2"
      ? sam2Ready
      : managedCatalogId == null ||
        managedModel?.installation_state === "Ready";

  useEffect(() => {
    const preferred = manifestsQuery.data?.find(
      (item) => item.provider_id === "grounding_dino",
    );
    if (!providerId && (preferred ?? manifestsQuery.data?.[0])) {
      setProviderId((preferred ?? manifestsQuery.data?.[0])?.provider_id ?? "");
    }
  }, [manifestsQuery.data, providerId]);

  useEffect(() => {
    const firstTask = selectedManifest?.supported_tasks[0] ?? "";
    const nextTask = selectedManifest?.supported_tasks.includes(task)
      ? task
      : firstTask;
    if (nextTask !== task) setTask(nextTask);
    const nextFields = defaultPromptFields(providerId, nextTask);
    if (providerId === "sam2") nextFields.sam2_variant = sam2Variant;
    const firstImage = imagesQuery.data?.[0];
    if ("image_id" in nextFields && firstImage)
      nextFields.image_id = firstImage.id;
    setPromptFields(nextFields);
    setRawJson(JSON.stringify(nextFields, null, 2));
  }, [imagesQuery.data, providerId, selectedManifest, task, sam2Variant]);

  function updateField(name: string, value: unknown) {
    setPromptFields((current) => {
      const next = { ...current, [name]: value };
      setRawJson(JSON.stringify(next, null, 2));
      return next;
    });
  }

  const preflightMutation = useMutation({
    mutationFn: () =>
      preflightAdvancedProvider(project.id, providerId, {
        task,
        device,
        model_id: null,
        allow_model_download: false,
        prompt_fields: promptFields,
      }),
  });
  const executeMutation = useMutation({
    mutationFn: () =>
      executeAdvancedProvider(project.id, providerId, {
        task,
        device,
        allow_model_download: false,
        prompt_fields: promptFields,
      }),
  });

  const imageRequired =
    selectedManifest?.prompt_fields_by_task[task]?.includes("image_id") ??
    false;

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Models &amp; AI</p>
          <h3>Advanced Provider Lab</h3>
          <p>
            Run optional vision providers through a guided, fail-closed
            workflow. SAM 2.1 supports explicitly approved model installation;
            other providers continue to require compatible local checkpoints.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>1. Choose a provider</h4>
          <label>
            Provider
            <select
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
            >
              {manifestsQuery.data?.map((manifest) => (
                <option key={manifest.provider_id} value={manifest.provider_id}>
                  {manifest.display_name} · {manifest.maturity}
                </option>
              ))}
            </select>
          </label>
          <label>
            Task
            <select
              value={task}
              onChange={(event) => setTask(event.target.value)}
            >
              {selectedManifest?.supported_tasks.map((item) => (
                <option key={item} value={item}>
                  {item.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Device
            <select
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="cuda">CUDA</option>
              <option value="cpu">CPU</option>
            </select>
          </label>
          {selectedManifest && (
            <p className="annotation-helper">
              {selectedManifest.execution_surface === "provider_lab"
                ? "This provider runs here in Advanced Provider Lab."
                : selectedManifest.execution_surface === "existing_workflow"
                  ? "This provider is available through an existing ReefVision workflow; Provider Lab launch is disabled."
                  : "This provider remains documented/preflight-only."}
            </p>
          )}
          {providerId === "sam2" && (
            <div className="annotation-selection-list">
              <label>
                SAM 2.1 checkpoint size
                <select
                  aria-label="SAM 2.1 model size"
                  value={sam2Variant}
                  onChange={(event) => {
                    setSam2Variant(event.target.value);
                    setSam2InstallJobId(null);
                  }}
                >
                  <option value="tiny">Hiera Tiny</option>
                  <option value="small">Hiera Small</option>
                  <option value="base-plus">Hiera Base+</option>
                  <option value="large">
                    Hiera Large (more VRAM required)
                  </option>
                </select>
              </label>
              <p>
                {selectedSam2Model?.ready
                  ? "Installed and verified"
                  : selectedSam2Model?.installed
                    ? "Checkpoint cached; runtime unavailable"
                    : (selectedSam2Model?.reason ?? "Checking installation...")}
              </p>
              <p className="annotation-helper">
                SAM 2.1 model weights are automatically downloaded and cached
                when you select a size. No approval dialog is required. Meta's
                Apache-2.0 source, revision, and SHA-256 are recorded. Large
                models can require substantial disk space and bandwidth.
              </p>
              <button
                type="button"
                disabled={
                  Boolean(selectedSam2Model?.installed) ||
                  sam2Install.isPending ||
                  ["queued", "running"].includes(
                    sam2InstallJob.data?.status ?? "",
                  )
                }
                onClick={() => sam2Install.mutate()}
              >
                {sam2Ready ? "SAM 2.1 ready" : "Retry SAM 2.1 download"}
              </button>
              {sam2InstallJob.data && (
                <p role="status">
                  Installation: {sam2InstallJob.data.status} ·
                  {sam2InstallJob.data.progress_current.toLocaleString()} /
                  {sam2InstallJob.data.progress_total.toLocaleString()}{" "}
                  bytes/files
                </p>
              )}
              {(sam2Install.error ||
                sam2InstallJob.error ||
                sam2InstallJob.data?.error_message) && (
                <p className="form-error">
                  {sam2Install.error?.message ||
                    sam2InstallJob.error?.message ||
                    sam2InstallJob.data?.error_message}
                </p>
              )}
            </div>
          )}
          {managedCatalogId && providerId !== "sam2" && (
            <div className="annotation-selection-list">
              <div className="annotation-selection-row">
                <strong>Model Hub checkpoint</strong>
                <span>
                  {managedModel?.display_name ??
                    (modelCatalogQuery.isPending ? "Checking…" : "Not found")}
                </span>
              </div>
              <div className="annotation-selection-row">
                <strong>Model status</strong>
                <span>
                  {modelCatalogQuery.isPending
                    ? "Checking…"
                    : (managedModel?.installation_state ?? "Model Required")}
                </span>
              </div>
              {managedModel?.checkpoint_identifier && (
                <div className="annotation-selection-row">
                  <strong>Pinned checkpoint</strong>
                  <span>{managedModel.checkpoint_identifier}</span>
                </div>
              )}
            </div>
          )}
          {managedCatalogId &&
            providerId !== "sam2" &&
            !managedModelReady &&
            !modelCatalogQuery.isPending && (
              <p className="form-error" role="alert">
                Model required — register a compatible model to use this
                feature. Automatic weight downloads are disabled.
              </p>
            )}
          {managedCatalogId && providerId !== "sam2" && managedModelReady && (
            <p className="annotation-helper">
              Ready · using the verified Model Hub checkpoint.
            </p>
          )}
          {modelCatalogQuery.error && managedCatalogId && (
            <p className="form-error">
              Model Hub status could not be loaded:{" "}
              {modelCatalogQuery.error.message}
            </p>
          )}
        </div>

        <div className="panel-card">
          <h4>2. Configure the action</h4>
          {imageRequired && (
            <label>
              Project image
              <select
                value={String(promptFields.image_id ?? "")}
                onChange={(event) =>
                  updateField("image_id", event.target.value)
                }
              >
                <option value="">Select an image</option>
                {imagesQuery.data?.map((image) => (
                  <option key={image.id} value={image.id}>
                    {image.original_filename} · {image.width_px}×
                    {image.height_px}
                  </option>
                ))}
              </select>
            </label>
          )}

          {providerId === "grounding_dino" && (
            <>
              <label>
                Text prompts (comma separated)
                <input
                  value={
                    Array.isArray(promptFields.text_prompts)
                      ? promptFields.text_prompts.join(", ")
                      : ""
                  }
                  onChange={(event) =>
                    updateField(
                      "text_prompts",
                      event.target.value
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                    )
                  }
                  placeholder="coral polyp, branch tip, lesion"
                />
              </label>
              <label>
                Detection threshold
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={Number(promptFields.confidence ?? 0.35)}
                  onChange={(event) =>
                    updateField("confidence", Number(event.target.value))
                  }
                />
              </label>
            </>
          )}

          {providerId === "sam2" && (
            <label>
              Prompt box: x_min, y_min, x_max, y_max
              <input
                value={
                  Array.isArray(promptFields.box)
                    ? promptFields.box.join(", ")
                    : ""
                }
                onChange={(event) =>
                  updateField(
                    "box",
                    event.target.value
                      .split(",")
                      .map((item) => Number(item.trim())),
                  )
                }
              />
            </label>
          )}

          {providerId === "smolvlm" && (
            <label>
              Question / instruction
              <textarea
                rows={5}
                value={String(promptFields.prompt ?? "")}
                onChange={(event) => updateField("prompt", event.target.value)}
              />
            </label>
          )}

          {providerId === "nnunet" && (
            <>
              {(
                [
                  "input_folder",
                  "output_folder",
                  "dataset",
                  "configuration",
                ] as const
              ).map((field) => (
                <label key={field}>
                  {field.replaceAll("_", " ")}
                  <input
                    value={String(promptFields[field] ?? "")}
                    onChange={(event) => updateField(field, event.target.value)}
                  />
                </label>
              ))}
            </>
          )}

          <details>
            <summary>Advanced: raw prompt fields</summary>
            <textarea
              rows={10}
              value={rawJson}
              spellCheck={false}
              onChange={(event) => {
                setRawJson(event.target.value);
                try {
                  const parsed = JSON.parse(event.target.value) as Record<
                    string,
                    unknown
                  >;
                  setPromptFields(parsed);
                } catch {
                  // Keep editing; preflight/execution uses the last valid object.
                }
              }}
            />
          </details>
        </div>

        <div className="panel-card">
          <h4>3. Preflight and run</h4>
          <div className="button-row">
            <button
              type="button"
              className="secondary"
              onClick={() => preflightMutation.mutate()}
              disabled={!providerId || !task || preflightMutation.isPending}
            >
              {preflightMutation.isPending ? "Checking…" : "Run preflight"}
            </button>
            <button
              type="button"
              onClick={() => executeMutation.mutate()}
              disabled={
                selectedManifest?.execution_surface !== "provider_lab" ||
                !managedModelReady ||
                !providerId ||
                !task ||
                executeMutation.isPending
              }
            >
              {executeMutation.isPending ? "Running…" : "Run provider"}
            </button>
          </div>
          {preflightMutation.data && (
            <div className="provider-result-summary">
              <p>
                Preflight:{" "}
                <strong>
                  {preflightMutation.data.ready ? "Ready" : "Blocked"}
                </strong>
              </p>
              {preflightMutation.data.blockers.length > 0 && (
                <ul>
                  {preflightMutation.data.blockers.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {(preflightMutation.error ?? executeMutation.error) && (
            <p className="form-error">
              {(preflightMutation.error ?? executeMutation.error)?.message}
            </p>
          )}
        </div>

        <div className="panel-card">
          <h4>Result</h4>
          {executeMutation.data ? (
            <>
              <p>
                <strong>{executeMutation.data.provider_id}</strong> ·{" "}
                {executeMutation.data.task}
              </p>
              {executeMutation.data.warnings.map((warning) => (
                <p className="annotation-helper" key={warning}>
                  {warning}
                </p>
              ))}
              {Array.isArray(executeMutation.data.result.proposal_ids) && (
                <div className="provider-result-summary">
                  <p>
                    <strong>
                      {executeMutation.data.result.proposal_ids.length}{" "}
                      reviewable{" "}
                      {executeMutation.data.result.proposal_ids.length === 1
                        ? "proposal"
                        : "proposals"}{" "}
                      saved
                    </strong>
                  </p>
                  <p className="annotation-helper">
                    Open the image in the annotation editor to inspect, edit,
                    accept, or reject the pending AI result. Nothing is verified
                    automatically.
                  </p>
                </div>
              )}
              <details>
                <summary>Technical result JSON</summary>
                <pre className="provider-result-json">
                  {JSON.stringify(executeMutation.data.result, null, 2)}
                </pre>
              </details>
            </>
          ) : (
            <p className="muted-copy">
              Provider outputs appear here. Model results remain
              proposals/advisory until you explicitly review and accept them in
              the scientific workflow.
            </p>
          )}
        </div>

        {selectedManifest && (
          <div className="panel-card">
            <h4>Provider details</h4>
            <p>
              Required packages:{" "}
              {selectedManifest.required_packages.join(", ") || "none"}
            </p>
            <h5>Known limitations</h5>
            <ul>
              {selectedManifest.known_limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
