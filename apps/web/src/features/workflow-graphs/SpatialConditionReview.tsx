import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  CONDITION_PAGE_SIZE,
  conditionReportUrl,
  decideCondition,
  listConditionRevisions,
  recordCondition,
} from "./spatialConditionApi";
import type {
  ConditionDecision,
  ConditionDecisionKind,
  ConditionRevision,
} from "./spatialConditionApi";

interface Props {
  projectId: string;
  assetId: string;
  sourceSha256: string;
  metadataRevisionId: string | null;
}

export function SpatialConditionReview(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="Biological condition">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        Condition review
      </button>
      {open && (
        <ConditionPanel
          key={`${props.projectId}:${props.assetId}`}
          {...props}
        />
      )}
    </section>
  );
}

function formText(form: FormData, name: string) {
  return String(form.get(name) ?? "").trim();
}

function localTimeToUtc(form: FormData, name: string) {
  return new Date(formText(form, name)).toISOString();
}

function ConditionPanel({
  projectId,
  assetId,
  sourceSha256,
  metadataRevisionId,
}: Props) {
  const [revisions, setRevisions] = useState<ConditionRevision[]>([]);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void listConditionRevisions(projectId, assetId, offset, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setRevisions(items);
      })
      .catch((issue: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            issue instanceof Error
              ? issue.message
              : "Condition history is unavailable.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, assetId, offset, reload]);

  async function save(operation: () => Promise<ConditionRevision>) {
    setBusy(true);
    setError(null);
    try {
      await operation();
      setOffset(0);
      setReload((value) => value + 1);
    } catch (issue) {
      setError(
        issue instanceof Error
          ? issue.message
          : "Condition changes could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  function submitObservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void save(() =>
      recordCondition(projectId, assetId, {
        rubric: {
          rubric_id: formText(form, "rubric"),
          version: formText(form, "version"),
          reference: formText(form, "rubric-reference"),
          observation_unit: formText(form, "unit"),
          labels: formText(form, "rubric-labels")
            .split(/\r?\n/)
            .map((label) => label.trim())
            .filter(Boolean),
        },
        source_sha256: sourceSha256,
        metadata_revision_id: metadataRevisionId,
        observation_unit_id: formText(form, "unit-id"),
        observer_id: formText(form, "observer"),
        observed_at_utc: localTimeToUtc(form, "observed-at"),
        label: formText(form, "label"),
        reference_evidence: formText(form, "observation-evidence"),
        uncertainty: formText(form, "observation-uncertainty"),
      }),
    );
  }

  const superseded = new Set(
    revisions.map((revision) => revision.previous_revision_id),
  );

  return (
    <>
      <p className="muted-copy">
        Use a supplied rubric and evidence reference. Decisions carry local
        attribution.
      </p>
      {error && <p role="alert">{error}</p>}
      <form onSubmit={submitObservation}>
        <fieldset disabled={busy}>
          <legend>Record condition observation</legend>
          <label>
            Rubric ID
            <input name="rubric" required maxLength={128} />
          </label>
          <label>
            Rubric version
            <input name="version" required maxLength={128} />
          </label>
          <label>
            Rubric reference
            <textarea name="rubric-reference" required maxLength={2000} />
          </label>
          <label>
            Observation unit
            <input name="unit" required maxLength={128} />
          </label>
          <label>
            Observation unit ID
            <input name="unit-id" required maxLength={128} />
          </label>
          <label>
            Rubric labels (one per line)
            <textarea name="rubric-labels" required maxLength={6500} />
          </label>
          <label>
            Observed label
            <input name="label" required maxLength={128} />
          </label>
          <label>
            Observer ID
            <input name="observer" required maxLength={128} />
          </label>
          <label>
            Observed at (local time)
            <input name="observed-at" type="datetime-local" step="1" required />
          </label>
          <label>
            Observation evidence
            <textarea name="observation-evidence" required maxLength={2000} />
          </label>
          <label>
            Observation uncertainty
            <textarea
              name="observation-uncertainty"
              required
              maxLength={2000}
            />
          </label>
          <button type="submit">Record observation</button>
        </fieldset>
      </form>
      <h5>Condition history</h5>
      {loading && <p role="status">Loading condition history…</p>}
      {!loading && !error && revisions.length === 0 && (
        <p>No condition observations have been recorded.</p>
      )}
      {revisions.length > 0 && (
        <ol>
          {revisions.map((revision) => (
            <li key={revision.id}>
              <h6>
                {revision.observation.observation_unit_id} ·{" "}
                {revision.observation.rubric.rubric_id}{" "}
                {revision.observation.rubric.version}
              </h6>
              <p>{revisionStatus(revision)}</p>
              <p>
                Observed {revision.observation.label} by{" "}
                {revision.observation.observer_id}.
              </p>
              {revision.decision && (
                <p>
                  {revision.phase === "adjudication"
                    ? "Adjudicator"
                    : "Reviewer"}{" "}
                  {revision.decision.actor_id}. {revision.decision.uncertainty}
                </p>
              )}
              {revision.stale_source_metadata && (
                <p>Asset metadata changed after this observation.</p>
              )}
              <a
                href={conditionReportUrl(projectId, assetId, revision.id)}
                download
              >
                Download report
              </a>
              <details>
                <summary>Workflow Builder IDs</summary>
                <div>
                  Asset ID <code>{assetId}</code>
                </div>
                <div>
                  Condition revision ID <code>{revision.id}</code>
                </div>
              </details>
              {!revision.stale_source_metadata &&
                !superseded.has(revision.id) &&
                canDecide(revision) && (
                  <DecisionForm
                    revision={revision}
                    disabled={busy}
                    onDecision={(decision) =>
                      save(() =>
                        decideCondition(
                          projectId,
                          assetId,
                          revision.id,
                          decision,
                        ),
                      )
                    }
                  />
                )}
            </li>
          ))}
        </ol>
      )}
      <button
        type="button"
        disabled={offset === 0 || loading}
        onClick={() => setOffset(offset - CONDITION_PAGE_SIZE)}
      >
        Newer condition history
      </button>
      <button
        type="button"
        disabled={revisions.length < CONDITION_PAGE_SIZE || loading}
        onClick={() => setOffset(offset + CONDITION_PAGE_SIZE)}
      >
        Older condition history
      </button>
    </>
  );
}

function canDecide(revision: ConditionRevision) {
  return (
    revision.phase === "observation" ||
    (revision.phase === "review" &&
      (revision.decision?.decision === "disagree" ||
        revision.decision?.decision === "inconclusive"))
  );
}

function revisionStatus(revision: ConditionRevision) {
  if (revision.resolved_label)
    return `Local decision: ${revision.resolved_label}`;
  if (revision.decision?.decision === "inconclusive") return "Inconclusive";
  if (revision.decision?.decision === "disagree")
    return `Disagreement: ${revision.decision.label}`;
  return "Awaiting independent review";
}

function DecisionForm({
  revision,
  disabled,
  onDecision,
}: {
  revision: ConditionRevision;
  disabled: boolean;
  onDecision: (decision: ConditionDecision) => Promise<void>;
}) {
  const adjudicating = revision.phase === "review";
  const [kind, setKind] = useState<ConditionDecisionKind>(
    adjudicating ? "adjudicated" : "agree",
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void onDecision({
      actor_id: formText(form, "actor"),
      decision: kind,
      label:
        kind === "disagree" || kind === "adjudicated"
          ? formText(form, "choice")
          : null,
      reference_evidence: formText(form, "review-evidence"),
      decided_at_utc: localTimeToUtc(form, "decided-at"),
      uncertainty: formText(form, "review-uncertainty"),
    });
  }

  return (
    <form onSubmit={submit}>
      <fieldset disabled={disabled}>
        <legend>{adjudicating ? "Adjudication" : "Independent review"}</legend>
        <label>
          {adjudicating ? "Adjudicator ID" : "Reviewer ID"}
          <input name="actor" required maxLength={128} />
        </label>
        <label>
          Decision
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.currentTarget.value as ConditionDecisionKind)
            }
          >
            {adjudicating ? (
              <option value="adjudicated">Adjudicate</option>
            ) : (
              <>
                <option value="agree">Agree</option>
                <option value="disagree">Disagree</option>
              </>
            )}
            <option value="inconclusive">Inconclusive</option>
          </select>
        </label>
        {(kind === "disagree" || kind === "adjudicated") && (
          <label>
            Decision label
            <select name="choice" defaultValue="" required>
              <option value="" disabled>
                Choose a rubric label
              </option>
              {revision.observation.rubric.labels
                .filter(
                  (label) =>
                    kind !== "disagree" || label !== revision.observation.label,
                )
                .map((label) => (
                  <option key={label}>{label}</option>
                ))}
            </select>
          </label>
        )}
        <label>
          Decided at (local time)
          <input name="decided-at" type="datetime-local" step="1" required />
        </label>
        <label>
          Decision evidence
          <textarea name="review-evidence" required maxLength={2000} />
        </label>
        <label>
          Decision uncertainty
          <textarea name="review-uncertainty" required maxLength={2000} />
        </label>
        <button type="submit">Save decision</button>
      </fieldset>
    </form>
  );
}
