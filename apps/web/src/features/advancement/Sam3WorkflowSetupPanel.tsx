import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getProject } from "../../api/client";
import { getModels } from "../phase456/api";
import {
  checkSam2SidecarHealth,
  registerSam2SidecarModel,
} from "./sam2SidecarApi";
import { registerSam3SidecarModel } from "./sam3SidecarApi";

const TOKEN_ENV_PATTERN = /^[A-Z][A-Z0-9_]*$/;

export function Sam3WorkflowSetupPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("SAM 3 octocoral segmenter");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8765");
  const [conceptPrompt, setConceptPrompt] = useState(
    "octocoral colony or fragment",
  );
  const [labelClassId, setLabelClassId] = useState("");
  const [scoreThreshold, setScoreThreshold] = useState(0.35);
  const [tokenEnv, setTokenEnv] = useState("REEFVISION_SAM3_SIDECAR_TOKEN");
  const [sam2ModelId, setSam2ModelId] = useState("");
  const [sam2DisplayName, setSam2DisplayName] = useState(
    "SAM 2 Hiera Large sidecar",
  );
  const [sam2Endpoint, setSam2Endpoint] = useState("http://127.0.0.1:8766");
  const [sam2TokenEnv, setSam2TokenEnv] = useState(
    "REEFVISION_SAM2_SIDECAR_TOKEN",
  );
  const [sam2TimeoutSeconds, setSam2TimeoutSeconds] = useState(120);

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
          ["sam2", "sam2_sidecar"].includes(item.provider_name.toLowerCase()) &&
          item.purpose === "assist" &&
          item.task === "assist_segmentation",
      ) ?? [],
    [models.data],
  );
  const selectedSam2Model = useMemo(
    () => sam2Models.find((item) => item.id === sam2ModelId) ?? null,
    [sam2ModelId, sam2Models],
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

  const registerSam3 = useMutation({
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
  const sam2Connection = {
    endpoint: sam2Endpoint.trim(),
    token_env: sam2TokenEnv.trim(),
    timeout_seconds: sam2TimeoutSeconds,
  };
  const checkSam2 = useMutation({
    mutationFn: () => checkSam2SidecarHealth(sam2Connection),
  });
  const registerSam2 = useMutation({
    mutationFn: () =>
      registerSam2SidecarModel(projectId, {
        ...sam2Connection,
        display_name: sam2DisplayName.trim(),
      }),
    onSuccess: async (model) => {
      setSam2ModelId(model.id);
      await queryClient.invalidateQueries({
        queryKey: ["phase5_models", projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["models", projectId],
      });
    },
  });

  const invalidSam3 =
    !displayName.trim() ||
    !endpoint.trim() ||
    !conceptPrompt.trim() ||
    !labelClassId ||
    scoreThreshold < 0 ||
    scoreThreshold > 1 ||
    !TOKEN_ENV_PATTERN.test(tokenEnv);
  const invalidSam2 =
    !sam2DisplayName.trim() ||
    !sam2Endpoint.trim() ||
    sam2TimeoutSeconds < 1 ||
    sam2TimeoutSeconds > 600 ||
    !TOKEN_ENV_PATTERN.test(sam2TokenEnv);

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
            disabled={invalidSam3 || registerSam3.isPending}
            onClick={() => registerSam3.mutate()}
          >
            {registerSam3.isPending
              ? "Registering..."
              : "Register SAM 3 segmenter"}
          </button>
          {registerSam3.data && (
            <div className="form-success">
              <strong>{registerSam3.data.display_name} registered.</strong>
              <p>
                Set the Workflow segmenter node <code>model_id</code> to{" "}
                <code>{registerSam3.data.id}</code>.
              </p>
            </div>
          )}
        </article>

        <article className="dashboard-card">
          <h4>3. Start and test the isolated SAM 2 runtime</h4>
          <p>
            Start the sidecar from its dedicated Meta SAM 2 environment. Replace
            the example config and checkpoint paths with the files installed in
            that environment.
          </p>
          <pre>
            python scripts/sam2_sidecar_server.py --config
            configs/sam2.1/sam2.1_hiera_l.yaml --checkpoint
            checkpoints/sam2.1_hiera_large.pt --device cuda:0
          </pre>
          <label>
            SAM 2 sidecar endpoint
            <input
              value={sam2Endpoint}
              onChange={(event) => setSam2Endpoint(event.target.value)}
            />
          </label>
          <label>
            Bearer-token environment variable
            <input
              value={sam2TokenEnv}
              onChange={(event) => setSam2TokenEnv(event.target.value)}
            />
          </label>
          <label>
            Timeout in seconds
            <input
              type="number"
              min="1"
              max="600"
              value={sam2TimeoutSeconds}
              onChange={(event) =>
                setSam2TimeoutSeconds(Number(event.target.value))
              }
            />
          </label>
          <button
            type="button"
            disabled={invalidSam2 || checkSam2.isPending}
            onClick={() => checkSam2.mutate()}
          >
            {checkSam2.isPending ? "Checking..." : "Test SAM 2 connection"}
          </button>
          {checkSam2.data && (
            <div className="form-success" data-testid="sam2-health-success">
              <strong>SAM 2 sidecar is ready.</strong>
              <p>
                {checkSam2.data.model_version ?? "Unknown model"} on{" "}
                <code>{checkSam2.data.device}</code>. Token{" "}
                {checkSam2.data.token_configured
                  ? "configured"
                  : "not configured"}
                .
              </p>
            </div>
          )}
        </article>

        <article className="dashboard-card">
          <h4>4. Register or select SAM 2 refinement</h4>
          <p>
            Sidecar registrations keep Meta SAM 2 outside ReefVision&apos;s
            pinned desktop runtime. Existing in-process SAM 2 registrations
            remain valid.
          </p>
          <label>
            Sidecar registration name
            <input
              value={sam2DisplayName}
              onChange={(event) => setSam2DisplayName(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={invalidSam2 || registerSam2.isPending}
            onClick={() => registerSam2.mutate()}
          >
            {registerSam2.isPending
              ? "Registering..."
              : "Register SAM 2 sidecar"}
          </button>
          {registerSam2.data && (
            <div className="form-success">
              <strong>{registerSam2.data.display_name} registered.</strong>
            </div>
          )}
          <label>
            Registered SAM 2 assist model
            <select
              value={sam2ModelId}
              onChange={(event) => setSam2ModelId(event.target.value)}
            >
              <option value="">Choose a SAM 2 model</option>
              {sam2Models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.display_name} ·{" "}
                  {model.provider_name === "sam2_sidecar"
                    ? "isolated sidecar"
                    : "in process"}
                </option>
              ))}
            </select>
          </label>
          {selectedSam2Model && (
            <small>
              Selected provider: <code>{selectedSam2Model.provider_name}</code>
            </small>
          )}
          {!sam2Models.length && (
            <p className="form-error">
              No registered SAM 2 Prompt Assist model is available. Register the
              sidecar above or import a compatible local checkpoint.
            </p>
          )}
          <p>
            The default aggregation is <code>pixel_majority</code>: a pixel is
            retained when at least two independent branches include it. Switch
            to
            <code>intersection</code> for the article&apos;s most conservative
            output.
          </p>
        </article>

        <article className="dashboard-card">
          <h4>5. Review the exact-mode node configuration</h4>
          <pre>{JSON.stringify(exactConfiguration, null, 2)}</pre>
          <small>
            Apply this object as <code>multi_model_consensus</code> on the SAM 3
            segmenter node. Keep <code>auto_accept</code> false until the
            workflow has been validated on representative images.
          </small>
        </article>

        <article className="dashboard-card">
          <h4>6. Enable remote branches deliberately</h4>
          <p>
            Set <code>REEFVISION_ALLOW_REMOTE_VISION=true</code>,{" "}
            <code>REEFVISION_GEMINI_API_KEY</code>, and{" "}
            <code>REEFVISION_OPENAI_API_KEY</code>. Then change the node&apos;s{" "}
            <code>allow_remote_review</code> value to <code>true</code>.
          </p>
          <p>
            Semantic-review mode sends source crops and highlighted-mask
            overlays. Independent-mask mode sends each selected full image to
            Gemini and OpenAI so both can detect objects independently. The
            default remains disabled to prevent accidental data transfer or API
            charges.
          </p>
        </article>
      </div>

      {(project.error ||
        models.error ||
        registerSam3.error ||
        checkSam2.error ||
        registerSam2.error) && (
        <p className="form-error">
          {project.error?.message ??
            models.error?.message ??
            registerSam3.error?.message ??
            checkSam2.error?.message ??
            registerSam2.error?.message}
        </p>
      )}
    </section>
  );
}
