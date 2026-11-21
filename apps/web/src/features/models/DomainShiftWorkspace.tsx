import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import {
  adjustmentPin,
  listAdjustments,
  type ImageAdjustmentPin,
} from "../annotation-editor/imageAdjustmentApi";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";

type Cohort = "reference" | "target";
type Mode = "original" | "adjusted";

interface SourceEntry {
  id: string;
  content_sha256: string;
  task: string;
  reference_sha256: string;
  lineage: string;
  model_labels: string[];
}

interface DomainSource extends SourceEntry {
  groups: {
    group_id: string;
    images: { id: string; exclusion: string | null }[];
  }[];
}

interface DomainEstimate {
  reference_n: number;
  target_n: number;
  reference_mean: number | null;
  target_mean: number | null;
  target_minus_reference: number | null;
  se: number | null;
  ci95: [number, number] | null;
  interval_status: string;
}

interface Report {
  content_sha256: string;
  snapshot: {
    declaration: {
      reference: { label: string };
      target: { label: string };
      independent_unit: string;
      preprocessing: Mode;
    };
    reference: { manifest_sha256: string };
    models: { label: string; checkpoint_sha256: string }[];
    lineage_reasons: string[];
    summary: {
      status: string;
      lineage: string;
      metrics: {
        name: string;
        unit: string;
        left: DomainEstimate;
        right: DomainEstimate;
        paired_gap: DomainEstimate;
      }[];
      groups: {
        group_id: string;
        domain: Cohort;
        status: string;
        observations: number;
        exclusions: string[];
      }[];
      outside_declared_roster: string[];
      assumptions: string[];
    };
  };
}

interface DomainJob {
  id: string;
  status: string;
  error_message: string | null;
  result_json: Report | null;
}

const pending = (status?: string) =>
  ["queued", "running", "cancel_requested"].includes(status ?? "");
const planned = (text: string) =>
  text
    .split("\n")
    .map((value) => value.trim())
    .filter(Boolean);
const format = (value: number | null) =>
  value == null
    ? "Unavailable"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(
        value,
      );

function AdjustmentChoice({
  imageId,
  value,
  onChange,
}: {
  imageId: string;
  value: ImageAdjustmentPin | undefined;
  onChange: (pin?: ImageAdjustmentPin) => void;
}) {
  const [page, setPage] = useState(1);
  const choices = useQuery({
    queryKey: ["domain-shift-adjustments", imageId, page],
    queryFn: ({ signal }) => listAdjustments(imageId, page, signal),
  });
  return (
    <div>
      <label>
        Adjustment for image {imageId.slice(0, 8)}
        <select
          value={value?.recipe_id ?? ""}
          onChange={(event) => {
            const row = choices.data?.items.find(
              (item) => item.id === event.target.value,
            );
            onChange(row ? adjustmentPin(row) : undefined);
          }}
        >
          <option value="">Choose a saved recipe</option>
          {value &&
            !choices.data?.items.some(
              (item) => item.id === value.recipe_id,
            ) && (
              <option value={value.recipe_id}>
                {value.content_sha256.slice(0, 12)}
              </option>
            )}
          {choices.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.content_sha256.slice(0, 12)}
            </option>
          ))}
        </select>
      </label>
      {choices.error && <p role="alert">{choices.error.message}</p>}
      {!!choices.data && choices.data.total === 0 && (
        <p>No saved adjustments for this image.</p>
      )}
      {!!choices.data && choices.data.total > choices.data.page_size && (
        <div>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            Previous recipes
          </button>
          <button
            type="button"
            disabled={page * choices.data.page_size >= choices.data.total}
            onClick={() => setPage(page + 1)}
          >
            More recipes
          </button>
        </div>
      )}
    </div>
  );
}

