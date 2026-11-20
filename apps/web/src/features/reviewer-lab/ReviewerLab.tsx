import { useEffect, useState } from "react";
import { AgreementReport } from "./AgreementReport";
import { CreateReviewRound } from "./CreateReviewRound";
import { LabAccess, LabRoles } from "./LabRoles";
import { ReviewRoundPanel } from "./ReviewRoundPanel";
import {
  displayError,
  labRequest,
  type LabReport,
  type LabRole,
  type LabRound,
  type LabSession,
} from "./reviewerLabApi";
import "./reviewerLab.css";

type ReportSummary = { id: string; title: string };
type Props = { projectId: string; onOpenWorkflow: () => void };

export function ReviewerLab({ projectId, onOpenWorkflow }: Props) {
  const [initialized, setInitialized] = useState<boolean>();
  const [session, setSession] = useState<LabSession>();
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [reportId, setReportId] = useState("");
  const [report, setReport] = useState<{ id: string; body: LabReport }>();
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [reportError, setReportError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void labRequest<{ initialized: boolean }>(projectId, "/status", {
      signal: controller.signal,
    }).then(
      (status) => {
        if (!controller.signal.aborted) setInitialized(status.initialized);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    setReportError("");
    void labRequest<ReportSummary[]>(projectId, "/reports", {
      signal: controller.signal,
    }).then(
      (rows) => {
        if (!controller.signal.aborted) setReports(rows);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setReportError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId, refresh]);

  useEffect(() => {
    if (!reportId) return;
    const controller = new AbortController();
    void labRequest<LabReport>(projectId, "/reports/" + reportId, {
      signal: controller.signal,
    }).then(
      (body) => {
        if (!controller.signal.aborted) setReport({ id: reportId, body });
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setReportError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId, reportId]);

  function selectReport(id: string) {
    setReportError("");
    if (id !== reportId) setReport(undefined);
    setReportId(id);
  }

  return (
    <section aria-label="Reviewer lab" className="reviewer-lab">
      <p>
        Assign two independent local reviewers to the same originals, then
        resolve disagreements with a separate adjudicator.
      </p>
      {error && <p role="alert">{error}</p>}
      {initialized !== undefined &&
        (session ? (
          <LabSessionView
            key={session.actor.id}
            projectId={projectId}
            session={session}
            onExit={() => setSession(undefined)}
            onOpenReport={selectReport}
            onSealed={(body) => {
              setReportId(body.id);
              setReport({ id: body.id, body });
              setRefresh((current) => current + 1);
            }}
          />
        ) : (
          <LabAccess
            projectId={projectId}
            initialized={initialized}
            onSession={(active) => {
              setInitialized(true);
              setSession(active);
            }}
          />
        ))}
      <section aria-label="Saved agreement reports" className="panel-card">
        <h3>Saved agreement reports</h3>
        {reports.length ? (
          <label>
            Saved report
            <select
              value={reportId}
              onChange={(event) => selectReport(event.target.value)}
            >
              <option value="">Choose report</option>
              {reports.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p>Sealed agreements appear here.</p>
        )}
        {reportError && <p role="alert">{reportError}</p>}
      </section>
      {report && (
        <AgreementReport
          key={report.id}
          projectId={projectId}
          reportId={report.id}
          report={report.body}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
    </section>
  );
}

function LabSessionView({
  projectId,
  session,
  onExit,
  onSealed,
  onOpenReport,
}: {
  projectId: string;
  session: LabSession;
  onExit: () => void;
  onSealed: (report: LabReport) => void;
  onOpenReport: (reportId: string) => void;
}) {
  const [roles, setRoles] = useState<LabRole[]>([]);
  const [rounds, setRounds] = useState<LabRound[]>([]);
  const [round, setRound] = useState<LabRound>();
  const [roundId, setRoundId] = useState("");
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const isManager = session.actor.role === "manager";
  const key = session.key;

  function refresh() {
    setRevision((current) => current + 1);
    setError("");
  }

  useEffect(() => {
    const controller = new AbortController();
    const options = { key, signal: controller.signal };
    void labRequest<LabRound[]>(projectId, "/rounds", options).then(
      (rows) => {
        if (!controller.signal.aborted) setRounds(rows);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(displayError(reason));
      },
    );
    if (isManager) {
      void labRequest<LabRole[]>(projectId, "/roles", options).then(
        (rows) => {
          if (!controller.signal.aborted) setRoles(rows);
        },
        (reason: unknown) => {
          if (!controller.signal.aborted) setError(displayError(reason));
        },
      );
    }
    return () => controller.abort();
  }, [projectId, key, isManager, revision]);

  useEffect(() => {
    if (!roundId) return;
    const controller = new AbortController();
    void labRequest<LabRound>(projectId, "/rounds/" + roundId, {
      key,
      signal: controller.signal,
    }).then(
      (row) => {
        if (!controller.signal.aborted) setRound(row);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId, key, roundId, revision]);

  return (
    <>
      <section className="panel-card" aria-label="Active local review session">
        <p>
          Signed in as {session.actor.name} · {session.actor.role} · revision{" "}
          {session.actor.revision}
        </p>
        <button type="button" onClick={onExit}>
          End local session
        </button>
      </section>
      {isManager && (
        <>
          <LabRoles
            projectId={projectId}
            session={session}
            roles={roles}
            onChanged={refresh}
          />
          <CreateReviewRound
            projectId={projectId}
            session={session}
            roles={roles}
            onCreated={(row) => {
              setRound(row);
              setRoundId(row.id);
              refresh();
            }}
          />
        </>
      )}
      <section className="panel-card" aria-label="Independent review rounds">
        <h3>{isManager ? "Review rounds" : "My review assignments"}</h3>
        <div className="toolbar-row">
          <label>
            Review round
            <select
              value={roundId}
              onChange={(event) => {
                setRound(undefined);
                setRoundId(event.target.value);
                setError("");
              }}
            >
              <option value="">Choose review round</option>
              {rounds.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={refresh}>
            Refresh assignments
          </button>
          {round?.report_id && (
            <button
              type="button"
              onClick={() => {
                if (round.report_id) onOpenReport(round.report_id);
              }}
            >
              Open sealed agreement
            </button>
          )}
        </div>
        {error && <p role="alert">{error}</p>}
      </section>
      {round && (
        <ReviewRoundPanel
          key={round.id}
          projectId={projectId}
          session={session}
          round={round}
          onRefresh={refresh}
          onSealed={onSealed}
        />
      )}
    </>
  );
}
