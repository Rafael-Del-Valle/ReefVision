import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getModelHubBootstrap, type Project } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { getPoseTrainingDatasets } from "../video/poseActiveLearningApi";
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
  type WorkflowArtifact,
} from "./workflowGraphApi";
import {
  createPoseArchitectureWorkflow,
  workflowTemplates,
} from "./workflowTemplates";
import { LocalMeshPreview } from "./LocalMeshPreview";
import { LocalPointCloudPreview } from "./LocalPointCloudPreview";
import { ProjectSpatialAssetPreview } from "./ProjectSpatialAssetPreview";
import { downloadPairedReport } from "../ecology/pairedGrowthContrastApi";
import { downloadFieldReconciliation } from "../field-capture/fieldCaptureApi";
import { MeshArtifactViewer } from "./MeshArtifactViewer";
import { PointCloudArtifactViewer } from "./PointCloudArtifactViewer";
import { WorkflowVisualEditor } from "./WorkflowVisualEditor";
import { scientificConfigurationIssue } from "./ScientificNodeControls";

interface WorkflowGraphWorkspaceProps {
  project: Project;
  initialPoseArchitecture?: string | null;
  initialRunId?: string | null;
  initialGraph?: Record<string, unknown>;
  onOpenScience?: (
    view: "ecology" | "models" | "quality_control" | "video",
  ) => void;
  onOpenReviewQueue?: (queueId: string, datasetVersionId?: string) => void;
}

