import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  coralDownload,
  listCoralCorrespondence,
  listCoralGraphs,
  listCoralGrowth,
  reviewCoralCorrespondence,
  saveCoralGrowth,
  type GraphRecord,
  type Match,
  type MatchKind,
} from "./coralGraphApi";

type DraftMatch = Match & { key: number };

function GraphSelect({
  label,
  value,
  graphs,
  onChange,
}: {
  label: string;
  value: string;
  graphs: GraphRecord[];
  onChange: (id: string) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose observation</option>
        {graphs.map((row) => (
          <option key={row.id} value={row.id}>
            {row.snapshot.organism_key} · {row.snapshot.observed_at} ·{" "}
            {row.snapshot.edges.length} branches
          </option>
        ))}
      </select>
    </label>
  );
}

function BranchChoices({
  label,
  graph,
  selected,
  onChange,
}: {
  label: string;
  graph?: GraphRecord;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <label>
      {label}
      <select
        multiple
        size={Math.min(5, Math.max(2, graph?.snapshot.edges.length ?? 0))}
        value={selected}
        onChange={(event) =>
          onChange(
            Array.from(
              event.currentTarget.selectedOptions,
              (option) => option.value,
            ),
          )
        }
      >
        {graph?.snapshot.edges.map((edge, index) => (
          <option key={edge.id} value={edge.id}>
            {index + 1} · {edge.id.slice(0, 8)} ·{" "}
            {edge.length_physical?.toFixed(3) ??
              edge.node_to_node_length_pixels.toFixed(2)}{" "}
            {graph.snapshot.calibration?.unit ?? "px"}
          </option>
        ))}
      </select>
    </label>
  );
}

