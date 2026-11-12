import { describe, expect, it } from "vitest";

import {
  createPoseArchitectureWorkflow,
  createPoseComparisonWorkflow,
  createPoseIdentityEvaluationWorkflow,
  workflowTemplates,
} from "./workflowTemplates";

describe("workflowTemplates", () => {
  it("connects a frozen dataset and multiple registered models to pose comparison", () => {
    const graph = createPoseComparisonWorkflow();
    const evaluation = graph.nodes.find(
      (node) => node.node_type === "pose_model_evaluation",
    );
    expect(evaluation?.parameters).toMatchObject({
      device: "auto",
      pck_thresholds: [0.05, 0.1, 0.2],
      calibration_bins: 10,
    });
    expect(
      graph.edges.filter((edge) => edge.target_port_id === "models"),
    ).toHaveLength(2);
    expect(graph.edges.some((edge) => edge.target_port_id === "dataset")).toBe(
      true,
    );
  });

  it("provides an executable scientist-gated multi-animal identity workflow", () => {
    const graph = createPoseIdentityEvaluationWorkflow();
    expect(graph.nodes.map((node) => node.node_type)).toEqual([
      "project_source",
      "project_video_source",
      "registered_model_source",
      "pose_inference",
      "pose_identity_association",
      "pose_identity_review_gate",
      "pose_identity_evaluation",
      "pose_identity_export",
    ]);
    expect(
      graph.nodes.find((node) => node.node_type === "pose_identity_evaluation")
        ?.parameters,
    ).toEqual({ truth_dataset_id: "", spatial_iou_threshold: 0.5 });
    expect(graph.edges.at(-1)).toMatchObject({
      source_port_id: "evaluation",
      target_port_id: "evaluation",
    });
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

  it("includes a native ReefPose random-initialization template", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "reefpose-native-training",
    );
    const nodes = template?.graph.nodes as
      | Array<{ node_type: string; parameters?: Record<string, unknown> }>
      | undefined;
    const train = nodes?.find(
      (node) => node.node_type === "pose_model_training",
    );

    expect(train?.parameters).toMatchObject({
      provider_id: "reefpose",
      architecture: "reefpose-s",
      initialization_mode: "random",
      device: "auto",
      precision: "amp",
      training_config: expect.objectContaining({
        epochs: 50,
        batch: 8,
        input_height: 256,
        input_width: 256,
        learning_rate: 0.0003,
      }),
    });
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
