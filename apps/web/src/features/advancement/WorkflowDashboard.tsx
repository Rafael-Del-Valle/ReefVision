import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { getDatasetVersions } from "../phase456/api";
import { ProviderDashboard } from "../providers/ProviderDashboard";
import {
  createCocoExport,
  getWorkflowDefinitions,
  getWorkflowTemplates,
  validateWorkflow,
} from "./api";
import { InterchangeDashboard } from "./InterchangeDashboard";
import {
  type EditableWorkflow,
  WorkflowGraphEditor,
} from "./WorkflowGraphEditor";

const blankWorkflow = JSON.stringify(
  {
    name: "Untitled workflow",
    nodes: [{ id: "images", node_type: "image_input", configuration: {} }],
    edges: [],
  },
  null,
  2,
);

function parseWorkflow(value: string): EditableWorkflow {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Workflow JSON must be an object");
  }
  const record = parsed as Record<string, unknown>;
  if (typeof record.name !== "string" || !record.name.trim()) {
    throw new Error("Workflow name is required");
  }
  if (!Array.isArray(record.nodes) || !Array.isArray(record.edges)) {
    throw new Error("Workflow JSON requires nodes and edges arrays");
  }
  const nodes = record.nodes.map((value, index) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`Node ${index + 1} must be an object`);
    }
    const node = value as Record<string, unknown>;
    if (typeof node.id !== "string" || typeof node.node_type !== "string") {
      throw new Error(`Node ${index + 1} requires id and node_type`);
    }
    const configuration =
      node.configuration &&
      typeof node.configuration === "object" &&
      !Array.isArray(node.configuration)
        ? (node.configuration as Record<string, unknown>)
        : {};
    return {
      id: node.id,
      node_type: node.node_type,
      label: typeof node.label === "string" ? node.label : null,
      configuration,
    };
  });
  const edges = record.edges.map((value, index) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`Edge ${index + 1} must be an object`);
    }
    const edge = value as Record<string, unknown>;
    const fields = [
      "source_node_id",
      "source_port",
      "target_node_id",
      "target_port",
    ] as const;
    for (const field of fields) {
      if (typeof edge[field] !== "string") {
        throw new Error(`Edge ${index + 1} requires ${field}`);
      }
    }
    return {
      source_node_id: edge.source_node_id as string,
      source_port: edge.source_port as string,
      target_node_id: edge.target_node_id as string,
      target_port: edge.target_port as string,
    };
  });
  return { name: record.name, nodes, edges };
}

