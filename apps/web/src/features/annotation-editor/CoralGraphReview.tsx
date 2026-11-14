import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  coralDownload,
  listCoralGraphs,
  reviewCoralGraph,
  type GapDisposition,
  type GraphEditKind,
  type GraphRecord,
  type GraphReview,
} from "../ecology/coralGraphApi";
import { getRegistry } from "../ecology/ecologyApi";
import type { SkeletonPixel } from "./skeletonAnalysisApi";

export function CoralGraphReview({
  projectId,
  analysisId,
  maskId,
  drawn,
  onGraph,
}: {
  projectId: string;
  analysisId: string;
  maskId: string;
  drawn: SkeletonPixel[];
  onGraph: (record: GraphRecord | null) => void;
}) {
  const [colony, setColony] = useState("");
  const [operation, setOperation] = useState<GraphEditKind | "source">(
    "source",
  );
  const [branchIds, setBranchIds] = useState<string[]>([]);
  const [observedAt, setObservedAt] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [gap, setGap] = useState<GapDisposition | "">("");
  const [tolerance, setTolerance] = useState("0");
  const queryClient = useQueryClient();
  const registry = useQuery({
    queryKey: ["ecology-registry", projectId],
    queryFn: ({ signal }) => getRegistry(projectId, signal),
    retry: false,
  });
  const graphQuery = useQuery({
    queryKey: ["coral-graphs", projectId, maskId],
    queryFn: ({ signal }) => listCoralGraphs(projectId, signal, maskId),
    retry: false,
  });
  const history = graphQuery.data ?? [];
  const base = history.find((item) => item.decision === "accepted") ?? null;
  const active = base?.current && base.analysis_id === analysisId ? base : null;
  const colonyRecord = registry.data?.identities.find(
    (item) =>
      item.kind === "colony" &&
      (base
        ? item.organism_key === base.snapshot.organism_key
        : item.id === colony),
  );
  useEffect(() => onGraph(active), [active, onGraph]);
  useEffect(() => {
    setOperation("source");
    setBranchIds([]);
  }, [active?.id]);

  const mutation = useMutation({
    mutationFn: (review: GraphReview) => reviewCoralGraph(projectId, review),
    onSuccess: async () => {
      setReason("");
      await queryClient.invalidateQueries({
        queryKey: ["coral-graphs", projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["coral-growth", projectId],
      });
    },
  });
  const count =
    operation === "merge"
      ? 2
      : operation === "source" || operation === "add"
        ? 0
        : 1;
  const requiresPath = operation === "add" || operation === "correct";
  const date =
    base?.snapshot.observed_at ??
    (observedAt && new Date(observedAt + "Z").toISOString());
  const valid =
    colonyRecord &&
    date &&
    reviewer.trim() &&
    reason.trim().length >= 3 &&
    branchIds.length === count &&
    (!requiresPath || drawn.length >= 2) &&
    (operation !== "split" || drawn.length === 1) &&
    (!gap || drawn.length >= 2) &&
    !mutation.isPending;

  function submit(decision: GraphReview["decision"]) {
    if (!valid || !colonyRecord || !date) return;
    mutation.mutate({
      identity_revision_id: colonyRecord.id,
      analysis_id: analysisId,
      base_revision_id: base?.id,
      observed_at: date,
      reviewer,
      reason,
      decision,
      edit:
        operation === "source"
          ? undefined
          : {
              kind: operation,
              branch_ids: branchIds,
              points: requiresPath || operation === "split" ? drawn : [],
              snap_tolerance_px: operation === "add" ? Number(tolerance) : 0,
            },
      gaps: gap ? [{ disposition: gap, points: drawn, reason }] : undefined,
    });
  }

  return (
    <section aria-label="Coral graph review">
      <h4>Coral graph review</h4>
      {(graphQuery.isError || registry.isError) && (
        <p role="alert">Could not load graph history or the colony registry.</p>
      )}
      {graphQuery.isPending ? (
        <p role="status">Loading coral graph history…</p>
      ) : (
        <>
          <p>
            Lengths describe projected 2D segments between graph junctions. Draw
            or select source pixels above before reviewing edits.
          </p>
          <label>
            Registered colony
            <select
              value={colonyRecord?.id ?? colony}
              disabled={!!base}
              onChange={(event) => setColony(event.target.value)}
            >
              <option value="">Choose a colony</option>
              {registry.data?.identities
                .filter((item) => item.kind === "colony")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.organism_key}
                  </option>
                ))}
            </select>
          </label>
          {!base && (
            <label>
              Observation time (UTC)
              <input
                type="datetime-local"
                value={observedAt}
                onChange={(event) => setObservedAt(event.target.value)}
                required
              />
            </label>
          )}
          {active && (
            <p role="status">
              Current reviewed graph revision {active.revision} ·{" "}
              {active.snapshot.edges.length} branches
            </p>
          )}
          {base && !active && (
            <p role="status">
              Source evidence changed. Review the current source before editing
              branches.
            </p>
          )}
          <label>
            Graph operation
            <select
              value={operation}
              onChange={(event) => {
                setOperation(event.target.value as typeof operation);
                setBranchIds([]);
              }}
            >
              <option value="source">
                {active ? "Review current geometry" : "Review source skeleton"}
              </option>
              {(!base || active) && (
                <option value="add">Add drawn branch</option>
              )}
              {active && (
                <>
                  <option value="split">Split at drawn point</option>
                  <option value="remove">Remove branch</option>
                  <option value="merge">Merge adjacent branches</option>
                  <option value="correct">
                    Replace branch with drawn path
                  </option>
                </>
              )}
            </select>
          </label>
          {count > 0 && (
            <label>
              Branch selection
              <select
                multiple={count > 1}
                value={count > 1 ? branchIds : (branchIds[0] ?? "")}
                onChange={(event) => {
                  setBranchIds(
                    Array.from(
                      event.currentTarget.selectedOptions,
                      (option) => option.value,
                    ).filter(Boolean),
                  );
                }}
              >
                {count === 1 && <option value="">Choose a branch</option>}
                {active?.snapshot.edges.map((edge, index) => (
                  <option key={edge.id} value={edge.id}>
                    Branch {index + 1} ·{" "}
                    {edge.node_to_node_length_pixels.toFixed(2)} px ·{" "}
                    {edge.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {operation === "add" && (
            <label>
              Attachment tolerance (px)
              <input
                type="number"
                min="0"
                max="25"
                step="0.5"
                value={tolerance}
                onChange={(event) => setTolerance(event.target.value)}
              />
            </label>
          )}
          <label>
            Gap disposition
            <select
              value={gap}
              onChange={(event) => setGap(event.target.value as typeof gap)}
            >
              <option value="">No gap recorded</option>
              <option value="observed_attachment">
                Visible tissue attachment
              </option>
              <option value="occluded">Occluded</option>
              <option value="unknown">Unresolved</option>
              <option value="separate_colony">Separate colony</option>
            </select>
          </label>
          <label>
            Graph reviewer
            <input
              value={reviewer}
              maxLength={100}
              onChange={(event) => setReviewer(event.target.value)}
            />
          </label>
          <label>
            Graph review reason
            <textarea
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <div className="annotation-editor-inline-actions">
            <button
              type="button"
              disabled={!valid}
              onClick={() => submit("accepted")}
            >
              Accept graph review
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!valid}
              onClick={() => submit("rejected")}
            >
              Record rejection
            </button>
          </div>
          {mutation.isPending && <p role="status">Saving graph review…</p>}
          {mutation.error && <p role="alert">{mutation.error.message}</p>}
          {history.length > 0 && (
            <details>
              <summary>Graph review history ({history.length})</summary>
              <ul>
                {history.map((row) => (
                  <li key={row.id}>
                    Revision {row.revision} · {row.decision} · {row.reviewer} ·{" "}
                    {row.reason}
                    {row.stale_reasons.length > 0 &&
                      " · " +
                        row.stale_reasons.join(", ").replaceAll("_", " ")}{" "}
                    <a
                      href={coralDownload(
                        projectId,
                        "coral-graphs/" + row.id + "/measurements.csv",
                      )}
                    >
                      CSV
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
