import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getDatasetVersions,
  getJob,
  getModels,
  type JobRecord,
  type Project,
} from "../../api/client";
import {
  listSegmentationDeploymentAudit,
  listSegmentationEvaluations,
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
  const [minimumImages, setMinimumImages] = useState(2);
  const [minimumMasks, setMinimumMasks] = useState(2);
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
  const history = useQuery({
    queryKey: ["segmentation-evaluation-history", project.id],
    queryFn: ({ signal }) => listSegmentationEvaluations(project.id, signal),
  });
  const deploymentAudit = useQuery({
    queryKey: ["segmentation-deployment-audit", project.id],
    queryFn: ({ signal }) =>
      listSegmentationDeploymentAudit(project.id, signal),
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
  const activeDeploymentId =
    activeModel?.metadata_json.active_segmentation_deployment_id;
  const rollbackId =
    typeof activeDeploymentId === "string" ? activeDeploymentId : null;
  const candidates = registered.filter((model) => model.id !== activeId);

  const evaluation = useQuery({
    queryKey: ["segmentation-evaluation", project.id, evaluationId],
    queryFn: async ({ signal }) => {
      const record = await getJob(evaluationId, signal);
      if (
        record.project_id !== project.id ||
        record.job_type !== "segmentation_learning_evaluation"
      ) {
        throw new Error("Evaluation does not belong to this project");
      }
      return record;
    },
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
        minimum_images: minimumImages,
        minimum_masks: minimumMasks,
        minimum_mask_map50: minimumMap50,
        minimum_gain: minimumGain,
      }),
    onSuccess: (record) => {
      setEvaluationId(record.id);
      setAuditMessage("");
      void queryClient.invalidateQueries({
        queryKey: ["segmentation-evaluation-history", project.id],
      });
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
        queryKey: ["models", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["segmentation-deployment-audit", project.id],
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
        queryKey: ["models", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["segmentation-deployment-audit", project.id],
      });
    },
  });

  const record = evaluation.data;

  useEffect(() => {
    setEvaluationId("");
    setAuditMessage("");
  }, [project.id]);

  useEffect(() => {
    if (record?.status === "completed" || record?.status === "failed") {
      void queryClient.invalidateQueries({
        queryKey: ["segmentation-evaluation-history", project.id],
      });
    }
  }, [project.id, queryClient, record?.status]);
  const candidateMetrics = metricsFrom(record, "candidate_metrics");
  const incumbentMetrics = metricsFrom(record, "incumbent_metrics");
  const evaluatedCandidateRegistered = registered.some(
    (model) => model.id === record?.request_json.candidate_model_id,
  );
  const eligible =
    record?.project_id === project.id &&
    record.status === "completed" &&
    record.result_json?.promotion_eligible === true &&
    evaluatedCandidateRegistered &&
    !models.isFetching;
  const comparedAgainstCurrent =
    (record?.request_json.incumbent_model_id ?? null) === activeId;
  const approvalReady =
    approvedBy.trim().length >= 2 && reason.trim().length >= 10;
  const validThresholds =
    Number.isInteger(minimumImages) &&
    minimumImages >= 2 &&
    Number.isInteger(minimumMasks) &&
    minimumMasks >= 2 &&
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
        Active segmenter: <strong>{activeModel?.display_name ?? "None"}</strong>
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
          Minimum held-out images
          <input
            type="number"
            min={2}
            step={1}
            value={minimumImages}
            onChange={(event) => setMinimumImages(event.target.valueAsNumber)}
          />
        </label>
        <label>
          Minimum verified instance masks
          <input
            type="number"
            min={2}
            step={1}
            value={minimumMasks}
            onChange={(event) => setMinimumMasks(event.target.valueAsNumber)}
          />
        </label>
        <p className="system-subtle">
          These are minimum dataset checks, not scientific sign-off. A
          representative independent holdout and review remain required.
        </p>
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

      <label>
        Previous segmentation evaluations
        <select
          aria-label="Segmentation evaluation history"
          value={evaluationId}
          onChange={(event) => setEvaluationId(event.target.value)}
        >
          <option value="">Choose an evaluation to inspect</option>
          {history.data?.map((job) => (
            <option key={job.id} value={job.id}>
              {job.status}:{" "}
              {String(job.request_json.candidate_model_id ?? job.id)}
            </option>
          ))}
          {evaluationId &&
            !history.data?.some((job) => job.id === evaluationId) && (
              <option value={evaluationId}>
                Current evaluation: {evaluationId}
              </option>
            )}
        </select>
      </label>
      {history.error && <p role="alert">{history.error.message}</p>}

      {evaluationId && (
        <section aria-label="Held-out segmentation results">
          <h5>Evaluation {evaluationId}</h5>
          <p role="status">
            Status:{" "}
            {record?.status ?? (evaluation.isPending ? "Loading" : "Unknown")}
            {record &&
              ` · ${record.progress_current}/${record.progress_total} inference jobs`}
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
          <details>
            <summary>
              Scientific evaluation provenance and class support
            </summary>
            <dl>
              <dt>Immutable dataset version</dt>
              <dd>
                {String(
                  record?.request_json.dataset_version_id ?? "Not recorded",
                )}
              </dd>
              <dt>Dataset manifest SHA-256</dt>
              <dd>
                {String(record?.request_json.manifest_sha256 ?? "Not recorded")}
              </dd>
              <dt>Holdout split</dt>
              <dd>{String(record?.request_json.split ?? "Not recorded")}</dd>
              <dt>Held-out images</dt>
              <dd>
                {Array.isArray(record?.request_json.heldout_image_ids)
                  ? record.request_json.heldout_image_ids.length
                  : "Not recorded"}
              </dd>
              <dt>Candidate checkpoint SHA-256</dt>
              <dd>
                {String(
                  record?.request_json.candidate_checksum ?? "Not recorded",
                )}
              </dd>
              <dt>Incumbent checkpoint SHA-256</dt>
              <dd>
                {String(record?.request_json.incumbent_checksum ?? "None")}
              </dd>
              <dt>Evaluation-only candidate inference job</dt>
              <dd>
                {String(
                  record?.request_json.candidate_job_id ?? "Not recorded",
                )}
              </dd>
              <dt>Evaluation method</dt>
              <dd>
                {String(
                  record?.result_json?.scientific_method ??
                    "Source-pixel instance mask AP50",
                )}
                ; mask IoU threshold 0.50; count metrics at confidence 0.25.
                AP50:95 is not reported.
              </dd>
            </dl>
            {Boolean(candidateMetrics?.per_class) &&
              typeof candidateMetrics?.per_class === "object" &&
              !Array.isArray(candidateMetrics.per_class) && (
                <table>
                  <caption>Candidate per-class held-out mask support</caption>
                  <thead>
                    <tr>
                      <th scope="col">Class ID</th>
                      <th scope="col">Verified masks</th>
                      <th scope="col">Mask AP50</th>
                      <th scope="col">Precision</th>
                      <th scope="col">Recall</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(
                      candidateMetrics.per_class as Record<string, unknown>,
                    ).map(([classId, value]) => {
                      const values =
                        value && typeof value === "object"
                          ? (value as Record<string, unknown>)
                          : {};
                      return (
                        <tr key={classId}>
                          <th scope="row">{classId}</th>
                          <td>
                            {String(values.ground_truth_count ?? "Unavailable")}
                          </td>
                          <td>{metric(values.ap50)}</td>
                          <td>{metric(values.precision)}</td>
                          <td>{metric(values.recall)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
          </details>
          <p>
            Promotion eligibility:{" "}
            <strong>
              {eligible ? "Eligible, approval required" : "Not eligible"}
            </strong>
          </p>
          {models.isSuccess &&
            record?.result_json?.promotion_eligible === true &&
            !evaluatedCandidateRegistered && (
              <p role="alert">
                The evaluated segmentation candidate is no longer registered for
                this project. Promotion is blocked.
              </p>
            )}
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
            {rollback.isPending
              ? "Rolling back…"
              : "Rollback segmentation deployment"}
          </button>
          {promote.error && <p role="alert">{promote.error.message}</p>}
          {rollback.error && <p role="alert">{rollback.error.message}</p>}
          {auditMessage && <p role="status">{auditMessage}</p>}
        </div>
      </fieldset>
      <section aria-label="Segmentation deployment audit history">
        <h5>Deployment audit history</h5>
        <p className="system-subtle">
          Past model activations and rollbacks are read-only. Viewing these
          records never changes the active segmentation model.
        </p>
        {deploymentAudit.isPending && (
          <p role="status">Loading audit records…</p>
        )}
        {deploymentAudit.error && (
          <p role="alert">{deploymentAudit.error.message}</p>
        )}
        {deploymentAudit.data?.length === 0 && (
          <p>No deployment changes recorded.</p>
        )}
        {deploymentAudit.data && deploymentAudit.data.length > 0 && (
          <ol>
            {deploymentAudit.data.slice(0, 10).map((entry) => {
              const action =
                entry.job_type === "segmentation_learning_deployment_rollback"
                  ? "Rollback"
                  : "Promotion";
              const modelId =
                entry.job_type === "segmentation_learning_deployment_rollback"
                  ? entry.result_json?.restored_model_id
                  : entry.result_json?.active_model_id;
              return (
                <li key={entry.id}>
                  <strong>{action}</strong> —{" "}
                  {String(modelId ?? "No active segmenter")} ·{" "}
                  {String(entry.request_json.approved_by ?? "Unknown operator")}{" "}
                  · {String(entry.request_json.reason ?? "No reason recorded")}
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </article>
  );
}
