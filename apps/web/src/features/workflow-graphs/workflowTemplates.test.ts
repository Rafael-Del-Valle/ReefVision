import { describe, expect, it } from "vitest";

import {
  createPoseArchitectureWorkflow,
  workflowTemplates,
} from "./workflowTemplates";

describe("workflowTemplates", () => {
  it("includes an explicit scientific-record metric workflow", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "computed-scientific-metric",
    );
    expect(template).toBeDefined();
    const graph = template?.graph as {
      nodes: Array<{
        node_type: string;
        parameters: Record<string, unknown>;
      }>;
      edges: Array<{ source_port_id: string; target_port_id: string }>;
    };
    expect(graph.nodes.map((node) => node.node_type)).toEqual([
      "project_source",
      "scientific_records_source",
      "computed_metric",
    ]);
    expect(graph.nodes[1].parameters.record_ids).toEqual([
      "replace-with-scientific-record-id",
    ]);
    expect(graph.nodes[2].parameters).toMatchObject({
      definition_id: "replace-with-metric-definition-id",
      bindings: { input: "replace-with-scientific-record-id" },
    });
    expect(
      graph.edges.some(
        (edge) =>
          edge.source_port_id === "records" &&
          edge.target_port_id === "records",
      ),
    ).toBe(true);
  });

  it("builds seed-free pose architecture training from an immutable dataset", () => {
    const graph = createPoseArchitectureWorkflow("yolo11m-pose.yaml");
    expect(
      graph.nodes.find((node) => node.node_type === "pose_training_dataset")
        ?.parameters,
    ).toEqual({ dataset_id: "" });
    expect(
      graph.nodes.find((node) => node.node_type === "pose_model_training")
        ?.parameters,
    ).toMatchObject({
      architecture: "yolo11m-pose.yaml",
      initialization_mode: "random",
    });
    expect(
      graph.edges.some((edge) => edge.target_port_id === "initial_model"),
    ).toBe(false);
    expect(graph.edges.some((edge) => edge.target_node_id === "register")).toBe(
      true,
    );
  });

  it("explicitly continues the researcher registered model in the pose retraining template", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "pose-active-learning-retrain",
    )!;
    const graph = template.graph as {
      nodes: Array<{ node_type: string; parameters: Record<string, unknown> }>;
    };
    expect(
      graph.nodes.find((node) => node.node_type === "pose_model_training")
        ?.parameters.initialization_mode,
    ).toBe("registered_model");
  });

  it("includes the scientist-gated pose Active Learning retraining loop", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "pose-active-learning-retrain",
    );

    expect(template).toBeDefined();

    const graph = template?.graph as {
      nodes: Array<{ node_id: string; node_type: string }>;
      edges: Array<{
        source_node_id: string;
        target_node_id: string;
      }>;
      metadata?: {
        truth_policy?: string;
        feedback_loop?: {
          from_node_id?: string;
          to_node_id?: string;
        };
      };
    };

    expect(graph.metadata?.truth_policy).toBe("scientist_verified_only");
    expect(graph.metadata?.feedback_loop).toEqual(
      expect.objectContaining({
        from_node_id: "register",
        to_node_id: "pose",
      }),
    );

    const nodeTypes = new Set(graph.nodes.map((node) => node.node_type));
    for (const nodeType of [
      "pose_inference",
      "pose_temporal_association",
      "pose_review_gate",
      "pose_active_learning",
      "pose_active_learning_review_gate",
      "pose_training_dataset_freeze",
      "pose_training_export",
      "pose_model_training",
      "register_trained_model",
      "training_results_package",
    ]) {
      expect(nodeTypes.has(nodeType)).toBe(true);
    }

    expect(
      graph.edges.some(
        (edge) =>
          edge.source_node_id === "register" && edge.target_node_id === "pose",
      ),
    ).toBe(false);
  });
});
