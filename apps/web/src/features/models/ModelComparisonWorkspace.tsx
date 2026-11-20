import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import { useSelections } from "./ReviewedModelRuntime";

const tasks = {
  detector: "Detector",
  mask: "Mask",
  pose: "Pose",
  tracking: "Tracking",
  event: "Event",
};
type Task = keyof typeof tasks;
const compatible: Record<Task, string[]> = {
  detector: ["detect"],
  mask: ["segment", "semantic_segment"],
  pose: ["pose"],
  tracking: ["pose"],
  event: ["pose"],
};
interface Source {
  id: string;
  sha256: string;
  label: string;
  model_ids: string[];
  reference_id: string;
  reference_sha256: string;
}
interface Metric {
  name: string;
  unit: string;
  left: number | null;
  right: number | null;
}
interface Estimate extends Metric {
  right_minus_left: number | null;
  groups: number;
  paired_observations: number;
  missing_pairs: number;
}
interface Observation {
  media_kind: "image" | "video";
  media_id: string;
  frame: number | null;
  seconds: number | null;
  metrics: Metric[];
  exclusion: string | null;
}
interface Result {
  snapshot: {
    comparison_id: string;
    summary: {
      method: string;
      metrics: Estimate[];
      excluded_observations: number;
      group_count: number;
    };
    evidence: {
      reference_sha256: string;
      evaluation_status: string;
      method: string;
      limitations: string[];
      groups: { group_id: string; observations: Observation[] }[];
    };
  };
  source_id_map: Record<string, string>;
  content_sha256: string;
}
interface Item {
  id: string;
  task: Task;
  status: string;
  content_sha256: string | null;
  error_message: string | null;
}
interface Job {
  id: string;
  status: string;
  result_json: Result | null;
  error_message: string | null;
}
type OpenSource = (
  kind: Observation["media_kind"],
  id: string,
  frame: number | null,
  seconds: number | null,
) => void;

