import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  completeReviewQueueItem,
  createDatasetVersionReviewQueue,
  createReviewQueue,
  getDatasetVersionQualityControlRuns,
  getDatasetVersionReviewQueues,
  getDatasetVersions,
  getQualityControlRuns,
  getReviewQueueItems,
  getReviewQueues,
  regenerateReviewQueue,
  returnReviewQueueItem,
  skipReviewQueueItem,
  startReviewQueueItem,
  type Project,
  type ReviewQueueItem,
  type ReviewQueueRecord,
  type ReviewScoreWeights,
} from "../../api/client";
import { QuickConfidenceReviewDialog } from "./QuickConfidenceReviewDialog";
import { ReviewQueueBulkTriage } from "./ReviewQueueBulkTriage";
import { ReviewQueueCoordinationPanel } from "./ReviewQueueCoordinationPanel";
import {
  reviewQueueItemsQueryKey,
  reviewQueuesQueryKey,
  scopedReviewQueueId,
} from "./reviewQueueState";

const defaultWeights: ReviewScoreWeights = {
  low_mean_confidence: 24,
  low_min_confidence: 12,
  pending_proposals: 14,
  rejection_rate: 8,
  count_disagreement: 12,
  unresolved_qc_severity: 18,
  rare_class_presence: 5,
  edited_acceptance_rate: 6,
  unreviewed_state: 10,
  missing_group_metadata: 4,
  incomplete_provenance: 5,
  recent_import: 4,
  stale_review_state: 6,
};

type QueueMutationScope = {
  projectId: string;
  scopeType: "project" | "dataset_version";
  datasetVersionId: string;
  navigationEpoch: number;
};

type CreateQueueRequest = QueueMutationScope & {
  sourceRunId: string;
  weights: ReviewScoreWeights;
  reviewBelowConfidence: string;
};

type ItemMutationRequest = QueueMutationScope & {
  queueId: string;
  itemId: string;
  actor: string;
};

function sameQueueScope(a: QueueMutationScope, b: QueueMutationScope): boolean {
  return (
    a.projectId === b.projectId &&
    a.scopeType === b.scopeType &&
    a.datasetVersionId === b.datasetVersionId &&
    a.navigationEpoch === b.navigationEpoch
  );
}

function queueLabel(queue: ReviewQueueRecord): string {
  return `${queue.status} | ${queue.item_count} ranked images`;
}

