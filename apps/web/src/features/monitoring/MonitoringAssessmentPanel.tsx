import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";

import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  getMonitoringRule,
  listMonitoringAlerts,
  listMonitoringReviews,
  reviewMonitoringAlert,
  type MonitoringAlert,
  type MonitoringAssessment,
  type MonitoringSourceReference,
  type ReviewDecision,
} from "./monitoringApi";
import {
  MonitoringFields,
  monitoringLabel,
  monitoringUtc,
} from "./monitoringPresentation";

export const monitoringRuleKey = (projectId: string, ruleId: string) => [
  "monitoring-rule",
  projectId,
  ruleId,
];

function SourceEvidence({
  reference,
}: {
  reference: MonitoringSourceReference;
}) {
  const {
    source,
    acquired_at,
    observed_at,
    original_value,
    normalized_value,
    qc,
  } = reference;
  return (
    <MonitoringFields
      fields={{
        kind: monitoringLabel(reference.kind),
        source_id: reference.id,
        ...(source && { source }),
        ...(observed_at && { observed_at: monitoringUtc(observed_at) }),
        ...(acquired_at && { acquired_at: monitoringUtc(acquired_at) }),
        ...(original_value != null && {
          original_quantity:
            `${original_value} ${reference.original_unit ?? ""}`.trim(),
        }),
        ...(normalized_value != null && {
          normalized_quantity:
            `${normalized_value} ${reference.normalized_unit ?? ""}`.trim(),
        }),
        ...(qc && { source_qc: qc }),
        sha256: reference.sha256,
      }}
    />
  );
}

function ReviewFinding({
  alert,
  onReview,
}: {
  alert: MonitoringAlert;
  onReview: () => void;
}) {
  const [reason, setReason] = useState("");
  const cache = useQueryClient();
  const key = ["monitoring-alert-history", alert.project_id, alert.id];
  const history = useInfiniteQuery({
    queryKey: key,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      listMonitoringReviews(alert.project_id, alert.id, pageParam, signal),
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total && last.items.length > 0
        ? last.offset + last.items.length
        : undefined,
  });
  const review = useMutation({
    mutationFn: (decision: ReviewDecision) =>
      reviewMonitoringAlert(
        alert.project_id,
        alert.id,
        alert.review_revision,
        decision,
        reason.trim(),
      ),
    onSuccess: () => {
      setReason("");
      void cache.invalidateQueries({ queryKey: key });
    },
    onSettled: onReview,
  });
  const reviews = history.data?.pages.flatMap((page) => page.items) ?? [];
  const blocked =
    alert.source_status === "stale" || review.isPending || !reason.trim();
  return (
    <div className="monitoring-review">
      {alert.source_status === "stale" && (
        <p>
          Source evidence is stale. Run a new assessment to review current
          evidence.
        </p>
      )}
      <label>
        Review reason
        <textarea
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
      </label>
      <div className="dashboard-actions">
        <button
          type="button"
          disabled={blocked}
          onClick={() => review.mutate("confirmed")}
        >
          Confirm finding
        </button>
        <button
          type="button"
          className="secondary"
          disabled={blocked}
          onClick={() => review.mutate("dismissed")}
        >
          Dismiss finding
        </button>
      </div>
      {review.error && (
        <p className="form-error" role="alert">
          {review.error.message}
        </p>
      )}
      <section aria-label="Review history">
        <h5>Review history</h5>
        {history.error && (
          <p className="form-error" role="alert">
            {history.error.message}
          </p>
        )}
        {history.isSuccess && !reviews.length && (
          <p>No attributed reviews yet.</p>
        )}
        <ul>
          {reviews.map((entry) => (
            <li key={entry.id}>
              <p>
                {entry.decision === "confirmed" ? "Confirmed" : "Dismissed"} by{" "}
                {entry.reviewer} · {monitoringUtc(entry.reviewed_at)} · revision{" "}
                {entry.revision}
              </p>
              <p>{entry.reason}</p>
            </li>
          ))}
        </ul>
        {history.hasNextPage && (
          <button
            className="secondary"
            type="button"
            disabled={history.isFetchingNextPage}
            onClick={() => void history.fetchNextPage()}
          >
            Load more reviews
          </button>
        )}
      </section>
    </div>
  );
}

