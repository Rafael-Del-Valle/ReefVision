import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  cancelAdvancedProviderJob,
  createDepthAnythingJob,
  getAdvancedProviderImages,
  getAdvancedProviderJob,
  getAdvancedProviderManifests,
  getAdvancedProviderModels,
  preflightAdvancedProvider,
  registerAdvancedProviderBundle,
} from "./advancedProvidersApi";

interface AdvancedProviderWorkspaceProps {
  project: Project;
}

const MANAGED_BUNDLE_PROVIDERS = new Set(["sam2", "depth_anything_v2"]);

export function AdvancedProviderWorkspace({
  project,
}: AdvancedProviderWorkspaceProps) {
  const queryClient = useQueryClient();
  const [providerId, setProviderId] = useState("");
  const [task, setTask] = useState("");
  const [device, setDevice] = useState("auto");
  const [modelId, setModelId] = useState("");
  const [promptJson, setPromptJson] = useState("{}");
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [bundleName, setBundleName] = useState("");
  const [selectedImageIds, setSelectedImageIds] = useState<string[]>([]);
  const [depthJobId, setDepthJobId] = useState("");

  const manifestsQuery = useQuery({
    queryKey: ["advanced-provider-manifests"],
    queryFn: ({ signal }) => getAdvancedProviderManifests(signal),
  });
  const modelsQuery = useQuery({
    queryKey: ["advanced-provider-models", project.id],
    queryFn: ({ signal }) => getAdvancedProviderModels(project.id, signal),
  });
  const imagesQuery = useQuery({
    queryKey: ["advanced-provider-images", project.id],
    queryFn: ({ signal }) => getAdvancedProviderImages(project.id, signal),
  });
  const selectedManifest = useMemo(
    () => manifestsQuery.data?.find((item) => item.provider_id === providerId),
    [manifestsQuery.data, providerId],
  );
  const eligibleModels = useMemo(
    () =>
      (modelsQuery.data ?? []).filter(
        (model) => model.provider_name === providerId,
      ),
    [modelsQuery.data, providerId],
  );
  const selectedModel = eligibleModels.find((model) => model.id === modelId);

  useEffect(() => {
    if (!providerId && manifestsQuery.data?.[0]) {
      setProviderId(manifestsQuery.data[0].provider_id);
    }
  }, [manifestsQuery.data, providerId]);

  useEffect(() => {
    const firstTask = selectedManifest?.supported_tasks[0] ?? "";
    const resolvedTask = selectedManifest?.supported_tasks.includes(task)
      ? task
      : firstTask;
    if (resolvedTask !== task) setTask(resolvedTask);
  }, [selectedManifest, task]);

  useEffect(() => {
    if (eligibleModels.some((model) => model.id === modelId)) return;
    setModelId(eligibleModels[0]?.id ?? "");
  }, [eligibleModels, modelId]);

  useEffect(() => {
    if (selectedImageIds.length || !imagesQuery.data?.[0]) return;
    setSelectedImageIds([imagesQuery.data[0].id]);
  }, [imagesQuery.data, selectedImageIds.length]);

  useEffect(() => {
    const fields = task
      ? selectedManifest?.prompt_fields_by_task[task] ?? []
      : [];
    const firstImageId = selectedImageIds[0] ?? "select-image";
    const example = Object.fromEntries(
      fields.map((field) => {
        if (field === "image_id") return [field, firstImageId];
        if (field === "prompt_type") return [field, "box"];
        return [
          field,
          field.endsWith("_id") ? "select-in-workflow" : "required",
        ];
      }),
    );
    setPromptJson(JSON.stringify(example, null, 2));
  }, [selectedImageIds, selectedManifest, task]);

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!bundleFile) throw new Error("Choose a local provider ZIP bundle first.");
      if (providerId !== "sam2" && providerId !== "depth_anything_v2") {
        throw new Error("This provider does not use the managed bundle importer.");
      }
      return registerAdvancedProviderBundle(
        project.id,
        providerId,
        bundleFile,
        bundleName || undefined,
      );
    },
    onSuccess: async (model) => {
      setModelId(model.id);
      setBundleFile(null);
      setBundleName("");
      await queryClient.invalidateQueries({
        queryKey: ["advanced-provider-models", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["model_hub_bootstrap", project.id],
      });
    },
  });

  const preflightMutation = useMutation({
    mutationFn: () => {
      const promptFields = JSON.parse(promptJson) as Record<string, unknown>;
      return preflightAdvancedProvider(project.id, providerId, {
        task,
        device,
        model_id: modelId || null,
        prompt_fields: promptFields,
      });
    },
  });

  const depthMutation = useMutation({
    mutationFn: () => {
      if (!modelId || selectedImageIds.length === 0) {
        throw new Error("Select a registered model and at least one image.");
      }
      return createDepthAnythingJob(project.id, {
        model_id: modelId,
        image_ids: selectedImageIds,
        device,
      });
    },
    onSuccess: (job) => setDepthJobId(job.id),
  });
  const depthJobQuery = useQuery({
    queryKey: ["advanced-depth-job", depthJobId],
    queryFn: ({ signal }) => getAdvancedProviderJob(depthJobId, signal),
    enabled: Boolean(depthJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && !["queued", "running", "cancel_requested"].includes(status)
        ? false
        : 750;
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelAdvancedProviderJob(depthJobId),
    onSuccess: () => void depthJobQuery.refetch(),
  });

  const depthJob = depthJobQuery.data;
  const depthOutputs = Array.isArray(depthJob?.result_json.outputs)
    ? depthJob.result_json.outputs
    : [];
  const depthActive = Boolean(
    depthJob && ["queued", "running", "cancel_requested"].includes(depthJob.status),
  );

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 8</p>
          <h3>Advanced Provider Lab</h3>
          <p>
            Inspect optional model adapters, register local model bundles, run
            fail-closed preflight checks, and execute supported providers without
            automatic checkpoint downloads.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>Provider manifest</h4>
          <label>
            Provider
            <select
              value={providerId}
              onChange={(event) => {
                setProviderId(event.target.value);
                setDepthJobId("");
              }}
            >
              {manifestsQuery.data?.map((manifest) => (
                <option key={manifest.provider_id} value={manifest.provider_id}>
                  {manifest.display_name} · {manifest.maturity}
                </option>
              ))}
            </select>
          </label>
          {selectedManifest && (
            <>
              <p>
                Execution:{" "}
                <strong>
                  {selectedManifest.execution_supported ? "implemented" : "blocked"}
                </strong>
              </p>
              <p>Tasks: {selectedManifest.supported_tasks.join(", ")}</p>
              <p>
                Model files: {selectedManifest.required_model_extensions.join(", ")}
              </p>
              <h5>Packages</h5>
              <ul>
                {selectedManifest.required_packages.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h5>Known limitations</h5>
              <ul>
                {selectedManifest.known_limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h5>Integration notes</h5>
              <ul>
                {selectedManifest.integration_notes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>

        {MANAGED_BUNDLE_PROVIDERS.has(providerId) && (
          <form
            className="panel-card"
            onSubmit={(event) => {
              event.preventDefault();
              uploadMutation.mutate();
            }}
          >
            <h4>Register local model bundle</h4>
            <p>
              Upload a self-contained Transformers-style ZIP bundle. ReefVision
              validates the archive and keeps model loading local-only.
            </p>
            <label>
              Display name
              <input
                value={bundleName}
                onChange={(event) => setBundleName(event.target.value)}
                placeholder="Optional friendly name"
              />
            </label>
            <label>
              ZIP bundle
              <input
                type="file"
                accept=".zip"
                onChange={(event) => setBundleFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button type="submit" disabled={!bundleFile || uploadMutation.isPending}>
              {uploadMutation.isPending ? "Registering..." : "Register bundle"}
            </button>
            {uploadMutation.error && (
              <p className="form-error">{uploadMutation.error.message}</p>
            )}
          </form>
        )}

        <form
          className="panel-card"
          onSubmit={(event) => {
            event.preventDefault();
            preflightMutation.mutate();
          }}
        >
          <h4>Execution preflight</h4>
          <label>
            Task
            <select value={task} onChange={(event) => setTask(event.target.value)}>
              {selectedManifest?.supported_tasks.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Registered model
            <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
              <option value="">Select a model</option>
              {eligibleModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.display_name} · {model.sha256.slice(0, 10)}
                </option>
              ))}
            </select>
          </label>
          {selectedModel && (
            <small>
              {selectedModel.framework} · {selectedModel.task} · provider {selectedModel.provider_version}
            </small>
          )}
          <label>
            Device
            <select value={device} onChange={(event) => setDevice(event.target.value)}>
              <option value="auto">Auto</option>
              <option value="cuda">CUDA</option>
              <option value="cpu">CPU</option>
            </select>
          </label>
          <label>
            Prompt fields JSON
            <textarea
              rows={8}
              value={promptJson}
              onChange={(event) => setPromptJson(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={!providerId || !task || preflightMutation.isPending}
          >
            {preflightMutation.isPending ? "Checking..." : "Run preflight"}
          </button>
          {preflightMutation.error && (
            <p className="form-error">{preflightMutation.error.message}</p>
          )}
        </form>

        <div className="panel-card">
          <h4>Source images</h4>
          {imagesQuery.data?.length ? (
            <div className="annotation-selection-list">
              {imagesQuery.data.map((image) => (
                <label key={image.id} className="annotation-selection-row">
                  <input
                    type="checkbox"
                    checked={selectedImageIds.includes(image.id)}
                    onChange={(event) =>
                      setSelectedImageIds((current) =>
                        event.target.checked
                          ? [...current, image.id]
                          : current.filter((item) => item !== image.id),
                      )
                    }
                  />
                  <span>
                    {image.original_filename} · {image.width_px}×{image.height_px}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p>Import project images before running an image provider.</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Preflight result</h4>
          {preflightMutation.data ? (
            <>
              <p>
                Ready: <strong>{preflightMutation.data.ready ? "Yes" : "No"}</strong>
              </p>
              <p>Availability: {preflightMutation.data.availability_status}</p>
              <p>Outputs: {preflightMutation.data.output_contract.join(", ")}</p>
              <h5>Blockers</h5>
              {preflightMutation.data.blockers.length ? (
                <ul>
                  {preflightMutation.data.blockers.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>None.</p>
              )}
              <h5>Warnings</h5>
              {preflightMutation.data.warnings.length ? (
                <ul>
                  {preflightMutation.data.warnings.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>None.</p>
              )}
              {providerId === "sam2" && preflightMutation.data.ready && (
                <p>
                  SAM2 is ready. Select this assist model in the annotation workspace
                  to use box, click, or Smart Mask prompts and persist the accepted mask.
                </p>
              )}
            </>
          ) : (
            <p>Run preflight to inspect prompts, assets, packages, and execution blockers.</p>
          )}
        </div>

        {providerId === "depth_anything_v2" && (
          <div className="panel-card">
            <h4>Depth Anything V2 execution</h4>
            <p>
              Generates relative-depth float arrays and 16-bit previews. Values are
              model estimates and are not metric distance.
            </p>
            <button
              type="button"
              onClick={() => depthMutation.mutate()}
              disabled={
                depthMutation.isPending ||
                depthActive ||
                !preflightMutation.data?.ready ||
                !modelId ||
                selectedImageIds.length === 0
              }
            >
              {depthMutation.isPending ? "Queueing..." : "Run selected images"}
            </button>
            {depthActive && (
              <button
                type="button"
                className="secondary"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
              >
                Cancel depth job
              </button>
            )}
            {depthMutation.error && <p className="form-error">{depthMutation.error.message}</p>}
            {depthJob && (
              <>
                <p>
                  Status: <strong>{depthJob.status}</strong> · {depthJob.progress_current}/
                  {depthJob.progress_total}
                </p>
                <progress
                  value={depthJob.progress_current}
                  max={Math.max(1, depthJob.progress_total)}
                />
                {depthJob.error_message && (
                  <p className="form-error">{depthJob.error_message}</p>
                )}
                {depthOutputs.length > 0 && (
                  <p>{depthOutputs.length} depth artifact set(s) recorded with provenance.</p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
