import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import {
  cancelWorkflowRunJob,
  getWorkflowNodeRegistry,
  getWorkflowRunDetail,
  listSavedWorkflowGraphs,
  listWorkflowRuns,
  planWorkflowGraph,
  queueWorkflowRun,
  resumeWorkflowReviewNode,
  saveWorkflowGraph,
  validateWorkflowGraph,
} from "./workflowGraphApi";

interface WorkflowGraphWorkspaceProps {
  project: Project;
}

const executableExampleGraph = {
  graph_id: "project-images-runtime",
  name: "Project images runtime",
  schema_version: "workflow-graph-0001",
  nodes: [
    { node_id: "project", node_type: "project_source" },
    { node_id: "images", node_type: "project_images" },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
  ],
};

const consensusExampleGraph = {
  graph_id: "two-of-three-detection-consensus",
  name: "2-of-3 detection consensus",
  schema_version: "workflow-graph-0001",
  nodes: [
    { node_id: "project", node_type: "project_source" },
    { node_id: "images", node_type: "project_images" },
    {
      node_id: "model_a",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-model-a-id" },
    },
    {
      node_id: "model_b",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-model-b-id" },
    },
    {
      node_id: "model_c",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-model-c-id" },
    },
    { node_id: "detect_a", node_type: "detection_inference" },
    { node_id: "detect_b", node_type: "detection_inference" },
    { node_id: "detect_c", node_type: "detection_inference" },
    {
      node_id: "consensus",
      node_type: "detection_consensus",
      parameters: {
        required_votes: 2,
        iou_threshold: 0.5,
        confidence_threshold: 0.25,
        class_aware: true,
        box_strategy: "mean",
      },
    },
    { node_id: "review", node_type: "detection_review_gate" },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
    ...["a", "b", "c"].flatMap((suffix) => [
      {
        edge_id: `project-model-${suffix}`,
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: `model_${suffix}`,
        target_port_id: "project",
      },
      {
        edge_id: `images-detect-${suffix}`,
        source_node_id: "images",
        source_port_id: "images",
        target_node_id: `detect_${suffix}`,
        target_port_id: "images",
      },
      {
        edge_id: `model-detect-${suffix}`,
        source_node_id: `model_${suffix}`,
        source_port_id: "model",
        target_node_id: `detect_${suffix}`,
        target_port_id: "model",
      },
      {
        edge_id: `detect-consensus-${suffix}`,
        source_node_id: `detect_${suffix}`,
        source_port_id: "proposals",
        target_node_id: "consensus",
        target_port_id: "predictions",
      },
    ]),
    {
      edge_id: "consensus-review",
      source_node_id: "consensus",
      source_port_id: "consensus",
      target_node_id: "review",
      target_port_id: "proposals",
    },
  ],
};

function statusIsActive(status: string | undefined): boolean {
  return (
    status === "queued" ||
    status === "running" ||
    status === "cancel_requested" ||
    status === "waiting_for_review"
  );
}