export function WorkflowDashboard({ project }: { project: Project }) {
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [workflowJson, setWorkflowJson] = useState(blankWorkflow);
  const [parseError, setParseError] = useState<string | null>(null);
  const [editorMode, setEditorMode] = useState<"visual" | "json">("visual");
  const [cocoVersionId, setCocoVersionId] = useState("");
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const definitions = useQuery({
    queryKey: ["workflow_node_definitions"],
    queryFn: getWorkflowDefinitions,
  });
  const templates = useQuery({
    queryKey: ["workflow_templates"],
    queryFn: getWorkflowTemplates,
  });
  const versions = useQuery({
    queryKey: ["workflow_dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const selectedTemplate = useMemo(
    () =>
      templates.data?.find(
        (template) => template.template_id === selectedTemplateId,
      ) ?? null,
    [selectedTemplateId, templates.data],
  );
  const parsedWorkflow = useMemo(() => {
    try {
      return { workflow: parseWorkflow(workflowJson), error: null };
    } catch (error) {
      return {
        workflow: null,
        error: error instanceof Error ? error.message : "Workflow JSON is invalid",
      };
    }
  }, [workflowJson]);

  useEffect(() => {
    if (selectedTemplate) {
      setWorkflowJson(JSON.stringify(selectedTemplate.workflow, null, 2));
      setParseError(null);
    }
  }, [selectedTemplate]);

  useEffect(() => {
    if (!cocoVersionId) {
      const firstComplete = versions.data?.find(
        (version) => version.status === "complete",
      );
      if (firstComplete) setCocoVersionId(firstComplete.id);
    }
  }, [cocoVersionId, versions.data]);

  const validation = useMutation({
    mutationFn: () => {
      try {
        const payload = parseWorkflow(workflowJson);
        setParseError(null);
        return validateWorkflow(project.id, payload);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Workflow JSON is invalid";
        setParseError(message);
        throw error;
      }
    },
  });
  const cocoExport = useMutation({
    mutationFn: () => createCocoExport(cocoVersionId),
    onSuccess: (result) =>
      setExportMessage(`COCO export queued as job ${result.job.id}.`),
  });

  return (
    <>
      <ProviderDashboard />
      <InterchangeDashboard project={project} />
      <section className="dashboard-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Phase 10</p>
            <h3>Fusion workflow planner and executor</h3>
            <span>
              Design typed detection, segmentation, classification, tracking,
              measurement, active-learning, and export graphs with resumable execution,
              artifact lineage, cache reuse, and resource-aware scheduling.
            </span>
          </div>
          <span>{definitions.data?.length ?? 0} node types</span>
        </div>

        {exportMessage && <p className="form-success">{exportMessage}</p>}
        {cocoExport.error && (
          <p className="form-error">{cocoExport.error.message}</p>
        )}

        <div className="dashboard-layout">
          <div className="dashboard-sidebar">
            <article className="dashboard-card">
              <p className="eyebrow">Immutable dataset export</p>
              <h4>COCO instance snapshot</h4>
              <p>
                Export frozen boxes, polygon masks, raster RLE masks, categories,
                splits, source IDs, and checksums without changing the dataset version.
              </p>
              <label>
                Immutable dataset version
                <select
                  value={cocoVersionId}
                  onChange={(event) => setCocoVersionId(event.target.value)}
                >
                  <option value="">Choose a complete version</option>
                  {versions.data
                    ?.filter((version) => version.status === "complete")
                    .map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version_number} · {version.name} ·{" "}
                        {version.annotation_count} boxes
                      </option>
                    ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!cocoVersionId || cocoExport.isPending}
                onClick={() => cocoExport.mutate()}
              >
                {cocoExport.isPending ? "Queuing..." : "Export COCO instances"}
              </button>
            </article>

            <article className="dashboard-card">
              <p className="eyebrow">Workflow templates</p>
              <label>
                Starting workflow
                <select
                  value={selectedTemplateId}
                  onChange={(event) => setSelectedTemplateId(event.target.value)}
                >
                  <option value="">Blank workflow</option>
                  {templates.data?.map((template) => (
                    <option key={template.template_id} value={template.template_id}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </label>
              {selectedTemplate && <p>{selectedTemplate.description}</p>}
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setSelectedTemplateId("");
                  setWorkflowJson(blankWorkflow);
                  setParseError(null);
                  validation.reset();
                }}
              >
                Reset to blank
              </button>
            </article>

            <article className="dashboard-card">
              <p className="eyebrow">Node catalog</p>
              <div className="dashboard-list compact-list">
                {definitions.data?.map((definition) => (
                  <div key={definition.node_type} className="dashboard-row">
                    <div>
                      <strong>{definition.display_name}</strong>
                      <p>
                        {definition.inputs.length} inputs · {definition.outputs.length}{" "}
                        outputs
                      </p>
                      <small>
                        {definition.requires_model
                          ? `Models: ${definition.supported_model_tasks.join(", ")}`
                          : "No model required"}
                      </small>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <div className="dashboard-main">
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Workflow graph</p>
                  <h4>Visual and typed JSON definition</h4>
                </div>
                <div className="annotation-editor-inline-actions">
                  <button
                    type="button"
                    className={editorMode === "visual" ? "active" : "secondary"}
                    aria-pressed={editorMode === "visual"}
                    onClick={() => setEditorMode("visual")}
                  >
                    Visual editor
                  </button>
                  <button
                    type="button"
                    className={editorMode === "json" ? "active" : "secondary"}
                    aria-pressed={editorMode === "json"}
                    onClick={() => setEditorMode("json")}
                  >
                    JSON editor
                  </button>
                  {validation.data && (
                    <span>{validation.data.workflow_checksum.slice(0, 12)}...</span>
                  )}
                </div>
              </div>
              <p>
                Drag nodes, connect compatible ports, and edit node configuration. The
                visual canvas remains synchronized with the persisted JSON workflow.
              </p>

              {editorMode === "visual" ? (
                parsedWorkflow.workflow && definitions.data ? (
                  <WorkflowGraphEditor
                    workflow={parsedWorkflow.workflow}
                    definitions={definitions.data}
                    onChange={(workflow) => {
                      setWorkflowJson(JSON.stringify(workflow, null, 2));
                      setParseError(null);
                      validation.reset();
                    }}
                  />
                ) : (
                  <div className="empty-state">
                    <h5>Visual editor cannot load this graph</h5>
                    <p className="form-error">
                      {parsedWorkflow.error ?? "Workflow node definitions are loading."}
                    </p>
                    <button type="button" onClick={() => setEditorMode("json")}>
                      Repair in JSON editor
                    </button>
                  </div>
                )
              ) : (
                <label>
                  Workflow JSON
                  <textarea
                    rows={30}
                    value={workflowJson}
                    aria-label="Workflow JSON"
                    onChange={(event) => {
                      setWorkflowJson(event.target.value);
                      setParseError(null);
                      validation.reset();
                    }}
                  />
                </label>
              )}

              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  disabled={validation.isPending || !parsedWorkflow.workflow}
                  onClick={() => validation.mutate()}
                >
                  {validation.isPending ? "Validating..." : "Validate workflow"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!parsedWorkflow.workflow}
                  onClick={() =>
                    setWorkflowJson(
                      JSON.stringify(parsedWorkflow.workflow, null, 2),
                    )
                  }
                >
                  Format JSON
                </button>
              </div>
              {(parseError || parsedWorkflow.error || validation.error) && (
                <p className="form-error">
                  {parseError ?? parsedWorkflow.error ?? validation.error?.message}
                </p>
              )}
            </article>

            {validation.data && (
              <>
                <article className="dashboard-card">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Validation</p>
                      <h4>
                        {validation.data.valid
                          ? "Workflow is structurally valid"
                          : "Workflow contains blocking errors"}
                      </h4>
                    </div>
                    <span>{validation.data.issues.length} findings</span>
                  </div>
                  <div className="dashboard-list">
                    {validation.data.issues.map((issue, index) => (
                      <div
                        key={`${issue.code}-${issue.node_id ?? index}`}
                        className="dashboard-row"
                      >
                        <div>
                          <strong>
                            {issue.severity.toUpperCase()} ·{" "}
                            {issue.code.replaceAll("_", " ")}
                          </strong>
                          <p>{issue.message}</p>
                          <small>
                            {issue.node_id ? `Node ${issue.node_id}` : "Graph"}
                            {issue.edge_index !== null
                              ? ` · edge ${issue.edge_index}`
                              : ""}
                          </small>
                        </div>
                      </div>
                    ))}
                    {validation.data.issues.length === 0 && (
                      <p>No missing ports, type mismatches, cycles, or model conflicts.</p>
                    )}
                  </div>
                </article>

                <article className="dashboard-card">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Execution plan</p>
                      <h4>{validation.data.execution_stages.length} stages</h4>
                    </div>
                  </div>
                  <p>
                    Nodes in the same stage have no dependency on one another and can
                    be scheduled in parallel when hardware resources permit.
                  </p>
                  <div className="dashboard-list">
                    {validation.data.execution_stages.map((stage) => (
                      <div key={stage.stage_index} className="dashboard-row">
                        <div>
                          <strong>Stage {stage.stage_index + 1}</strong>
                          <p>{stage.node_ids.join(" · ")}</p>
                        </div>
                        <span>{stage.node_ids.length} parallel nodes</span>
                      </div>
                    ))}
                  </div>
                  <small>
                    Topological order: {validation.data.topological_order.join(" → ")}
                  </small>
                </article>
              </>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
