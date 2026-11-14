import { describe, expect, it } from "vitest";

import {
  createPoseArchitectureWorkflow,
  createPoseComparisonWorkflow,
  createPoseIdentityEvaluationWorkflow,
  createBiologicalMovementWorkflow,
  workflowTemplates,
} from "./workflowTemplates";

describe("workflowTemplates", () => {
  it("includes executable templates for every environmental-analysis node", () => {
    const expected = new Set([
      "current_streamline_analysis",
      "lunar_context_analysis",
      "tidal_context_analysis",
      "event_window_analysis",
      "observation_environment_join",
      "lagged_comparison",
    ]);
    const found = new Set<string>();

    for (const template of workflowTemplates.filter((item) =>
      item.id.startsWith("environmental-"),
    )) {
      const graph = template.graph as {
        nodes: Array<{ node_type: string }>;
        edges: Array<{ source_port_id: string; target_port_id: string }>;
      };
      expect(graph.nodes[0].node_type).toBe("project_source");
      found.add(graph.nodes[1].node_type);
      expect(graph.edges).toContainEqual(
        expect.objectContaining({
          source_port_id: "project",
          target_port_id: "project",
        }),
      );
    }

    expect(found).toEqual(expected);
  });

  it("includes an explicit reviewed annotation aggregate workflow", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "reviewed-annotation-aggregate",
    );
    expect(template).toBeDefined();
    const graph = template?.graph as {
      nodes: Array<{ node_type: string; parameters: Record<string, unknown> }>;
      edges: Array<{ source_port_id: string; target_port_id: string }>;
    };
    expect(graph.nodes.map((node) => node.node_type)).toEqual([
      "project_source",
      "annotation_aggregate",
    ]);
    expect(graph.nodes[1].parameters).toEqual({
      definition_id: "replace-with-aggregate-definition-id",
      image_ids: ["replace-with-reviewed-image-id"],
    });
    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source_port_id: "project",
        target_port_id: "project",
      }),
    );
  });

  it("includes an executable verified mask coverage workflow", () => {
    const template = workflowTemplates.find(
      (item) => item.id === "verified-mask-coverage",
    );
    expect(template).toBeDefined();
    const graph = template?.graph as {
      nodes: Array<{ node_type: string; parameters: Record<string, unknown> }>;
    };
    expect(graph.nodes.map((node) => node.node_type)).toEqual([
      "project_source",
      "mask_coverage",
    ]);
    expect(graph.nodes[1].parameters).toEqual({
      definition_id: "replace-with-mask-coverage-definition-id",
      image_ids: ["replace-with-reviewed-image-id"],
    });
  });

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

  it("provides an executable scientist-reviewed biological movement workflow", () => {
    const graph = createBiologicalMovementWorkflow();
    expect(graph.nodes.map((node) => node.node_type)).toEqual([
      "project_source",
      "project_video_source",
      "registered_model_source",
      "pose_inference",
      "pose_identity_association",
      "pose_identity_review_gate",
      "anatomical_measurement",
      "biological_event_detection",
      "biological_event_review_gate",
      "biological_movement_export",
    ]);
    expect(graph.edges.at(-1)).toMatchObject({
      source_port_id: "events",
      target_port_id: "events",
    });
  });
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