function ResultPanel({
  report,
  projectId,
  id,
  onOpen,
  onWorkflow,
}: {
  report: Result;
  projectId: string;
  id: string;
  onOpen: OpenSource;
  onWorkflow: () => void;
}) {
  const { summary, evidence } = report.snapshot;
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const rows = evidence.groups
    .flatMap((group) =>
      group.observations.map((obs) => ({ group: group.group_id, obs })),
    )
    .filter(
      ({ obs }) =>
        showAll ||
        Boolean(obs.exclusion) ||
        obs.metrics.some((m) => m.left !== m.right),
    );
  const base =
    getApiBaseUrl() +
    "/projects/" +
    projectId +
    "/paired-model-comparisons/" +
    id +
    "/export?format=";
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      saveWorkflowGraph(projectId, {
        graph_id: "paired-models-" + id,
        name: "Paired model comparison · " + id.slice(0, 8),
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "comparison",
            node_type: "paired_model_comparison",
            parameters: {
              comparison_id: id,
              comparison_sha256: report.content_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-comparison",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "comparison",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["workflow-graphs", projectId] }),
  });
  return (
    <section aria-label="Paired comparison results">
      <h3>Paired results</h3>
      <p>
        {evidence.evaluation_status === "held_out" ? "Held-out" : "Exploratory"}{" "}
        · {summary.group_count} independent groups ·{" "}
        {summary.excluded_observations} excluded observations
      </p>
      <p>{evidence.method}</p>
      <p>{summary.method}</p>
      <table>
        <caption>Equal-weight group means</caption>
        <thead>
          <tr>
            {[
              "Metric",
              "Unit",
              "Left",
              "Right",
              "Right minus left",
              "Groups",
              "Paired observations",
              "Missing pairs",
            ].map((text) => (
              <th key={text}>{text}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {summary.metrics.map((m) => (
            <tr key={m.name + "-" + m.unit}>
              <td>{m.name}</td>
              <td>{m.unit}</td>
              {[m.left, m.right, m.right_minus_left].map((n, i) => (
                <td key={i}>
                  {n?.toLocaleString(undefined, {
                    maximumSignificantDigits: 6,
                  }) ?? "Unavailable"}
                </td>
              ))}
              <td>{m.groups}</td>
              <td>{m.paired_observations}</td>
              <td>{m.missing_pairs}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>Disagreements and exclusions</h4>
      <label>
        <input
          type="checkbox"
          checked={showAll}
          onChange={(e) => {
            setShowAll(e.target.checked);
            setPage(0);
          }}
        />
        Include matching observations
      </label>
      {!rows.length && <p>No observations meet this filter.</p>}
      <ul>
        {rows.slice(page * 25, (page + 1) * 25).map(({ group, obs }, i) => (
          <li key={group + "-" + obs.media_id + "-" + i}>
            <button
              type="button"
              onClick={() =>
                onOpen(
                  obs.media_kind,
                  report.source_id_map[obs.media_id] ?? obs.media_id,
                  obs.frame,
                  obs.seconds,
                )
              }
            >
              Open {obs.media_kind} {obs.media_id.slice(0, 8)}
              {obs.frame != null
                ? " · frame " + obs.frame
                : obs.seconds != null
                  ? " · " + obs.seconds + " s"
                  : ""}
            </button>{" "}
            · {group} ·{" "}
            {obs.exclusion ??
              obs.metrics
                .filter((m) => m.left !== m.right)
                .map(
                  (m) =>
                    m.name +
                    " " +
                    (m.left ?? "—") +
                    " / " +
                    (m.right ?? "—") +
                    " " +
                    m.unit,
                )
                .join(", ")}
          </li>
        ))}
      </ul>
      {rows.length > 25 && (
        <div>
          <button disabled={!page} onClick={() => setPage(page - 1)}>
            Previous observations
          </button>
          <button
            disabled={(page + 1) * 25 >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Next observations
          </button>
        </div>
      )}
      <details>
        <summary>Methods, limitations and hashes</summary>
        <ul>
          {evidence.limitations.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        <p>
          Frozen reference <code>{evidence.reference_sha256}</code>
        </p>
        <p>
          Report SHA-256 <code>{report.content_sha256}</code>
        </p>
      </details>
      <a href={base + "json"} download>
        Export comparison JSON
      </a>
      {" · "}
      <a href={base + "csv"} download>
        Export paired observations CSV
      </a>{" "}
      <button
        type="button"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        Save comparison workflow
      </button>
      {save.isSuccess && (
        <button onClick={onWorkflow}>Open saved comparison workflow</button>
      )}
      {save.error && <p role="alert">{save.error.message}</p>}
    </section>
  );
}

export function ModelComparisonWorkspace({
  projectId,
  onOpen,
  onWorkflow,
}: {
  projectId: string;
  onOpen: OpenSource;
  onWorkflow: () => void;
}) {
  const [task, setTask] = useState<Task>("detector");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const cache = useQueryClient();
  const base = "/projects/" + projectId + "/paired-model-comparisons";
  const image = task === "detector" || task === "mask";
  const models = useSelections(projectId);
  const a = models.data?.find((x) => x.id === left && !x.requires_re_review),
    b = models.data?.find((x) => x.id === right && !x.requires_re_review);
  const sources = useQuery({
    queryKey: ["paired-sources", projectId, task],
    queryFn: ({ signal }) =>
      request<Source[]>(base + "/sources?task=" + task, { signal }),
  });
  const history = useQuery({
    queryKey: ["paired-models", projectId, offset],
    queryFn: ({ signal }) =>
      request<Item[]>(base + "?offset=" + offset, { signal }),
    refetchInterval: (q) =>
      q.state.data?.some((x) =>
        ["queued", "running", "cancel_requested"].includes(x.status),
      )
        ? 1200
        : false,
  });
  const result = useQuery({
    queryKey: ["paired-model", projectId, selected],
    queryFn: ({ signal }) => request<Job>(base + "/" + selected, { signal }),
    enabled: Boolean(selected),
    refetchInterval: (q) =>
      q.state.data &&
      ["queued", "running", "cancel_requested"].includes(q.state.data.status)
        ? 800
        : false,
  });
  const leftSource = sources.data?.find((x) => x.id === first),
    rightSource = sources.data?.find((x) => x.id === second);
  const launch = useMutation({
    mutationFn: () =>
      request<Job>(base, {
        method: "POST",
        body: JSON.stringify({
          task,
          left: { id: a!.id, sha256: a!.content_sha256 },
          right: { id: b!.id, sha256: b!.content_sha256 },
          sources: (image ? [leftSource!] : [leftSource!, rightSource!]).map(
            (x) => ({ id: x.id, sha256: x.sha256 }),
          ),
        }),
      }),
    onSuccess: (job) => {
      setSelected(job.id);
      setOffset(0);
      void cache.invalidateQueries({ queryKey: ["paired-models", projectId] });
    },
  });
  function modelField(
    side: "Left" | "Right",
    value: string,
    change: (v: string) => void,
  ) {
    return (
      <label>
        {side} reviewed configuration
        <select
          value={value}
          onChange={(e) => {
            change(e.target.value);
            setFirst("");
            setSecond("");
          }}
        >
          <option value="">Choose a model</option>
          {models.data
            ?.filter((m) => compatible[task].includes(m.snapshot.task))
            .map((m) => (
              <option key={m.id} value={m.id} disabled={m.requires_re_review}>
                {m.snapshot.display_name} · {m.snapshot.settings.device} ·{" "}
                {m.content_sha256.slice(0, 12)}
                {m.requires_re_review ? " · Review again in Model Hub" : ""}
              </option>
            ))}
        </select>
      </label>
    );
  }
  function sourceField(
    label: string,
    value: string,
    change: (v: string) => void,
    choices: Source[],
  ) {
    return (
      <label>
        {label}
        <select value={value} onChange={(e) => change(e.target.value)}>
          <option value="">Choose frozen evidence</option>
          {choices.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label} · {s.sha256.slice(0, 12)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  const choices = sources.data ?? [];
  return (
    <section aria-label="Model comparison">
      <h2>Model comparison</h2>
      <label>
        Comparison task
        <select
          value={task}
          onChange={(e) => {
            setTask(e.target.value as Task);
            setLeft("");
            setRight("");
            setFirst("");
            setSecond("");
          }}
        >
          {Object.entries(tasks).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      {modelField("Left", left, setLeft)}
      {modelField("Right", right, setRight)}
      {sourceField(
        image ? "Frozen dataset" : "Left held-out score",
        first,
        (v) => {
          setFirst(v);
          setSecond("");
        },
        choices.filter(
          (s) => image || Boolean(a && s.model_ids.includes(a.model_id)),
        ),
      )}
      {!image &&
        sourceField(
          "Right held-out score",
          second,
          setSecond,
          choices.filter((s) =>
            Boolean(
              b &&
              s.model_ids.includes(b.model_id) &&
              leftSource &&
              s.reference_sha256 === leftSource.reference_sha256,
            ),
          ),
        )}
      <button
        type="button"
        disabled={
          launch.isPending ||
          !a ||
          !b ||
          a.model_id === b.model_id ||
          !leftSource ||
          (!image && !rightSource)
        }
        onClick={() => launch.mutate()}
      >
        Run paired comparison
      </button>
      {[
        models.error,
        sources.error,
        history.error,
        result.error,
        launch.error,
      ].map(
        (e, i) =>
          e && (
            <p role="alert" key={i}>
              {e.message}
            </p>
          ),
      )}
      <h3>Saved comparisons</h3>
      {!history.data?.length && <p>No comparisons on this page.</p>}
      <ul>
        {history.data?.map((x) => (
          <li key={x.id}>
            <button onClick={() => setSelected(x.id)}>
              {tasks[x.task]} · {x.id.slice(0, 8)} · {x.status}
            </button>
          </li>
        ))}
      </ul>
      {(offset > 0 || history.data?.length === 25) && (
        <div>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(offset - 25)}
          >
            Previous comparisons
          </button>
          <button
            disabled={history.data?.length !== 25}
            onClick={() => setOffset(offset + 25)}
          >
            Next comparisons
          </button>
        </div>
      )}
      {result.data && (
        <p role="status">
          {result.data.status}
          {result.data.error_message && " · " + result.data.error_message}
        </p>
      )}
      {result.data?.status === "succeeded" && result.data.result_json && (
        <ResultPanel
          key={selected}
          report={result.data.result_json}
          projectId={projectId}
          id={selected}
          onOpen={onOpen}
          onWorkflow={onWorkflow}
        />
      )}
    </section>
  );
}
