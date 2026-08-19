import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  getAdvancedProviderManifests,
  preflightAdvancedProvider,
} from "./advancedProvidersApi";

interface AdvancedProviderWorkspaceProps {
  project: Project;
}

export function AdvancedProviderWorkspace({
  project,
}: AdvancedProviderWorkspaceProps) {
  const [providerId, setProviderId] = useState("");
  const [task, setTask] = useState("");
  const [device, setDevice] = useState("auto");
  const [modelId, setModelId] = useState("");
  const [promptJson, setPromptJson] = useState("{}");

  const manifestsQuery = useQuery({
    queryKey: ["advanced-provider-manifests"],
    queryFn: ({ signal }) => getAdvancedProviderManifests(signal),
  });
  const selectedManifest = useMemo(
    () => manifestsQuery.data?.find((item) => item.provider_id === providerId),
    [manifestsQuery.data, providerId],
  );

  useEffect(() => {
    if (!providerId && manifestsQuery.data?.[0]) {
      setProviderId(manifestsQuery.data[0].provider_id);
    }
  }, [manifestsQuery.data, providerId]);
  useEffect(() => {
    const firstTask = selectedManifest?.supported_tasks[0] ?? "";
    const resolvedTask = selectedManifest?.supported_tasks.includes(task)
      ? task
      : firstTask;
    if (resolvedTask !== task) setTask(resolvedTask);
    const fields = resolvedTask
      ? (selectedManifest?.prompt_fields_by_task[resolvedTask] ?? [])
      : [];
    const example = Object.fromEntries(
      fields.map((field) => [
        field,
        field.endsWith("_id") ? "select-in-workflow" : "required",
      ]),
    );
    setPromptJson(JSON.stringify(example, null, 2));
  }, [selectedManifest, task]);

  const preflightMutation = useMutation({
    mutationFn: () => {
      const promptFields = JSON.parse(promptJson) as Record<string, unknown>;
      return preflightAdvancedProvider(project.id, providerId, {
        task,
        device,
        model_id: modelId || null,
        prompt_fields: promptFields,
      });
    },
  });

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 8</p>
          <h3>Advanced Provider Lab</h3>
          <p>
            Inspect optional model adapters and run fail-closed preflight
            checks. A blocked provider is documented here, not exposed as a
            working tool.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>Provider manifest</h4>
          <label>
            Provider
            <select
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
            >
              {manifestsQuery.data?.map((manifest) => (
                <option key={manifest.provider_id} value={manifest.provider_id}>
                  {manifest.display_name} · {manifest.maturity}
                </option>
              ))}
            </select>
          </label>
          {selectedManifest && (
            <>
              <p>
                Execution:{" "}
                <strong>
                  {selectedManifest.execution_supported
                    ? "implemented"
                    : "blocked"}
                </strong>
              </p>
              <p>Tasks: {selectedManifest.supported_tasks.join(", ")}</p>
              <p>
                Model files:{" "}
                {selectedManifest.required_model_extensions.join(", ")}
              </p>
              <h5>Packages</h5>
              <ul>
                {selectedManifest.required_packages.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h5>Known limitations</h5>
              <ul>
                {selectedManifest.known_limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>

        <form
          className="panel-card"
          onSubmit={(event) => {
            event.preventDefault();
            preflightMutation.mutate();
          }}
        >
          <h4>Execution preflight</h4>
          <label>
            Task
            <select
              value={task}
              onChange={(event) => setTask(event.target.value)}
            >
              {selectedManifest?.supported_tasks.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Registered model ID
            <input
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
              placeholder="Required for executable providers"
            />
          </label>
          <label>
            Device
            <select
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="cuda">CUDA</option>
              <option value="cpu">CPU</option>
            </select>
          </label>
          <label>
            Prompt fields JSON
            <textarea
              rows={10}
              value={promptJson}
              onChange={(event) => setPromptJson(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={!providerId || !task || preflightMutation.isPending}
          >
            {preflightMutation.isPending ? "Checking..." : "Run preflight"}
          </button>
          {preflightMutation.error && (
            <p className="form-error">{preflightMutation.error.message}</p>
          )}
        </form>

        <div className="panel-card">
          <h4>Preflight result</h4>
          {preflightMutation.data ? (
            <>
              <p>
                Ready:{" "}
                <strong>{preflightMutation.data.ready ? "Yes" : "No"}</strong>
              </p>
              <p>Availability: {preflightMutation.data.availability_status}</p>
              <p>
                Outputs: {preflightMutation.data.output_contract.join(", ")}
              </p>
              <h5>Blockers</h5>
              {preflightMutation.data.blockers.length ? (
                <ul>
                  {preflightMutation.data.blockers.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>None.</p>
              )}
              <h5>Warnings</h5>
              {preflightMutation.data.warnings.length ? (
                <ul>
                  {preflightMutation.data.warnings.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>None.</p>
              )}
            </>
          ) : (
            <p>
              Run preflight to inspect prompts, assets, packages, and execution
              blockers.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
