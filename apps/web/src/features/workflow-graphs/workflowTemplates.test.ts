import { describe, expect, it } from "vitest";

import { workflowTemplates } from "./workflowTemplates";

describe("workflowTemplates", () => {
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
