import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  getWorkflowRunDetail,
  listSavedWorkflowGraphs,
  listWorkflowRuns,
  previewProjectSpatialAsset,
  queueWorkflowRun,
  saveWorkflowGraph,
  type MeshPreviewCalibration,
  type SpatialSourceAsset,
  type WorkflowGraphRecord,
  type WorkflowRun,
} from "./workflowGraphApi";

interface AnatomicalBranchPanelProps {
  projectId: string;
  asset: SpatialSourceAsset;
  calibration: MeshPreviewCalibration;
}

const protocolTextFields = {
  protocol_reference: "Preregistered protocol reference",
  independent_reference_id: "Independent measurement reference",
  independent_reference_observer_id: "Independent measurement operator",
  independent_reference_scale_evidence: "Independent reference scale evidence",
  repeatability_reference: "Repeatability study reference",
  adjudicator_id: "Designated adjudicator",
} as const;

const protocolNumberFields = {
  independent_reference_length_m: "Independent reference length (m)",
  maximum_reference_error_m: "Maximum absolute reference error (m)",
  maximum_repeatability_range_m: "Maximum repeatability range (m)",
} as const;

const evidenceStatusLabels = {
  provisional_missing_evidence: "Provisional evidence",
  declared_tolerances_exceeded: "Outside the declared tolerances",
  awaiting_independent_adjudication: "Awaiting independent adjudication",
} as const;

interface CenterlineMeasurement {
  declaration: {
    base_landmark: string;
    tip_landmark: string;
    selection_method: string;
    operator_id: string;
  };
  length_m: number;
  scale_only_length_interval_m: [number, number] | null;
  reference_absolute_error_m: number | null;
  repeatability_range_m: number | null;
  evidence_status: keyof typeof evidenceStatusLabels;
  anatomical_claim_verified: false;
  schema_version: "anatomical-branch-centerline-1";
  source_payload_sha256: string;
}

function centerlineFromForm(form: FormData, withProtocol: boolean) {
  function text(field: string) {
    return String(form.get(field) ?? "").trim();
  }

  const points = text("points")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => line.trim().split(/\s*,\s*|\s+/));
  if (
    points.length < 2 ||
    points.some(
      (point) =>
        point.length !== 3 ||
        point.some((part) => !part || !Number.isFinite(Number(part))),
    )
  ) {
    throw new Error(
      "Enter at least two source-coordinate rows with three numbers each.",
    );
  }

  const lengths = text("repeats")
    .split(",")
    .map((value) => value.trim());
  if (
    withProtocol &&
    (lengths.length < 2 ||
      lengths.some(
        (value) =>
          !value || !Number.isFinite(Number(value)) || Number(value) <= 0,
      ))
  ) {
    throw new Error(
      "Enter two or more positive repeatability lengths in meters.",
    );
  }

  return {
    coordinate_frame_id: text("frame"),
    anatomical_branch: {
      ordered_points_source_units: points.map((point) => point.map(Number)),
      base_landmark: text("base"),
      tip_landmark: text("tip"),
      selection_method: text("method"),
      operator_id: text("operator"),
      protocol: withProtocol
        ? {
            ...Object.fromEntries(
              Object.keys(protocolTextFields).map((field) => [
                field,
                text(field),
              ]),
            ),
            ...Object.fromEntries(
              Object.keys(protocolNumberFields).map((field) => [
                field,
                Number(text(field)),
              ]),
            ),
            repeated_lengths_m: lengths.map(Number),
          }
        : null,
    },
  };
}

function isCenterlineMeasurement(
  value: unknown,
): value is CenterlineMeasurement {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<CenterlineMeasurement>;
  return (
    record.schema_version === "anatomical-branch-centerline-1" &&
    record.anatomical_claim_verified === false &&
    typeof record.length_m === "number" &&
    Number.isFinite(record.length_m) &&
    record.evidence_status != null &&
    Object.hasOwn(evidenceStatusLabels, record.evidence_status) &&
    record.declaration != null
  );
}

function pendingRun(run?: WorkflowRun) {
  return run?.status === "queued" || run?.status === "running";
}

function meters(value: number) {
  return `${Number(value.toPrecision(8))} m`;
}

export function AnatomicalBranchPanel(props: AnatomicalBranchPanelProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        Anatomical branch length
      </button>
      {open && (
        <AnatomicalBranchSession
          key={`${props.projectId}:${props.asset.id}`}
          {...props}
        />
      )}
    </>
  );
}

