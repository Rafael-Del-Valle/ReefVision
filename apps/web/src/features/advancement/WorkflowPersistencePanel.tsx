import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { EditableWorkflow } from "./WorkflowGraphEditor";
import {
  createPersistedWorkflow,
  createWorkflowRevision,
  getPersistedWorkflow,
  getWorkflowRun,
  listPersistedWorkflows,
  queueWorkflowRun,
} from "./workflowPersistenceApi";

function parseInputs(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Workflow run inputs must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function WorkflowPersistencePanel({
  projectId,
  workflow,
  onLoadWorkflow,
}: {
  projectId: string;
  workflow: EditableWorkflow;
  onLoadWorkflow: (workflow: EditableWorkflow) => void;
}) {
  const queryClient = useQueryClient();
  const [workflowId, setWorkflowId] = useState("");
  const [description, setDescription] = useState("");
  const [runInputs, setRunInputs] = useState("{}");
  const [useCache, setUseCache] = useState(true);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const workflows = useQuery({
    queryKey: ["persisted_workflows", projectId],
    queryFn: ({ signal }) => listPersistedWorkflows(projectId, signal),
  });
  const selected = useQuery({
    queryKey: ["persisted_workflow", workflowId],
    queryFn: ({ signal }) => getPersistedWorkflow(workflowId, signal),
    enabled: Boolean(workflowId),
  });
  const activeRun = useQuery({
    queryKey: ["workflow_run", activeRunId],
    queryFn: ({ signal }) => getWorkflowRun(activeRunId as string, signal),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "cancelled"].includes(status)
        ? false
        : 1000;
    },
  });

  useEffect(() => {
    if (!workflowId && workflows.data?.length) {
      setWorkflowId(workflows.data[0].id);
    }
  }, [workflowId, workflows.data]);

  useEffect(() => {
    if (selected.data) {
      setDescription(selected.data.workflow.description ?? "");
    }
  }, [selected.data]);

  const currentPersisted = useMemo(
    () => workflows.data?.find((item) => item.id === workflowId) ?? null,
    [workflowId, workflows.data],
  );

  const save = useMutation({
    mutationFn: async () => {
      if (workflowId) {
        return createWorkflowRevision(workflowId, workflow);
      }
      return createPersistedWorkflow(projectId, {
        name: workflow.name,
        description: description.trim() || null,
        workflow,
        status: "draft",
      });
    },
    onSuccess: async (detail) => {
      setWorkflowId(detail.workflow.id);
      setMessage(
        `Saved ${detail.workflow.name} revision ${detail.current_revision.revision_number} (${detail.current_revision.workflow_checksum.slice(0, 12)}…).`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["persisted_workflows", projectId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["persisted_workflow", detail.workflow.id],
        }),
      ]);
    },
  });

  const run = useMutation({
    mutationFn: async () => {
      let targetId = workflowId;
      let revisionId = selected.data?.current_revision.id;
      if (!targetId) {
        const detail = await createPersistedWorkflow(projectId, {
          name: workflow.name,
          description: description.trim() || null,
          workflow,
          status: "draft",
        });
        targetId = detail.workflow.id;
        revisionId = detail.current_revision.id;
        setWorkflowId(targetId);
      } else {
        const detail = await createWorkflowRevision(targetId, workflow);
        revisionId = detail.current_revision.id;
      }
      const result = await queueWorkflowRun(targetId, {
        workflow_revision_id: revisionId,
        inputs: parseInputs(runInputs),
        use_cache: useCache,
      });
      return result;
    },
    onSuccess: async (result) => {
      setActiveRunId(result.run.id);
      setMessage(
        `Run ${result.run.id.slice(0, 8)} queued from immutable revision ${result.run.workflow_revision_id.slice(0, 8)}.`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["persisted_workflows", projectId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["workflow_runs", result.run.workflow_id],
        }),
      ]);
    },
  });

  const error = workflows.error ?? selected.error ?? save.error ?? run.error ?? activeRun.error;

  return (
    <article className="dashboard-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Persist and execute</p>
          <h4>Save revisions and run the graph</h4>
          <span>
            Every launch pins an immutable workflow revision. Compatible upstream
            artifacts may be reused when cache reuse is enabled.
          </span>
        </div>
        <span>
          {currentPersisted
            ? `Revision ${currentPersisted.current_revision_number}`
            : "Unsaved graph"}
        </span>
      </div>

      {message && <p className="form-success">{message}</p>}
      {error && <p className="form-error">{error.message}</p>}

      <label>
        Persisted workflow
        <select
          value={workflowId}
          onChange={(event) => {
            setWorkflowId(event.target.value);
            setMessage(null);
            setActiveRunId(null);
          }}
        >
          <option value="">Save as a new workflow</option>
          {workflows.data?.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · revision {item.current_revision_number}
            </option>
          ))}
        </select>
      </label>

      <label>
        Description
        <textarea
          rows={3}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Scientific purpose, assumptions, or intended dataset."
        />
      </label>

      {selected.data && (
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => {
              onLoadWorkflow(
                selected.data.current_revision.workflow_json as unknown as EditableWorkflow,
              );
              setMessage(
                `Loaded persisted revision ${selected.data.current_revision.revision_number} into the editor.`,
              );
            }}
          >
            Load selected revision
          </button>
          <small>
            {selected.data.current_revision.workflow_checksum.slice(0, 16)}…
          </small>
        </div>
      )}

      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          disabled={save.isPending || run.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending
            ? "Saving revision..."
            : workflowId
              ? "Save new revision"
              : "Save workflow"}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={save.isPending || run.isPending}
          onClick={() => run.mutate()}
        >
          {run.isPending ? "Queuing run..." : "Save revision and run"}
        </button>
      </div>

      <label>
        Run inputs (JSON object)
        <textarea
          rows={5}
          value={runInputs}
          onChange={(event) => setRunInputs(event.target.value)}
          spellCheck={false}
        />
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={useCache}
          onChange={(event) => setUseCache(event.target.checked)}
        />
        Reuse compatible cached artifacts
      </label>

      {activeRun.data && (
        <div className="dashboard-list" aria-live="polite">
          <div className="dashboard-row">
            <div>
              <strong>
                Run {activeRun.data.id.slice(0, 8)} · {activeRun.data.status}
              </strong>
              <p>{activeRun.data.stage}</p>
              <small>
                {activeRun.data.current_node_id
                  ? `Current node: ${activeRun.data.current_node_id}`
                  : "No node is currently executing."}
              </small>
            </div>
            <span>
              {Object.keys(activeRun.data.node_state_json).length} node states
            </span>
          </div>
          {activeRun.data.error_message && (
            <p className="form-error">{activeRun.data.error_message}</p>
          )}
        </div>
      )}
    </article>
  );
}
