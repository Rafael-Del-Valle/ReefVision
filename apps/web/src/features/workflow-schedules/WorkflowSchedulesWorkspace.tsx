import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useActionConfirmation } from "../../components/ui/ActionConfirmation";
import {
  listSavedWorkflowGraphs,
  type WorkflowGraphRecord,
} from "../workflow-graphs/workflowGraphApi";
import {
  cancelScheduleOccurrence,
  createWorkflowSchedule,
  listScheduleOccurrences,
  listWorkflowSchedules,
  schedulePageSize,
  updateWorkflowSchedule,
  type ScheduleOccurrence,
  type ScheduleOccurrenceStatus,
  type SchedulePurpose,
  type ScheduleStatus,
  type WorkflowSchedule,
  type WorkflowScheduleCreate,
} from "./workflowScheduleApi";
import "./workflowSchedules.css";

const purposes: Record<SchedulePurpose, string> = {
  acquisition: "Acquisition",
  inference: "Inference",
  qc: "Quality control",
  report: "Report",
};

const statuses: Record<ScheduleStatus | ScheduleOccurrenceStatus, string> = {
  scheduled: "Scheduled",
  paused: "Paused",
  queued: "Queued",
  running: "Running",
  waiting_previous_run: "Waiting for previous run",
  waiting_for_review: "Waiting for review",
  blocked_storage: "Blocked by free space",
  dispatch_failed: "Dispatch failed",
  cancel_requested: "Cancellation requested",
  cancelled: "Cancelled",
  succeeded: "Succeeded",
  failed: "Failed",
};

const stoppable = new Set<ScheduleOccurrenceStatus>([
  "queued",
  "running",
  "waiting_for_review",
]);

interface WorkspaceProps {
  projectId: string;
  onOpenWorkflowRun: (runId: string, savedGraph?: WorkflowGraphRecord) => void;
}

const asUtcInput = (stamp: string) =>
  new Date(stamp).toISOString().slice(0, 19);

function UtcTime({ stamp }: { stamp: string }) {
  return (
    <time dateTime={stamp}>{asUtcInput(stamp).replace("T", " ")} UTC</time>
  );
}