export function CoralGrowthPanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const graphsQuery = useQuery({
    queryKey: ["coral-graphs", projectId],
    queryFn: ({ signal }) => listCoralGraphs(projectId, signal),
  });
  const correspondenceQuery = useQuery({
    queryKey: ["coral-correspondences", projectId],
    queryFn: ({ signal }) => listCoralCorrespondence(projectId, signal),
  });
  const growthQuery = useQuery({
    queryKey: ["coral-growth", projectId],
    queryFn: ({ signal }) => listCoralGrowth(projectId, signal),
  });
  const [earlier, setEarlier] = useState("");
  const [later, setLater] = useState("");
  const [matches, setMatches] = useState<DraftMatch[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState("");
  const [base, setBase] = useState<string>();
  const [nextKey, setNextKey] = useState(0);
  const [resultSelection, setResultSelection] = useState("");
  const graphs = graphsQuery.data?.filter((graph) => graph.current) ?? [];
  const previous = graphs.find((graph) => graph.id === earlier);
  const following = graphs.find((graph) => graph.id === later);
  const selectedReview = correspondenceQuery.data?.find(
    (row) => row.id === selected,
  );
  const result =
    growthQuery.data?.find((row) => row.id === resultSelection) ??
    growthQuery.data?.[0];
  const sameColonyLater = graphs.filter(
    (graph) =>
      graph.snapshot.organism_key === previous?.snapshot.organism_key &&
      Date.parse(graph.snapshot.observed_at) >
        Date.parse(previous.snapshot.observed_at),
  );
  const coverageComplete = (
    graph: GraphRecord | undefined,
    side: "earlier_branch_ids" | "later_branch_ids",
  ) => {
    const identifiers = matches.flatMap((row) => row[side]);
    return (
      !!graph &&
      identifiers.length === graph.snapshot.edges.length &&
      new Set(identifiers).size === identifiers.length &&
      graph.snapshot.edges.every((edge) => identifiers.includes(edge.id))
    );
  };
  const review = useMutation({
    mutationFn: () =>
      reviewCoralCorrespondence(projectId, {
        earlier_graph_revision_id: earlier,
        later_graph_revision_id: later,
        base_revision_id: base,
        matches: matches.map(({ key: _key, ...match }) => match),
        reviewer,
        reason,
      }),
    onSuccess: async (row) => {
      setSelected(row.id);
      setBase(row.id);
      await client.invalidateQueries({
        queryKey: ["coral-correspondences", projectId],
      });
      await client.invalidateQueries({ queryKey: ["coral-growth", projectId] });
    },
  });
  const growth = useMutation({
    mutationFn: () => saveCoralGrowth(projectId, selected),
    onSuccess: async (row) => {
      setResultSelection(row.id);
      await client.invalidateQueries({ queryKey: ["coral-growth", projectId] });
    },
  });

  function update(key: number, values: Partial<Match>) {
    setMatches((rows) =>
      rows.map((row) => (row.key === key ? { ...row, ...values } : row)),
    );
  }

  function editExisting() {
    if (!selectedReview) return;
    const oldEarlier = graphsQuery.data?.find(
      (graph) => graph.id === selectedReview.earlier_graph_revision_id,
    );
    const oldLater = graphsQuery.data?.find(
      (graph) => graph.id === selectedReview.later_graph_revision_id,
    );
    const first = graphs.find(
      (graph) => graph.graph_id === oldEarlier?.graph_id,
    );
    const last = graphs.find((graph) => graph.graph_id === oldLater?.graph_id);
    setEarlier(first?.id ?? "");
    setLater(last?.id ?? "");
    const sameDates = first?.id === oldEarlier?.id && last?.id === oldLater?.id;
    const rows = sameDates ? selectedReview.snapshot.matches : [];
    setMatches(rows.map((row, index) => ({ ...row, key: index })));
    setNextKey(rows.length);
    setBase(selectedReview.id);
  }

  return (
    <section className="management-card" aria-label="Reviewed coral growth">
      <h3>Coral branch correspondence and growth</h3>
      <p>
        Review a calibrated colony graph in the mask editor for each date.
        Branch lengths are projected 2D centerlines.
      </p>
      {(graphsQuery.isPending ||
        correspondenceQuery.isPending ||
        growthQuery.isPending) && (
        <p role="status">Loading coral observations…</p>
      )}
      {(graphsQuery.error ||
        correspondenceQuery.error ||
        growthQuery.error) && (
        <p role="alert">
          {
            (
              graphsQuery.error ||
              correspondenceQuery.error ||
              growthQuery.error
            )?.message
          }
        </p>
      )}
      <GraphSelect
        label="Earlier coral observation"
        value={earlier}
        graphs={graphs}
        onChange={(id) => {
          setEarlier(id);
          setLater("");
          setMatches([]);
          setBase(undefined);
        }}
      />
      <GraphSelect
        label="Later coral observation"
        value={later}
        graphs={sameColonyLater}
        onChange={(id) => {
          setLater(id);
          setMatches([]);
          setBase(undefined);
        }}
      />
      {previous && following && (
        <>
          <p>
            Account for every branch on both dates. Use the missing, occluded,
            or ambiguous states when an individual match cannot be established.
          </p>
          {matches.map((row, index) => (
            <fieldset key={row.key}>
              <legend>Correspondence {index + 1}</legend>
              <label>
                Match status
                <select
                  value={row.status}
                  onChange={(event) =>
                    update(row.key, { status: event.target.value as MatchKind })
                  }
                >
                  <option value="matched">Confirmed match</option>
                  <option value="ambiguous">Ambiguous</option>
                  <option value="missing">Missing observation</option>
                  <option value="occluded">Occluded</option>
                  <option value="split">Split</option>
                  <option value="merge">Merge</option>
                </select>
              </label>
              <BranchChoices
                label="Earlier branches"
                graph={previous}
                selected={row.earlier_branch_ids}
                onChange={(ids) => update(row.key, { earlier_branch_ids: ids })}
              />
              <BranchChoices
                label="Later branches"
                graph={following}
                selected={row.later_branch_ids}
                onChange={(ids) => update(row.key, { later_branch_ids: ids })}
              />
              <label>
                Match rationale
                <input
                  value={row.reason}
                  onChange={(event) =>
                    update(row.key, { reason: event.target.value })
                  }
                  maxLength={500}
                />
              </label>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setMatches((rows) =>
                    rows.filter((match) => match.key !== row.key),
                  )
                }
              >
                Remove correspondence row
              </button>
            </fieldset>
          ))}
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setMatches((rows) => [
                ...rows,
                {
                  key: nextKey,
                  status: "matched",
                  earlier_branch_ids: [],
                  later_branch_ids: [],
                  reason: "",
                },
              ]);
              setNextKey((key) => key + 1);
            }}
          >
            Add correspondence row
          </button>
          <label>
            Correspondence reviewer
            <input
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              maxLength={100}
            />
          </label>
          <label>
            Correspondence review reason
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
            />
          </label>
          <button
            type="button"
            disabled={
              !reviewer.trim() ||
              reason.trim().length < 3 ||
              matches.some((row) => row.reason.trim().length < 3) ||
              !coverageComplete(previous, "earlier_branch_ids") ||
              !coverageComplete(following, "later_branch_ids") ||
              review.isPending
            }
            onClick={() => review.mutate()}
          >
            {review.isPending
              ? "Saving correspondence…"
              : "Save reviewed correspondence"}
          </button>
        </>
      )}
      {review.error && <p role="alert">{review.error.message}</p>}
      <div className="annotation-editor-inline-actions">
        <label>
          Saved correspondence
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">Choose reviewed correspondence</option>
            {correspondenceQuery.data?.map((row) => (
              <option key={row.id} value={row.id}>
                Revision {row.revision} · {row.reviewer} · {row.id.slice(0, 8)}
                {row.stale_reasons.length > 0 ? " · stale" : ""}
              </option>
            ))}
          </select>
        </label>
        {selectedReview && (
          <button type="button" className="secondary" onClick={editExisting}>
            Revise correspondence
          </button>
        )}
        <button
          type="button"
          disabled={
            !selectedReview ||
            !!selectedReview.stale_reasons.length ||
            growth.isPending
          }
          onClick={() => growth.mutate()}
        >
          {growth.isPending ? "Calculating…" : "Calculate and save growth"}
        </button>
      </div>
      {selectedReview && selectedReview.stale_reasons.length > 0 && (
        <p role="status">
          Stale correspondence ·{" "}
          {selectedReview.stale_reasons.join(", ").replaceAll("_", " ")}
        </p>
      )}
      {growth.error && <p role="alert">{growth.error.message}</p>}
      {result && (
        <>
          <h4>Saved projected growth</h4>
          <label>
            Growth result
            <select
              value={result.id}
              onChange={(event) => setResultSelection(event.target.value)}
            >
              {growthQuery.data?.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.snapshot.organism_key} · {row.snapshot.later_observed_at}{" "}
                  · {row.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {result.stale_reasons.length > 0 && (
            <p role="status">
              Stale result ·{" "}
              {result.stale_reasons.join(", ").replaceAll("_", " ")}
            </p>
          )}
          <p>
            {result.snapshot.elapsed_days.toFixed(3)} days ·{" "}
            {result.snapshot.unit}
          </p>
          <table>
            <caption>Projected branch length changes</caption>
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Earlier</th>
                <th>Later</th>
                <th>Change</th>
                <th>Per day</th>
              </tr>
            </thead>
            <tbody>
              {[
                {
                  id: "total",
                  label: "Unique-edge colony total",
                  change: result.snapshot.total,
                },
                ...result.snapshot.branches.map((row, index) => ({
                  id: String(index),
                  label: `Branch review ${index + 1} · ${row.status}`,
                  change: row.change,
                })),
              ].map((row) => (
                <tr key={row.id}>
                  <th scope="row">{row.label}</th>
                  {row.change ? (
                    <>
                      <td>{row.change.earlier_length.toFixed(3)}</td>
                      <td>{row.change.later_length.toFixed(3)}</td>
                      <td>{row.change.absolute_change.toFixed(3)}</td>
                      <td>{row.change.change_per_day.toFixed(3)}</td>
                    </>
                  ) : (
                    <td colSpan={4}>Withheld</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <ul>
            {result.snapshot.limitations.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <div className="annotation-editor-inline-actions">
            <a
              href={coralDownload(
                projectId,
                `coral-growth/${result.id}/results.csv`,
              )}
            >
              Growth CSV
            </a>
            <a
              href={coralDownload(projectId, `coral-growth/${result.id}`)}
              target="_blank"
              rel="noreferrer"
            >
              Growth JSON
            </a>
          </div>
        </>
      )}
    </section>
  );
}
