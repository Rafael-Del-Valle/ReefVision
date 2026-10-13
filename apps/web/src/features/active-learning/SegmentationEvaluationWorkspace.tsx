import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getDatasetVersions, getModels, type Project } from "../../api/client";
import {
  getSegmentationEvaluation,
  promoteSegmentationCandidate,
  queueSegmentationEvaluation,
  rollbackSegmentationDeployment,
  type SegmentationMaskMetrics,
} from "./segmentationEvaluationApi";

function maskMetric(value: number | undefined): string {
  return value !== undefined && Number.isFinite(value)
    ? value.toFixed(3)
    : "Not available";
}

function MaskMetrics({
  label,
  metrics,
}: {
  label: string;
  metrics: SegmentationMaskMetrics | null;
}) {
  if (!metrics) return <p>{label}: No completed mask inference evidence.</p>;
  return (
    <div className="panel-card">
      <h5>{label} — source-pixel instance masks</h5>
      <dl className="metric-list">
        <div>
          <dt>Mask AP50</dt>
          <dd>{maskMetric(metrics.mask_map50)}</dd>
        </div>
        <div>
          <dt>Precision / recall</dt>
          <dd>
            {maskMetric(metrics.precision)} / {maskMetric(metrics.recall)}
          </dd>
        </div>
        <div>
          <dt>Mean absolute count error</dt>
          <dd>{maskMetric(metrics.mean_absolute_count_error)}</dd>
        </div>
        <div>
          <dt>Count bias per image</dt>
          <dd>{maskMetric(metrics.count_bias_per_image)}</dd>
        </div>
        <div>
          <dt>Matched mask IoU</dt>
          <dd>{maskMetric(metrics.mean_matched_mask_iou)}</dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * Explicit scientist-in-the-loop evaluation. No model is deployed on queue,
 * scoring, polling or render: promotion and rollback require separate clicks.
 */
export function SegmentationEvaluationWorkspace({ project }: { project: Project }) {
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [incumbentId, setIncumbentId] = useState("");
  const [split, setSplit] = useState<"validation" | "test">("validation");
  const [minimumMaskMap50, setMinimumMaskMap50] = useState(0.5);
  const [evaluationId, setEvaluationId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [expectedActiveId, setExpectedActiveId] = useState("");
  const [noActiveModel, setNoActiveModel] = useState(false);
  const [confirmPromotion, setConfirmPromotion] = useState(false);
  const [confirmRollback, setConfirmRollback] = useState(false);
  const [deploymentId, setDeploymentId] = useState("");
  const [rollbackActiveId, setRollbackActiveId] = useState("");

  useEffect(() => {
    setEvaluationId("");
    setDatasetVersionId("");
    setCandidateId("");
    setIncumbentId("");
    setDeploymentId("");
    setConfirmPromotion(false);
    setConfirmRollback(false);
  }, [project.id]);

  const datasets = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const models = useQuery({
    queryKey: ["models", project.id, "segmentation-evaluation"],
    queryFn: ({ signal }) => getModels(project.id, undefined, signal),
  });
  const segmenters = (models.data ?? []).filter(
    (model) => model.purpose === "segmenter" && model.task === "segment",
  );
  const evaluation = useQuery({
    queryKey: ["segmentation-evaluation", project.id, evaluationId],
    queryFn: ({ signal }) =>
      getSegmentationEvaluation(project.id, evaluationId, signal),
    enabled: Boolean(evaluationId.trim()),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 2500;
    },
  });
  const queue = useMutation({
    mutationFn: () =>
      queueSegmentationEvaluation(project.id, {
        dataset_version_id: datasetVersionId,
        candidate_model_id: candidateId,
        incumbent_model_id: incumbentId || null,
        split,
        minimum_images: 2,
        minimum_masks: 2,
        minimum_mask_map50: minimumMaskMap50,
        minimum_gain: 0,
      }),
    onSuccess: (job) => {
      setEvaluationId(job.id);
      setConfirmPromotion(false);
    },
  });
  const promote = useMutation({
    mutationFn: () =>
      promoteSegmentationCandidate(project.id, evaluationId, {
        expected_active_model_id: noActiveModel ? null : expectedActiveId.trim(),
        approved_by: reviewer.trim(),
        reason: reason.trim(),
      }),
    onSuccess: (audit) => {
      setDeploymentId(audit.id);
      setRollbackActiveId(audit.active_model_id ?? "");
      setConfirmPromotion(false);
      setConfirmRollback(false);
    },
  });
  const rollback = useMutation({
    mutationFn: () =>
      rollbackSegmentationDeployment(project.id, deploymentId.trim(), {
        expected_active_model_id: rollbackActiveId.trim(),
        approved_by: reviewer.trim(),
        reason: reason.trim(),
      }),
    onSuccess: () => setConfirmRollback(false),
  });

  const record = evaluation.data;
  const completed = record?.status === "completed";
  const eligible =
    completed && record?.promotion_eligible === true && Boolean(record?.candidate_metrics);
  const reasonValid = reason.trim().length >= 10;
  const reviewerValid = reviewer.trim().length >= 2;
  const promotionValid =
    eligible &&
    confirmPromotion &&
    reasonValid &&
    reviewerValid &&
    (noActiveModel || Boolean(expectedActiveId.trim())) &&
    !promote.isPending &&
    !rollback.isPending;
  const rollbackValid =
    confirmRollback &&
    Boolean(deploymentId.trim()) &&
    Boolean(rollbackActiveId.trim()) &&
    reasonValid &&
    reviewerValid &&
    !rollback.isPending &&
    !promote.isPending;

  return (
    <section
      className="panel-card"
      data-testid="segmentation-evaluation-workspace"
      aria-label="Segmentation candidate evaluation"
    >
      <h4>Evaluate segmentation candidate</h4>
      <p className="annotation-helper">
        Queue real candidate and optional incumbent inference against an immutable
        human-verified mask holdout. This computes <strong>instance mask AP50</strong>,
        not detector box AP; queueing never activates a model or verifies proposals.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          queue.mutate();
        }}
      >
        <label>
          Verified immutable dataset version
          <select
            value={datasetVersionId}
            onChange={(event) => setDatasetVersionId(event.target.value)}
            required
          >
            <option value="">Select a complete dataset</option>
            {(datasets.data ?? [])
              .filter((version) => version.status === "complete")
              .map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version_number} · {version.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Candidate segmentation model
          <select
            value={candidateId}
            onChange={(event) => setCandidateId(event.target.value)}
            required
          >
            <option value="">Select a registered segmenter</option>
            {segmenters.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Incumbent segmenter (optional, compared on the same split)
          <select
            value={incumbentId}
            onChange={(event) => setIncumbentId(event.target.value)}
          >
            <option value="">No incumbent comparison</option>
            {segmenters
              .filter((model) => model.id !== candidateId)
              .map((model) => (
                <option key={model.id} value={model.id}>
                  {model.display_name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Held-out split
          <select
            value={split}
            onChange={(event) =>
              setSplit(event.target.value as "validation" | "test")
            }
          >
            <option value="validation">Validation</option>
            <option value="test">Test</option>
          </select>
        </label>
        <label>
          Minimum mask AP50 (0–1)
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={minimumMaskMap50}
            onChange={(event) => setMinimumMaskMap50(Number(event.target.value))}
          />
        </label>
        <button
          type="submit"
          disabled={
            queue.isPending ||
            !datasetVersionId ||
            !candidateId ||
            candidateId === incumbentId ||
            !Number.isFinite(minimumMaskMap50) ||
            minimumMaskMap50 < 0 ||
            minimumMaskMap50 > 1
          }
        >
          {queue.isPending ? "Queueing evaluation..." : "Queue held-out evaluation"}
        </button>
        {segmenters.length === 0 && (
          <p className="annotation-helper">
            No locally registered segment model is available. Train and register
            a segmenter before evaluation.
          </p>
        )}
        {queue.error && <p role="alert">{queue.error.message}</p>}
      </form>

      <label>
        Existing evaluation ID (restore after restarting)
        <input
          value={evaluationId}
          onChange={(event) => {
            setEvaluationId(event.target.value.trim());
            setConfirmPromotion(false);
          }}
          placeholder="Paste an evaluation job ID"
        />
      </label>
      {evaluation.isFetching && !record && <p role="status">Loading evaluation...</p>}
      {evaluation.error && <p role="alert">{evaluation.error.message}</p>}
      {record && (
        <div data-testid="segmentation-evaluation-evidence">
          <p>
            <strong>Scientific evaluation: {record.status}</strong> · dataset
            manifest <code>{record.manifest_sha256.slice(0, 12)}</code> ·
            {record.split} split
          </p>
          <p>
            Candidate checkpoint <code>{record.candidate_checksum.slice(0, 12)}</code>
            {record.incumbent_checksum && (
              <> · Incumbent <code>{record.incumbent_checksum.slice(0, 12)}</code></>
            )}
          </p>
          <MaskMetrics label="Candidate" metrics={record.candidate_metrics} />
          {record.incumbent_model_id && (
            <MaskMetrics label="Incumbent" metrics={record.incumbent_metrics} />
          )}
          <p>
            Promotion eligibility:{" "}
            <strong>{eligible ? "Eligible for manual review" : "Not eligible"}</strong>
          </p>
          {record.blockers.map((blocker) => (
            <p className="form-error" key={blocker}>
              {blocker}
            </p>
          ))}
          <p className="annotation-helper">{record.warning}</p>
        </div>
      )}

      <h4>Audited manual model selection</h4>
      <p className="annotation-helper">
        Eligibility is not approval. The current active segmenter must match the
        expected ID. Never use a detector model ID or assume that an evaluation
        changed the active model.
      </p>
      <label>
        Operator/reviewer identity
        <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
      </label>
      <label>
        Scientific reason for this action (at least 10 characters)
        <textarea value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <label>
        Expected currently active segmenter ID
        <input
          value={expectedActiveId}
          onChange={(event) => setExpectedActiveId(event.target.value)}
          disabled={noActiveModel}
          placeholder="Required unless no active segmenter exists"
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={noActiveModel}
          onChange={(event) => setNoActiveModel(event.target.checked)}
        />{" "}
        Confirm that this project has no active segmenter
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmPromotion}
          onChange={(event) => setConfirmPromotion(event.target.checked)}
        />{" "}
        I reviewed the actual mask metrics and explicitly approve activating this
        candidate
      </label>
      <button
        type="button"
        disabled={!promotionValid}
        onClick={() => promote.mutate()}
      >
        {promote.isPending
          ? "Recording audited promotion..."
          : "Promote segmentation candidate"}
      </button>
      {promote.error && <p role="alert">{promote.error.message}</p>}
      {promote.data && (
        <p role="status">
          Audited promotion recorded: <code>{promote.data.id}</code>. Active
          segmenter <code>{promote.data.active_model_id}</code>.
        </p>
      )}

      <h4>Rollback active segmenter</h4>
      <p className="annotation-helper">
        Rollback requires the original deployment audit and the exact segmenter
        currently active. The server rejects stale or conflicting selections.
      </p>
      <label>
        Deployment audit ID to roll back
        <input
          value={deploymentId}
          onChange={(event) => setDeploymentId(event.target.value)}
        />
      </label>
      <label>
        Expected active segmenter ID for rollback
        <input
          value={rollbackActiveId}
          onChange={(event) => setRollbackActiveId(event.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmRollback}
          onChange={(event) => setConfirmRollback(event.target.checked)}
        />{" "}
        I explicitly approve reversing this segmentation deployment
      </label>
      <button
        type="button"
        disabled={!rollbackValid}
        onClick={() => rollback.mutate()}
      >
        {rollback.isPending ? "Recording rollback..." : "Rollback segmentation deployment"}
      </button>
      {rollback.error && <p role="alert">{rollback.error.message}</p>}
      {rollback.data && (
        <p role="status">
          Audited rollback recorded: <code>{rollback.data.id}</code>. Restored
          segmenter <code>{rollback.data.active_model_id ?? "none"}</code>.
        </p>
      )}
    </section>
  );
}
