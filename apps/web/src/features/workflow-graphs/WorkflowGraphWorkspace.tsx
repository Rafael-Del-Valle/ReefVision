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
import { workflowTemplates } from "./workflowTemplates";
import { WorkflowVisualEditor } from "./WorkflowVisualEditor";

interface WorkflowGraphWorkspaceProps {
  project: Project;
}

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

function safeParseGraph(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && !Array.isArray(parsed) && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function WorkflowGraphWorkspace({ project }: WorkflowGraphWorkspaceProps) {
  const [graphJson, setGraphJson] = useState(() =>
    JSON.stringify(workflowTemplates[0]?.graph ?? {}, null, 2),
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState(
    workflowTemplates[0]?.id ?? "",
  );

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
    const parsed = safeParseGraph(graphJson);
    if (!parsed) throw new Error("Graph JSON must be a valid JSON object.");
    return parsed;
  }

  function loadTemplate(templateId: string): void {
    const template = workflowTemplates.find((item) => item.id === templateId);
    if (!template) return;
    setSelectedTemplateId(template.id);
    setGraphJson(JSON.stringify(template.graph, null, 2));
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
  const visualGraph = safeParseGraph(graphJson);

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Executable workflows</p>
          <h3>Workflow graph editor and runner</h3>
          <p>
            Build typed computer-vision pipelines visually, validate them before
            execution, save immutable revisions, and inspect persisted node/artifact
            lineage after each run.
          </p>
        </div>
      </div>

      <div className="panel-card">
        <h4>Workflow templates</h4>
        <p className="muted-copy">
          Templates are starting points. Replace placeholder dataset, model, class, and
          cloud-model identifiers before validation. The visual editor and JSON view stay
          synchronized.
        </p>
        <div className="button-row" style={{ alignItems: "end" }}>
          <label>
            Template
            <select
              value={selectedTemplateId}
              onChange={(event) => loadTemplate(event.target.value)}
            >
              {workflowTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary"
            onClick={() => loadTemplate(selectedTemplateId)}
          >
            Reload template
          </button>
        </div>
        <p>
          {workflowTemplates.find((item) => item.id === selectedTemplateId)?.description}
        </p>
      </div>

      <div className="panel-card" style={{ marginTop: 12 }}>
        <h4>Visual workflow editor</h4>
        {visualGraph ? (
          <WorkflowVisualEditor
            graph={visualGraph}
            registry={registryQuery.data ?? []}
            onChange={(graph) => setGraphJson(JSON.stringify(graph, null, 2))}
          />
        ) : (
          <p className="form-error">
            Fix the JSON syntax below before continuing visual editing.
          </p>
        )}
      </div>

      <div className="feature-grid" style={{ marginTop: 12 }}>
        <div className="panel-card">
          <h4>Graph JSON</h4>
          <textarea
            rows={22}
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
            Review gates pause safely. Complete the requested review in ReefVision, then
            resume the waiting node below. Completed upstream nodes and paid/cloud
            artifacts are reused rather than recomputed.
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
              {definition.required_parameters.length > 0 && (
                <p>
                  Required parameters: {definition.required_parameters.join(", ")}
                </p>
              )}
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
              {savedGraphsQuery.data.slice(0, 10).map((record) => (
                <li key={record.id}>
                  <strong>{record.name}</strong> · rev {record.revision} ·{" "}
                  <code>{shortHash(record.graph_sha256)}</code>{" "}
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      setGraphJson(JSON.stringify(record.graph_json, null, 2))
                    }
                  >
                    Load
                  </button>
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
                    {Object.keys(node.result_json).length > 0 && (
                      <details>
                        <summary>Node result</summary>
                        <pre>{JSON.stringify(node.result_json, null, 2)}</pre>
                      </details>
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
                    <details>
                      <summary>Inspect artifact</summary>
                      <pre>{JSON.stringify(artifact.payload_json, null, 2)}</pre>
                    </details>
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
