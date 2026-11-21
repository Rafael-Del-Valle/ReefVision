import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getModelHubBootstrap,
  resultsPackageDownloadUrl,
  retryJob,
  type Project,
} from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import {
  getPoseTrainingDatasets,
  poseTrainingDatasetNativePackageUrl,
} from "../video/poseActiveLearningApi";
import { getVideos } from "../video/videoApi";
import type { WorkflowPoseReviewTarget } from "../video/videoWorkspaceBridge";
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
  type WorkflowNodeRun,
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
import {
  MeasurementReviewSummary,
  measurementReviewInput,
} from "./MeasurementReviewSummary";
import {
  WorkflowPoseSourceFields,
  type WorkflowSourceEdge,
  type WorkflowSourceNode,
} from "./WorkflowPoseSourceFields";
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
  onOpenPoseReview?: (target: WorkflowPoseReviewTarget) => void;
}

function PoseReviewActions({
  node,
  runId,
  projectId,
  artifacts,
  onOpen,
}: {
  node: WorkflowNodeRun;
  runId: string;
  projectId: string;
  artifacts: WorkflowArtifact[];
  onOpen?: (target: WorkflowPoseReviewTarget) => void;
}) {
  const temporal = node.node_type === "pose_review_gate";
  const acquisition = node.node_type === "pose_active_learning_review_gate";
  if (!onOpen || (!temporal && !acquisition)) return null;
  const review = node.result_json.review as
    { source_artifact_id?: unknown } | undefined;
  const source = artifacts.find(
    (artifact) =>
      artifact.id === review?.source_artifact_id &&
      artifact.data_type ===
        (temporal ? "pose_temporal_tracks" : "pose_active_learning_round"),
  );
  const data = source?.payload_json;
  if (data?.project_id !== projectId || typeof data.video_id !== "string")
    return null;
  const videoId = data.video_id;
  const roundId =
    acquisition && typeof data.round_id === "string"
      ? data.round_id
      : undefined;
  if (acquisition && !roundId) return null;
  const tracks = temporal ? data.track_ids : data.source_track_ids;
  if (!Array.isArray(tracks)) return null;
  const candidates = tracks.filter(
    (track): track is string => typeof track === "string",
  );
  if (acquisition) {
    const trackId = candidates[0];
    return trackId ? (
      <button
        type="button"
        className="secondary"
        onClick={() => onOpen({ runId, videoId, trackId, roundId })}
      >
        Open pose acquisition review
      </button>
    ) : null;
  }
  return candidates.map((trackId, index) => (
    <button
      key={trackId}
      type="button"
      className="secondary"
      onClick={() => onOpen({ runId, videoId, trackId, roundId })}
    >
      Review temporal associations
      {candidates.length > 1 && ` · track ${index + 1}`}
    </button>
  ));
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
    artifact.data_type === "results_package" &&
    data.project_id === projectId &&
    typeof data.download_url === "string" &&
    data.download_url.startsWith("/training-runs/") &&
    data.verification_valid === true
  ) {
    return (
      <a href={resultsPackageDownloadUrl(data.download_url)}>
        Download verified training results
      </a>
    );
  }
  if (
    artifact.data_type === "pose_training_package" &&
    data.project_id === projectId &&
    typeof data.dataset_id === "string" &&
    data.export_format === "native"
  ) {
    return (
      <a href={poseTrainingDatasetNativePackageUrl(data.dataset_id)}>
        Download reviewed native poses
      </a>
    );
  }
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
  onOpenPoseReview,
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
    ? (visualGraph.nodes as WorkflowSourceNode[])
    : [];
  const graphEdges = Array.isArray(visualGraph?.edges)
    ? (visualGraph.edges as WorkflowSourceEdge[])
    : [];
  const poseDatasetSources = graphNodes.filter(
    (node) => node.node_type === "pose_training_dataset",
  );
  const poseDatasets = useQuery({
    queryKey: ["pose-training-datasets", project.id],
    queryFn: ({ signal }) => getPoseTrainingDatasets(project.id, signal),
    enabled: poseDatasetSources.length > 0,
  });
  const hasRecordingSource = graphNodes.some(
    (node) => node.node_type === "project_video_source",
  );
  const recordings = useQuery({
    queryKey: ["project-videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
    enabled: hasRecordingSource,
  });

  function pickSource(nodeId: string, id: string, digest: string) {
    setGraphJson((text) => {
      const graph = safeParseGraph(text);
      if (!graph || !Array.isArray(graph.nodes)) return text;
      return JSON.stringify(
        {
          ...graph,
          nodes: (graph.nodes as WorkflowSourceNode[]).map((node) => {
            if (node.node_id !== nodeId) return node;
            const parameters = { ...node.parameters };
            const [idField, digestField] =
              node.node_type === "project_video_source"
                ? ["video_id", "video_sha256"]
                : ["dataset_id", "manifest_sha256"];
            parameters[idField] = id;
            if (id && digest) parameters[digestField] = digest;
            else delete parameters[digestField];
            return { ...node, parameters };
          }),
        },
        null,
        2,
      );
    });
  }
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
  const retryMutation = useMutation({
    mutationFn: (request: {
      projectId: string;
      runId: string;
      jobId: string;
    }) => retryJob(request.jobId),
    onSettled: async (_job, _error, { projectId, runId }) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["workflow-runs", projectId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["workflow-run", projectId, runId],
          refetchType: "all",
        }),
      ]);
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
  const retryJobId =
    selectedRun?.status === "failed" ? selectedRun.job_id : null;
  const retryIsForSelectedRun =
    retryMutation.variables?.projectId === project.id &&
    retryMutation.variables.runId === selectedRun?.id;
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

      {(poseDatasetSources.length > 0 || hasRecordingSource) && (
        <section className="panel-card">
          <h4>
            {poseDatasetSources.length
              ? "Verified pose workflow sources"
              : "Recording sources"}
          </h4>
          {poseDatasetSources.length > 0 && (
            <p>
              Choose pose evidence frozen after scientist review. The workflow
              keeps the selected original checksums.
            </p>
          )}
          <WorkflowPoseSourceFields
            nodes={graphNodes}
            edges={graphEdges}
            datasets={poseDatasets.data ?? []}
            recordings={recordings.data ?? []}
            onPick={pickSource}
          />
          {poseDatasetSources.length > 0 && poseDatasets.isPending && (
            <p>Loading frozen pose datasets…</p>
          )}
          {poseDatasets.error && (
            <p className="form-error">{poseDatasets.error.message}</p>
          )}
          {poseDatasets.data?.length === 0 && (
            <p>
              Review pose annotations and freeze a verified dataset in Video
              &amp; tracking before training.
            </p>
          )}
          {hasRecordingSource && recordings.isPending && (
            <p>Loading project recordings…</p>
          )}
          {recordings.error && (
            <p className="form-error">{recordings.error.message}</p>
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
              {retryJobId && (
                <div>
                  <p className="muted-copy">
                    Resolve the reported issue before retrying. Completed steps
                    and their artifacts are reused.
                  </p>
                  <button
                    type="button"
                    className="secondary"
                    disabled={retryMutation.isPending}
                    onClick={() =>
                      retryMutation.mutate({
                        projectId: project.id,
                        runId: selectedRun.id,
                        jobId: retryJobId,
                      })
                    }
                  >
                    {retryIsForSelectedRun && retryMutation.isPending
                      ? "Retrying workflow…"
                      : "Retry failed workflow"}
                  </button>
                </div>
              )}
              {retryIsForSelectedRun && retryMutation.error && (
                <p className="form-error" role="alert">
                  {retryMutation.error.message}
                </p>
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
                {runDetailQuery.data?.nodes.map((node) => {
                  const reviewMeasurement =
                    node.node_type === "measurement_review_gate";
                  const input = reviewMeasurement
                    ? measurementReviewInput(
                        node,
                        runDetailQuery.data?.artifacts ?? [],
                      )
                    : undefined;
                  return (
                    <li key={node.id}>
                      <strong>{node.node_id}</strong> · {node.node_type} ·{" "}
                      {node.status}
                      {node.error_message ? ` — ${node.error_message}` : ""}
                      {node.status === "waiting_for_review" && (
                        <>
                          {reviewMeasurement && (
                            <MeasurementReviewSummary artifact={input} />
                          )}
                          <div className="button-row">
                            <PoseReviewActions
                              node={node}
                              runId={selectedRun.id}
                              projectId={project.id}
                              artifacts={runDetailQuery.data?.artifacts ?? []}
                              onOpen={onOpenPoseReview}
                            />
                            <button
                              type="button"
                              disabled={
                                resumeReviewMutation.isPending ||
                                (reviewMeasurement && !input)
                              }
                              onClick={() =>
                                resumeReviewMutation.mutate(node.id)
                              }
                            >
                              Resume after review
                            </button>
                          </div>
                        </>
                      )}
                      {Object.keys(node.result_json).length > 0 && (
                        <details>
                          <summary>Node result</summary>
                          <pre>{JSON.stringify(node.result_json, null, 2)}</pre>
                        </details>
                      )}
                    </li>
                  );
                })}
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