function ScienceArtifact({
  artifact,
  projectId,
  onOpen,
  onOpenReviewQueue,
}: {
  artifact: WorkflowArtifact;
  projectId: string;
  onOpen: WorkflowGraphWorkspaceProps["onOpenScience"];
  onOpenReviewQueue: WorkflowGraphWorkspaceProps["onOpenReviewQueue"];
}) {
  const data = artifact.payload_json;
  const api = `${getApiBaseUrl()}/projects/${projectId}`;
  if (
    artifact.data_type === "review_queue_reference" &&
    data.project_id === projectId &&
    typeof data.queue_id === "string" &&
    data.review_status === "requires_researcher_review"
  ) {
    const queueId = data.queue_id;
    const datasetVersionId =
      typeof data.dataset_version_id === "string"
        ? data.dataset_version_id
        : undefined;
    return (
      <div>
        <p>
          {String(data.item_count)} ranked images · Requires researcher review
        </p>
        {onOpenReviewQueue && (
          <button
            type="button"
            onClick={() => onOpenReviewQueue(queueId, datasetVersionId)}
          >
            Open generated review queue
          </button>
        )}
      </div>
    );
  }
  if (
    artifact.data_type === "research_reproducibility_proof" &&
    typeof data.proof_sha256 === "string"
  ) {
    return (
      <p>
        Verified research proof · SHA-256 <code>{data.proof_sha256}</code>
      </p>
    );
  }
  if (
    artifact.data_type === "study_design_report" &&
    typeof data.content_sha256 === "string"
  ) {
    return (
      <p>
        Replayed frozen study design · SHA-256{" "}
        <code>{data.content_sha256}</code>
      </p>
    );
  }
  if (
    artifact.data_type === "field_capture_reconciliation" &&
    typeof data.report_sha256 === "string"
  ) {
    const digest = data.report_sha256;
    return (
      <button
        type="button"
        onClick={() => downloadFieldReconciliation(data, digest)}
      >
        Download field reconciliation JSON
      </button>
    );
  }
  if (
    artifact.data_type === "paired_growth_contrast" &&
    typeof data.report_sha256 === "string"
  ) {
    const digest = data.report_sha256;
    return (
      <div>
        <p>
          Paired growth contrast · {String(data.included_unit_count)}{" "}
          independent units
        </p>
        <button
          type="button"
          onClick={() => downloadPairedReport(data, digest)}
        >
          Download paired result JSON
        </button>
      </div>
    );
  }
  if (artifact.data_type === "acquisition_quality_result")
    return onOpen ? (
      <button type="button" onClick={() => onOpen("quality_control")}>
        Open Quality Control
      </button>
    ) : null;
  if (artifact.data_type === "verified_ecology_analysis")
    return onOpen ? (
      <button type="button" onClick={() => onOpen("ecology")}>
        Open reviewed analyses
      </button>
    ) : null;
  if (
    artifact.data_type === "reviewed_ecology_event_summary" &&
    typeof data.summary_id === "string"
  )
    return (
      <div className="button-row">
        <span>
          {Array.isArray(data.organisms) ? data.organisms.length : 0} organisms
        </span>
        <a
          href={`${api}/ecology/event-summaries/${data.summary_id}/results.csv`}
          download
        >
          Download event CSV
        </a>
        {onOpen && (
          <button type="button" onClick={() => onOpen("ecology")}>
            Open organism evidence
          </button>
        )}
      </div>
    );
  if (
    artifact.data_type === "research_report_figure" &&
    typeof data.report_id === "string"
  )
    return (
      <div className="button-row">
        <a
          href={`${api}/research-reports/${data.report_id}/figure.svg`}
          download
        >
          Download figure
        </a>
        <a
          href={`${api}/research-reports/${data.report_id}/table.csv`}
          download
        >
          Download table
        </a>
        {onOpen && (
          <button type="button" onClick={() => onOpen("ecology")}>
            Open Research reports
          </button>
        )}
      </div>
    );
  if (
    artifact.data_type === "scientific_comparison_report" &&
    typeof data.export_path === "string" &&
    data.export_path.startsWith(`/projects/${projectId}/`)
  )
    return (
      <div className="button-row">
        <a href={`${getApiBaseUrl()}${data.export_path}?format=csv`} download>
          Download comparison CSV
        </a>
        {onOpen && (
          <button type="button" onClick={() => onOpen("models")}>
            Open Model Hub comparisons
          </button>
        )}
      </div>
    );
  if (artifact.data_type === "mesh_longitudinal_comparison")
    return (
      <button
        type="button"
        className="secondary"
        onClick={() => downloadSpatialComparison(artifact)}
      >
        Download 3D comparison JSON
      </button>
    );
  if (artifact.data_type.startsWith("temporal_reefpose") && onOpen)
    return (
      <button type="button" onClick={() => onOpen("video")}>
        Open temporal ReefPose
      </button>
    );
  return null;
}

