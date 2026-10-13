import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getDatasetVersions,
  getJob,
  getModels,
  type JobRecord,
  type Project,
} from "../../api/client";
import {
  promoteSegmentationCandidate,
  queueSegmentationEvaluation,
  rollbackSegmentationDeployment,
} from "./segmentationEvaluationApi";

type HoldoutSplit = "validation" | "test";

function metric(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "Unavailable";
}

function metricsFrom(job: JobRecord | undefined, name: string) {
  const value = job?.result_json?.[name];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function SegmentationEvaluationPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [datasetId, setDatasetId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [split, setSplit] = useState<HoldoutSplit>("validation");
  const [minimumMap50, setMinimumMap50] = useState(0.5);
  const [minimumGain, setMinimumGain] = useState(0);
  const [evaluationId, setEvaluationId] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [reason, setReason] = useState("");
  const [auditMessage, setAuditMessage] = useState("");

  const versions = useQuery({
    queryKey: ["dataset_versions", project.id, "segmentation-evaluation"],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const models = useQuery({
    queryKey: ["models", project.id, "segmentation-evaluation"],
    queryFn: ({ signal }) => getModels(project.id, undefined, signal),
  });
  const registered = (models.data ?? []).filter(
    (model) => model.purpose === "segmenter" && model.task === "segment",
  );
  const active = registered.filter(
    (model) => model.metadata_json.active_for_predictions === true,
  );
  const activeModel = active.length === 1 ? active[0] : null;
  const activeId = activeModel?.id ?? null;
  const activeDeploymentId = activeModel?.metadata_json.active_segmentation_deployment_id;
  const rollbackId =
    typeof activeDeploymentId === "string" ? activeDeploymentId : null;
  const candidates = registered.filter((model) => model.id !== activeId);

  const evaluation = useQuery({
    queryKey: ["segmentation-evaluation", evaluationId],
    queryFn: ({ signal }) => getJob(evaluationId, signal),
    enabled: Boolean(evaluationId),
    refetchInterval: (query) => {
      const job = query.state.data as JobRecord | undefined;
      return !job || ["waiting", "queued", "running"].includes(job.status)
        ? 2000
        : false;
    },
  });

  const enqueue = useMutation({
    mutationFn: () =>
      queueSegmentationEvaluation(project.id, {
        dataset_version_id: datasetId,
        candidate_model_id: candidateId,
        incumbent_model_id: activeId,
        split,
        minimum_images: 2,
        minimum_masks: 2,
        minimum_mask_map50: minimumMap50,
        minimum_gain: minimumGain,
      }),
    onSuccess: (record) => {
      setEvaluationId(record.id);
      setAuditMessage("");
    },
  });
  const promote = useMutation({
    mutationFn: () =>
      promoteSegmentationCandidate(
        project.id,
        evaluationId,
        activeId,
        approvedBy.trim(),
        reason.trim(),
      ),
    onSuccess: async (audit) => {
      setAuditMessage(`Promotion audit recorded: ${audit.id}`);
      await queryClient.invalidateQueries({
        queryKey: ["models", project.id, "segmentation-evaluation"],
      });
    },
  });
  const rollback = useMutation({
    mutationFn: () =>
      rollbackSegmentationDeployment(
        project.id,
        rollbackId ?? "",
        activeId ?? "",
        approvedBy.trim(),
        reason.trim(),
      ),
    onSuccess: async (audit) => {
      setAuditMessage(`Rollback audit recorded: ${audit.id}`);
      await queryClient.invalidateQueries({
        queryKey: ["models", project.id, "segmentation-evaluation"],
      });
    },
  });

  const record = evaluation.data;
  const candidateMetrics = metricsFrom(record, "candidate_metrics");
  const incumbentMetrics = metricsFrom(record, "incumbent_metrics");
  const eligible =
    record?.status === "completed" &&
    record.result_json?.promotion_eligible === true;
  const comparedAgainstCurrent =
    (record?.request_json.incumbent_model_id ?? null) === activeId;
  const approvalReady =
    approvedBy.trim().length >= 2 && reason.trim().length >= 10;
  const validThresholds =
    Number.isFinite(minimumMap50) &&
    minimumMap50 >= 0 &&
    minimumMap50 <= 1 &&
    Number.isFinite(minimumGain) &&
    minimumGain >= 0 &&
    minimumGain <= 1;
  const blockedByMultipleActive = active.length > 1;

  return (
    <article className="system-card" aria-label="Segmentation evaluation">
      <h4>Evaluate segmentation candidate</h4>
      <p className="system-subtle">
        Queue evaluation-only inference on an immutable, verified-mask holdout.
        Results use source-pixel instance mask AP50, not detector box AP.
        Evaluation never activates a model automatically.
      </p>
      {blockedByMultipleActive && (
        <p role="alert">
          Multiple active segmenters detected. Resolve the conflicting model
          selection before evaluating or changing deployment.
        </p>
      )}
      <p>
        Active segmenter:{" "}
        <strong>{activeModel?.display_name ?? "None"}</strong>
      </p>
      <div className="training-run-list">
        <label>
          Verified dataset version
          <select
            aria-label="Segmentation holdout dataset"
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
          >
            <option value="">Select immutable dataset</option>
            {versions.data
              ?.filter((version) => version.status === "complete")
              .map((version) => (
                <option key={version.id} value={version.id}>
                  {version.name} (v{version.version_number})
                </option>
              ))}
          </select>
        </label>
        <label>
          Candidate segmenter
          <select
            aria-label="Candidate segmenter"
            value={candidateId}
            onChange={(event) => setCandidateId(event.target.value)}
          >
            <option value="">Select registered model</option>
            {candidates.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Holdout split
          <select
            aria-label="Segmentation evaluation split"
            value={split}
            onChange={(event) => setSplit(event.target.value as HoldoutSplit)}
          >
            <option value="validation">Validation</option>
            <option value="test">Test</option>
          </select>
        </label>
        <label>
          Minimum instance mask AP50
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={minimumMap50}
            onChange={(event) => setMinimumMap50(event.target.valueAsNumber)}
          />
        </label>
        <label>
          Minimum gain over incumbent
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={minimumGain}
            onChange={(event) => setMinimumGain(event.target.valueAsNumber)}
          />
        </label>
        <button
          type="button"
          disabled={
            !datasetId ||
            !candidateId ||
            !validThresholds ||
            blockedByMultipleActive ||
            enqueue.isPending
          }
          onClick={() => enqueue.mutate()}
        >
          {enqueue.isPending ? "Queueing…" : "Queue held-out evaluation"}
        </button>
        {enqueue.error && <p role="alert">{enqueue.error.message}</p>}
        {versions.error && <p role="alert">{versions.error.message}</p>}
        {models.error && <p role="alert">{models.error.message}</p>}
      </div>

      {evaluationId && (
        <section aria-label="Held-out segmentation results">
          <h5>Evaluation {evaluationId}</h5>
          <p role="status">
            Status: {record?.status ?? (evaluation.isPending ? "Loading" : "Unknown")}
            {record && ` · ${record.progress_current}/${record.progress_total} inference jobs`}
          </p>
          {evaluation.error && <p role="alert">{evaluation.error.message}</p>}
          {record?.error_message && <p role="alert">{record.error_message}</p>}
          {candidateMetrics && (
            <dl>
              <dt>Candidate mask AP50</dt>
              <dd>{metric(candidateMetrics.mask_map50)}</dd>
              <dt>Candidate count MAE</dt>
              <dd>{metric(candidateMetrics.mean_absolute_count_error)}</dd>
              <dt>Candidate count bias per image</dt>
              <dd>{metric(candidateMetrics.count_bias_per_image)}</dd>
              <dt>Candidate precision / recall</dt>
              <dd>
                {metric(candidateMetrics.precision)} /{" "}
                {metric(candidateMetrics.recall)}
              </dd>
            </dl>
          )}
          {incumbentMetrics && (
            <dl>
              <dt>Incumbent mask AP50</dt>
              <dd>{metric(incumbentMetrics.mask_map50)}</dd>
              <dt>Incumbent count MAE</dt>
              <dd>{metric(incumbentMetrics.mean_absolute_count_error)}</dd>
            </dl>
          )}
          <p>
            Promotion eligibility:{" "}
            <strong>{eligible ? "Eligible, approval required" : "Not eligible"}</strong>
          </p>
          {Array.isArray(record?.result_json?.blockers) && (
            <ul>
              {record.result_json.blockers.map((blocker, index) => (
                <li key={index}>{String(blocker)}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      <fieldset>
        <legend>Audited human approval</legend>
        <label>
          Operator identity
          <input
            value={approvedBy}
            onChange={(event) => setApprovedBy(event.target.value)}
          />
        </label>
        <label>
          Reason (at least 10 characters)
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <div className="training-run-list">
          <button
            type="button"
            disabled={
              !eligible ||
              !comparedAgainstCurrent ||
              !approvalReady ||
              blockedByMultipleActive ||
              promote.isPending
            }
            onClick={() => {
              if (
                window.confirm(
                  "Promote the evaluated segmentation candidate? This changes the active segmenter.",
                )
              ) {
                promote.mutate();
              }
            }}
          >
            {promote.isPending ? "Promoting…" : "Promote evaluated segmenter"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              !rollbackId ||
              !activeId ||
              !approvalReady ||
              blockedByMultipleActive ||
              rollback.isPending
            }
            onClick={() => {
              if (
                window.confirm(
                  "Rollback the active segmentation deployment? This changes the active segmenter.",
                )
              ) {
                rollback.mutate();
              }
            }}
          >
            {rollback.isPending ? "Rolling back…" : "Rollback segmentation deployment"}
          </button>
          {promote.error && <p role="alert">{promote.error.message}</p>}
          {rollback.error && <p role="alert">{rollback.error.message}</p>}
          {auditMessage && <p role="status">{auditMessage}</p>}
        </div>
      </fieldset>
    </article>
  );
}
