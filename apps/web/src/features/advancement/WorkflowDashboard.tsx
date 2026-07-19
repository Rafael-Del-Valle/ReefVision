import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  getWorkflowDefinitions,
  getWorkflowTemplates,
  validateWorkflow,
} from "./api";

const blankWorkflow = JSON.stringify(
  {
    name: "Untitled workflow",
    nodes: [{ id: "images", node_type: "image_input", configuration: {} }],
    edges: [],
  },
  null,
  2,
);

export function WorkflowDashboard({ project }: { project: Project }) {
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [workflowJson, setWorkflowJson] = useState(blankWorkflow);
  const [parseError, setParseError] = useState<string | null>(null);

  const definitions = useQuery({
    queryKey: ["workflow_node_definitions"],
    queryFn: getWorkflowDefinitions,
  });
  const templates = useQuery({
    queryKey: ["workflow_templates"],
    queryFn: getWorkflowTemplates,
  });
  const selectedTemplate = useMemo(
    () =>
      templates.data?.find(
        (template) => template.template_id === selectedTemplateId,
      ) ?? null,
    [selectedTemplateId, templates.data],
  );

  useEffect(() => {
    if (selectedTemplate) {
      setWorkflowJson(JSON.stringify(selectedTemplate.workflow, null, 2));
      setParseError(null);
    }
  }, [selectedTemplate]);

  const validation = useMutation({
    mutationFn: () => {
      try {
        const payload = JSON.parse(workflowJson) as Record<string, unknown>;
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

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 10</p>
          <h3>Fusion workflow planner</h3>
          <span>
            Design typed detection, segmentation, classification, tracking,
            measurement, active-learning, and export graphs before execution.
          </span>
        </div>
        <span>{definitions.data?.length ?? 0} node types</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <p className="eyebrow">Templates</p>
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
                <h4>Typed JSON definition</h4>
              </div>
              {validation.data && (
                <span>{validation.data.workflow_checksum.slice(0, 12)}...</span>
              )}
            </div>
            <p>
              Replace template model placeholders with registered model IDs before
              validation. Every edge names a source and target port.
            </p>
            <label>
              Workflow JSON
              <textarea
                rows={28}
                value={workflowJson}
                onChange={(event) => setWorkflowJson(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={validation.isPending}
              onClick={() => validation.mutate()}
            >
              {validation.isPending ? "Validating..." : "Validate workflow"}
            </button>
            {(parseError || validation.error) && (
              <p className="form-error">
                {parseError ?? validation.error?.message}
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
  );
}
