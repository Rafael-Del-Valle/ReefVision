import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  listPersistedWorkflows,
  listWorkflowRuns,
  retryWorkflowRun,
  type WorkflowRunRecord,
} from "./workflowPersistenceApi";

function recoveryNodes(run: WorkflowRunRecord): string[] {
  return Object.keys(run.node_state_json);
}

function canRecover(run: WorkflowRunRecord): boolean {
  return ["failed", "cancelled", "succeeded"].includes(run.status);
}

export function WorkflowRecoveryPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [workflowId, setWorkflowId] = useState("");
  const [selectedNodeByRun, setSelectedNodeByRun] = useState<
    Record<string, string>
  >({});
  const [useCacheByRun, setUseCacheByRun] = useState<Record<string, boolean>>(
    {},
  );
  const [message, setMessage] = useState<string | null>(null);

  const workflows = useQuery({
    queryKey: ["persisted_workflows", projectId],
    queryFn: ({ signal }) => listPersistedWorkflows(projectId, signal),
  });
  useEffect(() => {
    if (!workflowId && workflows.data?.length) {
      setWorkflowId(workflows.data[0].id);
    }
  }, [workflowId, workflows.data]);

  const runs = useQuery({
    queryKey: ["workflow_runs", workflowId],
    queryFn: ({ signal }) => listWorkflowRuns(workflowId, signal),
    enabled: Boolean(workflowId),
  });
  const retry = useMutation({
    mutationFn: (run: WorkflowRunRecord) => {
      const selectedNode = selectedNodeByRun[run.id] ?? "";
      return retryWorkflowRun(run.id, {
        ...(selectedNode ? { from_node_id: selectedNode } : {}),
        use_cache: useCacheByRun[run.id] ?? true,
      });
    },
    onSuccess: (result) => {
      setMessage(
        `Recovery run ${result.run.id.slice(0, 8)} queued from ${String(
          result.run.result_json.rerun_from_node_id ?? "the first incomplete node",
        )}.`,
      );
      void queryClient.invalidateQueries({
        queryKey: ["workflow_runs", workflowId],
      });
    },
  });

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workflow recovery</p>
          <h3>Retry and partial reruns</h3>
          <span>
            Create a new run that reuses immutable successful upstream artifacts
            and reruns the failed or selected node plus everything downstream.
          </span>
        </div>
        <span>{runs.data?.length ?? 0} recorded runs</span>
      </div>

      {message && <p className="form-success">{message}</p>}
      {(workflows.error || runs.error || retry.error) && (
        <p className="form-error">
          {workflows.error?.message ?? runs.error?.message ?? retry.error?.message}
        </p>
      )}

      <article className="dashboard-card">
        <label>
          Persisted workflow
          <select
            value={workflowId}
            onChange={(event) => {
              setWorkflowId(event.target.value);
              setMessage(null);
            }}
          >
            <option value="">Choose a workflow</option>
            {workflows.data?.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>
                {workflow.name} · revision {workflow.current_revision_number}
              </option>
            ))}
          </select>
        </label>
      </article>

      {!workflowId && (
        <div className="empty-state">
          <h4>No persisted workflow selected</h4>
          <p>Persist a workflow before recovery history can be displayed.</p>
        </div>
      )}

      {workflowId && runs.data?.length === 0 && (
        <div className="empty-state">
          <h4>No workflow runs yet</h4>
          <p>Queue the workflow once before recovery controls are needed.</p>
        </div>
      )}

      <div className="dashboard-list">
        {runs.data?.map((run) => {
          const nodes = recoveryNodes(run);
          const selectedNode = selectedNodeByRun[run.id] ?? "";
          const active = ["queued", "running", "cancel_requested"].includes(
            run.status,
          );
          return (
            <article key={run.id} className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{run.status.replaceAll("_", " ")}</p>
                  <h4>Run {run.id.slice(0, 8)}</h4>
                  <span>
                    {new Date(run.created_at).toLocaleString()} · {run.stage}
                  </span>
                </div>
                <span>{run.current_node_id ?? "No active node"}</span>
              </div>
              {run.error_message && (
                <p className="form-error">{run.error_message}</p>
              )}
              <div className="dashboard-grid">
                {nodes.map((nodeId) => (
                  <div key={nodeId} className="dashboard-row">
                    <strong>{nodeId}</strong>
                    <span>
                      {String(run.node_state_json[nodeId]?.status ?? "unknown")}
                    </span>
                  </div>
                ))}
              </div>
              <label>
                Recovery starting point
                <select
                  value={selectedNode}
                  disabled={!canRecover(run)}
                  onChange={(event) =>
                    setSelectedNodeByRun((current) => ({
                      ...current,
                      [run.id]: event.target.value,
                    }))
                  }
                >
                  <option value="">
                    {run.status === "succeeded"
                      ? "Choose a node for partial rerun"
                      : "Resume first incomplete node"}
                  </option>
                  {nodes.map((nodeId) => (
                    <option key={nodeId} value={nodeId}>
                      Rerun from {nodeId}
                    </option>
                  ))}
                </select>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={useCacheByRun[run.id] ?? true}
                  disabled={!canRecover(run)}
                  onChange={(event) =>
                    setUseCacheByRun((current) => ({
                      ...current,
                      [run.id]: event.target.checked,
                    }))
                  }
                />
                Reuse compatible cached outputs for rerun nodes
              </label>
              <button
                type="button"
                disabled={
                  active ||
                  !canRecover(run) ||
                  retry.isPending ||
                  (run.status === "succeeded" && !selectedNode)
                }
                onClick={() => retry.mutate(run)}
              >
                {retry.isPending ? "Queuing recovery..." : "Create recovery run"}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