export function ReviewQueueDashboard({
  project,
  onOpenImage,
  onSelectedQueueChange,
}: {
  project: Project;
  onOpenImage: (item: ReviewQueueItem) => void;
  onSelectedQueueChange?: (queueId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const currentScope = useRef<QueueMutationScope>({
    projectId: project.id,
    scopeType: "project",
    datasetVersionId: "",
    navigationEpoch: 0,
  });
  const [scopeProjectId, setScopeProjectId] = useState(project.id);
  const [scopeType, setScopeType] = useState<"project" | "dataset_version">(
    "project",
  );
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [selectedQueueId, setSelectedQueueId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [page, setPage] = useState(1);
  const [labelClassId, setLabelClassId] = useState("");
  const [split, setSplit] = useState("");
  const [qcSeverity, setQcSeverity] = useState("");
  const [reviewState, setReviewState] = useState("");
  const [modelId, setModelId] = useState("");
  const [singleItemActor, setSingleItemActor] = useState("");
  const [weights, setWeights] = useState<ReviewScoreWeights>(defaultWeights);
  const [reviewBelowConfidence, setReviewBelowConfidence] = useState("");
  const [quickReviewItemId, setQuickReviewItemId] = useState<string | null>(
    null,
  );
  const [coordinationItemId, setCoordinationItemId] = useState<string | null>(
    null,
  );
  const [openQuickReviewWhenReady, setOpenQuickReviewWhenReady] =
    useState(false);

  // Mutation completions must never select a queue from a project or dataset
  // that the researcher has since navigated away from.
  const previousScope = currentScope.current;
  const nextScope = {
    projectId: project.id,
    scopeType,
    datasetVersionId,
    navigationEpoch: previousScope.navigationEpoch,
  };
  if (!sameQueueScope(previousScope, nextScope)) {
    // Even A -> B -> A is a new navigation. A response from the first
    // visit must not replace the researcher's newer queue selection.
    nextScope.navigationEpoch += 1;
  }
  currentScope.current = nextScope;

  // A dataset-version scope without a selected version is not a project scope.
  const scopeReady =
    scopeProjectId === project.id &&
    (scopeType === "project" || Boolean(datasetVersionId));
  const versions = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const runs = useQuery({
    queryKey: ["quality_control_runs", project.id, scopeType, datasetVersionId],
    queryFn: ({ signal }) =>
      scopeType === "dataset_version" && datasetVersionId
        ? getDatasetVersionQualityControlRuns(datasetVersionId, signal)
        : getQualityControlRuns(project.id, signal),
    enabled: scopeReady,
  });
  const queues = useQuery({
    queryKey: reviewQueuesQueryKey(project.id, scopeType, datasetVersionId),
    queryFn: ({ signal }) =>
      scopeType === "dataset_version" && datasetVersionId
        ? getDatasetVersionReviewQueues(datasetVersionId, signal)
        : getReviewQueues(project.id, signal),
    enabled: scopeReady,
  });
  // Do not query a stale queue from another project or dataset scope.
  const activeQueueId = scopedReviewQueueId(selectedQueueId, queues.data);
  const items = useQuery({
    queryKey: reviewQueueItemsQueryKey(
      activeQueueId,
      page,
      labelClassId,
      split,
      qcSeverity,
      reviewState,
      modelId,
    ),
    queryFn: ({ signal }) =>
      getReviewQueueItems(
        activeQueueId,
        {
          page,
          pageSize: 25,
          labelClassId: labelClassId || undefined,
          split: split || undefined,
          qcSeverity: qcSeverity || undefined,
          reviewState: reviewState || undefined,
          modelId: modelId.trim() || undefined,
        },
        signal,
      ),
    enabled: activeQueueId.length > 0,
  });

  useEffect(() => {
    // Dataset IDs and QC source runs belong to the prior project too.
    setSingleItemActor("");
    setScopeType("project");
    setDatasetVersionId("");
    setSelectedRunId("");
    setSelectedQueueId("");
    setQuickReviewItemId(null);
    setCoordinationItemId(null);
    setOpenQuickReviewWhenReady(false);
    setPage(1);
    setScopeProjectId(project.id);
  }, [project.id]);

  useEffect(() => {
    // A just-created queue can be selected before the refreshed list arrives.
    // Do not erase that selection merely because the previous list was empty.
    if (!queues.data?.length) return;
    if (!selectedQueueId) {
      setSelectedQueueId(queues.data[0].id);
    }
  }, [queues.data, selectedQueueId]);

  useEffect(() => {
    setCoordinationItemId(null);
    onSelectedQueueChange?.(activeQueueId || null);
  }, [onSelectedQueueChange, activeQueueId]);

  useEffect(
    () => () => {
      onSelectedQueueChange?.(null);
    },
    [onSelectedQueueChange, project.id],
  );

  useEffect(() => {
    setPage(1);
  }, [labelClassId, split, qcSeverity, reviewState, modelId]);

  useEffect(() => {
    if (!openQuickReviewWhenReady || !items.data || !selectedQueueId) return;
    setOpenQuickReviewWhenReady(false);
    setQuickReviewItemId(items.data.items[0]?.id ?? null);
  }, [items.data, openQuickReviewWhenReady, selectedQueueId]);

  const createQueue = useMutation({
    mutationFn: async (request: CreateQueueRequest) => {
      if (
        !request.projectId ||
        (request.scopeType === "dataset_version" && !request.datasetVersionId)
      ) {
        throw new Error("Review scope is not ready");
      }
      const payload = {
        source_quality_control_run_id: request.sourceRunId || undefined,
        signal_weights: request.weights,
        review_below_confidence:
          request.reviewBelowConfidence === ""
            ? undefined
            : Number(request.reviewBelowConfidence) / 100,
      };
      return request.scopeType === "dataset_version"
        ? createDatasetVersionReviewQueue(request.datasetVersionId, payload)
        : createReviewQueue(request.projectId, payload);
    },
    onSuccess: async (queue, request) => {
      if (sameQueueScope(currentScope.current, request)) {
        setSelectedQueueId(queue.id);
        setQuickReviewItemId(null);
        setOpenQuickReviewWhenReady(request.reviewBelowConfidence !== "");
      }
      await queryClient.invalidateQueries({
        queryKey: reviewQueuesQueryKey(
          request.projectId,
          request.scopeType,
          request.datasetVersionId,
        ),
      });
    },
  });
  const regenerateQueue = useMutation({
    mutationFn: (request: QueueMutationScope & { queueId: string }) =>
      regenerateReviewQueue(request.queueId),
    onSuccess: async (queue, request) => {
      if (sameQueueScope(currentScope.current, request)) {
        setSelectedQueueId(queue.id);
      }
      await queryClient.invalidateQueries({
        queryKey: reviewQueuesQueryKey(
          request.projectId,
          request.scopeType,
          request.datasetVersionId,
        ),
      });
    },
  });
  // Capture reviewer identity and queue provenance when the researcher acts.
  // A delayed mutation must not invalidate another project's selected queue.
  const itemRequest = (itemId: string): ItemMutationRequest => ({
    ...currentScope.current,
    queueId: activeQueueId,
    itemId,
    actor: singleItemActor.trim(),
  });
  const invalidateItemRequest = async (request: ItemMutationRequest) => {
    await queryClient.invalidateQueries({
      queryKey: ["review_queue_items", request.queueId],
    });
    await queryClient.invalidateQueries({
      queryKey: ["review_queue_events", request.queueId],
    });
  };
  const startItem = useMutation({
    mutationFn: (request: ItemMutationRequest) =>
      startReviewQueueItem(request.itemId, request.actor),
    onSuccess: (_, request) => invalidateItemRequest(request),
  });
  const completeItem = useMutation({
    mutationFn: (request: ItemMutationRequest) =>
      completeReviewQueueItem(request.itemId, request.actor, true),
    onSuccess: (_, request) => invalidateItemRequest(request),
  });
  const skipItem = useMutation({
    mutationFn: async (request: ItemMutationRequest) => {
      const reason = window.prompt("Skip reason");
      if (!reason?.trim()) {
        throw new Error("A skip reason is required");
      }
      return skipReviewQueueItem(request.itemId, reason.trim(), request.actor);
    },
    onSuccess: (_, request) => invalidateItemRequest(request),
  });
  const returnItem = useMutation({
    mutationFn: (request: ItemMutationRequest) =>
      returnReviewQueueItem(request.itemId, request.actor),
    onSuccess: (_, request) => invalidateItemRequest(request),
  });

  const selectedQueue = useMemo(
    () => queues.data?.find((queue) => queue.id === activeQueueId) ?? null,
    [queues.data, activeQueueId],
  );
  const quickReviewItems = items.data?.items ?? [];
  const quickReviewIndex = quickReviewItems.findIndex(
    (item) => item.id === quickReviewItemId,
  );
  const quickReviewItem =
    quickReviewIndex >= 0 ? quickReviewItems[quickReviewIndex] : null;
  const storedThreshold =
    selectedQueue?.configuration_json.review_below_confidence;
  const activeReviewThreshold =
    typeof storedThreshold === "number" && Number.isFinite(storedThreshold)
      ? storedThreshold
      : null;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Guided review</p>
          <h3>Review Queue</h3>
          <span>{queues.data?.length ?? 0} historical queues</span>
        </div>
        <button
          type="button"
          disabled={!quickReviewItems.length}
          onClick={() => setQuickReviewItemId(quickReviewItems[0].id)}
        >
          Open quick-review popout
        </button>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Queue configuration</p>
                <h4>Generate ranking</h4>
              </div>
            </div>
            <label>
              Scope
              <select
                disabled={coordinationItemId !== null}
                value={scopeType}
                onChange={(event) => {
                  setScopeType(
                    event.target.value as "project" | "dataset_version",
                  );
                  setDatasetVersionId("");
                  setSelectedRunId("");
                  setSelectedQueueId("");
                  setQuickReviewItemId(null);
                  setCoordinationItemId(null);
                  setOpenQuickReviewWhenReady(false);
                  setPage(1);
                }}
              >
                <option value="project">Entire project</option>
                <option value="dataset_version">Dataset version</option>
              </select>
            </label>
            {scopeType === "dataset_version" && (
              <label>
                Dataset version
                <select
                  disabled={coordinationItemId !== null}
                  value={datasetVersionId}
                  onChange={(event) => {
                    setDatasetVersionId(event.target.value);
                    setSelectedRunId("");
                    setSelectedQueueId("");
                    setQuickReviewItemId(null);
                    setCoordinationItemId(null);
                    setOpenQuickReviewWhenReady(false);
                    setPage(1);
                  }}
                >
                  <option value="">Choose a version</option>
                  {versions.data?.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version_number} - {version.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Source QC run
              <select
                disabled={!scopeReady || runs.isPending}
                value={selectedRunId}
                onChange={(event) => setSelectedRunId(event.target.value)}
              >
                <option value="">Latest completed run</option>
                {runs.data?.map((run) => (
                  <option key={run.id} value={run.id}>
                    {new Date(run.created_at).toLocaleString()} | {run.status}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Review predictions at or below confidence (%) — optional
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                placeholder="50"
                value={reviewBelowConfidence}
                onChange={(event) =>
                  setReviewBelowConfidence(event.target.value)
                }
              />
            </label>
            <p className="annotation-helper">
              Enter 50 to review predictions with confidence 50% or lower.
              Predictions above 50% are ignored by this queue, not automatically
              accepted or human-verified.
            </p>
            <div className="dashboard-grid compact-grid">
              {Object.entries(weights).map(([key, value]) => (
                <label key={key}>
                  {key.replaceAll("_", " ")}
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={value}
                    onChange={(event) =>
                      setWeights((current) => ({
                        ...current,
                        [key]: Number(event.target.value),
                      }))
                    }
                  />
                </label>
              ))}
            </div>
            <div className="version-actions">
              <button
                type="button"
                disabled={
                  !scopeReady ||
                  coordinationItemId !== null ||
                  createQueue.isPending ||
                  (scopeType === "dataset_version" && !datasetVersionId)
                }
                onClick={() =>
                  createQueue.mutate({
                    ...currentScope.current,
                    sourceRunId: selectedRunId,
                    weights: { ...weights },
                    reviewBelowConfidence,
                  })
                }
              >
                {createQueue.isPending ? "Generating..." : "Generate queue"}
              </button>
              {selectedQueue && (
                <button
                  type="button"
                  className="secondary"
                  disabled={coordinationItemId !== null}
                  onClick={() =>
                    regenerateQueue.mutate({
                      ...currentScope.current,
                      queueId: selectedQueue.id,
                    })
                  }
                >
                  Regenerate
                </button>
              )}
            </div>
            {(createQueue.error || regenerateQueue.error) && (
              <p className="form-error">
                {(createQueue.error ?? regenerateQueue.error)?.message}
              </p>
            )}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Queue history</p>
                <h4>Generated queues</h4>
              </div>
            </div>
            {coordinationItemId !== null && (
              <p className="annotation-helper" role="status">
                Close researcher coordination before changing queues or scope;
                unsent biological notes and uncertain audit-event retry IDs must
                not be lost by unmounting the panel.
              </p>
            )}
            <div className="version-list">
              {queues.data?.map((queue) => (
                <button
                  key={queue.id}
                  type="button"
                  className={`version-card ${
                    selectedQueueId === queue.id ? "selected" : ""
                  }`}
                  disabled={
                    coordinationItemId !== null && selectedQueueId !== queue.id
                  }
                  onClick={() => {
                    setSelectedQueueId(queue.id);
                    setQuickReviewItemId(null);
                    setCoordinationItemId(null);
                    setOpenQuickReviewWhenReady(false);
                    setPage(1);
                  }}
                >
                  <strong>{new Date(queue.created_at).toLocaleString()}</strong>
                  <span>{queueLabel(queue)}</span>
                  <small>{queue.formula_id}</small>
                </button>
              ))}
            </div>
            {queues.error && (
              <p className="form-error">{queues.error.message}</p>
            )}
          </div>
        </div>

        <div className="dashboard-main">
          {selectedQueue && (
            <div className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Selected queue</p>
                  <h4>{selectedQueue.formula_id}</h4>
                </div>
                <span>
                  {selectedQueue.item_count} images
                  {activeReviewThreshold !== null
                    ? ` · review at or below ${Math.round(activeReviewThreshold * 100)}%`
                    : ""}
                </span>
              </div>
              <div className="version-preview-metrics">
                <span>Status: {selectedQueue.status}</span>
                <span>
                  Created: {new Date(selectedQueue.created_at).toLocaleString()}
                </span>
                <span>Formula version: {selectedQueue.formula_version}</span>
              </div>
            </div>
          )}

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Queue filters</p>
                <h4>Ranked images</h4>
              </div>
              <span>{items.data?.total ?? 0} matches</span>
            </div>
            <div className="dashboard-grid compact-grid">
              <label>
                Class
                <select
                  value={labelClassId}
                  onChange={(event) => setLabelClassId(event.target.value)}
                >
                  <option value="">All classes</option>
                  {project.label_classes.map((labelClass) => (
                    <option key={labelClass.id} value={labelClass.id}>
                      {labelClass.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Split
                <select
                  value={split}
                  onChange={(event) => setSplit(event.target.value)}
                >
                  <option value="">All splits</option>
                  <option value="train">Train</option>
                  <option value="validation">Validation</option>
                  <option value="test">Test</option>
                  <option value="unassigned">Unassigned</option>
                </select>
              </label>
              <label>
                QC severity
                <select
                  value={qcSeverity}
                  onChange={(event) => setQcSeverity(event.target.value)}
                >
                  <option value="">All severities</option>
                  <option value="error">Error</option>
                  <option value="warning">Warning</option>
                  <option value="info">Info</option>
                </select>
              </label>
              <label>
                Review state
                <select
                  value={reviewState}
                  onChange={(event) => setReviewState(event.target.value)}
                >
                  <option value="">All states</option>
                  <option value="pending">Pending</option>
                  <option value="in_progress">In progress</option>
                  <option value="completed">Completed</option>
                  <option value="skipped">Skipped</option>
                </select>
              </label>
              <label>
                Model ID
                <input
                  value={modelId}
                  onChange={(event) => setModelId(event.target.value)}
                  placeholder="Filter model id"
                />
              </label>
            </div>
            {items.isPending && <p>Loading review queue items...</p>}
            {items.error && <p className="form-error">{items.error.message}</p>}
            {activeQueueId && items.data && (
              <ReviewQueueBulkTriage
                key={[
                  selectedQueueId,
                  page,
                  labelClassId,
                  split,
                  qcSeverity,
                  reviewState,
                  modelId,
                ].join(":")}
                queueId={selectedQueueId}
                items={items.data.items}
              />
            )}
            {activeQueueId && (
              <label>
                Single-item reviewer label (self-reported, not authenticated)
                <input
                  aria-label="Single-item reviewer label"
                  maxLength={100}
                  value={singleItemActor}
                  onChange={(event) => setSingleItemActor(event.target.value)}
                />
              </label>
            )}
            <div className="dashboard-list">
              {items.data?.items.map((item) => (
                <article key={item.id} className="dashboard-row">
                  <div>
                    <div className="image-card-topline">
                      <strong>Rank #{item.rank_position}</strong>
                      <span className="count-chip">
                        Score {item.score.toFixed(2)}
                      </span>
                      {item.highest_qc_severity && (
                        <span className="count-chip secondary-chip">
                          {item.highest_qc_severity}
                        </span>
                      )}
                      <span className="count-chip secondary-chip">
                        {item.review_state}
                      </span>
                    </div>
                    <p>
                      {item.reason_summary || "No score summary available."}
                    </p>
                    <small>
                      Image {item.image_id}
                      {item.split ? ` | ${item.split}` : ""}
                    </small>
                    <div className="annotation-selection-list">
                      {item.score_breakdown_json.slice(0, 4).map((entry) => (
                        <div
                          key={`${item.id}-${entry.signal_id}`}
                          className="annotation-selection-row"
                        >
                          <strong>{entry.label}</strong>
                          <span>+{entry.contribution.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="dashboard-actions">
                    <button
                      type="button"
                      onClick={() => setQuickReviewItemId(item.id)}
                    >
                      Quick review
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => onOpenImage(item)}
                    >
                      Open image
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setCoordinationItemId(item.id)}
                    >
                      Comments &amp; assignments
                    </button>
                    {item.review_state === "pending" && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={
                          !singleItemActor.trim() || startItem.isPending
                        }
                        onClick={() => startItem.mutate(itemRequest(item.id))}
                      >
                        Start review
                      </button>
                    )}
                    {item.review_state !== "completed" && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={
                          !singleItemActor.trim() || completeItem.isPending
                        }
                        onClick={() => {
                          if (
                            window.confirm(
                              "Confirm you personally reviewed this queue item. " +
                                "Completing a QC queue item does not verify model predictions or annotations.",
                            )
                          ) {
                            completeItem.mutate(itemRequest(item.id));
                          }
                        }}
                      >
                        Mark complete
                      </button>
                    )}
                    {item.review_state !== "skipped" ? (
                      <button
                        type="button"
                        className="secondary"
                        disabled={!singleItemActor.trim() || skipItem.isPending}
                        onClick={() => skipItem.mutate(itemRequest(item.id))}
                      >
                        Skip
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="secondary"
                        disabled={
                          !singleItemActor.trim() || returnItem.isPending
                        }
                        onClick={() => returnItem.mutate(itemRequest(item.id))}
                      >
                        Return to queue
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {activeQueueId && coordinationItemId && (
              <ReviewQueueCoordinationPanel
                queueId={selectedQueueId}
                itemId={coordinationItemId}
                onClose={() => setCoordinationItemId(null)}
              />
            )}
            {items.data && items.data.pages > 1 && (
              <nav className="pagination" aria-label="Review queue item pages">
                <button
                  type="button"
                  className="secondary"
                  disabled={page === 1}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {items.data.page} of {items.data.pages}
                </span>
                <button
                  type="button"
                  className="secondary"
                  disabled={page === items.data.pages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </button>
              </nav>
            )}
          </div>
        </div>
      </div>
      {quickReviewItem && (
        <QuickConfidenceReviewDialog
          key={quickReviewItem.image_id}
          item={quickReviewItem}
          reviewBelowConfidence={activeReviewThreshold}
          position={quickReviewIndex + 1}
          total={quickReviewItems.length}
          onClose={() => setQuickReviewItemId(null)}
          onPreviousImage={() =>
            setQuickReviewItemId(
              quickReviewItems[quickReviewIndex - 1]?.id ?? null,
            )
          }
          onNextImage={() =>
            setQuickReviewItemId(
              quickReviewItems[quickReviewIndex + 1]?.id ?? null,
            )
          }
          onOpenFullEditor={() => {
            setQuickReviewItemId(null);
            onOpenImage(quickReviewItem);
          }}
          onMarkComplete={() => {
            if (!singleItemActor.trim()) {
              window.alert(
                "Enter a reviewer label before completing this QC item.",
              );
              return;
            }
            if (
              window.confirm(
                "Confirm you personally reviewed this queue item. " +
                  "Completing QC does not verify predictions or annotations.",
              )
            ) {
              const request = itemRequest(quickReviewItem.id);
              completeItem.mutate(request, {
                onSuccess: () => {
                  if (
                    sameQueueScope(currentScope.current, request) &&
                    activeQueueId === request.queueId
                  ) {
                    setQuickReviewItemId(null);
                  }
                },
              });
            }
          }}
          markingComplete={completeItem.isPending}
        />
      )}
    </section>
  );
}