function Findings({ assessment }: { assessment: MonitoringAssessment }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState("");
  const key = ["monitoring-alerts", assessment.project_id, assessment.id];
  const alerts = useInfiniteQuery({
    queryKey: key,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      listMonitoringAlerts(
        assessment.project_id,
        assessment.id,
        pageParam,
        signal,
      ),
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total && last.items.length > 0
        ? last.offset + last.items.length
        : undefined,
  });
  const rows = alerts.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <section className="panel" aria-label="Monitoring findings">
      <h3>Findings</h3>
      {alerts.isPending && <p>Loading findings…</p>}
      {alerts.error && (
        <p className="form-error" role="alert">
          {alerts.error.message}
        </p>
      )}
      {alerts.isSuccess && !rows.length && (
        <p>No proposed findings for this window.</p>
      )}
      <div className="dashboard-list">
        {rows.map((alert) => (
          <article
            className="dashboard-card"
            key={alert.id}
            aria-label={alert.proposal.detail}
          >
            <div className="section-heading">
              <h4>{monitoringLabel(alert.kind)}</h4>
              <span className="count-chip">
                {alert.status === "proposed"
                  ? "Proposed"
                  : alert.status === "confirmed"
                    ? "Confirmed"
                    : "Dismissed"}
              </span>
            </div>
            <p>{alert.proposal.detail}</p>
            {Boolean(alert.proposal.source_ids?.length) && (
              <details>
                <summary>Inspect linked evidence</summary>
                {assessment.result.source_refs
                  .filter((entry) =>
                    alert.proposal.source_ids?.includes(entry.id),
                  )
                  .map((entry) => (
                    <SourceEvidence key={entry.id} reference={entry} />
                  ))}
              </details>
            )}
            {alert.proposal.observed_at && (
              <p>{monitoringUtc(alert.proposal.observed_at)}</p>
            )}
            {alert.proposal.value !== undefined &&
              alert.proposal.value !== null && (
                <MonitoringFields
                  fields={{
                    value: alert.proposal.value,
                    threshold: alert.proposal.threshold,
                  }}
                />
              )}
            {alert.latest_review && (
              <p>
                Last reviewed by {alert.latest_review.reviewer} ·{" "}
                {monitoringUtc(alert.latest_review.reviewed_at)}
              </p>
            )}
            <button
              className="secondary"
              type="button"
              aria-expanded={selected === alert.id}
              onClick={() => setSelected(selected === alert.id ? "" : alert.id)}
            >
              {selected === alert.id ? "Close review" : "Review finding"}
            </button>
            {selected === alert.id && (
              <ReviewFinding
                alert={alert}
                onReview={() => {
                  void cache.invalidateQueries({ queryKey: key });
                }}
              />
            )}
          </article>
        ))}
      </div>
      {alerts.hasNextPage && (
        <button
          className="secondary"
          type="button"
          disabled={alerts.isFetchingNextPage}
          onClick={() => void alerts.fetchNextPage()}
        >
          Load more findings
        </button>
      )}
    </section>
  );
}

export function MonitoringAssessmentPanel({
  assessment,
  onOpenWorkflow,
}: {
  assessment: MonitoringAssessment;
  onOpenWorkflow?: () => void;
}) {
  const cache = useQueryClient();
  const rule = useQuery({
    queryKey: monitoringRuleKey(assessment.project_id, assessment.rule_id),
    queryFn: ({ signal }) =>
      getMonitoringRule(assessment.project_id, assessment.rule_id, signal),
  });
  const save = useMutation({
    mutationFn: (ruleSha256: string) =>
      saveWorkflowGraph(assessment.project_id, {
        graph_id: `monitoring-assessment-${assessment.id}`,
        name: `Monitoring assessment · ${monitoringUtc(assessment.window_start)}`,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "assessment",
            node_type: "monitoring_assessment",
            parameters: {
              rule_id: assessment.rule_id,
              rule_sha256: ruleSha256,
              assessment_id: assessment.id,
              assessment_sha256: assessment.result_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-assessment",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "assessment",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["workflow-graphs", assessment.project_id],
      });
      onOpenWorkflow?.();
    },
  });
  const result = assessment.result;
  const ruleDigest = rule.data?.rule_sha256;
  return (
    <>
      <section className="panel" aria-label="Assessment evidence">
        <h3>Assessment evidence</h3>
        <p>
          {monitoringUtc(assessment.window_start)} to{" "}
          {monitoringUtc(assessment.window_end)}
        </p>
        <MonitoringFields
          fields={{
            source: result.kind,
            ...(result.method && { method: result.method }),
            protocol: result.protocol,
            metric: monitoringLabel(result.metric),
            unit: result.unit,
            estimate:
              result.estimate === null
                ? null
                : `${result.estimate} ${result.unit}`,
          }}
        />
        <p>
          Source status ·{" "}
          {assessment.source_status === "current" ? "Current" : "Stale"}
        </p>
        {!!assessment.stale_reasons.length && (
          <ul>
            {assessment.stale_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        <h4>Effort</h4>
        <MonitoringFields fields={result.effort} />
        <details>
          <summary>Source evidence ({result.source_refs.length})</summary>
          <p>
            Evidence SHA-256 <code>{assessment.evidence_sha256}</code>
          </p>
          <ul>
            {result.source_refs.map((ref) => (
              <li key={`${ref.kind}-${ref.id}`}>
                <SourceEvidence reference={ref} />
              </li>
            ))}
          </ul>
        </details>
        {!!result.biological_sessions?.length && (
          <details>
            <summary>
              Reviewed biological sessions ({result.biological_sessions.length})
            </summary>
            {result.biological_sessions.map((session) => (
              <MonitoringFields
                key={`${session.summary_id}-${session.link_revision_id}`}
                fields={{
                  ...session,
                  observed_at: session.observed_at
                    ? monitoringUtc(session.observed_at)
                    : null,
                }}
              />
            ))}
          </details>
        )}
        {!!result.exclusions.length && (
          <details>
            <summary>Excluded evidence ({result.exclusions.length})</summary>
            <ul>
              {result.exclusions.map((entry, index) => (
                <li key={index}>
                  {entry.reason}
                  {entry.observed_at
                    ? ` · ${monitoringUtc(entry.observed_at)}`
                    : ""}
                  {entry.source_id && (
                    <>
                      {" "}
                      · <code>{entry.source_id}</code>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
        <p>
          Result SHA-256 <code>{assessment.result_sha256}</code>
        </p>
        <button
          type="button"
          className="secondary"
          disabled={!ruleDigest || save.isPending}
          onClick={() => {
            if (ruleDigest) save.mutate(ruleDigest);
          }}
        >
          Save assessment workflow
        </button>
        {save.isSuccess && <p role="status">Saved in Workflow Builder.</p>}
        {(rule.error || save.error) && (
          <p className="form-error" role="alert">
            {(rule.error ?? save.error)?.message}
          </p>
        )}
      </section>
      <Findings assessment={assessment} />
    </>
  );
}
