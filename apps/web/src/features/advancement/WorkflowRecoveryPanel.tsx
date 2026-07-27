import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Sam3WorkflowSetupPanel } from "./Sam3WorkflowSetupPanel";
import {
  applyWorkflowArtifactCleanup,
  listPersistedWorkflows,
  listWorkflowArtifactQuarantine,
  listWorkflowRuns,
  previewWorkflowArtifactCleanup,
  restoreWorkflowArtifacts,
  retryWorkflowRun,
  type WorkflowArtifactCleanupPreview,
  type WorkflowArtifactQuarantine,
  type WorkflowRunRecord,
} from "./workflowPersistenceApi";

function recoveryNodes(run: WorkflowRunRecord): string[] {
  return Object.keys(run.node_state_json);
}

function canRecover(run: WorkflowRunRecord): boolean {
  return ["failed", "cancelled", "succeeded"].includes(run.status);
}

function isTerminal(run: WorkflowRunRecord): boolean {
  return ["failed", "cancelled", "succeeded"].includes(run.status);
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
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
  const [cleanupPreviewByRun, setCleanupPreviewByRun] = useState<
    Record<string, WorkflowArtifactCleanupPreview>
  >({});
  const [selectedCleanupActionsByRun, setSelectedCleanupActionsByRun] =
    useState<Record<string, string[]>>({});
  const [quarantineByRun, setQuarantineByRun] = useState<
    Record<string, WorkflowArtifactQuarantine>
  >({});
  const [selectedRestoreArtifactsByRun, setSelectedRestoreArtifactsByRun] =
    useState<Record<string, string[]>>({});
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
          result.run.result_json.rerun_from_node_id ??
            "the first incomplete node",
        )}.`,
      );
      void queryClient.invalidateQueries({
        queryKey: ["workflow_runs", workflowId],
      });
    },
  });
  const previewCleanup = useMutation({
    mutationFn: (run: WorkflowRunRecord) =>
      previewWorkflowArtifactCleanup(run.id),
    onSuccess: (preview) => {
      setCleanupPreviewByRun((current) => ({
        ...current,
        [preview.workflow_run_id]: preview,
      }));
      setSelectedCleanupActionsByRun((current) => ({
        ...current,
        [preview.workflow_run_id]: [],
      }));
      setMessage(
        `Cleanup preview found ${preview.eligible_action_count} eligible actions reclaiming up to ${formatBytes(
          preview.reclaimable_bytes,
        )}. Nothing is selected automatically.`,
      );
    },
  });
  const applyCleanup = useMutation({
    mutationFn: ({
      runId,
      preview,
      actionIds,
    }: {
      runId: string;
      preview: WorkflowArtifactCleanupPreview;
      actionIds: string[];
    }) =>
      applyWorkflowArtifactCleanup(runId, {
        preview_checksum: preview.preview_checksum,
        action_ids: actionIds,
      }),
    onSuccess: (result) => {
      setCleanupPreviewByRun((current) => {
        const next = { ...current };
        delete next[result.workflow_run_id];
        return next;
      });
      setSelectedCleanupActionsByRun((current) => ({
        ...current,
        [result.workflow_run_id]: [],
      }));
      setQuarantineByRun((current) => {
        const next = { ...current };
        delete next[result.workflow_run_id];
        return next;
      });
      setMessage(
        `Cleanup quarantined ${result.quarantined_file_count} files, cleared ${result.cleared_reference_count} missing references, and reclaimed ${formatBytes(
          result.reclaimed_bytes,
        )}.`,
      );
    },
  });
  const inspectQuarantine = useMutation({
    mutationFn: (run: WorkflowRunRecord) =>
      listWorkflowArtifactQuarantine(run.id),
    onSuccess: (quarantine) => {
      setQuarantineByRun((current) => ({
        ...current,
        [quarantine.workflow_run_id]: quarantine,
      }));
      setSelectedRestoreArtifactsByRun((current) => ({
        ...current,
        [quarantine.workflow_run_id]: [],
      }));
      setMessage(
        `Quarantine contains ${quarantine.item_count} files totaling ${formatBytes(
          quarantine.total_bytes,
        )}; ${quarantine.restorable_count} can currently be restored. Nothing is selected automatically.`,
      );
    },
  });
  const restoreArtifacts = useMutation({
    mutationFn: ({
      runId,
      artifactIds,
    }: {
      runId: string;
      artifactIds: string[];
    }) => restoreWorkflowArtifacts(runId, artifactIds),
    onSuccess: (result) => {
      setQuarantineByRun((current) => {
        const next = { ...current };
        delete next[result.workflow_run_id];
        return next;
      });
      setSelectedRestoreArtifactsByRun((current) => ({
        ...current,
        [result.workflow_run_id]: [],
      }));
      setMessage(
        `Restored ${result.restored_artifact_count} workflow artifacts (${formatBytes(
          result.restored_bytes,
        )}) to their original managed paths.`,
      );
    },
  });

  function toggleCleanupAction(runId: string, actionId: string) {
    setSelectedCleanupActionsByRun((current) => {
      const selected = current[runId] ?? [];
      return {
        ...current,
        [runId]: selected.includes(actionId)
          ? selected.filter((item) => item !== actionId)
          : [...selected, actionId],
      };
    });
  }

  function toggleRestoreArtifact(runId: string, artifactId: string) {
    setSelectedRestoreArtifactsByRun((current) => {
      const selected = current[runId] ?? [];
      return {
        ...current,
        [runId]: selected.includes(artifactId)
          ? selected.filter((item) => item !== artifactId)
          : [...selected, artifactId],
      };
    });
  }

  const actionError =
    workflows.error ??
    runs.error ??
    retry.error ??
    previewCleanup.error ??
    applyCleanup.error ??
    inspectQuarantine.error ??
    restoreArtifacts.error;

  return (
    <>
      <Sam3WorkflowSetupPanel projectId={projectId} />
      <section className="dashboard-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Workflow recovery</p>
            <h3>Retry, partial reruns, and safe artifact cleanup</h3>
            <span>
              Create a new run that reuses immutable successful upstream
              artifacts, or preview terminal-run files before moving selected
              outputs into reversible project quarantine.
            </span>
          </div>
          <span>{runs.data?.length ?? 0} recorded runs</span>
        </div>

        {message && <p className="form-success">{message}</p>}
        {actionError && <p className="form-error">{actionError.message}</p>}

        <article className="dashboard-card">
          <label>
            Persisted workflow
            <select
              value={workflowId}
              onChange={(event) => {
                setWorkflowId(event.target.value);
                setMessage(null);
                setCleanupPreviewByRun({});
                setSelectedCleanupActionsByRun({});
                setQuarantineByRun({});
                setSelectedRestoreArtifactsByRun({});
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
            const cleanupPreview = cleanupPreviewByRun[run.id];
            const selectedCleanupActions =
              selectedCleanupActionsByRun[run.id] ?? [];
            const quarantine = quarantineByRun[run.id];
            const selectedRestoreArtifacts =
              selectedRestoreArtifactsByRun[run.id] ?? [];
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
                        {String(
                          run.node_state_json[nodeId]?.status ?? "unknown",
                        )}
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
                  {retry.isPending
                    ? "Queuing recovery..."
                    : "Create recovery run"}
                </button>

                <hr />
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Artifact cleanup</p>
                    <h5>Quarantine terminal-run outputs</h5>
                    <span>
                      Shared files and files outside the managed workflow
                      directory are blocked. Previewing never selects or moves
                      anything.
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  className="secondary"
                  disabled={!isTerminal(run) || previewCleanup.isPending}
                  onClick={() => previewCleanup.mutate(run)}
                >
                  {previewCleanup.isPending
                    ? "Inspecting artifacts..."
                    : "Preview artifact cleanup"}
                </button>

                {cleanupPreview && (
                  <div
                    className="dashboard-list"
                    data-testid={`cleanup-${run.id}`}
                  >
                    <p>
                      {cleanupPreview.action_count} actions ·{" "}
                      {cleanupPreview.eligible_action_count} eligible ·{" "}
                      {formatBytes(cleanupPreview.reclaimable_bytes)}{" "}
                      reclaimable
                    </p>
                    {cleanupPreview.actions.map((action) => (
                      <label
                        key={action.action_id}
                        className="annotation-selection-row"
                      >
                        <input
                          type="checkbox"
                          checked={selectedCleanupActions.includes(
                            action.action_id,
                          )}
                          disabled={!action.eligible}
                          onChange={() =>
                            toggleCleanupAction(run.id, action.action_id)
                          }
                        />
                        <span>
                          <strong>
                            {action.action_kind === "quarantine_file"
                              ? "Quarantine file"
                              : "Clear missing reference"}
                          </strong>
                          <small>
                            {action.node_id}.{action.port_name} ·{" "}
                            {action.managed_path}
                          </small>
                          {action.blockers.map((blocker) => (
                            <small key={blocker} className="form-error">
                              {blocker}
                            </small>
                          ))}
                        </span>
                        <small>{formatBytes(action.size_bytes)}</small>
                      </label>
                    ))}
                    <button
                      type="button"
                      disabled={
                        selectedCleanupActions.length === 0 ||
                        applyCleanup.isPending
                      }
                      onClick={() =>
                        applyCleanup.mutate({
                          runId: run.id,
                          preview: cleanupPreview,
                          actionIds: selectedCleanupActions,
                        })
                      }
                    >
                      {applyCleanup.isPending
                        ? "Applying selected cleanup..."
                        : `Apply ${selectedCleanupActions.length} selected actions`}
                    </button>
                  </div>
                )}

                <hr />
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Artifact restoration</p>
                    <h5>Inspect and restore quarantined outputs</h5>
                    <span>
                      ReefVision rechecks the original destination and SHA-256
                      before restoring. Nothing is selected automatically.
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  className="secondary"
                  disabled={!isTerminal(run) || inspectQuarantine.isPending}
                  onClick={() => inspectQuarantine.mutate(run)}
                >
                  {inspectQuarantine.isPending
                    ? "Inspecting quarantine..."
                    : "Inspect artifact quarantine"}
                </button>

                {quarantine && (
                  <div
                    className="dashboard-list"
                    data-testid={`quarantine-${run.id}`}
                  >
                    <p>
                      {quarantine.item_count} quarantined ·{" "}
                      {quarantine.restorable_count} restorable ·{" "}
                      {formatBytes(quarantine.total_bytes)} total
                    </p>
                    {quarantine.items.map((item) => (
                      <label
                        key={item.artifact_id}
                        className="annotation-selection-row"
                      >
                        <input
                          type="checkbox"
                          checked={selectedRestoreArtifacts.includes(
                            item.artifact_id,
                          )}
                          disabled={!item.restorable}
                          onChange={() =>
                            toggleRestoreArtifact(run.id, item.artifact_id)
                          }
                        />
                        <span>
                          <strong>Restore quarantined file</strong>
                          <small>
                            {item.node_id}.{item.port_name} ·{" "}
                            {item.original_managed_path}
                          </small>
                          {item.blockers.map((blocker) => (
                            <small key={blocker} className="form-error">
                              {blocker}
                            </small>
                          ))}
                        </span>
                        <small>{formatBytes(item.size_bytes)}</small>
                      </label>
                    ))}
                    <button
                      type="button"
                      disabled={
                        selectedRestoreArtifacts.length === 0 ||
                        restoreArtifacts.isPending
                      }
                      onClick={() =>
                        restoreArtifacts.mutate({
                          runId: run.id,
                          artifactIds: selectedRestoreArtifacts,
                        })
                      }
                    >
                      {restoreArtifacts.isPending
                        ? "Restoring selected artifacts..."
                        : `Restore ${selectedRestoreArtifacts.length} selected artifacts`}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}