function downloadSpatialComparison(artifact: WorkflowArtifact): void {
  const blob = new Blob([JSON.stringify(artifact, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `3d-comparison-${artifact.id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function statusIsActive(status: string | undefined): boolean {
  return (
    status === "queued" ||
    status === "running" ||
    status === "cancel_requested" ||
    status === "waiting_for_review"
  );
}

function shortHash(value: string | undefined): string {
  if (!value) return "unavailable";
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

export function WorkflowGraphWorkspace({
  project,
  initialPoseArchitecture,
  initialRunId,
  initialGraph,
  onOpenScience,
  onOpenReviewQueue,
}: WorkflowGraphWorkspaceProps) {
  const queryClient = useQueryClient();
  const [graphJson, setGraphJson] = useState(() =>
    JSON.stringify(
      initialGraph ??
        (initialPoseArchitecture
          ? createPoseArchitectureWorkflow(initialPoseArchitecture)
          : (workflowTemplates[0]?.graph ?? {})),
      null,
      2,
    ),
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(
    initialRunId ?? null,
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState(
    workflowTemplates[0]?.id ?? "",
  );

  const visualGraph = safeParseGraph(graphJson);
  const graphNodes = Array.isArray(visualGraph?.nodes)
    ? (visualGraph.nodes as Array<{
        node_id: string;
        node_type: string;
        parameters?: Record<string, unknown>;
      }>)
    : [];
  const poseDatasetSources = graphNodes.filter(
    (node) => node.node_type === "pose_training_dataset",
  );
  const poseDatasets = useQuery({
    queryKey: ["pose-training-datasets", project.id],
    queryFn: ({ signal }) => getPoseTrainingDatasets(project.id, signal),
    enabled: poseDatasetSources.length > 0,
  });
  const modelHubQuery = useQuery({
    queryKey: ["model_hub_bootstrap", project.id],
    queryFn: ({ signal }) => getModelHubBootstrap(project.id, signal),
    enabled: poseDatasetSources.length > 0,
  });

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
    queryKey: ["workflow-run", project.id, selectedRunId],
    queryFn: async ({ signal }) => {
      const detail = await getWorkflowRunDetail(selectedRunId ?? "", signal);
      if (detail.run.project_id !== project.id)
        throw new Error("This run belongs to another project.");
      return detail;
    },
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
  const runSavedMutation = useMutation({
    mutationFn: (recordId: string) => queueWorkflowRun(project.id, recordId),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
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
    runSavedMutation.error ??
    resumeReviewMutation.error ??
    cancelMutation.error;
  const selectedRun = runDetailQuery.data?.run;
  useEffect(() => {
    if (selectedRun?.status === "succeeded") {
      void queryClient.invalidateQueries({
        queryKey: ["model_hub_bootstrap", project.id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["video-tracking-models", project.id],
      });
    }
  }, [project.id, queryClient, selectedRun?.status]);
  const selectedProvenanceSha =
    typeof selectedRun?.result_json.provenance_sha256 === "string"
      ? selectedRun.result_json.provenance_sha256
      : null;
  const selectedProvenanceManifest =
    selectedRun?.result_json.provenance_manifest &&
    !Array.isArray(selectedRun.result_json.provenance_manifest) &&
    typeof selectedRun.result_json.provenance_manifest === "object"
      ? (selectedRun.result_json.provenance_manifest as Record<string, unknown>)
      : null;
  const pytorchRuntime = modelHubQuery.data?.runtime_statuses?.find(
    (runtime) => runtime.runtime_id === "pytorch",
  );
  const reefposeCudaRequested = graphNodes.some(
    (node) =>
      node.node_type === "pose_model_training" &&
      node.parameters?.provider_id === "reefpose" &&
      String(node.parameters?.device ?? "auto").startsWith("cuda"),
  );
  const scienceIssue = graphNodes
    .map((node) =>
      scientificConfigurationIssue(node.node_type, node.parameters ?? {}),
    )
    .find(Boolean);
  const guiConfigurationIssue =
    reefposeCudaRequested && pytorchRuntime?.cuda_available === false
      ? "CUDA was selected for ReefPose, but the PyTorch runtime reports that CUDA is unavailable."
      : (scienceIssue ?? null);

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Executable workflows</p>
          <h3>Workflow graph editor and runner</h3>
          <p>
            Build typed computer-vision pipelines visually, validate them before
            execution, save immutable revisions, and inspect persisted
            node/artifact lineage after each run.
          </p>
        </div>
      </div>

      <div className="workspace-guide" aria-label="Workflow builder steps">
        <div className="workspace-guide-step">
          <span>1</span>
          <div>
            <strong>Start from a template</strong>
            <small>Choose the closest scientific workflow.</small>
          </div>
        </div>
        <div className="workspace-guide-step">
          <span>2</span>
          <div>
            <strong>Connect and configure</strong>
            <small>Edit nodes visually and resolve required parameters.</small>
          </div>
        </div>
        <div className="workspace-guide-step">
          <span>3</span>
          <div>
            <strong>Validate and run</strong>
            <small>
              Plan first; review gates pause safely before execution continues.
            </small>
          </div>
        </div>
      </div>

      <div className="panel-card">
        <h4>Workflow templates</h4>
        <p className="muted-copy">
          Templates are starting points. Replace placeholder dataset, model,
          class, and cloud-model identifiers before validation. The visual
          editor and JSON view stay synchronized.
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
          {
            workflowTemplates.find((item) => item.id === selectedTemplateId)
              ?.description
          }
        </p>
      </div>

      <ProjectSpatialAssetPreview
        projectId={project.id}
        onComparisonSaved={() => void savedGraphsQuery.refetch()}
      />
      <LocalMeshPreview projectId={project.id} />
      <LocalPointCloudPreview projectId={project.id} />

      {poseDatasetSources.length > 0 && (
        <section className="panel-card">
          <h4>Verified pose training data</h4>
          <p>
            Choose an immutable dataset frozen after scientist review. The
            dataset supplies its landmark schema and revision to training.
          </p>
          {poseDatasetSources.map((source) => (
            <label key={source.node_id}>
              Frozen pose dataset
              <select
                value={String(source.parameters?.dataset_id ?? "")}
                onChange={(event) =>
                  setGraphJson(
                    JSON.stringify(
                      {
                        ...visualGraph,
                        nodes: graphNodes.map((node) =>
                          node.node_id === source.node_id
                            ? {
                                ...node,
                                parameters: {
                                  ...node.parameters,
                                  dataset_id: event.target.value,
                                },
                              }
                            : node,
                        ),
                      },
                      null,
                      2,
                    ),
                  )
                }
              >
                <option value="">Choose a verified pose dataset</option>
                {(poseDatasets.data ?? []).map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name} — {dataset.item_count} observations — schema
                    revision {dataset.pose_schema_revision}
                  </option>
                ))}
              </select>
              {(() => {
                const dataset = poseDatasets.data?.find(
                  (item) =>
                    item.id === String(source.parameters?.dataset_id ?? ""),
                );
                return dataset ? (
                  <small>
                    Immutable manifest {shortHash(dataset.manifest_sha256)} ·
                    schema {shortHash(dataset.pose_schema_id)} revision{" "}
                    {dataset.pose_schema_revision} · integrity{" "}
                    {shortHash(dataset.pose_schema_content_hash)}
                  </small>
                ) : null;
              })()}
            </label>
          ))}
          {poseDatasets.isPending && <p>Loading frozen pose datasets...</p>}
          {poseDatasets.error && (
            <p className="form-error">{poseDatasets.error.message}</p>
          )}
          {poseDatasets.data?.length === 0 && (
            <p>
              Review pose annotations and freeze a verified dataset in Pose
              Tracking before training.
            </p>
          )}
        </section>
      )}

      <div className="panel-card" style={{ marginTop: 12 }}>
        <h4>Visual workflow editor</h4>
        {visualGraph ? (
          <WorkflowVisualEditor
            projectId={project.id}
            graph={visualGraph}
            registry={registryQuery.data ?? []}
            plan={planMutation.data ?? null}
            runDetail={runDetailQuery.data ?? null}
            poseDatasets={poseDatasets.data ?? []}
            registeredModels={modelHubQuery.data?.models ?? []}
            runtimeStatuses={modelHubQuery.data?.runtime_statuses ?? []}
            onChange={(graph) => setGraphJson(JSON.stringify(graph, null, 2))}
          />
        ) : (
          <p className="form-error">
            Fix the JSON syntax below before continuing visual editing.
          </p>
        )}
      </div>

      <div className="workflow-scientist-boundary-note">
        <strong>Scientific truth stays scientist-gated.</strong>
        <span>
          Purple review nodes pause execution before machine output becomes
          verified training truth. Dashed feedback cues describe the next saved
          iteration and never create a cyclic execution dependency.
        </span>
      </div>

      <div className="feature-grid" style={{ marginTop: 12 }}>
        <div className="panel-card">
          <h4>Validate, save, and run</h4>
          <details className="advanced-disclosure">
            <summary>Advanced: edit workflow JSON directly</summary>
            <p className="muted-copy">
              Most workflows can be edited visually above. Use JSON when you
              need exact parameters or want to inspect the complete graph
              definition.
            </p>
            <textarea
              rows={22}
              value={graphJson}
              onChange={(event) => setGraphJson(event.target.value)}
              spellCheck={false}
            />
          </details>
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
              disabled={
                saveAndRunMutation.isPending || guiConfigurationIssue !== null
              }
            >
              Save &amp; run
            </button>
          </div>
          {mutationError && (
            <p className="form-error">{mutationError.message}</p>
          )}
          {guiConfigurationIssue && (
            <p className="form-error">{guiConfigurationIssue}</p>
          )}
          <p className="muted-copy">
            Review gates pause safely. Complete the requested review in
            ReefVision, then resume the waiting node below. Completed upstream
            nodes and paid/cloud artifacts are reused rather than recomputed.
          </p>
        </div>

        <div className="panel-card">
          <h4>Node registry</h4>
          {registryQuery.data?.map((definition) => (
            <details key={definition.node_type}>
              <summary>
                <strong>{definition.display_name}</strong> ·{" "}
                {definition.category} ·{" "}
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
                {definition.output_ports
                  .map((item) => item.port_id)
                  .join(", ") || "none"}
              </p>
              {definition.required_parameters.length > 0 && (
                <p>
                  Required parameters:{" "}
                  {definition.required_parameters.join(", ")}
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
                  <button
                    type="button"
                    className="secondary"
                    disabled={runSavedMutation.isPending}
                    onClick={() => runSavedMutation.mutate(record.id)}
                  >
                    Run saved revision
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
                  This run is safely paused. Complete the requested human
                  review, then resume the waiting node below. Completed upstream
                  nodes and artifacts will be reused.
                </p>
              )}
              {selectedRun.error_message && (
                <p className="form-error">{selectedRun.error_message}</p>
              )}
              {(selectedProvenanceSha || selectedProvenanceManifest) && (
                <div className="workflow-provenance-summary">
                  <h5>Workflow provenance</h5>
                  {selectedProvenanceSha && (
                    <p>
                      Canonical SHA-256:{" "}
                      <code>{shortHash(selectedProvenanceSha)}</code>
                    </p>
                  )}
                  <p className="muted-copy">
                    The terminal manifest records node parameters, input/output
                    artifact hashes, scientist approvals, recovery history, and
                    terminal outputs for this saved run.
                  </p>
                  {selectedProvenanceManifest && (
                    <details>
                      <summary>Inspect provenance manifest</summary>
                      <pre>
                        {JSON.stringify(selectedProvenanceManifest, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
              <h5>Nodes</h5>
              <ol>
                {runDetailQuery.data?.nodes.map((node) => (
                  <li key={node.id}>
                    <strong>{node.node_id}</strong> · {node.node_type} ·{" "}
                    {node.status}
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
                    <code>{artifact.data_type}</code> from{" "}
                    {artifact.producer_port_id} ·{" "}
                    <code>{shortHash(artifact.payload_sha256)}</code>
                    {artifact.data_type === "mesh_measurement_preview" && (
                      <MeshArtifactViewer artifact={artifact.payload_json} />
                    )}
                    {artifact.data_type ===
                      "point_cloud_measurement_preview" && (
                      <PointCloudArtifactViewer
                        artifact={artifact.payload_json}
                      />
                    )}
                    <ScienceArtifact
                      artifact={artifact}
                      projectId={project.id}
                      onOpen={onOpenScience}
                      onOpenReviewQueue={onOpenReviewQueue}
                    />
                    <details>
                      <summary>Inspect artifact</summary>
                      <pre>
                        {JSON.stringify(artifact.payload_json, null, 2)}
                      </pre>
                    </details>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>
              Select a recent run or use Save &amp; run to inspect execution.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
