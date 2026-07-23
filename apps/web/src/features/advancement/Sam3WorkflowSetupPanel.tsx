import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getProject } from "../../api/client";
import { registerSam3SidecarModel } from "./sam3SidecarApi";

export function Sam3WorkflowSetupPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("SAM 3 octocoral segmenter");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8765");
  const [conceptPrompt, setConceptPrompt] = useState(
    "octocoral colony or fragment",
  );
  const [labelClassId, setLabelClassId] = useState("");
  const [scoreThreshold, setScoreThreshold] = useState(0.35);
  const [tokenEnv, setTokenEnv] = useState(
    "REEFVISION_SAM3_SIDECAR_TOKEN",
  );

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => getProject(projectId, signal),
  });
  const activeClasses = useMemo(
    () => project.data?.label_classes.filter((item) => item.is_active) ?? [],
    [project.data],
  );
  useEffect(() => {
    if (!labelClassId && activeClasses.length) {
      setLabelClassId(activeClasses[0].id);
    }
  }, [activeClasses, labelClassId]);

  const register = useMutation({
    mutationFn: () =>
      registerSam3SidecarModel(projectId, {
        display_name: displayName.trim(),
        endpoint: endpoint.trim(),
        concept_prompt: conceptPrompt.trim(),
        label_class_id: labelClassId,
        score_threshold: scoreThreshold,
        token_env: tokenEnv.trim(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["phase5_models", projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["models", projectId],
      });
    },
  });

  const invalid =
    !displayName.trim() ||
    !endpoint.trim() ||
    !conceptPrompt.trim() ||
    !labelClassId ||
    scoreThreshold < 0 ||
    scoreThreshold > 1 ||
    !/^[A-Z][A-Z0-9_]*$/.test(tokenEnv);

  return (
    <section className="dashboard-panel" data-testid="sam3-workflow-setup">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Multi-model auto-labeling</p>
          <h3>Connect SAM 3 to Workflows</h3>
          <span>
            Register a localhost SAM 3 concept segmenter, then use the SAM 3 +
            Gemini + GPT template to require two accepted votes per mask.
          </span>
        </div>
        <span>Local sidecar · remote reviewers opt-in</span>
      </div>

      <div className="dashboard-layout">
        <article className="dashboard-card">
          <h4>1. Start the isolated SAM 3 runtime</h4>
          <p>
            Run <code>python scripts/sam3_sidecar_server.py</code> inside the
            dedicated SAM 3 Python 3.12/CUDA environment. The server binds to
            localhost by default.
          </p>
          <label>
            Sidecar endpoint
            <input
              value={endpoint}
              onChange={(event) => setEndpoint(event.target.value)}
            />
          </label>
          <label>
            Optional bearer-token environment variable
            <input
              value={tokenEnv}
              onChange={(event) => setTokenEnv(event.target.value)}
            />
          </label>
          <small>
            Set the same environment variable in ReefVision and the sidecar
            process. Keys and bearer tokens are never stored in the Workflow.
          </small>
        </article>

        <article className="dashboard-card">
          <h4>2. Register the concept segmenter</h4>
          <label>
            Model name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>
          <label>
            SAM 3 text concept
            <input
              value={conceptPrompt}
              onChange={(event) => setConceptPrompt(event.target.value)}
            />
          </label>
          <label>
            Map every accepted instance to
            <select
              value={labelClassId}
              onChange={(event) => setLabelClassId(event.target.value)}
            >
              <option value="">Choose a project class</option>
              {activeClasses.map((labelClass) => (
                <option key={labelClass.id} value={labelClass.id}>
                  {labelClass.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            SAM 3 minimum score
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={scoreThreshold}
              onChange={(event) =>
                setScoreThreshold(Number(event.target.value))
              }
            />
          </label>
          <button
            type="button"
            disabled={invalid || register.isPending}
            onClick={() => register.mutate()}
          >
            {register.isPending ? "Registering..." : "Register SAM 3 segmenter"}
          </button>
          {(project.error || register.error) && (
            <p className="form-error">
              {project.error?.message ?? register.error?.message}
            </p>
          )}
          {register.data && (
            <div className="form-success">
              <strong>{register.data.display_name} registered.</strong>
              <p>
                Set the Workflow segmenter node <code>model_id</code> to{" "}
                <code>{register.data.id}</code>.
              </p>
            </div>
          )}
        </article>

        <article className="dashboard-card">
          <h4>3. Enable the reviewers deliberately</h4>
          <p>
            Before running the template, set{" "}
            <code>REEFVISION_ALLOW_REMOTE_VISION=true</code>,{" "}
            <code>REEFVISION_GEMINI_API_KEY</code>, and{" "}
            <code>REEFVISION_OPENAI_API_KEY</code>. Then change the node&apos;s{" "}
            <code>allow_remote_review</code> value to <code>true</code>.
          </p>
          <p>
            Source crops and highlighted-mask overlays are sent to Gemini and
            OpenAI. The default remains disabled to prevent accidental data
            transfer or API charges.
          </p>
        </article>
      </div>
    </section>
  );
}
