import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  completeReviewQueueItem,
  getReviewQueueItems,
  getReviewQueues,
  skipReviewQueueItem,
  startReviewQueueItem,
  type Project,
  type ReviewQueueItem,
  type ReviewQueueRecord,
} from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { listProviderModels, type ProviderModelAsset } from "../providers/api";
import { cancelJob, getJob } from "../phase456/api";

const PREPROCESSING_VERSION = "ultralytics-rgb-imgsz224-embed-v1";
const ACTIVE_FORMULA = "active_learning_diversity_v1";

interface EmbeddingGenerationResult {
  embedding_model_id: string;
  requested_image_count: number;
  job: { id: string; status: string };
}

interface EmbeddingCoverage {
  total_image_count: number;
  ready_image_count: number;
  missing_image_count: number;
  stale_image_count: number;
  failed_image_count: number;
  dimension: number | null;
  warnings: string[];
}

interface ActiveLearningCycle {
  id: string;
  cycle_index: number;
  name: string;
  status: string;
  selection_strategy: string;
  selected_count: number;
  reviewed_count: number;
  source_model_id: string | null;
  candidate_model_id: string | null;
  promoted_model_id: string | null;
  dataset_version_id: string | null;
  training_run_id: string | null;
  review_queue_id: string | null;
  embedding_provider_id: string | null;
  embedding_model_id: string | null;
  embedding_model_checksum: string | null;
  queue_revision: number | null;
  accepted_annotation_ids: string[];
  rejected_item_ids: string[];
  warnings: string[];
  baseline_metrics: Record<string, unknown>;
  candidate_metrics: Record<string, unknown>;
  history: Array<Record<string, unknown>>;
  created_at: string;
  completed_at: string | null;
}

interface PromotionResult {
  queue_id: string;
  queue_revision: number;
  dataset_version_id: string;
  cycle_id: string | null;
  promoted_at: string;
  idempotent_replay: boolean;
}

interface TrainingRunOption {
  id: string;
  run_name: string;
  status: string;
  dataset_version_id: string | null;
  metrics?: Record<string, number>;
  metrics_json?: Record<string, number>;
}

interface RegisteredModelOption {
  id: string;
  display_name: string;
  task: string;
  provider_name: string;
  metadata_json: Record<string, unknown>;
}

