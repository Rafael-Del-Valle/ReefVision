import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { getProjectSummaries } from "../../api/client";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  createMonitoringSummary,
  downloadMonitoringSummary,
  getMonitoringSummary,
  listMonitoringSummaries,
  type MonitoringSummary,
  type MonitoringSummarySelection,
} from "./monitoringApi";
import {
  assessmentLabel,
  MonitoringFields,
  monitoringLabel,
  monitoringUtc,
  useMonitoringAssessments,
} from "./monitoringPresentation";
import "./monitoring.css";

function AssessmentSelect({
  label,
  projectId,
  value,
  onChange,
}: {
  label: string;
  projectId: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const assessments = useMonitoringAssessments(projectId);
  const records = assessments.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <label>
        {label}
        <select
          required
          disabled={!projectId || !records.length}
          value={value}
          onChange={(event) => onChange(event.currentTarget.value)}
        >
          <option value="">Choose a saved assessment</option>
          {records.map((record) => (
            <option key={record.id} value={record.id}>
              {assessmentLabel(record)}
            </option>
          ))}
        </select>
      </label>
      {assessments.isSuccess && !records.length && (
        <p>No saved assessments in this project.</p>
      )}
      {assessments.error && (
        <p role="alert" className="form-error">
          {assessments.error.message}
        </p>
      )}
      {assessments.hasNextPage && (
        <button
          className="secondary"
          type="button"
          disabled={assessments.isFetchingNextPage}
          onClick={() => void assessments.fetchNextPage()}
        >
          Load more assessments
        </button>
      )}
    </div>
  );
}

