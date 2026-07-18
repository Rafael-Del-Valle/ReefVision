import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import {
  getWorkflowNodeRegistry,
  planWorkflowGraph,
  validateWorkflowGraph,
} from "./workflowGraphApi";

interface WorkflowGraphWorkspaceProps {
  project: Project;
}

const exampleGraph = {
  graph_id: "reviewed-segmentation-measurements",
  name: "Segment, review, and measure",
  schema_version: "workflow-graph-0001",
  nodes: [
    { node_id: "project", node_type: "project_source" },
    { node_id: "images", node_type: "project_images" },
    {
      node_id: "model",
      node_type: "registered_model_source",
      parameters: { model_id: "replace-with-segmenter-model-id" },
    },
    { node_id: "segment", node_type: "segmentation_inference" },
    { node_id: "review", node_type: "mask_review_gate" },
    { node_id: "measure", node_type: "mask_measurements" },
  ],
  edges: [
    {
      edge_id: "project-images",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "images",
      target_port_id: "project",
    },
    {
      edge_id: "project-model",
      source_node_id: "project",
      source_port_id: "project",
      target_node_id: "model",
      target_port_id: "project",
    },
    {
      edge_id: "images-segment",
      source_node_id: "images",
      source_port_id: "images",
      target_node_id: "segment",
      target_port_id: "images",
    },
    {
      edge_id: "model-segment",
      source_node_id: "model",
      source_port_id: "model",
      target_node_id: "segment",
      target_port_id: "model",
    },
    {
      edge_id: "segment-review",
      source_node_id: "segment",
      source_port_id: "proposals",
      target_node_id: "review",
      target_port_id: "proposals",
    },
    {
      edge_id: "review-measure",
      source_node_id: "review",
      source_port_id: "masks",
      target_node_id: "measure",
      target_port_id: "masks",
    },
  ],
};

export function WorkflowGraphWorkspace({ project }: WorkflowGraphWorkspaceProps) {
  const [graphJson, setGraphJson] = useState(
    JSON.stringify(exampleGraph, null, 2),
  );
  const registryQuery = useQuery({
    queryKey: ["workflow-node-registry"],
    queryFn: ({ signal }) => getWorkflowNodeRegistry(signal),
  });

  function parsedGraph(): Record<string, unknown> {
    return JSON.parse(graphJson) as Record<string, unknown>;
  }

  const validationMutation = useMutation({
    mutationFn: () => validateWorkflowGraph(project.id, parsedGraph()),
  });
  const planMutation = useMutation({
    mutationFn: () => planWorkflowGraph(project.id, parsedGraph()),
  });

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 10 foundation</p>
          <h3>Workflow graph specification</h3>
          <p>
            Define a typed graph as JSON, validate ports and project references,
            and inspect a dry-run plan. Graph execution is intentionally disabled.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>Graph JSON</h4>
          <textarea
            rows={28}
            value={graphJson}
            onChange={(event) => setGraphJson(event.target.value)}
            spellCheck={false}
          />
          <div className="button-row">
            <button
              type="button"
              onClick={() => validationMutation.mutate()}
              disabled={validationMutation.isPending}
            >
              Validate graph
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => planMutation.mutate()}
              disabled={planMutation.isPending}
            >
              Create dry-run plan
            </button>
          </div>
          {(validationMutation.error || planMutation.error) && (
            <p className="form-error">
              {(validationMutation.error ?? planMutation.error)?.message}
            </p>
          )}
          <button type="button" disabled title="No workflow executor is implemented">
            Run graph disabled
          </button>
        </div>

        <div className="panel-card">
          <h4>Node registry</h4>
          {registryQuery.data?.map((definition) => (
            <details key={definition.node_type}>
              <summary>
                <strong>{definition.display_name}</strong> · {definition.category}
              </summary>
              <p>{definition.description}</p>
              <p>Type: <code>{definition.node_type}</code></p>
              <p>
                Inputs: {definition.input_ports.map((item) => item.port_id).join(", ") || "none"}
              </p>
              <p>
                Outputs: {definition.output_ports.map((item) => item.port_id).join(", ") || "none"}
              </p>
            </details>
          ))}
        </div>

        <div className="panel-card">
          <h4>Validation</h4>
          {validationMutation.data ? (
            <>
              <p>Valid: <strong>{validationMutation.data.valid ? "Yes" : "No"}</strong></p>
              <p>Order: {validationMutation.data.topological_order.join(" → ") || "unavailable"}</p>
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
        </div>

        <div className="panel-card">
          <h4>Dry-run plan</h4>
          {planMutation.data ? (
            <>
              <p>Executable: <strong>{planMutation.data.executable ? "Yes" : "No"}</strong></p>
              <p>{planMutation.data.execution_blocker}</p>
              <ol>
                {planMutation.data.steps.map((step) => (
                  <li key={step.node_id}>
                    <strong>{step.display_name}</strong>: {step.action}
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p>Create a plan to view the topological sequence and intended actions.</p>
          )}
        </div>
      </div>
    </section>
  );
}