interface EvaluationResult {
  cycle: ActiveLearningCycle;
  all_required_gates_passed: boolean;
  promoted: boolean;
  stopped: boolean;
  stop_reasons: string[];
  comparison_compatible: boolean;
  compatibility_warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof body.detail === "string") message = body.detail;
      if (body.detail && typeof body.detail === "object") {
        message = body.detail.message ?? body.detail.reason ?? message;
      }
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function activeConfig(queue: ReviewQueueRecord): Record<string, unknown> {
  const value = queue.configuration_json.active_learning;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function queueMatchesModel(
  queue: ReviewQueueRecord,
  asset: ProviderModelAsset | null,
): boolean {
  if (!asset) return false;
  const config = activeConfig(queue);
  return (
    config.embedding_model_id === asset.model_id &&
    config.embedding_model_checksum === asset.checkpoint_sha256
  );
}

export function EmbeddingDashboard({
  project,
  onOpenImage,
  onLaunchTraining,
}: {
  project: Project;
  onOpenImage?: (item: ReviewQueueItem) => void;
  onLaunchTraining?: () => void;
}) {
  const queryClient = useQueryClient();
  const [assetId, setAssetId] = useState("");
  const [device, setDevice] = useState<"auto" | "cpu" | "cuda">("auto");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [selectionStrategy, setSelectionStrategy] = useState("k_center");
  const [maximumItems, setMaximumItems] = useState(25);
  const [uncertaintyWeight, setUncertaintyWeight] = useState(0.45);
  const [noveltyWeight, setNoveltyWeight] = useState(0.45);
  const [maximumPerGroup, setMaximumPerGroup] = useState(3);
  const [maximumPerFragment, setMaximumPerFragment] = useState(3);
  const [classBalancing, setClassBalancing] = useState(true);
  const [manualIncludes, setManualIncludes] = useState("");
  const [manualExcludes, setManualExcludes] = useState("");
  const [selectedQueueId, setSelectedQueueId] = useState("");
  const [promotionName, setPromotionName] = useState(
    "Reviewed active-learning cycle",
  );
  const [trainingRunId, setTrainingRunId] = useState("");
  const [candidateModelId, setCandidateModelId] = useState("");
  const [metricName, setMetricName] = useState("map50_95");
  const [baselineMetric, setBaselineMetric] = useState("");
  const [candidateMetric, setCandidateMetric] = useState("");
  const [metricSchemaId, setMetricSchemaId] = useState(
    "reefvision-evaluation-v1",
  );

  const providerModels = useQuery({
    queryKey: ["provider-models"],
    queryFn: ({ signal }) => listProviderModels(signal),
  });
  const embeddingAssets = useMemo(
    () =>
      (providerModels.data?.items ?? []).filter(
        (asset) =>
          asset.provider_id === "ultralytics" &&
          ["detect", "segment"].includes(asset.task) &&
          ["ready", "loaded", "unloaded"].includes(asset.state) &&
          asset.verification.verified === true,
      ),
    [providerModels.data?.items],
  );
  const selectedAsset =
    embeddingAssets.find((asset) => asset.id === assetId) ?? null;

  useEffect(() => {
    const preferred =
      embeddingAssets.find(
        (asset) => asset.model_id === "ultralytics/yolo11/detect/n",
      ) ?? embeddingAssets[0];
    if (!embeddingAssets.some((asset) => asset.id === assetId)) {
      setAssetId(preferred?.id ?? "");
    }
  }, [assetId, embeddingAssets]);

  const coverage = useQuery({
    queryKey: [
      "embedding-coverage",
      project.id,
      selectedAsset?.model_id,
      selectedAsset?.checkpoint_sha256,
    ],
    queryFn: ({ signal }) => {
      const search = new URLSearchParams({
        provider_id: "ultralytics_backbone",
        embedding_model_id: selectedAsset?.model_id ?? "",
        preprocessing_version: PREPROCESSING_VERSION,
      });
      if (selectedAsset?.checkpoint_sha256)
        search.set("embedding_model_checksum", selectedAsset.checkpoint_sha256);
      return request<EmbeddingCoverage>(
        `/projects/${project.id}/embedding-coverage?${search}`,
        { signal },
      );
    },
    enabled: Boolean(selectedAsset),
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
  const queues = useQuery({
    queryKey: ["review_queues", project.id],
    queryFn: ({ signal }) => getReviewQueues(project.id, signal),
  });
  const activeQueues = useMemo(
    () =>
      (queues.data ?? [])
        .filter((queue) => queue.formula_id === ACTIVE_FORMULA)
        .sort((left, right) => right.revision - left.revision),
    [queues.data],
  );
  const selectedQueue =
    activeQueues.find((queue) => queue.id === selectedQueueId) ?? null;
  const queueItems = useQuery({
    queryKey: [
      "review_queue_items",
      selectedQueueId,
      "active-learning-workspace",
    ],
    queryFn: ({ signal }) =>
      getReviewQueueItems(selectedQueueId, { page: 1, pageSize: 500 }, signal),
    enabled: Boolean(selectedQueueId),
  });
  const cycles = useQuery({
    queryKey: ["active-learning-cycles", project.id],
    queryFn: ({ signal }) =>
      request<{ cycles: ActiveLearningCycle[] }>(
        `/projects/${project.id}/active-learning-cycles`,
        { signal },
      ),
  });
  const selectedCycle =
    cycles.data?.cycles.find(
      (cycle) => cycle.review_queue_id === selectedQueueId,
    ) ??
    cycles.data?.cycles.find(
      (cycle) => cycle.id === selectedQueue?.promoted_cycle_id,
    ) ??
    null;
  const trainingRuns = useQuery({
    queryKey: ["training-runs", project.id, "active-learning"],
    queryFn: ({ signal }) =>
      request<TrainingRunOption[]>(`/projects/${project.id}/training-runs`, {
        signal,
      }),
    enabled: Boolean(selectedCycle?.dataset_version_id),
  });
  const registeredModels = useQuery({
    queryKey: ["models", project.id, "active-learning"],
    queryFn: ({ signal }) =>
      request<RegisteredModelOption[]>(`/projects/${project.id}/models`, {
        signal,
      }),
    enabled: Boolean(selectedCycle?.dataset_version_id),
  });
  const compatibleRuns = useMemo(
    () =>
      (trainingRuns.data ?? []).filter(
        (run) => run.dataset_version_id === selectedCycle?.dataset_version_id,
      ),
    [selectedCycle?.dataset_version_id, trainingRuns.data],
  );
  const compatibleModels = useMemo(
    () =>
      (registeredModels.data ?? []).filter(
        (model) => model.metadata_json.source_training_run_id === trainingRunId,
      ),
    [registeredModels.data, trainingRunId],
  );

  useEffect(() => {
    setSelectedQueueId((current) => {
      const currentQueue = activeQueues.find((queue) => queue.id === current);
      if (currentQueue && queueMatchesModel(currentQueue, selectedAsset))
        return current;
      return (
        activeQueues.find((queue) => queueMatchesModel(queue, selectedAsset))
          ?.id ?? ""
      );
    });
  }, [activeQueues, selectedAsset]);

  useEffect(() => {
    setActiveJobId(null);
    setSelectedQueueId("");
    setTrainingRunId("");
    setCandidateModelId("");
    setBaselineMetric("");
    setCandidateMetric("");
  }, [project.id]);

  useEffect(() => {
    if (!compatibleRuns.some((run) => run.id === trainingRunId)) {
      setTrainingRunId(compatibleRuns[0]?.id ?? "");
    }
  }, [compatibleRuns, trainingRunId]);

  useEffect(() => {
    if (
      candidateModelId &&
      !compatibleModels.some((model) => model.id === candidateModelId)
    ) {
      setCandidateModelId("");
    }
  }, [candidateModelId, compatibleModels]);

  useEffect(() => {
    if (activeJob.data?.status === "succeeded") {
      void coverage.refetch();
    }
  }, [activeJob.data?.status, coverage]);

  const refreshCycle = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["review_queues", project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["review_queue_items", selectedQueueId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["active-learning-cycles", project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["dataset_versions", project.id],
      }),
    ]);
  };

  const generation = useMutation({
    mutationFn: () => {
      if (!selectedAsset)
        throw new Error("Choose a verified local embedding model.");
      return request<EmbeddingGenerationResult>(
        `/projects/${project.id}/embedding-jobs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: "ultralytics_backbone",
            model_id: selectedAsset.model_id,
            model_checksum: selectedAsset.checkpoint_sha256,
            preprocessing_version: PREPROCESSING_VERSION,
            device,
            local_files_only: true,
            image_ids: [],
            replace_existing: false,
            batch_size: 8,
          }),
        },
      );
    },
    onSuccess: (result) => setActiveJobId(result.job.id),
  });
  const createQueue = useMutation({
    mutationFn: () => {
      if (!selectedAsset) throw new Error("Choose a verified embedding model.");
      const parseIds = (value: string) =>
        value
          .split(/[\s,]+/)
          .map((item) => item.trim())
          .filter(Boolean);
      return request<ReviewQueueRecord>(
        `/projects/${project.id}/active-learning-queues`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            max_items: maximumItems,
            selection_strategy: selectionStrategy,
            uncertainty_weight: uncertaintyWeight,
            novelty_weight: noveltyWeight,
            base_priority_weight: Math.max(
              0,
              1 - uncertaintyWeight - noveltyWeight,
            ),
            embedding_provider_id: "ultralytics_backbone",
            embedding_model_id: selectedAsset.model_id,
            embedding_model_checksum: selectedAsset.checkpoint_sha256,
            embedding_preprocessing_version: PREPROCESSING_VERSION,
            max_items_per_group: maximumPerGroup || null,
            max_items_per_fragment: maximumPerFragment || null,
            class_balancing: classBalancing,
            manual_include_image_ids: parseIds(manualIncludes),
            manual_exclude_image_ids: parseIds(manualExcludes),
            suppress_exact_duplicates: true,
            suppress_near_duplicates: true,
            create_cycle: true,
          }),
        },
      );
    },
    onSuccess: async (queue) => {
      setSelectedQueueId(queue.id);
      await refreshCycle();
    },
  });
  const itemAction = useMutation({
    mutationFn: ({
      item,
      action,
    }: {
      item: ReviewQueueItem;
      action: string;
    }) => {
      if (action === "start") return startReviewQueueItem(item.id);
      if (action === "skip")
        return skipReviewQueueItem(
          item.id,
          "Excluded from the current active-learning cycle by the reviewer.",
        );
      return completeReviewQueueItem(item.id);
    },
    onSuccess: refreshCycle,
  });
  const promotion = useMutation({
    mutationFn: () => {
      if (!selectedQueue)
        throw new Error("Choose a queue revision to promote.");
      return request<PromotionResult>(
        `/active-learning-queues/${selectedQueue.id}/promote`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: promotionName,
            split_method: "group_random",
            cycle_id:
              typeof selectedQueue.summary_json.cycle_id === "string"
                ? selectedQueue.summary_json.cycle_id
                : null,
          }),
        },
      );
    },
    onSuccess: refreshCycle,
  });
  const attachTraining = useMutation({
    mutationFn: () => {
      if (!selectedCycle || !trainingRunId) {
        throw new Error("Choose the cycle training run to record.");
      }
      return request<ActiveLearningCycle>(
        `/active-learning-cycles/${selectedCycle.id}/training`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            training_run_id: trainingRunId,
            candidate_model_id: candidateModelId || null,
          }),
        },
      );
    },
    onSuccess: async (cycle) => {
      const run = compatibleRuns.find(
        (item) => item.id === cycle.training_run_id,
      );
      const metrics = run?.metrics ?? run?.metrics_json ?? {};
      const initialMetric = metrics[metricName];
      if (typeof initialMetric === "number") {
        setCandidateMetric(String(initialMetric));
      }
      await refreshCycle();
    },
  });
  const actionCycle = attachTraining.data ?? selectedCycle;
  const evaluation = useMutation({
    mutationFn: () => {
      if (!actionCycle) throw new Error("Choose an active-learning cycle.");
      const baseline = Number(baselineMetric);
      const candidate = Number(candidateMetric);
      if (
        !metricName.trim() ||
        !Number.isFinite(baseline) ||
        !Number.isFinite(candidate)
      ) {
        throw new Error(
          "Enter a metric name and finite before-and-after values.",
        );
      }
      if (!metricSchemaId.trim()) {
        throw new Error("Enter the metric schema used by both evaluations.");
      }
      return request<EvaluationResult>(
        `/active-learning-cycles/${actionCycle.id}/evaluate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            baseline_metrics: { [metricName.trim()]: baseline },
            candidate_metrics: { [metricName.trim()]: candidate },
            candidate_model_id: candidateModelId || null,
            baseline_dataset_version_id: actionCycle.dataset_version_id,
            candidate_dataset_version_id: actionCycle.dataset_version_id,
            baseline_metric_schema_id: metricSchemaId.trim(),
            candidate_metric_schema_id: metricSchemaId.trim(),
          }),
        },
      );
    },
    onSuccess: refreshCycle,
  });

  useEffect(() => {
    generation.reset();
    createQueue.reset();
    itemAction.reset();
    promotion.reset();
    attachTraining.reset();
    evaluation.reset();
  }, [project.id]);

  const reviewedCount =
    queueItems.data?.items.filter((item) =>
      ["completed", "skipped"].includes(item.review_state),
    ).length ?? 0;
  const unfinishedCount = (queueItems.data?.total ?? 0) - reviewedCount;
  const coverageReady =
    coverage.data &&
    coverage.data.missing_image_count === 0 &&
    coverage.data.stale_image_count === 0 &&
    coverage.data.failed_image_count === 0;

  return (
    <section
      className="dashboard-panel"
      data-testid="active-learning-workspace"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 7 active-learning cycle</p>
          <h3>Embed, select, review, promote, retrain</h3>
          <span>
            Local model features and immutable queue revisions preserve every
            selection and dataset decision across restarts.
          </span>
        </div>
        <span>{cycles.data?.cycles.length ?? 0} recorded cycles</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>1. Automatic embeddings</h4>
            <label>
              Verified local backbone
              <select
                value={assetId}
                onChange={(event) => setAssetId(event.target.value)}
              >
                {embeddingAssets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.model_id} ·{" "}
                    {asset.latest_acceptance_status ?? asset.state}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Device
              <select
                value={device}
                onChange={(event) =>
                  setDevice(event.target.value as "auto" | "cpu" | "cuda")
                }
              >
                <option value="auto">Automatic</option>
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA</option>
              </select>
            </label>
            <button
              type="button"
              disabled={generation.isPending || !selectedAsset}
              onClick={() => generation.mutate()}
            >
              {generation.isPending
                ? "Queueing..."
                : "Generate missing embeddings"}
            </button>
            {activeJob.data && (
              <div>
                <p>
                  {activeJob.data.status} · {activeJob.data.progress_current}/
                  {activeJob.data.progress_total}
                </p>
                {!["succeeded", "failed", "cancelled"].includes(
                  activeJob.data.status,
                ) && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => activeJobId && cancelJob(activeJobId)}
                  >
                    Cancel embedding job
                  </button>
                )}
              </div>
            )}
            {generation.error && (
              <p className="form-error">{generation.error.message}</p>
            )}
          </article>

          <article className="dashboard-card">
            <h4>2. Queue controls</h4>
            <label>
              Strategy
              <select
                value={selectionStrategy}
                onChange={(event) => setSelectionStrategy(event.target.value)}
              >
                <option value="k_center">Cosine novelty / k-center</option>
                <option value="entropy">Entropy uncertainty</option>
                <option value="margin">Confidence margin</option>
                <option value="least_confidence">Least confidence</option>
                <option value="cluster_balanced">Cluster balanced</option>
                <option value="density_aware">Density aware</option>
              </select>
            </label>
            <label>
              Maximum images
              <input
                type="number"
                min="1"
                max="500"
                value={maximumItems}
                onChange={(event) =>
                  setMaximumItems(Number(event.target.value))
                }
              />
            </label>
            <label>
              Uncertainty weight: {uncertaintyWeight.toFixed(2)}
              <input
                type="range"
                min="0"
                max="0.9"
                step="0.05"
                value={uncertaintyWeight}
                onChange={(event) =>
                  setUncertaintyWeight(Number(event.target.value))
                }
              />
            </label>
            <label>
              Novelty weight: {noveltyWeight.toFixed(2)}
              <input
                type="range"
                min="0"
                max="0.9"
                step="0.05"
                value={noveltyWeight}
                onChange={(event) =>
                  setNoveltyWeight(Number(event.target.value))
                }
              />
            </label>
            <label>
              Maximum per group
              <input
                type="number"
                min="0"
                value={maximumPerGroup}
                onChange={(event) =>
                  setMaximumPerGroup(Number(event.target.value))
                }
              />
            </label>
            <label>
              Maximum per fragment
              <input
                type="number"
                min="0"
                value={maximumPerFragment}
                onChange={(event) =>
                  setMaximumPerFragment(Number(event.target.value))
                }
              />
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={classBalancing}
                onChange={(event) => setClassBalancing(event.target.checked)}
              />
              Balance rare and missing classes
            </label>
            <label>
              Manual include image UUIDs
              <textarea
                value={manualIncludes}
                onChange={(event) => setManualIncludes(event.target.value)}
              />
            </label>
            <label>
              Manual exclude image UUIDs
              <textarea
                value={manualExcludes}
                onChange={(event) => setManualExcludes(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={createQueue.isPending || !coverageReady}
              onClick={() => createQueue.mutate()}
            >
              {createQueue.isPending
                ? "Generating..."
                : "Generate queue revision"}
            </button>
            {!coverageReady && coverage.data && (
              <p className="form-warning">
                Generate current embeddings before creating a queue from this
                model.
              </p>
            )}
            {createQueue.error && (
              <p className="form-error">{createQueue.error.message}</p>
            )}
          </article>
        </div>

        <div className="dashboard-main">
          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Coverage</p>
                <h4>Current embedding identity</h4>
              </div>
              <span>{coverage.data?.dimension ?? "—"} dimensions</span>
            </div>
            {coverage.isPending ? (
              <p>Checking coverage...</p>
            ) : (
              <div className="version-preview-metrics">
                <span>{coverage.data?.ready_image_count ?? 0} ready</span>
                <span>{coverage.data?.missing_image_count ?? 0} missing</span>
                <span>{coverage.data?.stale_image_count ?? 0} stale</span>
                <span>{coverage.data?.failed_image_count ?? 0} failed</span>
                <span>
                  {coverage.data?.total_image_count ?? 0} project images
                </span>
              </div>
            )}
            {coverage.data?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            {coverage.error && (
              <p className="form-error">{coverage.error.message}</p>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Persistent queue</p>
                <h4>Selection and review</h4>
              </div>
              <select
                aria-label="Active-learning queue revision"
                value={selectedQueueId}
                onChange={(event) => setSelectedQueueId(event.target.value)}
              >
                <option value="">No compatible queue selected</option>
                {activeQueues.map((queue) => (
                  <option key={queue.id} value={queue.id}>
                    Revision {queue.revision} · {queue.item_count} images
                    {queueMatchesModel(queue, selectedAsset)
                      ? ""
                      : " · stale model"}
                  </option>
                ))}
              </select>
            </div>
            {queueItems.isPending && selectedQueueId && <p>Loading queue...</p>}
            {selectedQueue && (
              <div className="version-preview-metrics">
                <span>Revision {selectedQueue.revision}</span>
                <span>{reviewedCount} reviewed/skipped</span>
                <span>{unfinishedCount} unfinished</span>
                <span>
                  {selectedQueue.promoted_dataset_version_id
                    ? "Promoted"
                    : "Not promoted"}
                </span>
              </div>
            )}
            <div className="dashboard-list">
              {queueItems.data?.items.map((item) => (
                <div key={item.id} className="dashboard-row">
                  <div>
                    <strong>
                      #{item.rank_position} · {item.image_id}
                    </strong>
                    <p>{item.selection_reasons_json.join(" · ")}</p>
                    <small>{item.reason_summary}</small>
                  </div>
                  <div className="annotation-editor-inline-actions">
                    <span>{item.review_state}</span>
                    {onOpenImage && (
                      <button type="button" onClick={() => onOpenImage(item)}>
                        Annotate
                      </button>
                    )}
                    {item.review_state === "pending" && (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                          itemAction.mutate({ item, action: "start" })
                        }
                      >
                        Start
                      </button>
                    )}
                    {["pending", "in_progress"].includes(item.review_state) && (
                      <>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() =>
                            itemAction.mutate({ item, action: "complete" })
                          }
                        >
                          Complete
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() =>
                            itemAction.mutate({ item, action: "skip" })
                          }
                        >
                          Exclude
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {queueItems.data?.items.length === 0 && selectedQueueId && (
              <p className="empty-state">This queue revision is empty.</p>
            )}
            {queueItems.error && (
              <p className="form-error">{queueItems.error.message}</p>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Immutable promotion</p>
                <h4>Reviewed dataset and training handoff</h4>
              </div>
            </div>
            <label>
              Dataset version name
              <input
                value={promotionName}
                onChange={(event) => setPromotionName(event.target.value)}
              />
            </label>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                disabled={
                  !selectedQueue ||
                  unfinishedCount > 0 ||
                  Boolean(selectedQueue.promoted_dataset_version_id) ||
                  promotion.isPending
                }
                onClick={() => promotion.mutate()}
              >
                {promotion.isPending
                  ? "Promoting..."
                  : "Create immutable dataset"}
              </button>
              {selectedQueue?.promoted_dataset_version_id &&
                onLaunchTraining && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={onLaunchTraining}
                  >
                    Launch training
                  </button>
                )}
            </div>
            {unfinishedCount > 0 && selectedQueue && (
              <p className="form-warning">
                Promotion is locked until every queue item is completed or
                explicitly excluded and completed images are saved as reviewed.
              </p>
            )}
            {promotion.error && (
              <p className="form-error">{promotion.error.message}</p>
            )}
            {promotion.data && (
              <p className="form-success">
                Dataset {promotion.data.dataset_version_id} created from queue
                revision {promotion.data.queue_revision}.
              </p>
            )}
          </article>

          {selectedCycle?.dataset_version_id && (
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Retraining-cycle record</p>
                  <h4>Attach training and compare models</h4>
                </div>
                <span>{selectedCycle.status}</span>
              </div>
              <p>
                Frozen dataset: {selectedCycle.dataset_version_id}. ReefVision
                only offers runs that used this exact immutable version.
              </p>
              <label>
                Training run
                <select
                  aria-label="Cycle training run"
                  value={trainingRunId}
                  onChange={(event) => setTrainingRunId(event.target.value)}
                >
                  <option value="">Choose a compatible run</option>
                  {compatibleRuns.map((run) => (
                    <option key={run.id} value={run.id}>
                      {run.run_name || run.id} · {run.status}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Resulting registered model
                <select
                  aria-label="Cycle resulting model"
                  value={candidateModelId}
                  onChange={(event) => setCandidateModelId(event.target.value)}
                >
                  <option value="">Not registered yet</option>
                  {compatibleModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.display_name} · {model.task}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!trainingRunId || attachTraining.isPending}
                onClick={() => attachTraining.mutate()}
              >
                {attachTraining.isPending
                  ? "Recording training..."
                  : "Record training result"}
              </button>
              {compatibleRuns.length === 0 && !trainingRuns.isPending && (
                <p className="form-warning">
                  No training run uses this cycle's immutable dataset yet.
                </p>
              )}
              {attachTraining.error && (
                <p className="form-error">{attachTraining.error.message}</p>
              )}
              {attachTraining.data && (
                <p className="form-success">
                  Training run {attachTraining.data.training_run_id} is linked
                  to this cycle.
                </p>
              )}

              <h5>Before-and-after evaluation</h5>
              <label>
                Comparison metric
                <input
                  value={metricName}
                  onChange={(event) => setMetricName(event.target.value)}
                />
              </label>
              <label>
                Baseline value
                <input
                  inputMode="decimal"
                  value={baselineMetric}
                  onChange={(event) => setBaselineMetric(event.target.value)}
                />
              </label>
              <label>
                Candidate value
                <input
                  inputMode="decimal"
                  value={candidateMetric}
                  onChange={(event) => setCandidateMetric(event.target.value)}
                />
              </label>
              <label>
                Metric schema
                <input
                  value={metricSchemaId}
                  onChange={(event) => setMetricSchemaId(event.target.value)}
                />
              </label>
              <p className="form-warning">
                Both values are compared on {actionCycle?.dataset_version_id}
                using one metric schema. The API blocks explicitly incompatible
                datasets or schemas.
              </p>
              <button
                type="button"
                disabled={
                  !actionCycle?.training_run_id ||
                  !baselineMetric ||
                  !candidateMetric ||
                  evaluation.isPending
                }
                onClick={() => evaluation.mutate()}
              >
                {evaluation.isPending
                  ? "Comparing..."
                  : "Compare before and after"}
              </button>
              {evaluation.error && (
                <p className="form-error">{evaluation.error.message}</p>
              )}
              {evaluation.data && (
                <div>
                  <p
                    className={
                      evaluation.data.comparison_compatible
                        ? "form-success"
                        : "form-error"
                    }
                  >
                    {evaluation.data.comparison_compatible
                      ? `Compatible comparison recorded; ${
                          evaluation.data.promoted
                            ? "candidate promoted"
                            : "baseline retained"
                        }.`
                      : "Comparison rejected as incompatible."}
                  </p>
                  {evaluation.data.compatibility_warnings.map((warning) => (
                    <p key={warning} className="form-warning">
                      {warning}
                    </p>
                  ))}
                </div>
              )}
              {(trainingRuns.error || registeredModels.error) && (
                <p className="form-error">
                  Failed to load project training or model registrations.
                </p>
              )}
            </article>
          )}

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Cycle history</p>
                <h4>Source-to-result model provenance</h4>
              </div>
            </div>
            <div className="dashboard-list">
              {cycles.data?.cycles
                .slice()
                .reverse()
                .map((cycle) => (
                  <details key={cycle.id} className="dashboard-row">
                    <summary>
                      Cycle {cycle.cycle_index} · {cycle.status} ·{" "}
                      {cycle.reviewed_count}/{cycle.selected_count} reviewed
                    </summary>
                    <p>
                      Source model: {cycle.source_model_id ?? "not selected"} ·
                      Result model:{" "}
                      {cycle.promoted_model_id ??
                        cycle.candidate_model_id ??
                        "not trained"}
                    </p>
                    <p>
                      Dataset: {cycle.dataset_version_id ?? "not frozen"} ·
                      Queue revision: {cycle.queue_revision ?? "—"}
                    </p>
                    <small>
                      Before: {JSON.stringify(cycle.baseline_metrics)} · After:{" "}
                      {JSON.stringify(cycle.candidate_metrics)}
                    </small>
                    {cycle.warnings.map((warning) => (
                      <p key={warning} className="form-warning">
                        {warning}
                      </p>
                    ))}
                  </details>
                ))}
            </div>
            {cycles.data?.cycles.length === 0 && (
              <p>No active-learning cycles yet.</p>
            )}
            {cycles.error && (
              <p className="form-error">{cycles.error.message}</p>
            )}
          </article>
        </div>
      </div>
    </section>
  );
}
