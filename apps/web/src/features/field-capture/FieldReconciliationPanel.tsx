import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";

import {
  downloadFieldReconciliation,
  fieldOriginalDownload,
  getFieldReconciliation,
  listFieldReviews,
  reconcileFieldBatch,
  recordFieldReview,
  type FieldBatch,
  type FieldConflict,
  type FieldDecision,
  type FieldReview,
  type FieldSourceEvidence,
} from "./fieldCaptureApi";

const outcomeLabels = {
  imported: "Original imported",
  duplicate_media: "Identical project original reused",
  conflict: "Conflicting observations retained for review",
};

const reasonLabels = {
  source_identity_changed: "The same source identity has different evidence",
  declared_observation_changed:
    "The same observation key has different evidence",
  media_metadata_changed: "Identical media has different field metadata",
};

const decisionLabels: Record<FieldDecision, string> = {
  retain_both: "Retain both records",
  prefer_existing: "Prefer the existing observation",
  prefer_incoming: "Prefer the incoming observation",
};

export function FieldEvidence({ evidence }: { evidence: FieldSourceEvidence }) {
  const { metadata } = evidence;
  return (
    <dl className="field-capture-evidence">
      <dt>Original</dt>
      <dd>
        {evidence.filename} · {evidence.size_bytes.toLocaleString()} bytes
      </dd>
      <dt>Source observation</dt>
      <dd>{evidence.source_observation_id}</dd>
      <dt>SHA-256</dt>
      <dd>
        <code>{evidence.sha256}</code>
      </dd>
      <dt>Observer</dt>
      <dd>{metadata.observer}</dd>
      {metadata.observation_key && (
        <>
          <dt>Observation key</dt>
          <dd>{metadata.observation_key}</dd>
        </>
      )}
      {metadata.site && (
        <>
          <dt>Site</dt>
          <dd>{metadata.site}</dd>
        </>
      )}
      {metadata.subject && (
        <>
          <dt>Subject</dt>
          <dd>{metadata.subject}</dd>
        </>
      )}
      {metadata.source_label && (
        <>
          <dt>Source label</dt>
          <dd>{metadata.source_label}</dd>
        </>
      )}
      {metadata.position && (
        <>
          <dt>Coordinates</dt>
          <dd>
            {metadata.position.latitude}, {metadata.position.longitude} ·{" "}
            {metadata.position.evidence}
          </dd>
        </>
      )}
      <dt>Source wall time</dt>
      <dd>{metadata.clock.wall_time ?? "Unrecorded"}</dd>
      <dt>UTC offset</dt>
      <dd>
        {metadata.clock.utc_offset_minutes === null
          ? "Unknown"
          : `${metadata.clock.utc_offset_minutes} minutes`}
      </dd>
      <dt>Clock evidence</dt>
      <dd>{metadata.clock.evidence}</dd>
      {metadata.notes && (
        <>
          <dt>Notes</dt>
          <dd>{metadata.notes}</dd>
        </>
      )}
    </dl>
  );
}