function shortHash(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}…` : value;
}

export function WorkflowGraphWorkspace({ project }: WorkflowGraphWorkspaceProps) {
  const [graphJson, setGraphJson] = useState(
    JSON.stringify(executableExampleGraph, null, 2),
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const registryQuery = useQuery({
    queryKey: ["workflow-node-registry"],
    queryFn: ({ signal }) => getWorkflowNodeRegistry(signal),
  });
  const savedGraphsQuery = useQuery({
    queryKey: ["workflow-graphs", project.id],
    queryFn: ({ signal }) => listSavedWorkflowGraphs(project.id, signal),
  });
  const runsQuery = useQuery({
    queryKey: ["workflow-runs", project.id],
    queryFn: ({ signal }) => listWorkflowRuns(project.id, signal),
    refetchInterval: 2000,
  });
  const runDetailQuery = useQuery({
    queryKey: ["workflow-run", selectedRunId],
    queryFn: ({ signal }) => getWorkflowRunDetail(selectedRunId ?? "", signal),
    enabled: selectedRunId !== null,
    refetchInterval: 1500,
  });

  function parsedGraph(): Record<string, unknown> {
    return JSON.parse(graphJson) as Record<string, unknown>;
  }

  const validationMutation = useMutation({
    mutationFn: () => validateWorkflowGraph(project.id, parsedGraph()),
  });
  const planMutation = useMutation({
    mutationFn: () => planWorkflowGraph(project.id, parsedGraph()),
  });
  const saveMutation = useMutation({
    mutationFn: () => saveWorkflowGraph(project.id, parsedGraph()),
    onSuccess: () => void savedGraphsQuery.refetch(),
  });
  const saveAndRunMutation = useMutation({
    mutationFn: async () => {
      const graph = parsedGraph();
      const plan = await planWorkflowGraph(project.id, graph);
      if (!plan.valid || !plan.executable) {
        throw new Error(
          plan.execution_blocker ?? "The workflow is not executable yet.",
        );
      }
      const saved = await saveWorkflowGraph(project.id, graph);
      const run = await queueWorkflowRun(project.id, saved.id);
      return { saved, run };
    },
    onSuccess: ({ run }) => {
      setSelectedRunId(run.id);
      void savedGraphsQuery.refetch();
      void runsQuery.refetch();
    },
  });
  const resumeReviewMutation = useMutation({
    mutationFn: (nodeRunId: string) =>
      resumeWorkflowReviewNode(
        nodeRunId,
        "local_user",
        "Approved from the workflow workspace after human review.",
      ),
    onSuccess: () => {
      void runsQuery.refetch();
      void runDetailQuery.refetch();
    },
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelWorkflowRunJob(jobId),
    onSuccess: () => {
      void runsQuery.refetch();
      void runDetailQuery.refetch();
    },
  });

  const mutationError =
    validationMutation.error ??
    planMutation.error ??
    saveMutation.error ??
    saveAndRunMutation.error ??
    resumeReviewMutation.error ??
    cancelMutation.error;
  const selectedRun = runDetailQuery.data?.run;

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Executable workflows</p>
          <h3>Workflow graph editor and runner</h3>
          <p>
            Define typed ReefVision workflows, validate and save immutable revisions,
            then execute supported nodes with persisted run history and artifacts.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>Graph JSON</h4>
          <div className="button-row">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setGraphJson(JSON.stringify(executableExampleGraph, null, 2))
              }
            >
              Load executable example
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                setGraphJson(JSON.stringify(consensusExampleGraph, null, 2))
              }
            >
              Load 2-of-3 consensus + review
            </button>
          </div>
          <textarea
            rows={30}
            value={graphJson}
            onChange={(event) => setGraphJson(event.target.value)}
            spellCheck={false}
          />
          <div className="button-row">
            <button
              type="button"
              onClick={() => validationMutation.mutate()}
              disabled={validationMutation.isPending}
            >
              Validate
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => planMutation.mutate()}
              disabled={planMutation.isPending}
            >
              Plan
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
            >
              Save revision
            </button>
            <button
              type="button"
              onClick={() => saveAndRunMutation.mutate()}
              disabled={saveAndRunMutation.isPending}
            >
              Save &amp; run
            </button>
          </div>
          {mutationError && <p className="form-error">{mutationError.message}</p>}
          <p className="muted-copy">
            The 2-of-3 template uses registered detection models today. Replace its
            three placeholder model IDs before validation. When a review gate pauses,
            review the underlying predictions in the relevant ReefVision review tool,
            then resume it here. GPT, Gemini, and Claude provider nodes can feed the
            same consensus node once those cloud adapters are enabled.
          </p>
        </div>

        <div className="panel-card">
          <h4>Node registry</h4>
          {registryQuery.data?.map((definition) => (
            <details key={definition.node_type}>
              <summary>
                <strong>{definition.display_name}</strong> · {definition.category} ·{" "}
                {definition.executable ? "executable" : "pending"}
              </summary>
              <p>{definition.description}</p>
              <p>
                Type: <code>{definition.node_type}</code>
              </p>
              <p>
                Inputs:{" "}
                {definition.input_ports
                  .map(
                    (item) =>
                      `${item.port_id}${item.multiple ? " (multiple)" : ""}`,
                  )
                  .join(", ") || "none"}
              </p>
              <p>
                Outputs:{" "}
                {definition.output_ports.map((item) => item.port_id).join(", ") ||
                  "none"}
              </p>
            </details>
          ))}
        </div>

        <div className="panel-card">
          <h4>Validation and plan</h4>
          {validationMutation.data ? (
            <>
              <p>
                Valid:{" "}
                <strong>{validationMutation.data.valid ? "Yes" : "No"}</strong>
              </p>
              <p>
                Order:{" "}
                {validationMutation.data.topological_order.join(" → ") ||
                  "unavailable"}
              </p>
              <ul>
                {validationMutation.data.issues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`}>
                    {issue.severity}: {issue.code} — {issue.message}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>Validate the graph to inspect structural and semantic issues.</p>
          )}
          {planMutation.data && (
            <>
              <hr />
              <p>
                Executable:{" "}
                <strong>{planMutation.data.executable ? "Yes" : "No"}</strong>
              </p>
              {planMutation.data.execution_blocker && (
                <p>{planMutation.data.execution_blocker}</p>
              )}
              <ol>
                {planMutation.data.steps.map((step) => (
                  <li key={step.node_id}>
                    <strong>{step.display_name}</strong> ·{" "}
                    {step.executable ? "ready" : "pending"}: {step.action}
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>

        <div className="panel-card">
          <h4>Saved revisions</h4>
          {savedGraphsQuery.data?.length ? (
            <ul>
              {savedGraphsQuery.data.slice(0, 8).map((record) => (
                <li key={record.id}>
                  <strong>{record.name}</strong> · rev {record.revision} ·{" "}
                  <code>{shortHash(record.graph_sha256)}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p>No workflow revisions saved for this project yet.</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Recent runs</h4>
          {runsQuery.data?.length ? (
            <div>
              {runsQuery.data.slice(0, 10).map((run) => (
                <div className="button-row" key={run.id}>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setSelectedRunId(run.id)}
                  >
                    {run.status} · {shortHash(run.graph_sha256)}
                  </button>
                  {run.job_id && statusIsActive(run.status) && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={cancelMutation.isPending}
                      onClick={() => cancelMutation.mutate(run.job_id ?? "")}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p>No workflow runs queued for this project yet.</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Run inspection</h4>
          {selectedRun ? (
            <>
              <p>
                Status: <strong>{selectedRun.status}</strong>
              </p>
              {selectedRun.status === "waiting_for_review" && (
                <p className="muted-copy">
                  This run is safely paused. Complete the requested human review, then
                  resume the waiting node below. Completed upstream nodes and artifacts
                  will be reused.
                </p>
              )}
              {selectedRun.error_message && (
                <p className="form-error">{selectedRun.error_message}</p>
              )}
              <h5>Nodes</h5>
              <ol>
                {runDetailQuery.data?.nodes.map((node) => (
                  <li key={node.id}>
                    <strong>{node.node_id}</strong> · {node.node_type} · {node.status}
                    {node.error_message ? ` — ${node.error_message}` : ""}
                    {node.status === "waiting_for_review" && (
                      <div className="button-row">
                        <button
                          type="button"
                          disabled={resumeReviewMutation.isPending}
                          onClick={() => resumeReviewMutation.mutate(node.id)}
                        >
                          Resume after review
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ol>
              <h5>Artifacts</h5>
              <ul>
                {runDetailQuery.data?.artifacts.map((artifact) => (
                  <li key={artifact.id}>
                    <code>{artifact.data_type}</code> from {artifact.producer_port_id} ·{" "}
                    <code>{shortHash(artifact.payload_sha256)}</code>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>Select a recent run or use Save &amp; run to inspect execution.</p>
          )}
        </div>
      </div>
    </section>
  );
}
