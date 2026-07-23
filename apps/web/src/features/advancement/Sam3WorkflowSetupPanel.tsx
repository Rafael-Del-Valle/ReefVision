import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getProject } from "../../api/client";
import { getModels } from "../phase456/api";
import { registerSam3SidecarModel } from "./sam3SidecarApi";

export function Sam3WorkflowSetupPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("SAM 3 octocoral segmenter");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8765");
  const [conceptPrompt, setConceptPrompt] = useState(
    "octocoral colony or fragment",
  );
  const [labelClassId, setLabelClassId] = useState("");
  const [sam2ModelId, setSam2ModelId] = useState("");
  const [scoreThreshold, setScoreThreshold] = useState(0.35);
  const [tokenEnv, setTokenEnv] = useState(
    "REEFVISION_SAM3_SIDECAR_TOKEN",
  );

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => getProject(projectId, signal),
  });
  const models = useQuery({
    queryKey: ["models", projectId],
    queryFn: ({ signal }) => getModels(projectId, signal),
  });
  const activeClasses = useMemo(
    () => project.data?.label_classes.filter((item) => item.is_active) ?? [],
    [project.data],
  );
  const sam2Models = useMemo(
    () =>
      models.data?.filter(
        (item) =>
          item.provider_name.toLowerCase() === "sam2" &&
          item.purpose === "assist" &&
          item.task === "assist_segmentation",
      ) ?? [],
    [models.data],
  );
  useEffect(() => {
    if (!labelClassId && activeClasses.length) {
      setLabelClassId(activeClasses[0].id);
    }
  }, [activeClasses, labelClassId]);
  useEffect(() => {
    if (!sam2ModelId && sam2Models.length) {
      setSam2ModelId(sam2Models[0].id);
    }
  }, [sam2ModelId, sam2Models]);

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

  const exactConfiguration = {
    enabled: true,
    mode: "independent_masks",
    required_primary_provider: "sam3_sidecar",
    sam2_model_id: sam2ModelId || "<select-registered-sam2-assist-model>",
    label_class_id: labelClassId || "<select-project-class>",
    predicted_label: conceptPrompt,
    prompt: conceptPrompt,
    required_votes: 2,
    iou_threshold: 0.3,
    aggregation: "pixel_majority",
    minimum_vlm_confidence: 0.25,
    gemini_model: "gemini-2.5-flash",
    openai_model: "gpt-5-mini",
    sam2_device: "auto",
    allow_remote_review: false,
    auto_accept: false,
    fail_closed: true,
  };

  return (
    <section className="dashboard-panel" data-testid="sam3-workflow-setup">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Multi-model auto-labeling</p>
          <h3>Connect SAM 3 and SAM 2 to Workflows</h3>
          <span>
            Choose the lower-cost semantic-review workflow or the independent
            three-mask workflow that matches instances and aggregates pixels.
          </span>
        </div>
        <span>Local segmenters · remote branches opt-in</span>
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
          <h4>2. Register the SAM 3 concept segmenter</h4>
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
          {(project.error || models.error || register.error) && (
            <p className="form-error">
              {project.error?.message ??
                models.error?.message ??
                register.error?.message}
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
          <h4>3. Select SAM 2 for independent refinement</h4>
          <p>
            The exact three-branch workflow turns Gemini and OpenAI boxes into
            masks with a trusted local SAM 2 Prompt Assist checkpoint.
          </p>
          <label>
            Registered SAM 2 assist model
            <select
              value={sam2ModelId}
              onChange={(event) => setSam2ModelId(event.target.value)}
            >
              <option value="">Choose a SAM 2 model</option>
              {sam2Models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.display_name}
                </option>
              ))}
            </select>
          </label>
          {!sam2Models.length && (
            <p className="form-error">
              No registered SAM 2 Prompt Assist model is available. Import one
              before running independent-mask consensus.
            </p>
          )}
          <p>
            The default aggregation is <code>pixel_majority</code>: a pixel is
            retained when at least two independent branches include it. Switch to
            <code>intersection</code> for the article&apos;s most conservative output.
          </p>
        </article>

        <article className="dashboard-card">
          <h4>4. Review the exact-mode node configuration</h4>
          <pre>{JSON.stringify(exactConfiguration, null, 2)}</pre>
          <small>
            Apply this object as <code>multi_model_consensus</code> on the SAM 3
            segmenter node. Keep <code>auto_accept</code> false until the workflow
            has been validated on representative images.
          </small>
        </article>

        <article className="dashboard-card">
          <h4>5. Enable remote branches deliberately</h4>
          <p>
            Set <code>REEFVISION_ALLOW_REMOTE_VISION=true</code>,{" "}
            <code>REEFVISION_GEMINI_API_KEY</code>, and{" "}
            <code>REEFVISION_OPENAI_API_KEY</code>. Then change the node&apos;s{" "}
            <code>allow_remote_review</code> value to <code>true</code>.
          </p>
          <p>
            Semantic-review mode sends source crops and highlighted-mask overlays.
            Independent-mask mode sends each selected full image to Gemini and
            OpenAI so both can detect objects independently. The default remains
            disabled to prevent accidental data transfer or API charges.
          </p>
        </article>
      </div>
    </section>
  );
}