function AnatomicalBranchSession({
  projectId,
  asset,
  calibration,
}: AnatomicalBranchPanelProps) {
  const queryClient = useQueryClient();
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [withProtocol, setWithProtocol] = useState(false);
  const graphKey = ["anatomical-branch-graphs", projectId];
  const runKey = ["anatomical-branch-runs", projectId];
  const history = useQuery({
    queryKey: graphKey,
    queryFn: ({ signal }) => listSavedWorkflowGraphs(projectId, signal),
  });
  const matchingGraphs = (history.data ?? []).filter((graph) => {
    const nodes = graph.graph_json.nodes as
      | {
          node_id: string;
          node_type: string;
          parameters?: Record<string, unknown>;
        }[]
      | undefined;
    return (
      graph.project_id === projectId &&
      graph.graph_key.startsWith("anatomical-branch-") &&
      Array.isArray(nodes) &&
      nodes.some(
        (node) =>
          node.node_id === "centerline" &&
          node.node_type === "mesh_surface_preview" &&
          node.parameters?.asset_id === asset.id &&
          node.parameters.expected_source_payload_sha256 === asset.sha256 &&
          node.parameters.anatomical_branch != null,
      )
    );
  });
  const selected = matchingGraphs.find((graph) => graph.id === selectedGraphId);
  const runs = useQuery({
    queryKey: runKey,
    queryFn: ({ signal }) => listWorkflowRuns(projectId, signal),
    enabled: Boolean(selectedGraphId),
    refetchInterval: (query) =>
      pendingRun(
        query.state.data?.find(
          (run) => run.workflow_graph_record_id === selectedGraphId,
        ),
      )
        ? 500
        : false,
  });
  const run = runs.data?.find(
    (item) =>
      item.project_id === projectId &&
      item.workflow_graph_record_id === selectedGraphId,
  );
  const detail = useQuery({
    queryKey: ["anatomical-branch-run", run?.id],
    queryFn: ({ signal }) => getWorkflowRunDetail(run!.id, signal),
    enabled: run?.status === "succeeded",
  });
  const nodeRun = detail.data?.nodes.find(
    (node) =>
      node.node_id === "centerline" &&
      node.node_type === "mesh_surface_preview",
  );
  const artifact = detail.data?.artifacts.find(
    (item) =>
      item.workflow_run_id === run?.id &&
      item.producer_node_run_id === nodeRun?.id &&
      item.data_type === "mesh_measurement_preview",
  );
  const result = artifact?.payload_json.declared_branch_centerline;
  const measurement =
    artifact?.payload_json.project_id === projectId &&
    isCenterlineMeasurement(result) &&
    result.source_payload_sha256 === asset.sha256
      ? result
      : undefined;

  const action = useMutation({
    mutationFn: async (input: FormData | WorkflowGraphRecord) => {
      let graph: WorkflowGraphRecord;
      if (input instanceof FormData) {
        const parameters = {
          ...calibration,
          ...centerlineFromForm(input, withProtocol),
        };
        await previewProjectSpatialAsset(projectId, asset, "mesh", parameters);
        const branch = parameters.anatomical_branch;
        graph = await saveWorkflowGraph(projectId, {
          graph_id: `anatomical-branch-${crypto.randomUUID()}`,
          name: `${branch.base_landmark} → ${branch.tip_landmark}`.slice(
            0,
            120,
          ),
          nodes: [
            { node_id: "project", node_type: "project_source" },
            {
              node_id: "centerline",
              node_type: "mesh_surface_preview",
              parameters: {
                ...parameters,
                asset_id: asset.id,
                expected_source_payload_sha256: asset.sha256,
              },
            },
          ],
          edges: [
            {
              edge_id: "project-centerline",
              source_node_id: "project",
              source_port_id: "project",
              target_node_id: "centerline",
              target_port_id: "project",
            },
          ],
        });
        queryClient.setQueryData<WorkflowGraphRecord[]>(
          graphKey,
          (previous = []) => [
            graph,
            ...previous.filter((item) => item.id !== graph.id),
          ],
        );
        setSelectedGraphId(graph.id);
        void queryClient.invalidateQueries({ queryKey: graphKey });
      } else {
        graph = input;
      }
      const queued = await queueWorkflowRun(projectId, graph.id);
      queryClient.setQueryData<WorkflowRun[]>(runKey, (previous = []) => [
        queued,
        ...previous.filter((item) => item.id !== queued.id),
      ]);
      void queryClient.invalidateQueries({ queryKey: runKey });
    },
  });

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    action.mutate(new FormData(event.currentTarget));
  }

  function exportEvidence() {
    if (!measurement || !artifact || !run || !selected) return;
    const evidence = {
      workflow_graph_sha256: selected.graph_sha256,
      workflow_run_id: run.id,
      workflow_payload_sha256: artifact.payload_sha256,
      source: artifact.payload_json.provenance,
      measurement,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(evidence, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `centerline-${run.id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const working = action.isPending || pendingRun(run);
  const error = action.error ?? history.error ?? runs.error ?? detail.error;
  return (
    <section className="panel-card" aria-label="Anatomical branch measurements">
      <h5>Anatomical centerline evidence</h5>
      <p>
        Declare a centerline in the mesh source frame and retain its operator,
        scale and protocol. Results are provisional pending independent
        adjudication.
      </p>
      <form onSubmit={save}>
        <fieldset disabled={working}>
          <legend>New centerline</legend>
          <div className="feature-grid">
            <label>
              Source coordinate frame
              <input
                name="frame"
                defaultValue={calibration.coordinate_frame_id}
                required
                maxLength={128}
              />
            </label>
            <label>
              Base landmark
              <input name="base" required maxLength={56} />
            </label>
            <label>
              Tip landmark
              <input name="tip" required maxLength={56} />
            </label>
            <label>
              Centerline selection method
              <input name="method" required maxLength={2000} />
            </label>
            <label>
              Measurement operator
              <input name="operator" required maxLength={128} />
            </label>
          </div>
          <label>
            Ordered centerline coordinates
            <textarea
              name="points"
              required
              maxLength={16000}
              rows={4}
              placeholder={"0 0 0\n1.2 0.4 0.7"}
            />
          </label>
          <p className="muted-copy">
            Enter one X Y Z point per line, from the base to the tip, in source
            units.
          </p>
          <label>
            <input
              type="checkbox"
              checked={withProtocol}
              onChange={(event) => setWithProtocol(event.currentTarget.checked)}
            />
            Supply reference and repeatability evidence
          </label>
          {withProtocol && (
            <fieldset>
              <legend>Declared protocol</legend>
              <div className="feature-grid">
                {Object.entries(protocolTextFields).map(([name, label]) => (
                  <label key={name}>
                    {label}
                    <input
                      name={name}
                      required
                      maxLength={name.endsWith("_id") ? 128 : 2000}
                    />
                  </label>
                ))}
                {Object.entries(protocolNumberFields).map(([name, label]) => (
                  <label key={name}>
                    {label}
                    <input
                      type="number"
                      name={name}
                      min={0}
                      step="any"
                      required
                    />
                  </label>
                ))}
                <label>
                  Repeated lengths (m, comma-separated)
                  <input name="repeats" required maxLength={2000} />
                </label>
              </div>
            </fieldset>
          )}
          <button type="submit">Save and calculate centerline</button>
        </fieldset>
      </form>
      <label>
        Saved centerline workflow
        <select
          value={selectedGraphId}
          disabled={working || history.isLoading}
          onChange={(event) => {
            action.reset();
            setSelectedGraphId(event.currentTarget.value);
          }}
        >
          <option value="">Select a saved centerline</option>
          {matchingGraphs.map((graph) => (
            <option key={graph.id} value={graph.id} title={graph.created_at}>
              {graph.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={!selected || working}
        onClick={() => selected && action.mutate(selected)}
      >
        Replay saved centerline
      </button>
      {working && <p role="status">Calculating the saved centerline…</p>}
      {error && <p role="alert">{error.message}</p>}
      {!working && run?.error_message && (
        <p role="alert">{run.error_message}</p>
      )}
      {!working && measurement && (
        <>
          <dl>
            <dt>Declared centerline length</dt>
            <dd>{meters(measurement.length_m)}</dd>
            <dt>Scale-only range</dt>
            <dd>
              {measurement.scale_only_length_interval_m
                ?.map(meters)
                .join(" to ") ?? "Unavailable"}
            </dd>
            <dt>Landmarks</dt>
            <dd>
              {measurement.declaration.base_landmark} →{" "}
              {measurement.declaration.tip_landmark}
            </dd>
            <dt>Selection method</dt>
            <dd>{measurement.declaration.selection_method}</dd>
            <dt>Operator</dt>
            <dd>{measurement.declaration.operator_id}</dd>
            {measurement.reference_absolute_error_m !== null && (
              <>
                <dt>Absolute reference error</dt>
                <dd>{meters(measurement.reference_absolute_error_m)}</dd>
              </>
            )}
            {measurement.repeatability_range_m !== null && (
              <>
                <dt>Repeatability range</dt>
                <dd>{meters(measurement.repeatability_range_m)}</dd>
              </>
            )}
            <dt>Evidence status</dt>
            <dd>{evidenceStatusLabels[measurement.evidence_status]}</dd>
          </dl>
          <button type="button" onClick={exportEvidence}>
            Export centerline evidence
          </button>
        </>
      )}
    </section>
  );
}