function SummaryDetail({
  summary,
  onOpenWorkflow,
}: {
  summary: MonitoringSummary;
  onOpenWorkflow?: () => void;
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      saveWorkflowGraph(summary.project_id, {
        graph_id: `monitoring-summary-${summary.id}`,
        name: `Monitoring project summary · ${monitoringUtc(summary.created_at)}`,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "summary",
            node_type: "monitoring_project_summary",
            parameters: {
              summary_id: summary.id,
              content_sha256: summary.content_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-summary",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "summary",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workflow-graphs", summary.project_id],
      });
      onOpenWorkflow?.();
    },
  });
  const download = useMutation({
    mutationFn: () => downloadMonitoringSummary(summary.project_id, summary),
  });
  const error = download.error ?? save.error;
  return (
    <section className="panel" aria-label="Saved project summary">
      <h3>Saved project summary</h3>
      <p>{monitoringUtc(summary.created_at)}</p>
      <p>
        Summary SHA-256 <code>{summary.content_sha256}</code>
      </p>
      <div className="dashboard-actions">
        <button
          className="secondary"
          type="button"
          disabled={download.isPending}
          onClick={() => download.mutate()}
        >
          Download summary JSON
        </button>
        <button
          className="secondary"
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save summary workflow
        </button>
      </div>
      {save.isSuccess && <p role="status">Saved in Workflow Builder.</p>}
      {error && (
        <p role="alert" className="form-error">
          {error.message}
        </p>
      )}
      <div className="dashboard-list">
        {summary.snapshot.rows.map((row) => (
          <article
            className="dashboard-card"
            key={row.project_id}
            aria-label={row.project_name}
          >
            <div className="section-heading">
              <h4>{row.project_name}</h4>
              <span className="count-chip">
                {row.status === "included" ? "Included" : "Excluded"}
              </span>
            </div>
            {row.project_id === summary.snapshot.reference_project_id && (
              <p>Reference project</p>
            )}
            <p>
              {monitoringUtc(row.window_start)} to{" "}
              {monitoringUtc(row.window_end)}
            </p>
            <MonitoringFields
              fields={{
                metric: monitoringLabel(row.metric),
                unit: row.unit,
                protocol: row.protocol,
                project_id: row.project_id,
                assessment_id: row.assessment_id,
                rule_id: row.rule_id,
              }}
            />
            {!!row.reasons.length && (
              <ul>
                {row.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            <h5>Effort</h5>
            <MonitoringFields fields={row.effort} />
            <h5>Values</h5>
            <MonitoringFields
              fields={{
                estimate:
                  row.values.estimate === null
                    ? null
                    : `${row.values.estimate} ${row.unit}`,
                method: row.values.method,
              }}
            />
            <h5>Review</h5>
            <MonitoringFields
              fields={{
                proposed: row.review.proposed,
                confirmed: row.review.confirmed,
                dismissed: row.review.dismissed,
              }}
            />
            {!!row.review.alerts.length && (
              <details>
                <summary>Finding decisions</summary>
                <ul>
                  {row.review.alerts.map((alert) => (
                    <li key={alert.alert_id}>
                      {monitoringLabel(alert.kind)} · {alert.status}
                      {alert.latest_review && (
                        <p>
                          {alert.latest_review.reviewer} ·{" "}
                          {monitoringUtc(alert.latest_review.reviewed_at)} ·{" "}
                          {alert.latest_review.reason}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <details>
              <summary>Evidence and independent units</summary>
              <MonitoringFields
                fields={{
                  rule_sha256: row.rule_sha256,
                  result_sha256: row.result_sha256,
                  evidence_sha256: row.evidence_sha256,
                  source_records: row.values.source_refs,
                  independent_units: row.values.independent_units,
                  exclusions: row.values.exclusions,
                  rule_parameters: row.values.rule_parameters,
                }}
              />
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}

const emptyPeer = { project_id: "", assessment_id: "" };

export function MonitoringProjectSummaries({
  projectId,
  onOpenWorkflow,
}: {
  projectId: string;
  onOpenWorkflow?: () => void;
}) {
  const cache = useQueryClient();
  const [reference, setReference] = useState("");
  const [peers, setPeers] = useState([emptyPeer]);
  const [selected, setSelected] = useState("");
  const key = ["monitoring-project-summaries", projectId];
  const projects = useQuery({
    queryKey: ["project_summaries"],
    queryFn: ({ signal }) => getProjectSummaries(signal),
  });
  const available =
    projects.data?.filter((project) => project.id !== projectId) ?? [];
  const saved = useInfiniteQuery({
    queryKey: key,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      listMonitoringSummaries(projectId, pageParam, signal),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce(
        (count, page) => count + page.items.length,
        0,
      );
      return loaded < last.total && last.items.length ? loaded : undefined;
    },
  });
  const summaryKey = (id: string) => [
    "monitoring-project-summary",
    projectId,
    id,
  ];
  const details = useQuery({
    queryKey: summaryKey(selected),
    queryFn: ({ signal }) => getMonitoringSummary(projectId, selected, signal),
    enabled: Boolean(selected),
  });
  const create = useMutation({
    mutationFn: (selections: MonitoringSummarySelection[]) =>
      createMonitoringSummary(projectId, selections),
    onSuccess: (summary) => {
      cache.setQueryData(summaryKey(summary.id), summary);
      setSelected(summary.id);
      void cache.invalidateQueries({ queryKey: key });
    },
  });

  function updatePeer(index: number, replacement: MonitoringSummarySelection) {
    setPeers((rows) =>
      rows.map((row, position) => (position === index ? replacement : row)),
    );
  }

  const ready =
    reference &&
    peers.every((peer) => peer.project_id && peer.assessment_id) &&
    new Set(peers.map((peer) => peer.project_id)).size === peers.length;

  function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready)
      create.mutate([
        { project_id: projectId, assessment_id: reference },
        ...peers,
      ]);
  }

  const records = saved.data?.pages.flatMap((page) => page.items) ?? [];
  const error = projects.error ?? saved.error ?? details.error ?? create.error;
  return (
    <section className="monitoring-workspace" aria-label="Project summaries">
      <form className="panel" onSubmit={compare}>
        <h3>Compare project assessments</h3>
        <p>
          Use the current project as the reference. Each project keeps its own
          values and review state.
        </p>
        <AssessmentSelect
          projectId={projectId}
          label="Reference assessment"
          value={reference}
          onChange={setReference}
        />
        {projects.isSuccess && available.length === 0 && (
          <p>
            Add another local project with a saved assessment to compare
            projects.
          </p>
        )}
        {peers.map((peer, index) => (
          <div className="dashboard-grid monitoring-peer" key={index}>
            <label>
              Comparison project {index + 1}
              <select
                required
                disabled={!available.length}
                value={peer.project_id}
                onChange={(event) =>
                  updatePeer(index, {
                    project_id: event.currentTarget.value,
                    assessment_id: "",
                  })
                }
              >
                <option value="">Choose another project</option>
                {available
                  .filter(
                    ({ id }) =>
                      !peers.some(
                        (row, position) =>
                          row.project_id === id && position !== index,
                      ),
                  )
                  .map(({ id, name, archived_at }) => (
                    <option key={id} value={id}>
                      {name}
                      {archived_at ? " (archived)" : ""}
                    </option>
                  ))}
              </select>
            </label>
            <AssessmentSelect
              projectId={peer.project_id}
              label={`Comparison assessment ${index + 1}`}
              value={peer.assessment_id}
              onChange={(id) =>
                updatePeer(index, { ...peer, assessment_id: id })
              }
            />
            {peers.length > 1 && (
              <button
                className="secondary"
                type="button"
                onClick={() =>
                  setPeers((rows) =>
                    rows.filter((_, position) => position !== index),
                  )
                }
              >
                Remove project {index + 1}
              </button>
            )}
          </div>
        ))}
        <div className="dashboard-actions">
          <button
            type="button"
            className="secondary"
            disabled={peers.length >= Math.min(19, available.length)}
            onClick={() => setPeers((rows) => [...rows, emptyPeer])}
          >
            Add comparison project
          </button>
          <button type="submit" disabled={!ready || create.isPending}>
            Compare projects
          </button>
        </div>
      </form>
      {error && (
        <p role="alert" className="form-error">
          {error.message}
        </p>
      )}
      <section className="panel" aria-label="Saved project summaries">
        <h3>Saved project summaries</h3>
        {saved.isPending && <p>Loading summaries…</p>}
        {saved.isSuccess && !records.length && (
          <p>No saved project summaries.</p>
        )}
        <div className="dashboard-list">
          {records.map((record) => (
            <button
              key={record.id}
              type="button"
              className="secondary"
              aria-pressed={record.id === selected}
              onClick={() => setSelected(record.id)}
            >
              Open project summary {monitoringUtc(record.created_at)}
            </button>
          ))}
        </div>
        {saved.hasNextPage && (
          <button
            className="secondary"
            type="button"
            disabled={saved.isFetchingNextPage}
            onClick={() => void saved.fetchNextPage()}
          >
            Load more summaries
          </button>
        )}
      </section>
      {details.data && (
        <SummaryDetail
          key={details.data.id}
          summary={details.data}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
    </section>
  );
}
