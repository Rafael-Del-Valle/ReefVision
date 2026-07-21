import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getAnnotationSession,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { getImages, getJob, type ImageListItem } from "../phase456/api";
import {
  depthContentUrl,
  depthPreviewUrl,
  getDepthProviderReadiness,
  listDepthMaps,
  measureMaskDepth,
  queueDepthMap,
} from "./api";
import { listProviderModels, type ProviderModelAsset } from "../providers/api";

interface MaskSummary {
  id: string;
  geometry_kind: string;
  label_class_id: string;
  area_pixels: number | null;
}

type DepthAnnotationSession = AnnotationSession & {
  mask_annotations?: MaskSummary[];
};

export function DepthDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [imageId, setImageId] = useState("");
  const [providerId, setProviderId] = useState("depth_anything_v2_relative");
  const [modelId, setModelId] = useState(
    "depth-anything/Depth-Anything-V2-Small-hf",
  );
  const [device, setDevice] = useState("auto");
  const localOnly = true;
  const [registeredDepthAssetId, setRegisteredDepthAssetId] = useState("");
  const [maximumDepth, setMaximumDepth] = useState(20);
  const [useIntrinsics, setUseIntrinsics] = useState(false);
  const [fx, setFx] = useState(1000);
  const [fy, setFy] = useState(1000);
  const [cx, setCx] = useState(0);
  const [cy, setCy] = useState(0);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [selectedDepthMapId, setSelectedDepthMapId] = useState("");
  const [selectedMaskId, setSelectedMaskId] = useState("");
  const [previewRevision, setPreviewRevision] = useState(0);
  const [previewState, setPreviewState] = useState<
    "idle" | "loading" | "loaded" | "error"
  >("idle");

  const usesFixture = providerId === "luminance_relative";
  const providerModels = useQuery({
    queryKey: ["provider-models"],
    queryFn: ({ signal }) => listProviderModels(signal),
  });
  const registeredDepthAssets = useMemo(
    () =>
      (providerModels.data?.items ?? []).filter(
        (asset: ProviderModelAsset) =>
          asset.task === "depth" &&
          ["ready", "loaded", "unloaded"].includes(asset.state) &&
          asset.verification.verified === true,
      ),
    [providerModels.data?.items],
  );
  const registeredDepthAsset =
    registeredDepthAssets.find(
      (asset) => asset.id === registeredDepthAssetId,
    ) ?? null;
  const providerReadiness = useQuery({
    queryKey: [
      "depth-provider-readiness",
      providerId,
      modelId,
      device,
      localOnly,
    ],
    queryFn: () =>
      getDepthProviderReadiness({
        providerId,
        modelId: modelId.trim(),
        device,
        localFilesOnly: localOnly,
      }),
    enabled: modelId.trim().length > 0,
    staleTime: 10_000,
    retry: false,
  });
  const images = useQuery({
    queryKey: ["depth_images", project.id],
    queryFn: ({ signal }) => getImages(project.id, signal),
  });
  const session = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    enabled: imageId.length > 0,
  });
  const depthMaps = useQuery({
    queryKey: ["depth_maps", imageId],
    queryFn: ({ signal }) => listDepthMaps(imageId, signal),
    enabled: imageId.length > 0,
  });
  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId as string, signal),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "cancelled"].includes(status)
        ? false
        : 1000;
    },
  });
  const masks = useMemo(
    () =>
      (
        (session.data as DepthAnnotationSession | undefined)
          ?.mask_annotations ?? []
      ).filter((mask) =>
        ["polygon", "raster_mask"].includes(mask.geometry_kind),
      ),
    [session.data],
  );
  const providerReady = providerReadiness.data?.ready === true;
  const generationBlockedReason =
    providerReadiness.isSuccess && !providerReady
      ? (providerReadiness.data.reason ??
        "The selected depth model is not ready.")
      : null;
  const providerCheckPending = providerReadiness.isPending;
  const providerCheckFailed = providerReadiness.isError;
  const selectedDepthMap =
    depthMaps.data?.find((item) => item.id === selectedDepthMapId) ?? null;

  useEffect(() => {
    if (
      registeredDepthAssetId === "manual" ||
      registeredDepthAssets.some((asset) => asset.id === registeredDepthAssetId)
    ) {
      return;
    }
    const preferred =
      registeredDepthAssets.find(
        (asset) => asset.model_id === "external/depth-anything-v2/small",
      ) ?? registeredDepthAssets[0];
    if (!preferred) return;
    setRegisteredDepthAssetId(preferred.id);
    setProviderId("depth_anything_v2_relative");
    setModelId(preferred.checkpoint_path);
  }, [registeredDepthAssetId, registeredDepthAssets]);
  const depthMeasurement = useQuery({
    queryKey: ["depth_mask_measurement", selectedMaskId, selectedDepthMapId],
    queryFn: ({ signal }) =>
      measureMaskDepth(selectedMaskId, selectedDepthMapId, signal),
    enabled: selectedMaskId.length > 0 && selectedDepthMapId.length > 0,
  });

  useEffect(() => {
    const first = images.data?.items[0];
    if (!imageId && first) setImageId(first.id);
  }, [imageId, images.data?.items]);

  useEffect(() => {
    if (imageId && session.data) {
      setCx(session.data.image.width_px / 2);
      setCy(session.data.image.height_px / 2);
    }
    setSelectedDepthMapId("");
    setSelectedMaskId("");
    setPreviewState("idle");
    setPreviewRevision(0);
  }, [imageId, session.data]);

  useEffect(() => {
    if (!selectedDepthMapId && depthMaps.data?.length) {
      setSelectedDepthMapId(depthMaps.data[0].id);
    }
  }, [depthMaps.data, selectedDepthMapId]);

  useEffect(() => {
    if (!selectedMaskId && masks.length) setSelectedMaskId(masks[0].id);
  }, [masks, selectedMaskId]);

  useEffect(() => {
    if (activeJob.data?.status === "succeeded") {
      void queryClient.invalidateQueries({ queryKey: ["depth_maps", imageId] });
    }
  }, [activeJob.data?.status, imageId, queryClient]);

  const generation = useMutation({
    mutationFn: () => {
      if (!imageId) throw new Error("Choose an image");
      const metric = providerId === "depth_anything_v2_metric";
      return queueDepthMap(imageId, {
        provider_id: providerId,
        model_id: modelId,
        device,
        local_files_only: localOnly,
        depth_kind: metric ? "metric" : "relative",
        unit: metric ? "m" : null,
        maximum_metric_depth: metric ? maximumDepth : null,
        camera_intrinsics:
          metric && useIntrinsics
            ? { fx_px: fx, fy_px: fy, cx_px: cx, cy_px: cy }
            : null,
      });
    },
    onSuccess: (result) => {
      setActiveJobId(result.job.id);
      setSelectedDepthMapId(result.depth_map_id);
    },
  });

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Depth and scale</p>
          <h3>Depth mapping</h3>
          <span>
            Generate aligned relative or metric depth, measure masks in 3D, and
            prepare depth cues for fish tracking.
          </span>
        </div>
        <span>{depthMaps.data?.length ?? 0} depth maps</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Source image</h4>
            <label>
              Image
              <select
                value={imageId}
                onChange={(event) => setImageId(event.target.value)}
              >
                <option value="">Choose an image</option>
                {images.data?.items.map((image: ImageListItem) => (
                  <option key={image.id} value={image.id}>
                    {image.original_filename}
                  </option>
                ))}
              </select>
            </label>
          </article>

          <article className="dashboard-card">
            <h4>Depth provider</h4>
            <label>
              Method
              <select
                value={providerId}
                onChange={(event) => {
                  const provider = event.target.value;
                  setProviderId(provider);
                  if (provider === "luminance_relative") {
                    setRegisteredDepthAssetId("manual");
                    setModelId("reefvision-luminance-fixture");
                  } else if (provider === "depth_anything_v2_metric") {
                    setRegisteredDepthAssetId("manual");
                    setModelId(
                      "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf",
                    );
                  } else {
                    const preferred =
                      registeredDepthAsset ?? registeredDepthAssets[0];
                    setRegisteredDepthAssetId(preferred?.id ?? "manual");
                    setModelId(
                      preferred?.checkpoint_path ??
                        "depth-anything/Depth-Anything-V2-Small-hf",
                    );
                  }
                }}
              >
                <option value="depth_anything_v2_relative">
                  Depth Anything V2 · relative
                </option>
                <option value="depth_anything_v2_metric">
                  Depth Anything V2 · metric checkpoint
                </option>
                <option value="luminance_relative">
                  Workflow test fixture · not scientific
                </option>
              </select>
            </label>
            {registeredDepthAssets.length > 0 && (
              <label>
                Verified registered checkpoint
                <select
                  value={registeredDepthAssetId}
                  onChange={(event) => {
                    const value = event.target.value;
                    setRegisteredDepthAssetId(value);
                    const asset = registeredDepthAssets.find(
                      (candidate) => candidate.id === value,
                    );
                    if (asset) {
                      setProviderId("depth_anything_v2_relative");
                      setModelId(asset.checkpoint_path);
                    }
                  }}
                >
                  <option value="manual">Manual local path</option>
                  {registeredDepthAssets.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.model_id} ·{" "}
                      {asset.latest_acceptance_status ?? asset.state}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Model ID or local path
              <input
                value={modelId}
                onChange={(event) => {
                  setRegisteredDepthAssetId("manual");
                  setModelId(event.target.value);
                }}
              />
            </label>
            <label>
              Device
              <select
                value={device}
                onChange={(event) => setDevice(event.target.value)}
              >
                <option value="auto">Auto</option>
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA</option>
              </select>
            </label>
            <label className="toggle-row">
              <input type="checkbox" checked disabled readOnly />
              Use installed/local checkpoints only
            </label>
            <p className="annotation-helper">
              Depth inference never downloads weights. Install or register a
              checkpoint explicitly, then verify it before generation.
            </p>
            {providerId === "depth_anything_v2_metric" && (
              <label>
                Maximum metric depth: {maximumDepth} m
                <input
                  type="range"
                  min="1"
                  max="100"
                  value={maximumDepth}
                  onChange={(event) =>
                    setMaximumDepth(Number(event.target.value))
                  }
                />
              </label>
            )}
            <button
              type="button"
              disabled={
                !imageId ||
                generation.isPending ||
                providerCheckPending ||
                providerCheckFailed ||
                Boolean(generationBlockedReason)
              }
              onClick={() => generation.mutate()}
            >
              {generation.isPending
                ? "Queueing..."
                : "Generate aligned depth map"}
            </button>
            {generationBlockedReason && (
              <p className="form-warning">{generationBlockedReason}</p>
            )}
            {providerCheckPending && (
              <p className="annotation-helper" role="status">
                Checking Depth Anything dependencies and devices...
              </p>
            )}
            {providerCheckFailed && (
              <div className="form-error" role="alert">
                <p>
                  Provider readiness could not be checked:{" "}
                  {providerReadiness.error.message}
                </p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void providerReadiness.refetch()}
                >
                  Retry provider check
                </button>
              </div>
            )}
            {usesFixture && (
              <p className="form-warning">
                The luminance fixture is non-scientific and only verifies the
                workflow.
              </p>
            )}
            {generation.error && (
              <p className="form-error">{generation.error.message}</p>
            )}
            {activeJob.data && (
              <div>
                <p>
                  Job: {activeJob.data.status} ·{" "}
                  {activeJob.data.progress_current}/
                  {activeJob.data.progress_total}
                </p>
                {activeJob.data.error_message && (
                  <p className="form-error">{activeJob.data.error_message}</p>
                )}
                {activeJob.data.status === "failed" &&
                  activeJob.data.result_json && (
                    <pre>
                      {JSON.stringify(activeJob.data.result_json, null, 2)}
                    </pre>
                  )}
              </div>
            )}
          </article>

          {providerId === "depth_anything_v2_metric" && (
            <article className="dashboard-card">
              <h4>Camera intrinsics</h4>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={useIntrinsics}
                  onChange={(event) => setUseIntrinsics(event.target.checked)}
                />
                Enable physical width, height, area, and 3D coordinates
              </label>
              {useIntrinsics && (
                <div className="version-form-row">
                  <label>
                    fx
                    <input
                      type="number"
                      value={fx}
                      onChange={(event) => setFx(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    fy
                    <input
                      type="number"
                      value={fy}
                      onChange={(event) => setFy(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    cx
                    <input
                      type="number"
                      value={cx}
                      onChange={(event) => setCx(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    cy
                    <input
                      type="number"
                      value={cy}
                      onChange={(event) => setCy(Number(event.target.value))}
                    />
                  </label>
                </div>
              )}
            </article>
          )}
        </div>

        <div className="dashboard-main">
          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Aligned output</p>
                <h4>Depth map preview</h4>
              </div>
            </div>
            <label>
              Depth map
              <select
                value={selectedDepthMapId}
                onChange={(event) => {
                  setSelectedDepthMapId(event.target.value);
                  setPreviewRevision(0);
                  setPreviewState(event.target.value ? "loading" : "idle");
                }}
              >
                <option value="">Choose a map</option>
                {depthMaps.data?.map((depthMap) => (
                  <option key={depthMap.id} value={depthMap.id}>
                    {depthMap.depth_kind} · {depthMap.provider_id} ·{" "}
                    {depthMap.model_id}
                  </option>
                ))}
              </select>
            </label>
            {selectedDepthMap ? (
              <>
                {previewState === "loading" && <p>Loading depth preview...</p>}
                {previewState === "error" && (
                  <div className="form-error" role="alert">
                    <p>
                      Preview failed to load from{" "}
                      {depthPreviewUrl(selectedDepthMap.id)}.
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setPreviewRevision((current) => current + 1);
                        setPreviewState("loading");
                      }}
                    >
                      Retry preview
                    </button>
                  </div>
                )}
                <img
                  key={`${selectedDepthMap.id}:${previewRevision}`}
                  src={`${depthPreviewUrl(selectedDepthMap.id)}?revision=${previewRevision}`}
                  alt="Depth map preview"
                  onLoad={() => setPreviewState("loaded")}
                  onError={() => setPreviewState("error")}
                  style={{
                    display: previewState === "error" ? "none" : "block",
                    width: "100%",
                    maxHeight: "520px",
                    objectFit: "contain",
                  }}
                />
                <div className="version-preview-metrics">
                  <span>Kind: {selectedDepthMap.depth_kind}</span>
                  <span>
                    Median: {selectedDepthMap.median_depth.toFixed(4)}
                  </span>
                  <span>
                    Valid pixels: {selectedDepthMap.valid_pixel_count}
                  </span>
                </div>
                <p className="annotation-helper">
                  The NumPy export preserves raw model-relative values. This
                  preview is display-normalized independently and has no
                  physical unit.
                </p>
                {selectedDepthMap.depth_kind === "relative" && (
                  <p className="form-warning">
                    Relative depth is not centimeters, meters, or physical coral
                    height without independent calibration.
                  </p>
                )}
                <a href={depthContentUrl(selectedDepthMap.id)}>
                  Download NumPy depth array
                </a>
              </>
            ) : (
              <p>No depth map has been generated for this image.</p>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Depth-aware measurement</p>
                <h4>Selected mask</h4>
              </div>
            </div>
            <label>
              Mask
              <select
                value={selectedMaskId}
                onChange={(event) => setSelectedMaskId(event.target.value)}
              >
                <option value="">Choose a polygon or raster mask</option>
                {masks.map((mask) => (
                  <option key={mask.id} value={mask.id}>
                    {mask.geometry_kind} · {mask.area_pixels ?? 0}px² ·{" "}
                    {mask.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            {depthMeasurement.isPending && selectedMaskId && (
              <p>Calculating...</p>
            )}
            {depthMeasurement.error && (
              <p className="form-error">{depthMeasurement.error.message}</p>
            )}
            {depthMeasurement.data && (
              <>
                <div className="version-preview-metrics">
                  <span>
                    Median depth:{" "}
                    {depthMeasurement.data.depth.median?.toFixed(4)}
                  </span>
                  <span>
                    Metric area:{" "}
                    {depthMeasurement.data.metric_area?.toFixed(6) ??
                      "Unavailable"}
                  </span>
                  <span>
                    Metric width:{" "}
                    {depthMeasurement.data.metric_width?.toFixed(4) ??
                      "Unavailable"}
                  </span>
                  <span>
                    Metric height:{" "}
                    {depthMeasurement.data.metric_height?.toFixed(4) ??
                      "Unavailable"}
                  </span>
                </div>
                <p>Method: {depthMeasurement.data.method}</p>
                {depthMeasurement.data.warnings.map((warning) => (
                  <p key={warning} className="annotation-helper">
                    {warning}
                  </p>
                ))}
              </>
            )}
          </article>

          <article className="dashboard-card">
            <h4>How depth is used</h4>
            <p>
              Relative depth can improve foreground/background reasoning,
              occlusion recovery, and track association. Metric depth plus
              camera intrinsics can produce 3D positions, distance, speed, and
              approximate projected size.
            </p>
            <p>
              Standard Ultralytics checkpoints remain RGB models. A separate
              RGB-D training path is required before depth becomes an actual
              model input.
            </p>
          </article>
        </div>
      </div>
    </section>
  );
}
