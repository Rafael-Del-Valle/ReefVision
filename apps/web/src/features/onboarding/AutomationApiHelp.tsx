import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { listSavedWorkflowGraphs } from "../workflow-graphs/workflowGraphApi";

const executable = ".\\automation\\reefvision.exe";
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const sha256 = /^[0-9a-f]{64}$/;

function attachedCommandPrefix(baseUrl: string): string | null {
  try {
    const url = new URL(baseUrl);
    if (
      url.protocol !== "http:" ||
      !["127.0.0.1", "[::1]", "localhost"].includes(url.hostname) ||
      url.pathname.replace(/\/$/, "") !== "/api/v1" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    )
      return null;
    return `${executable} --api-url ${url.origin}/api/v1`;
  } catch {
    return null;
  }
}

function CopyableCommand({
  label,
  action,
  command,
}: {
  label: string;
  action: string;
  command: string;
}) {
  const field = useRef<HTMLTextAreaElement>(null);
  const [feedback, setFeedback] = useState<{
    command: string;
    message: string;
  }>();

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(command);
      setFeedback({ command, message: "Copied command." });
    } catch {
      field.current?.focus();
      field.current?.select();
      setFeedback({
        command,
        message: "Command selected. Press Ctrl+C to copy.",
      });
    }
  }

  return (
    <div className="rv-automation-command">
      <label>
        {label}
        <textarea
          rows={3}
          ref={field}
          readOnly
          value={command}
          spellCheck={false}
        />
      </label>
      <button type="button" className="secondary" onClick={() => void copy()}>
        Copy {action} command
      </button>
      {feedback?.command === command && <p role="status">{feedback.message}</p>}
    </div>
  );
}

export function AutomationApiHelp({
  apiBaseUrl,
  project,
  preferredRevisionId,
}: {
  apiBaseUrl: string;
  project?: { id: string; name: string };
  preferredRevisionId?: string;
}) {
  const activeProject = project && uuid.test(project.id) ? project : undefined;
  const attached = attachedCommandPrefix(apiBaseUrl);
  const projectId = activeProject?.id ?? "";
  const [selected, setSelected] = useState<string>();
  const [mode, setMode] = useState<"plan" | "run">("plan");
  const revisions = useQuery({
    queryKey: ["workflow-graphs", projectId],
    queryFn: ({ signal }) => listSavedWorkflowGraphs(projectId, signal),
    enabled: Boolean(attached && projectId),
  });
  const records = (revisions.data ?? []).filter(
    (record) =>
      record.project_id === projectId &&
      uuid.test(record.id) &&
      sha256.test(record.graph_sha256),
  );
  const selectedRevision = records.find(
    (record) => record.id === (selected ?? preferredRevisionId),
  );

  return (
    <div className="rv-automation-help">
      <p>
        Open PowerShell in the ReefVision installation folder to use{" "}
        <code>{executable}</code>.
      </p>
      <section className="onboarding-card" aria-label="Attach to the desktop">
        <h3>Attach to the desktop</h3>
        <p>
          Keep this desktop open while the command runs. Use{" "}
          <code>--api-url</code> to use the same local service as the desktop.
        </p>
        {!attached && (
          <p>Connect to a local ReefVision API to create attached commands.</p>
        )}
        {attached && !activeProject && (
          <p>Open a project to generate its commands.</p>
        )}
        {attached && activeProject && (
          <>
            <p>
              <strong>{activeProject.name}</strong> · <code>{projectId}</code>
            </p>
            <CopyableCommand
              label="Open project command"
              action="project open"
              command={`${attached} project open ${projectId}`}
            />
            {revisions.isPending && (
              <p role="status">Loading saved revisions…</p>
            )}
            {revisions.isError && (
              <p role="alert">
                Could not load saved revisions. Reopen Automation API to try
                again.
              </p>
            )}
            {!revisions.isPending &&
              !revisions.isError &&
              records.length === 0 && (
                <p>
                  Save a revision in Workflow Builder to generate a pinned
                  command.
                </p>
              )}
            {!revisions.isError && records.length > 0 && (
              <>
                <div className="rv-automation-options">
                  <label>
                    Saved workflow revision
                    <select
                      value={selectedRevision?.id ?? ""}
                      onChange={(event) =>
                        setSelected(event.currentTarget.value)
                      }
                    >
                      <option value="">Choose a saved revision</option>
                      {records.map((record) => (
                        <option key={record.id} value={record.id}>
                          {record.name} · revision {record.revision} ·{" "}
                          {record.graph_sha256.slice(0, 12)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Workflow action
                    <select
                      value={mode}
                      onChange={(event) =>
                        setMode(
                          event.currentTarget.value === "run" ? "run" : "plan",
                        )
                      }
                    >
                      <option value="plan">Plan</option>
                      <option value="run">Run</option>
                    </select>
                  </label>
                </div>
                {selectedRevision && (
                  <CopyableCommand
                    label="Pinned workflow command"
                    action="workflow"
                    command={`${attached} workflow ${mode} ${projectId} ${selectedRevision.id} --sha256 ${selectedRevision.graph_sha256}`}
                  />
                )}
              </>
            )}
          </>
        )}
      </section>
      <section
        className="onboarding-card"
        aria-label="Offline profile and review"
      >
        <h3>Offline profile and review</h3>
        <p>
          Use <code>--profile</code> with an absolute path to a separate offline
          profile.
        </p>
        <pre>
          <code>{`${executable} --profile 'C:\\ReefVisionOffline' project create 'Survey notes'`}</code>
        </pre>
        <p>
          Exit code 3 means the workflow is waiting for human review. Inspect
          the evidence before running <code>workflow resume</code> with the
          project and run IDs, <code>--node</code> review node ID,{" "}
          <code>--reviewer</code>, and <code>--note</code>.
        </p>
        <p>
          Use <code>infer --help</code>, <code>benchmark --help</code>, or{" "}
          <code>export --help</code> after the executable to see the required
          inputs.
        </p>
      </section>
    </div>
  );
}
