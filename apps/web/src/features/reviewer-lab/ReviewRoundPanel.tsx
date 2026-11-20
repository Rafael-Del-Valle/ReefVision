import { useEffect, useState, type FormEvent } from "react";
import {
  displayError,
  labRequest,
  reviewImage,
  values,
  valueLabels,
  type LabDecision,
  type LabReport,
  type LabRound,
  type LabSession,
  type LabSubject,
  type ReviewValue,
} from "./reviewerLabApi";

export function ReviewRoundPanel({
  projectId,
  session,
  round,
  onRefresh,
  onSealed,
}: {
  projectId: string;
  session: LabSession;
  round: LabRound;
  onRefresh: () => void;
  onSealed: (report: LabReport) => void;
}) {
  const [subjectId, setSubjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const subject =
    round.subjects.find((item) => item.id === subjectId) ?? round.subjects[0];
  const isManager = session.actor.role === "manager";
  const ready =
    round.subjects.length > 0 && round.subjects.every((item) => item.complete);

  async function seal() {
    setBusy(true);
    setError("");
    try {
      onSealed(
        await labRequest<LabReport>(
          projectId,
          "/rounds/" + round.id + "/seal",
          {
            key: session.key,
            body: {},
          },
        ),
      );
      onRefresh();
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Selected review round" className="panel-card">
      <h3>{round.title}</h3>
      <p>{round.criterion}</p>
      {round.report_id ? (
        <p role="status">Agreement report sealed.</p>
      ) : isManager ? (
        <>
          <p>
            {round.subjects.filter((item) => item.complete).length} of{" "}
            {round.subjects.length} sources ready to seal.
          </p>
          <button
            disabled={!ready || busy}
            type="button"
            onClick={() => void seal()}
          >
            Seal agreement report
          </button>
        </>
      ) : (
        <p>
          {session.actor.role === "reviewer"
            ? "Your assignment shows your decisions. Peer decisions remain hidden until the round is sealed."
            : "Two committed decisions are required before a disagreement can be adjudicated."}
        </p>
      )}
      {round.subjects.length > 0 && (
        <label>
          Assigned original
          <select
            value={subject?.id ?? ""}
            onChange={(event) => setSubjectId(event.target.value)}
          >
            {round.subjects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.filename}
              </option>
            ))}
          </select>
        </label>
      )}
      {subject && (
        <ReviewSubject
          key={subject.id}
          projectId={projectId}
          session={session}
          round={round}
          subject={subject}
          onCommitted={onRefresh}
        />
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function ReviewSubject({
  projectId,
  session,
  round,
  subject,
  onCommitted,
}: {
  projectId: string;
  session: LabSession;
  round: LabRound;
  subject: LabSubject;
  onCommitted: () => void;
}) {
  const [url, setUrl] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [decoded, setDecoded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [value, setValue] = useState<ReviewValue | "">("");
  const [reason, setReason] = useState("");
  const [operation, setOperation] = useState(() => crypto.randomUUID());
  const isReviewer = session.actor.role === "reviewer";
  const isAdjudicator = session.actor.role === "adjudicator";
  const pair = subject.paired_decisions;
  const canAdjudicate =
    !!pair && pair[0].value !== pair[1].value && !subject.resolution;
  const open =
    !round.report_id &&
    ((isReviewer && !subject.own_decision) || (isAdjudicator && canAdjudicate));
  const roundId = round.id;
  const subjectId = subject.id;
  const accessKey = session.key;

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void reviewImage(
      projectId,
      roundId,
      subjectId,
      accessKey,
      controller.signal,
    ).then(
      (blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setSourceError(displayError(cause));
      },
    );
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId, roundId, subjectId, accessKey]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!value || !decoded) return;
    setBusy(true);
    setError("");
    try {
      const action = isReviewer ? "/decision" : "/adjudication";
      await labRequest<LabDecision>(
        projectId,
        "/rounds/" + roundId + "/subjects/" + subjectId + action,
        {
          key: session.key,
          body: {
            operation_id: operation,
            plan_sha256: round.plan_sha256,
            value,
            reason,
            ...(isAdjudicator && pair
              ? { decision_ids: pair.map((item) => item.id) }
              : {}),
          },
        },
      );
      onCommitted();
    } catch (cause) {
      setError(displayError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-guide" aria-label="Pinned review source">
      <h4>{subject.filename}</h4>
      {url && (
        <img
          src={url}
          alt={"Original " + subject.filename}
          className="reviewer-lab-image"
          onLoad={() => setDecoded(true)}
          onError={() =>
            setSourceError(
              "This original cannot be displayed by the reviewer browser.",
            )
          }
        />
      )}
      {sourceError && <p role="alert">{sourceError}</p>}
      {subject.own_decision && (
        <p role="status">
          Your committed review · {valueLabels[subject.own_decision.value]} ·{" "}
          {subject.own_decision.reason}
        </p>
      )}
      {isAdjudicator && !pair && <p>Waiting for both independent reviewers.</p>}
      {pair && (
        <ol aria-label="Committed independent decisions">
          {pair.map((item) => (
            <li key={item.id}>
              {valueLabels[item.value]} · {item.reason}
            </li>
          ))}
        </ol>
      )}
      {subject.resolution && (
        <p role="status">
          Adjudication committed · {valueLabels[subject.resolution.value]} ·{" "}
          {subject.resolution.reason}
        </p>
      )}
      {open && (
        <form
          onSubmit={(event) => void submit(event)}
          onChange={() => setOperation(crypto.randomUUID())}
        >
          <fieldset disabled={busy || !decoded} className="toolbar-row">
            <label>
              {isReviewer ? "Independent decision" : "Adjudication decision"}
              <select
                required
                value={value}
                onChange={(event) => {
                  const selected = values.find(
                    (item) => item === event.target.value,
                  );
                  setValue(selected ?? "");
                }}
              >
                <option value="">Choose a decision</option>
                {values.map((item) => (
                  <option key={item} value={item}>
                    {valueLabels[item]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Decision reason
              <textarea
                value={reason}
                required
                maxLength={1000}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button type="submit">
              {isReviewer
                ? "Commit independent decision"
                : "Commit adjudication"}
            </button>
          </fieldset>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