function PageControls({
  label,
  offset,
  total,
  onPage,
}: {
  label: string;
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (total <= schedulePageSize) return null;

  return (
    <nav className="pagination" aria-label={label}>
      <button
        className="secondary"
        type="button"
        disabled={offset === 0}
        onClick={() => onPage(offset - schedulePageSize)}
      >
        Previous
      </button>
      <span>
        {offset + 1}–{Math.min(offset + schedulePageSize, total)} of {total}
      </span>
      <button
        className="secondary"
        type="button"
        disabled={offset + schedulePageSize >= total}
        onClick={() => onPage(offset + schedulePageSize)}
      >
        Next
      </button>
    </nav>
  );
}

function ScheduleForm({
  graphs,
  editing,
  pending,
  onSubmit,
  onDiscard,
}: {
  graphs: WorkflowGraphRecord[];
  editing: WorkflowSchedule | null;
  pending: boolean;
  onSubmit: (draft: WorkflowScheduleCreate) => void;
  onDiscard: () => void;
}) {
  const [graphId, setGraphId] = useState(
    editing?.workflow_graph_record_id ?? "",
  );
  const [name, setName] = useState(editing?.name ?? "");
  const due =
    editing?.next_due_at ?? new Date(Date.now() + 60_000).toISOString();
  const [firstDue, setFirstDue] = useState(() => asUtcInput(due));
  const graph = graphs.find((record) => record.id === graphId);
  const graphHash = editing?.graph_sha256 ?? graph?.graph_sha256;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const dueUtc = new Date(`${firstDue}Z`);
    if (!graphId || !name.trim() || Number.isNaN(dueUtc.getTime())) return;
    onSubmit({
      name: name.trim(),
      purpose: editing?.purpose ?? (form.get("purpose") as SchedulePurpose),
      workflow_graph_record_id: graphId,
      interval_seconds: Number(form.get("interval")),
      next_due_at: dueUtc.toISOString().replace(/\.000Z$/, "Z"),
      enabled: form.has("enabled"),
      minimum_free_bytes: Number(form.get("minimum-free")),
    });
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h3>{editing ? `Edit ${editing.name}` : "New schedule"}</h3>
      <div className="dashboard-grid">
        <label>
          Schedule name
          <input
            required
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
          />
        </label>
        <label>
          Purpose
          <select
            name="purpose"
            defaultValue={editing?.purpose ?? "acquisition"}
            disabled={Boolean(editing)}
          >
            {Object.entries(purposes).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Saved workflow revision
          <select
            required
            value={graphId}
            disabled={Boolean(editing)}
            onChange={(event) => setGraphId(event.currentTarget.value)}
          >
            <option value="">Choose a saved workflow</option>
            {editing && !graph && (
              <option value={graphId}>Pinned workflow revision</option>
            )}
            {graphs.map(({ id, name, revision }) => (
              <option key={id} value={id}>
                {name} (revision {revision})
              </option>
            ))}
          </select>
        </label>
        <label>
          {editing ? "Next due (UTC)" : "First due (UTC)"}
          <input
            required
            type="datetime-local"
            step={1}
            value={firstDue}
            onChange={(event) => setFirstDue(event.currentTarget.value)}
          />
        </label>
        <label>
          Repeat interval (seconds)
          <input
            required
            type="number"
            name="interval"
            min={1}
            max={31_536_000}
            step={1}
            defaultValue={editing?.interval_seconds ?? 60}
          />
        </label>
        <label>
          Minimum free storage (bytes)
          <input
            required
            type="number"
            name="minimum-free"
            min={0}
            max={Number.MAX_SAFE_INTEGER}
            step={1}
            defaultValue={editing?.minimum_free_bytes ?? 0}
          />
        </label>
      </div>
      <p className="muted">
        Dates and times are UTC. The selected workflow revision supplies the
        inputs.
        {graphHash && (
          <>
            {" "}
            Workflow SHA-256 <code className="schedule-hash">{graphHash}</code>
          </>
        )}
      </p>
      <label className="checkbox-row">
        <input
          type="checkbox"
          name="enabled"
          defaultChecked={editing?.enabled ?? true}
        />
        Enable schedule
      </label>
      <div className="dashboard-actions">
        <button disabled={pending || !graphId || !name.trim()} type="submit">
          {editing ? "Save schedule changes" : "Create schedule"}
        </button>
        {editing && (
          <button className="secondary" type="button" onClick={onDiscard}>
            Discard changes
          </button>
        )}
      </div>
    </form>
  );
}

function OccurrenceRow({
  item,
  onOpen,
  onCancel,
  pending,
}: {
  item: ScheduleOccurrence;
  onOpen: (runId: string) => void;
  onCancel: (item: ScheduleOccurrence) => void;
  pending: boolean;
}) {
  const runId = item.workflow_run_id;

  return (
    <article className="dashboard-row">
      <div>
        <h4>
          <UtcTime stamp={item.scheduled_at} />
        </h4>
        <span className="count-chip">{statuses[item.status]}</span>
        {item.missed_intervals > 0 && (
          <p>
            {item.missed_intervals} coalesced{" "}
            {item.missed_intervals === 1 ? "interval" : "intervals"}
          </p>
        )}
        {item.detail && <p>{item.detail}</p>}
        <dl className="schedule-identifiers">
          <dt>Occurrence ID</dt>
          <dd>
            <code>{item.id}</code>
          </dd>
          {runId && (
            <>
              <dt>Workflow run ID</dt>
              <dd>
                <code>{runId}</code>
              </dd>
            </>
          )}
          {item.job_id && (
            <>
              <dt>Job ID</dt>
              <dd>
                <code>{item.job_id}</code>
              </dd>
            </>
          )}
          <dt>Workflow SHA-256</dt>
          <dd>
            <code>{item.graph_sha256}</code>
          </dd>
          <dt>Inputs SHA-256</dt>
          <dd>
            <code>{item.inputs_sha256}</code>
          </dd>
        </dl>
      </div>
      <div className="dashboard-actions">
        {runId && (
          <button
            type="button"
            className="secondary"
            onClick={() => onOpen(runId)}
          >
            Open workflow run
          </button>
        )}
        {stoppable.has(item.status) && (
          <button
            type="button"
            className="danger-ghost"
            disabled={pending}
            onClick={() => onCancel(item)}
          >
            Cancel occurrence
          </button>
        )}
      </div>
    </article>
  );
}

function Schedules({ projectId, onOpenWorkflowRun }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const { confirm, confirmationDialog } = useActionConfirmation();
  const [selectedId, setSelectedId] = useState("");
  const [scheduleOffset, setScheduleOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [editing, setEditing] = useState<WorkflowSchedule | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const schedulesKey = ["workflow-schedules", projectId];
  const historyKey = ["workflow-schedule-occurrences", projectId];
  const schedules = useQuery({
    queryKey: [...schedulesKey, scheduleOffset],
    queryFn: ({ signal }) =>
      listWorkflowSchedules(projectId, scheduleOffset, signal),
    refetchInterval: 2_000,
  });
  const graphs = useQuery({
    queryKey: ["saved-workflow-graphs", projectId],
    queryFn: ({ signal }) => listSavedWorkflowGraphs(projectId, signal),
  });
  const current = schedules.data?.items.find(({ id }) => id === selectedId);
  const history = useQuery({
    queryKey: [...historyKey, selectedId, historyOffset],
    queryFn: ({ signal }) =>
      listScheduleOccurrences(projectId, selectedId, historyOffset, signal),
    enabled: Boolean(current),
    refetchInterval: 2_000,
  });

  function refreshSchedules() {
    void queryClient.invalidateQueries({ queryKey: schedulesKey });
    void queryClient.invalidateQueries({ queryKey: historyKey });
  }

  function select(id: string) {
    setSelectedId(id);
    setHistoryOffset(0);
  }

  const save = useMutation({
    mutationFn: (draft: WorkflowScheduleCreate) => {
      if (!editing) return createWorkflowSchedule(projectId, draft);
      return updateWorkflowSchedule(projectId, editing.id, {
        name: draft.name,
        interval_seconds: draft.interval_seconds,
        minimum_free_bytes: draft.minimum_free_bytes,
        enabled: draft.enabled,
        expected_revision: editing.revision,
        ...(asUtcInput(draft.next_due_at) !== asUtcInput(editing.next_due_at)
          ? { next_due_at: draft.next_due_at }
          : {}),
      });
    },
    onSuccess: (record) => {
      if (!editing) setScheduleOffset(0);
      select(record.id);
      setEditing(null);
      setDraftRevision((value) => value + 1);
    },
    onSettled: refreshSchedules,
  });
  const toggle = useMutation({
    mutationFn: (record: WorkflowSchedule) =>
      updateWorkflowSchedule(projectId, record.id, {
        enabled: !record.enabled,
        expected_revision: record.revision,
      }),
    onSettled: refreshSchedules,
  });
  const cancel = useMutation({
    mutationFn: (item: ScheduleOccurrence) =>
      cancelScheduleOccurrence(projectId, item.schedule_id, item.id),
    onSettled: refreshSchedules,
  });
  const pending = save.isPending || toggle.isPending || cancel.isPending;

  async function requestCancellation(item: ScheduleOccurrence) {
    if (
      await confirm({
        title: "Cancel scheduled occurrence",
        message:
          "Request cancellation for this occurrence. The schedule stays active for future runs.",
        confirmLabel: "Request cancellation",
        destructive: true,
      })
    ) {
      cancel.mutate(item);
    }
  }

  const readError = schedules.error ?? graphs.error ?? history.error;
  const actionError = save.error ?? toggle.error ?? cancel.error;

  return (
    <section
      className="dashboard-page schedule-workspace"
      aria-labelledby="workflow-schedules-heading"
    >
      <header className="section-header">
        <h2 id="workflow-schedules-heading">Schedules</h2>
      </header>
      {readError && (
        <p className="form-error" role="alert">
          {readError.message}
        </p>
      )}
      {actionError && (
        <p className="form-error" role="alert">
          {actionError.message}
        </p>
      )}
      <ScheduleForm
        key={editing ? `${editing.id}:${editing.revision}` : draftRevision}
        graphs={graphs.data ?? []}
        editing={editing}
        pending={pending}
        onSubmit={(draft) => {
          toggle.reset();
          cancel.reset();
          save.mutate(draft);
        }}
        onDiscard={() => {
          save.reset();
          setEditing(null);
        }}
      />
      {graphs.isSuccess && graphs.data.length === 0 && (
        <p className="muted">
          Save an executable revision in Workflow builder to schedule it.
        </p>
      )}
      <section className="panel" aria-labelledby="scheduled-workflows-heading">
        <h3 id="scheduled-workflows-heading">Scheduled workflows</h3>
        {schedules.isPending && <p>Loading schedules…</p>}
        {schedules.isSuccess && schedules.data.total === 0 && (
          <p>No schedules in this project.</p>
        )}
        <div className="dashboard-list">
          {schedules.data?.items.map((record) => (
            <div key={record.id} className="dashboard-row">
              <button
                type="button"
                className="secondary"
                aria-pressed={record.id === selectedId}
                onClick={() => select(record.id)}
              >
                {record.name}
              </button>
              <span>
                {purposes[record.purpose]} ·{" "}
                {record.enabled ? "Enabled" : "Paused"} ·{" "}
                {statuses[record.last_status]}
              </span>
            </div>
          ))}
        </div>
        <PageControls
          label="Schedule pages"
          offset={scheduleOffset}
          total={schedules.data?.total ?? 0}
          onPage={setScheduleOffset}
        />
      </section>
      {current && (
        <section
          className="panel"
          aria-label={`Schedule details for ${current.name}`}
        >
          <h3>{current.name}</h3>
          <p>
            Revision {current.revision} · Every {current.interval_seconds}{" "}
            seconds · Minimum free storage{" "}
            {current.minimum_free_bytes.toLocaleString()} bytes
          </p>
          <p>
            Next due <UtcTime stamp={current.next_due_at} />
          </p>
          <p>
            Workflow SHA-256{" "}
            <code className="schedule-hash">{current.graph_sha256}</code>
          </p>
          {current.last_message && <p>{current.last_message}</p>}
          <div className="dashboard-actions">
            <button
              type="button"
              className="secondary"
              disabled={pending}
              onClick={() => {
                save.reset();
                setEditing(current);
              }}
            >
              Edit schedule
            </button>
            <button
              type="button"
              className="secondary"
              disabled={pending}
              onClick={() => {
                save.reset();
                cancel.reset();
                toggle.mutate(current);
              }}
            >
              {current.enabled ? "Pause schedule" : "Resume schedule"}
            </button>
          </div>
          <h4>Occurrence history</h4>
          {history.isPending && <p>Loading occurrences…</p>}
          {history.isSuccess && history.data.total === 0 && (
            <p>No occurrences yet.</p>
          )}
          <div className="dashboard-list">
            {history.data?.items.map((item) => (
              <OccurrenceRow
                key={item.id}
                item={item}
                pending={pending}
                onOpen={(runId) => {
                  const graph = graphs.data?.find(
                    (record) => record.graph_sha256 === item.graph_sha256,
                  );
                  onOpenWorkflowRun(runId, graph);
                }}
                onCancel={(row) => {
                  save.reset();
                  toggle.reset();
                  void requestCancellation(row);
                }}
              />
            ))}
          </div>
          <PageControls
            label="Occurrence pages"
            offset={historyOffset}
            total={history.data?.total ?? 0}
            onPage={setHistoryOffset}
          />
        </section>
      )}
      {confirmationDialog}
    </section>
  );
}

export function WorkflowSchedulesWorkspace(props: WorkspaceProps) {
  return <Schedules key={props.projectId} {...props} />;
}