function DomainReport({
  projectId,
  job,
  onWorkflow,
}: {
  projectId: string;
  job: DomainJob;
  onWorkflow: () => void;
}) {
  const client = useQueryClient();
  const report = job.result_json!;
  const { snapshot, content_sha256 } = report;
  const { summary, declaration } = snapshot;
  const save = useMutation({
    mutationFn: () =>
      saveWorkflowGraph(projectId, {
        graph_id: `domain-shift-${job.id}`,
        name: `Domain shift · ${job.id.slice(0, 8)}`,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "domain",
            node_type: "domain_shift_report",
            parameters: { report_id: job.id, content_sha256 },
          },
        ],
        edges: [
          {
            edge_id: "project-domain",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "domain",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () =>
      void client.invalidateQueries({
        queryKey: ["workflow-graphs", projectId],
      }),
  });
  const exportPath = `${getApiBaseUrl()}/projects/${projectId}/domain-shift/${job.id}`;
  return (
    <section aria-label="Domain shift results">
      <h4>
        {declaration.reference.label} and {declaration.target.label}
      </h4>
      <p>
        {summary.status === "withheld"
          ? "Domain estimates withheld"
          : "Held-out domain comparison"}{" "}
        · {summary.lineage}
      </p>
      <p>
        Independent unit: {declaration.independent_unit} · Input:{" "}
        {declaration.preprocessing}
      </p>
      {snapshot.lineage_reasons.map((reason) => (
        <p key={reason}>{reason}</p>
      ))}
      <dl>
        <dt>Frozen reference SHA-256</dt>
        <dd>{snapshot.reference.manifest_sha256}</dd>
        <dt>Report SHA-256</dt>
        <dd>{content_sha256}</dd>
        {snapshot.models.map((model) => (
          <div key={model.checkpoint_sha256}>
            <dt>{model.label} checkpoint</dt>
            <dd>{model.checkpoint_sha256}</dd>
          </div>
        ))}
      </dl>
      {summary.metrics.length > 0 && (
        <div className="table-scroll">
          <table aria-label="Domain shift estimates">
            <thead>
              <tr>
                <th>Measure</th>
                <th>Model or gap</th>
                <th>Reference mean (groups)</th>
                <th>Target mean (groups)</th>
                <th>Target − reference</th>
                <th>SE</th>
                <th>95% interval</th>
              </tr>
            </thead>
            <tbody>
              {summary.metrics.flatMap((row) =>
                (
                  [
                    [snapshot.models[0].label, row.left],
                    [snapshot.models[1].label, row.right],
                    ["Paired model gap", row.paired_gap],
                  ] as [string, DomainEstimate][]
                ).map(([label, estimate]) => (
                  <tr key={`${row.name}-${row.unit}-${label}`}>
                    <td>
                      {row.name} · {row.unit}
                    </td>
                    <td>{label}</td>
                    <td>
                      {format(estimate.reference_mean)} ({estimate.reference_n})
                    </td>
                    <td>
                      {format(estimate.target_mean)} ({estimate.target_n})
                    </td>
                    <td>{format(estimate.target_minus_reference)}</td>
                    <td>{format(estimate.se)}</td>
                    <td>
                      {estimate.ci95
                        ? estimate.ci95.map(format).join(" to ")
                        : estimate.interval_status.replaceAll("_", " ")}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}
      <details open>
        <summary>Group coverage and exclusions</summary>
        <ul>
          {summary.groups.map((row) => (
            <li key={`${row.domain}-${row.group_id}`}>
              {row.group_id} · {declaration[row.domain].label} · {row.status} ·{" "}
              {row.observations} images
              {row.exclusions.length > 0 && ` · ${row.exclusions.join("; ")}`}
            </li>
          ))}
        </ul>
        {!!summary.outside_declared_roster.length && (
          <p>
            Outside the declared roster:{" "}
            {summary.outside_declared_roster.join(", ")}
          </p>
        )}
      </details>
      <details>
        <summary>Method and assumptions</summary>
        <ul>
          {summary.assumptions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
      <div className="button-row">
        <a href={`${exportPath}/report`}>Export domain report JSON</a>
        <a href={`${exportPath}/groups.csv`}>Export acquisition groups CSV</a>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save domain replay to Workflow Builder
        </button>
        {save.isSuccess && (
          <button type="button" onClick={onWorkflow}>
            Open Workflow Builder
          </button>
        )}
      </div>
      {save.error && <p role="alert">{save.error.message}</p>}
    </section>
  );
}

export function DomainShiftWorkspace({
  projectId,
  onWorkflow,
}: {
  projectId: string;
  onWorkflow: () => void;
}) {
  const client = useQueryClient();
  const base = `/projects/${projectId}/domain-shift`;
  const [sourceId, setSourceId] = useState("");
  const [sourceOffset, setSourceOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [selectedReport, setSelectedReport] = useState("");
  const [reference, setReference] = useState("");
  const [target, setTarget] = useState("");
  const [independentUnit, setIndependentUnit] = useState("");
  const [assignment, setAssignment] = useState<Record<string, string>>({});
  const [missingReference, setMissingReference] = useState("");
  const [missingTarget, setMissingTarget] = useState("");
  const [mode, setMode] = useState<Mode>("original");
  const [pins, setPins] = useState<Record<string, ImageAdjustmentPin>>({});
  const [recipePage, setRecipePage] = useState(0);
  const sources = useQuery({
    queryKey: ["domain-shift-sources", projectId, sourceOffset],
    queryFn: ({ signal }) =>
      request<SourceEntry[]>(`${base}/sources?offset=${sourceOffset}`, {
        signal,
      }),
  });
  const source = useQuery({
    queryKey: ["domain-shift-source", projectId, sourceId],
    queryFn: ({ signal }) =>
      request<DomainSource>(`${base}/sources/${sourceId}`, { signal }),
    enabled: Boolean(sourceId),
  });
  const history = useQuery({
    queryKey: ["domain-shift-history", projectId, historyOffset],
    queryFn: ({ signal }) =>
      request<DomainJob[]>(`${base}?offset=${historyOffset}`, { signal }),
    refetchInterval: ({ state }) =>
      state.data?.some((item) => pending(item.status)) ? 1000 : false,
  });
  const selected = useQuery({
    queryKey: ["domain-shift-report", projectId, selectedReport],
    queryFn: ({ signal }) =>
      request<DomainJob>(`${base}/${selectedReport}`, { signal }),
    enabled: Boolean(selectedReport),
    refetchInterval: ({ state }) => (pending(state.data?.status) ? 800 : false),
  });
  const images =
    source.data?.groups.flatMap((group) =>
      group.images.filter((row) => !row.exclusion).map((row) => row.id),
    ) ?? [];
  const groupLists = {
    reference: [
      ...Object.keys(assignment).filter(
        (key) => assignment[key] === "reference",
      ),
      ...planned(missingReference),
    ],
    target: [
      ...Object.keys(assignment).filter((key) => assignment[key] === "target"),
      ...planned(missingTarget),
    ],
  };
  const groupKeys = [...groupLists.reference, ...groupLists.target].map(
    (value) => value.trim().toLowerCase(),
  );
  const ready =
    !!source.data &&
    reference.trim() &&
    target.trim() &&
    reference.trim().toLowerCase() !== target.trim().toLowerCase() &&
    independentUnit.trim() &&
    groupLists.reference.length &&
    groupLists.target.length &&
    new Set(groupKeys).size === groupKeys.length &&
    (mode === "original" ||
      (images.length > 0 && images.every((id) => pins[id])));
  const launch = useMutation({
    mutationFn: () =>
      request<DomainJob>(base, {
        method: "POST",
        body: JSON.stringify({
          comparison_id: sourceId,
          comparison_sha256: source.data!.content_sha256,
          reference: { label: reference, groups: groupLists.reference },
          target: { label: target, groups: groupLists.target },
          independent_unit: independentUnit,
          preprocessing: mode,
          adjustments:
            mode === "adjusted"
              ? images.map((image_id) => ({ image_id, ...pins[image_id] }))
              : [],
        }),
      }),
    onSuccess: (job) => {
      setSelectedReport(job.id);
      setHistoryOffset(0);
      void client.invalidateQueries({
        queryKey: ["domain-shift-history", projectId],
      });
    },
  });
  const resetSource = (value: string) => {
    setSourceId(value);
    setAssignment({});
    setPins({});
    setRecipePage(0);
  };
  return (
    <section aria-label="Domain shift">
      <h3>Domain shift</h3>
      <label>
        Completed paired comparison
        <select
          value={sourceId}
          onChange={(event) => resetSource(event.target.value)}
        >
          <option value="">Choose frozen still evidence</option>
          {sources.data?.map((item) => (
            <option key={item.id} value={item.id}>
              {item.model_labels.join(" and ")} · {item.task} ·{" "}
              {item.content_sha256.slice(0, 12)}
            </option>
          ))}
        </select>
      </label>
      {sourceOffset > 0 || sources.data?.length === 20 ? (
        <div className="button-row">
          <button
            type="button"
            disabled={!sourceOffset}
            onClick={() => {
              resetSource("");
              setSourceOffset(sourceOffset - 20);
            }}
          >
            Previous paired sources
          </button>
          <button
            type="button"
            disabled={sources.data?.length !== 20}
            onClick={() => {
              resetSource("");
              setSourceOffset(sourceOffset + 20);
            }}
          >
            More paired sources
          </button>
        </div>
      ) : null}
      {source.data && (
        <>
          <p>
            Frozen holdout: {source.data.reference_sha256} ·{" "}
            {source.data.lineage}
          </p>
          <label>
            Reference domain
            <input
              value={reference}
              onChange={(event) => setReference(event.target.value)}
            />
          </label>
          <label>
            Target domain
            <input
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            />
          </label>
          <label>
            Declared independent unit
            <input
              value={independentUnit}
              onChange={(event) => setIndependentUnit(event.target.value)}
              placeholder="For example, one surveyed site"
            />
          </label>
          <fieldset>
            <legend>Assign frozen acquisition groups</legend>
            {source.data.groups.map((group) => (
              <label key={group.group_id}>
                Group {group.group_id}
                <select
                  value={assignment[group.group_id] ?? ""}
                  onChange={(event) =>
                    setAssignment((previous) => ({
                      ...previous,
                      [group.group_id]: event.target.value,
                    }))
                  }
                >
                  <option value="">Outside roster</option>
                  <option value="reference">Reference</option>
                  <option value="target">Target</option>
                </select>
              </label>
            ))}
          </fieldset>
          <label>
            Planned missing reference groups, one per line
            <textarea
              value={missingReference}
              onChange={(event) => setMissingReference(event.target.value)}
            />
          </label>
          <label>
            Planned missing target groups, one per line
            <textarea
              value={missingTarget}
              onChange={(event) => setMissingTarget(event.target.value)}
            />
          </label>
          <label>
            Model input preprocessing
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as Mode)}
            >
              <option value="original">
                Original inputs from the frozen comparison
              </option>
              <option value="adjusted">
                Rerun both models on pinned adjustments
              </option>
            </select>
          </label>
          {mode === "adjusted" && (
            <fieldset>
              <legend>
                Pick the same adjustment settings for every usable frozen test
                image
              </legend>
              <p>
                {images.filter((id) => pins[id]).length} of {images.length}{" "}
                signed recipes selected
              </p>
              {images
                .slice(recipePage * 12, (recipePage + 1) * 12)
                .map((id) => (
                  <AdjustmentChoice
                    key={id}
                    imageId={id}
                    value={pins[id]}
                    onChange={(pin) =>
                      setPins((previous) => {
                        const next = { ...previous };
                        if (pin) next[id] = pin;
                        else delete next[id];
                        return next;
                      })
                    }
                  />
                ))}
              {images.length > 12 && (
                <div className="button-row">
                  <button
                    type="button"
                    disabled={!recipePage}
                    onClick={() => setRecipePage(recipePage - 1)}
                  >
                    Previous images
                  </button>
                  <button
                    type="button"
                    disabled={(recipePage + 1) * 12 >= images.length}
                    onClick={() => setRecipePage(recipePage + 1)}
                  >
                    More images
                  </button>
                </div>
              )}
            </fieldset>
          )}
          <button
            type="button"
            disabled={!ready || launch.isPending}
            onClick={() => launch.mutate()}
          >
            Run domain shift analysis
          </button>
        </>
      )}
      {[
        sources.error,
        source.error,
        history.error,
        selected.error,
        launch.error,
      ].map(
        (error, index) =>
          error && (
            <p role="alert" key={index}>
              {error.message}
            </p>
          ),
      )}
      <h4>Saved domain analyses</h4>
      <ul>
        {history.data?.map((item) => (
          <li key={item.id}>
            <button type="button" onClick={() => setSelectedReport(item.id)}>
              Domain shift · {item.id.slice(0, 8)} · {item.status}
            </button>
          </li>
        ))}
      </ul>
      {historyOffset || history.data?.length === 20 ? (
        <div className="button-row">
          <button
            type="button"
            disabled={!historyOffset}
            onClick={() => setHistoryOffset(historyOffset - 20)}
          >
            Previous domain analyses
          </button>
          <button
            type="button"
            disabled={history.data?.length !== 20}
            onClick={() => setHistoryOffset(historyOffset + 20)}
          >
            More domain analyses
          </button>
        </div>
      ) : null}
      {selected.data && (
        <p role="status">
          {selected.data.status}
          {selected.data.error_message && ` · ${selected.data.error_message}`}
        </p>
      )}
      {selected.data?.status === "succeeded" && selected.data.result_json && (
        <DomainReport
          key={selectedReport}
          projectId={projectId}
          job={selected.data}
          onWorkflow={onWorkflow}
        />
      )}
    </section>
  );
}