function ConflictReview({
  projectId,
  batchId,
  observationId,
  conflict,
  decision,
}: {
  projectId: string;
  batchId: string;
  observationId: string;
  conflict: FieldConflict;
  decision: FieldReview | undefined;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: ({
      reviewer,
      notes,
      decision,
    }: {
      reviewer: string;
      notes: string;
      decision: FieldDecision;
    }) =>
      recordFieldReview(projectId, batchId, {
        reviewer,
        notes,
        decision,
        observation_id: observationId,
        against_observation_id: conflict.against_observation_id,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["field-reviews", projectId, batchId],
      }),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const choice = values.get("decision");
    if (
      choice !== "retain_both" &&
      choice !== "prefer_existing" &&
      choice !== "prefer_incoming"
    )
      return;
    mutation.mutate({
      reviewer: String(values.get("reviewer")),
      notes: String(values.get("notes")),
      decision: choice,
    });
  }

  return (
    <details className="field-capture-conflict">
      <summary>
        {reasonLabels[conflict.reason]} · {conflict.against.filename}
      </summary>
      <h5>Existing observation</h5>
      <FieldEvidence evidence={conflict.against} />
      <a
        href={fieldOriginalDownload(
          projectId,
          conflict.against_batch_id,
          conflict.against_observation_id,
        )}
      >
        Download existing original
      </a>
      {decision ? (
        <p>
          <strong>{decisionLabels[decision.decision]}</strong> ·{" "}
          {decision.reviewer} · {decision.notes}
        </p>
      ) : (
        <form aria-label="Review field conflict" onSubmit={submit}>
          <fieldset
            className="field-capture-grid"
            disabled={mutation.isPending}
          >
            <legend>Record a review decision</legend>
            <label>
              Reviewer
              <input name="reviewer" required maxLength={200} />
            </label>
            <label>
              Decision
              <select name="decision" aria-label="Decision">
                {Object.entries(decisionLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Review notes
              <textarea name="notes" required maxLength={2000} rows={2} />
            </label>
            <button type="submit">Save review decision</button>
          </fieldset>
          {mutation.error && <p role="alert">{mutation.error.message}</p>}
        </form>
      )}
    </details>
  );
}

export function FieldReconciliationPanel({
  batch,
  onOpenQC,
}: {
  batch: FieldBatch;
  onOpenQC: () => void;
}) {
  const { id: batchId, project_id: projectId } = batch;
  const manifest = batch.manifest_sha256;
  const queryClient = useQueryClient();
  const resultKey = ["field-reconciliation", projectId, batchId];
  const report = useQuery({
    queryKey: resultKey,
    queryFn: ({ signal }) => getFieldReconciliation(projectId, batchId, signal),
  });
  const reviews = useQuery({
    queryKey: ["field-reviews", projectId, batchId],
    queryFn: ({ signal }) => listFieldReviews(projectId, batchId, signal),
    enabled: !!report.data?.rows.some((row) => row.conflicts.length),
  });
  const reconcile = useMutation({
    mutationFn: (digest: string) =>
      reconcileFieldBatch(projectId, batchId, digest),
    onSuccess: async (receipt) => {
      queryClient.setQueryData(resultKey, receipt);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["images", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["videos", projectId] }),
      ]);
    },
  });
  if (!manifest) return null;

  return (
    <section
      aria-label="Field reconciliation"
      className="field-capture-section"
    >
      <h3>Reconciliation</h3>
      <div className="button-row">
        <button
          type="button"
          disabled={reconcile.isPending}
          onClick={() => reconcile.mutate(manifest)}
        >
          {reconcile.isPending ? "Reconciling…" : "Reconcile field batch"}
        </button>
        {report.data && (
          <>
            <button
              type="button"
              onClick={() => {
                if (report.data)
                  downloadFieldReconciliation(
                    report.data,
                    report.data.report_sha256,
                  );
              }}
            >
              Download field reconciliation JSON
            </button>
            <button type="button" onClick={onOpenQC}>
              Open acquisition quality control
            </button>
          </>
        )}
      </div>
      {(report.error || reconcile.error || reviews.error) && (
        <p role="alert">
          {(report.error || reconcile.error || reviews.error)?.message}
        </p>
      )}
      {report.data && (
        <ul className="field-capture-list">
          {report.data.rows.map((row) => {
            const incoming = batch.observations.find(
              (item) => item.id === row.observation_id,
            );
            return (
              <li key={row.observation_id}>
                <h4>{incoming?.filename ?? row.source_observation_id}</h4>
                <p>{outcomeLabels[row.outcome]}</p>
                {row.conflicts.length > 0 && incoming && (
                  <details>
                    <summary>Incoming field evidence</summary>
                    <FieldEvidence evidence={incoming} />
                  </details>
                )}
                {row.conflicts.map((conflict) => (
                  <ConflictReview
                    key={conflict.against_observation_id}
                    projectId={projectId}
                    batchId={batchId}
                    observationId={row.observation_id}
                    conflict={conflict}
                    decision={reviews.data?.find(
                      (item) =>
                        item.observation_id === row.observation_id &&
                        item.against_observation_id ===
                          conflict.against_observation_id,
                    )}
                  />
                ))}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
