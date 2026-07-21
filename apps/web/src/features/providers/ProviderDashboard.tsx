import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { getImages, type Project } from "../../api/client";
import {
  cancelProviderRequest,
  diagnoseProviderModel,
  discoverProviderModels,
  healthCheckProviderModel,
  inferProviderModel,
  listProviderAcceptance,
  listProviderModels,
  loadProviderModel,
  unloadProviderModel,
  verifyProviderModel,
  type ProviderLifecycleAction,
  type ProviderLifecycleState,
  type ProviderModelAsset,
} from "./api";

type DeviceMode = "auto" | "cpu" | "cuda";
type LifecycleAction = "verify" | "diagnose" | "load" | "health" | "unload";

function bytesLabel(value: number | null | undefined): string {
  if (value == null) return "Unknown";
  if (value >= 1_073_741_824)
    return `${(value / 1_073_741_824).toFixed(2)} GiB`;
  if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MiB`;
  return `${value.toLocaleString()} B`;
}

function stateLabel(state: ProviderLifecycleState): string {
  return state.replaceAll("_", " ");
}

function capability(asset: ProviderModelAsset | null, name: string): boolean {
  return asset?.capabilities[name] === true;
}

function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `provider-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function ProviderDashboard({ project }: { project?: Project }) {
  const queryClient = useQueryClient();
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [device, setDevice] = useState<DeviceMode>("auto");
  const [healthKind, setHealthKind] = useState<"metadata" | "load">("metadata");
  const [selectedImageId, setSelectedImageId] = useState("");
  const [textPrompts, setTextPrompts] = useState("coral polyp");
  const [usePositivePoint, setUsePositivePoint] = useState(false);
  const [positivePoint, setPositivePoint] = useState({ x: 10, y: 10 });
  const [useNegativePoint, setUseNegativePoint] = useState(false);
  const [negativePoint, setNegativePoint] = useState({ x: 1, y: 1 });
  const [useBox, setUseBox] = useState(false);
  const [box, setBox] = useState({ x_min: 1, y_min: 1, x_max: 40, y_max: 40 });
  const [inferenceResult, setInferenceResult] = useState<{
    outputCount: number;
    empty: boolean;
    device: string;
    warnings: string[];
  } | null>(null);
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const requestEpoch = useRef(0);
  const previousAssetId = useRef<string | null>(null);

  const models = useQuery({
    queryKey: ["provider-models"],
    queryFn: ({ signal }) => listProviderModels(signal),
    refetchInterval: 30_000,
  });
  const assets = models.data?.items ?? [];
  const selectedAsset =
    assets.find((asset) => asset.id === selectedAssetId) ?? null;

  const images = useQuery({
    queryKey: ["provider-inference-images", project?.id],
    queryFn: ({ signal }) =>
      getImages(project?.id as string, { page: 1, pageSize: 100 }, signal),
    enabled: Boolean(project?.id),
  });
  const acceptance = useQuery({
    queryKey: ["provider-acceptance", selectedAssetId],
    queryFn: ({ signal }) => listProviderAcceptance(selectedAssetId, signal),
    enabled: Boolean(selectedAssetId),
  });

  useEffect(() => {
    if (!assets.length) {
      setSelectedAssetId("");
      return;
    }
    if (!assets.some((asset) => asset.id === selectedAssetId)) {
      setSelectedAssetId(assets[0].id);
    }
  }, [assets, selectedAssetId]);

  useEffect(() => {
    const availableImages = images.data?.items ?? [];
    if (!availableImages.some((image) => image.id === selectedImageId)) {
      setSelectedImageId(availableImages[0]?.id ?? "");
    }
  }, [images.data?.items, selectedImageId]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["provider-models"] }),
      queryClient.invalidateQueries({
        queryKey: ["provider-acceptance", selectedAssetId],
      }),
    ]);
  };

  const discovery = useMutation({
    mutationFn: discoverProviderModels,
    onSuccess: refresh,
  });
  const lifecycle = useMutation<
    ProviderLifecycleAction,
    Error,
    { action: LifecycleAction; assetId: string }
  >({
    mutationFn: ({ action, assetId }) => {
      if (action === "verify") return verifyProviderModel(assetId);
      if (action === "diagnose") return diagnoseProviderModel(assetId, device);
      if (action === "load") return loadProviderModel(assetId, device);
      if (action === "unload") return unloadProviderModel(assetId);
      return healthCheckProviderModel(assetId, {
        device,
        kind: healthKind,
        keep_loaded: healthKind === "load",
      });
    },
    onSuccess: refresh,
  });
  const inference = useMutation({
    mutationFn: async ({
      asset,
      epoch,
      id,
    }: {
      asset: ProviderModelAsset;
      epoch: number;
      id: string;
    }) => {
      const parameters: Record<string, unknown> = {};
      if (capability(asset, "text_prompt")) {
        parameters.text_prompts = textPrompts
          .split(/[,\n]/)
          .map((value) => value.trim())
          .filter(Boolean);
      }
      if (capability(asset, "point_prompt") && usePositivePoint) {
        parameters.positive_points = [positivePoint];
      }
      if (capability(asset, "negative_point_prompt") && useNegativePoint) {
        parameters.negative_points = [negativePoint];
      }
      if (capability(asset, "box_prompt") && useBox) parameters.box = box;
      const result = await inferProviderModel(asset.id, {
        request_id: id,
        image_id: selectedImageId,
        device,
        parameters,
      });
      return { result, epoch };
    },
    onSuccess: ({ result, epoch }) => {
      if (epoch !== requestEpoch.current) return;
      setInferenceResult({
        outputCount: result.outputs.length,
        empty:
          Boolean(result.metadata.empty_result) || result.outputs.length === 0,
        device: result.resolved_device,
        warnings: result.warnings,
      });
      setActiveRequestId(null);
      void refresh();
    },
    onError: () => setActiveRequestId(null),
  });

  useEffect(() => {
    const prior = previousAssetId.current;
    if (prior && prior !== selectedAssetId) {
      requestEpoch.current += 1;
      if (activeRequestId) void cancelProviderRequest(activeRequestId);
      void unloadProviderModel(prior).finally(refresh);
      setInferenceResult(null);
      setActiveRequestId(null);
      if (!capability(selectedAsset, "text_prompt")) setTextPrompts("");
      if (!capability(selectedAsset, "point_prompt"))
        setUsePositivePoint(false);
      if (!capability(selectedAsset, "negative_point_prompt"))
        setUseNegativePoint(false);
      if (!capability(selectedAsset, "box_prompt")) setUseBox(false);
    }
    previousAssetId.current = selectedAssetId || null;
  }, [activeRequestId, selectedAsset, selectedAssetId]);

  const statusCounts = useMemo(
    () =>
      assets.reduce<Record<ProviderLifecycleState, number>>(
        (counts, asset) => {
          counts[asset.state] += 1;
          return counts;
        },
        {
          ready: 0,
          unavailable: 0,
          degraded: 0,
          loading: 0,
          loaded: 0,
          failed: 0,
          unloaded: 0,
        },
      ),
    [assets],
  );
  const selectedImage = images.data?.items.find(
    (image) => image.id === selectedImageId,
  );
  const promptRequired =
    capability(selectedAsset, "text_prompt") && !textPrompts.trim();
  const spatialPromptRequired =
    selectedAsset?.task === "assist_segmentation" &&
    !usePositivePoint &&
    !useBox;
  const canInfer =
    Boolean(selectedAsset?.supports_inference) &&
    Boolean(selectedImageId) &&
    !promptRequired &&
    !spatialPromptRequired &&
    !inference.isPending;

  if (models.isPending) {
    return (
      <section className="dashboard-panel">
        <div className="empty-state">
          <h3>Loading provider lifecycle</h3>
          <p>Reading checkpoint verification and runtime state.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="dashboard-panel" data-testid="provider-dashboard">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 8 provider lifecycle</p>
          <h3>Installed model providers</h3>
          <span>
            Metadata verification, real loading, inference acceptance, and GPU
            residency are reported separately.
          </span>
        </div>
        <button
          type="button"
          className="secondary"
          disabled={discovery.isPending}
          onClick={() => discovery.mutate()}
        >
          {discovery.isPending ? "Discovering..." : "Discover and verify"}
        </button>
      </div>

      <div className="version-preview-metrics">
        <span>{models.data?.total ?? 0} registered</span>
        <span>{statusCounts.ready + statusCounts.unloaded} provider-ready</span>
        <span>{statusCounts.loaded} loaded</span>
        <span>
          {statusCounts.unavailable + statusCounts.failed} unavailable/failed
        </span>
        <span>
          {models.data?.duplicate_checksum_groups.length ?? 0} duplicate
          checksum groups
        </span>
      </div>
      {models.error && <p className="form-error">{models.error.message}</p>}
      {discovery.error && (
        <p className="form-error">{discovery.error.message}</p>
      )}

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Model inventory</h4>
            <div className="project-list">
              {assets.map((asset) => (
                <button
                  key={asset.id}
                  type="button"
                  className={`project-card ${asset.id === selectedAssetId ? "selected" : ""}`}
                  aria-pressed={asset.id === selectedAssetId}
                  onClick={() => setSelectedAssetId(asset.id)}
                >
                  <strong>{asset.model_id}</strong>
                  <span>{stateLabel(asset.state)}</span>
                  <small>
                    {asset.task} · {asset.provider_id}
                  </small>
                </button>
              ))}
            </div>
          </article>
        </div>

        <div className="dashboard-main">
          {selectedAsset && (
            <>
              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">{selectedAsset.provider_id}</p>
                    <h4>{selectedAsset.architecture}</h4>
                    <p>{selectedAsset.model_id}</p>
                  </div>
                  <span className="status-chip">
                    {stateLabel(selectedAsset.state)}
                  </span>
                </div>
                <div className="version-preview-metrics">
                  <span>
                    Metadata{" "}
                    {selectedAsset.verification.verified
                      ? "verified"
                      : "unverified"}
                  </span>
                  <span>
                    Acceptance{" "}
                    {selectedAsset.latest_acceptance_status ?? "not run"}
                  </span>
                  <span>
                    {selectedAsset.checkpoint_path_kind.replace("_", " ")}
                  </span>
                  <span>{bytesLabel(selectedAsset.checkpoint_size_bytes)}</span>
                  <span>
                    Training {selectedAsset.supports_training ? "yes" : "no"}
                  </span>
                  <span>
                    Video {selectedAsset.supports_video ? "yes" : "no"}
                  </span>
                </div>
                {selectedAsset.failure_reason && (
                  <p className="form-error">{selectedAsset.failure_reason}</p>
                )}
                <p className="annotation-helper">
                  Outputs: {selectedAsset.output_types.join(", ") || "None"}.
                  Prompts: {selectedAsset.prompt_types.join(", ") || "None"}.
                </p>
                <label>
                  Device
                  <select
                    value={device}
                    onChange={(event) =>
                      setDevice(event.target.value as DeviceMode)
                    }
                  >
                    <option value="auto">Automatic</option>
                    <option value="cpu">CPU</option>
                    <option value="cuda">CUDA</option>
                  </select>
                </label>
                <div className="annotation-editor-inline-actions">
                  {(
                    [
                      "verify",
                      "diagnose",
                      "load",
                      "unload",
                    ] as LifecycleAction[]
                  ).map((action) => (
                    <button
                      key={action}
                      type="button"
                      className={action === "load" ? undefined : "secondary"}
                      disabled={lifecycle.isPending}
                      onClick={() =>
                        lifecycle.mutate({ action, assetId: selectedAsset.id })
                      }
                    >
                      {action[0].toUpperCase() + action.slice(1)}
                    </button>
                  ))}
                </div>
                <div className="annotation-editor-inline-actions">
                  <select
                    aria-label="Health check kind"
                    value={healthKind}
                    onChange={(event) =>
                      setHealthKind(event.target.value as "metadata" | "load")
                    }
                  >
                    <option value="metadata">Metadata-only health</option>
                    <option value="load">Real load health</option>
                  </select>
                  <button
                    type="button"
                    className="secondary"
                    disabled={lifecycle.isPending}
                    onClick={() =>
                      lifecycle.mutate({
                        action: "health",
                        assetId: selectedAsset.id,
                      })
                    }
                  >
                    Run health check
                  </button>
                </div>
                {lifecycle.error && (
                  <p className="form-error">{lifecycle.error.message}</p>
                )}
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Capability-driven inference</p>
                    <h4>Managed image smoke test</h4>
                  </div>
                </div>
                {!project ? (
                  <p>Select a project to run managed-image inference.</p>
                ) : (
                  <label>
                    Project image
                    <select
                      value={selectedImageId}
                      onChange={(event) =>
                        setSelectedImageId(event.target.value)
                      }
                    >
                      {(images.data?.items ?? []).map((image) => (
                        <option key={image.id} value={image.id}>
                          {image.original_filename} ({image.width_px}×
                          {image.height_px})
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {capability(selectedAsset, "text_prompt") && (
                  <label>
                    Required text classes (comma or line separated)
                    <textarea
                      value={textPrompts}
                      onChange={(event) => setTextPrompts(event.target.value)}
                    />
                  </label>
                )}
                {capability(selectedAsset, "point_prompt") && (
                  <fieldset>
                    <legend>Point and box prompts</legend>
                    <label className="toggle-row">
                      <input
                        type="checkbox"
                        checked={usePositivePoint}
                        onChange={(event) =>
                          setUsePositivePoint(event.target.checked)
                        }
                      />
                      Positive point
                    </label>
                    {usePositivePoint && (
                      <div className="annotation-editor-inline-actions">
                        <input
                          aria-label="Positive point x"
                          type="number"
                          value={positivePoint.x}
                          onChange={(event) =>
                            setPositivePoint({
                              ...positivePoint,
                              x: Number(event.target.value),
                            })
                          }
                        />
                        <input
                          aria-label="Positive point y"
                          type="number"
                          value={positivePoint.y}
                          onChange={(event) =>
                            setPositivePoint({
                              ...positivePoint,
                              y: Number(event.target.value),
                            })
                          }
                        />
                      </div>
                    )}
                    <label className="toggle-row">
                      <input
                        type="checkbox"
                        checked={useNegativePoint}
                        disabled={
                          !capability(selectedAsset, "negative_point_prompt")
                        }
                        onChange={(event) =>
                          setUseNegativePoint(event.target.checked)
                        }
                      />
                      Negative point
                    </label>
                    {useNegativePoint && (
                      <div className="annotation-editor-inline-actions">
                        <input
                          aria-label="Negative point x"
                          type="number"
                          value={negativePoint.x}
                          onChange={(event) =>
                            setNegativePoint({
                              ...negativePoint,
                              x: Number(event.target.value),
                            })
                          }
                        />
                        <input
                          aria-label="Negative point y"
                          type="number"
                          value={negativePoint.y}
                          onChange={(event) =>
                            setNegativePoint({
                              ...negativePoint,
                              y: Number(event.target.value),
                            })
                          }
                        />
                      </div>
                    )}
                    <label className="toggle-row">
                      <input
                        type="checkbox"
                        checked={useBox}
                        disabled={!capability(selectedAsset, "box_prompt")}
                        onChange={(event) => setUseBox(event.target.checked)}
                      />
                      Box prompt / mixed refinement
                    </label>
                    {useBox && (
                      <div className="annotation-editor-inline-actions">
                        {Object.entries(box).map(([key, value]) => (
                          <input
                            key={key}
                            aria-label={`Box ${key}`}
                            type="number"
                            value={value}
                            onChange={(event) =>
                              setBox({
                                ...box,
                                [key]: Number(event.target.value),
                              })
                            }
                          />
                        ))}
                      </div>
                    )}
                  </fieldset>
                )}
                {selectedAsset.task === "depth" && (
                  <p className="form-warning">
                    Depth output is relative, not meters or centimeters. Use the
                    Depth tab for source-aligned visualization and export.
                  </p>
                )}
                <div className="annotation-editor-inline-actions">
                  <button
                    type="button"
                    disabled={!canInfer}
                    onClick={() => {
                      const id = requestId();
                      const epoch = ++requestEpoch.current;
                      setActiveRequestId(id);
                      setInferenceResult(null);
                      inference.mutate({ asset: selectedAsset, epoch, id });
                    }}
                  >
                    {inference.isPending
                      ? "Running..."
                      : "Run managed inference"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!activeRequestId}
                    onClick={() => {
                      if (activeRequestId)
                        void cancelProviderRequest(activeRequestId);
                      requestEpoch.current += 1;
                      setActiveRequestId(null);
                    }}
                  >
                    Cancel request
                  </button>
                </div>
                {inference.error && (
                  <p className="form-error">{inference.error.message}</p>
                )}
                {inferenceResult && (
                  <p className="form-success">
                    {inferenceResult.empty
                      ? "Valid empty result"
                      : `${inferenceResult.outputCount} normalized proposals`}{" "}
                    · {inferenceResult.device}
                  </p>
                )}
                {selectedImage && spatialPromptRequired && (
                  <p className="annotation-helper">
                    Choose at least one supported point or box prompt.
                  </p>
                )}
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Software acceptance</p>
                    <h4>Validation records</h4>
                  </div>
                  <span>{acceptance.data?.total ?? 0} records</span>
                </div>
                {acceptance.isPending && <p>Loading validation records...</p>}
                {acceptance.error && (
                  <p className="form-error">{acceptance.error.message}</p>
                )}
                <div className="dashboard-list">
                  {acceptance.data?.items.map((record) => (
                    <details key={record.id} className="dashboard-row">
                      <summary>
                        {record.load_result}/{record.inference_result}/
                        {record.unload_result} · {record.device} ·{" "}
                        {record.execution_time_ms.toLocaleString()} ms
                      </summary>
                      <p>
                        {new Date(record.recorded_at).toLocaleString()} · peak{" "}
                        {bytesLabel(record.peak_memory_bytes)}
                      </p>
                      <small>
                        Software/runtime acceptance only; not coral scientific
                        validation.
                      </small>
                      {record.failure_reason && (
                        <p className="form-error">{record.failure_reason}</p>
                      )}
                    </details>
                  ))}
                </div>
              </article>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
