import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  WorkflowNodeDefinition,
  WorkflowRunDetail,
} from "./workflowGraphApi";
import { WorkflowVisualEditor } from "./WorkflowVisualEditor";

const registry: WorkflowNodeDefinition[] = [
  {
    node_type: "pose_inference",
    display_name: "Pose Inference",
    category: "Pose",
    description: "Run pose inference.",
    input_ports: [],
    output_ports: [
      {
        port_id: "poses",
        display_name: "Pose tracks",
        accepted_types: ["pose_tracks"],
        required: false,
        multiple: true,
      },
    ],
    required_parameters: [],
    optional_parameters: {
      device: "auto",
      confidence: 0.25,
    },
    execution_state: "executable_pose_workflow",
    executable: true,
    implementation_notes: [],
  },
  {
    node_type: "pose_review_gate",
    display_name: "Pose Review Gate",
    category: "Human review",
    description: "Require scientist review.",
    input_ports: [
      {
        port_id: "tracks",
        display_name: "Temporal pose tracks",
        accepted_types: ["pose_temporal_tracks"],
        required: true,
        multiple: false,
      },
    ],
    output_ports: [
      {
        port_id: "poses",
        display_name: "Reviewed pose tracks",
        accepted_types: ["reviewed_pose_tracks"],
        required: false,
        multiple: true,
      },
    ],
    required_parameters: [],
    optional_parameters: {},
    execution_state: "pausable_review_gate",
    executable: true,
    implementation_notes: [],
  },
  {
    node_type: "register_trained_model",
    display_name: "Register Trained Model",
    category: "Training",
    description: "Register a completed model.",
    input_ports: [],
    output_ports: [
      {
        port_id: "model",
        display_name: "Registered model",
        accepted_types: ["model_reference"],
        required: false,
        multiple: true,
      },
    ],
    required_parameters: [],
    optional_parameters: {},
    execution_state: "executable",
    executable: true,
    implementation_notes: [],
  },
];

const graph = {
  graph_id: "pose-loop",
  name: "Pose loop",
  schema_version: "workflow-graph-0001",
  metadata: {
    feedback_loop: {
      from_node_id: "register",
      to_node_id: "pose",
      label: "Next iteration: trained model → inference",
      description:
        "Use the trained model as the seed for the next saved workflow revision.",
    },
  },
  nodes: [
    {
      node_id: "pose",
      node_type: "pose_inference",
      parameters: {
        device: "auto",
        confidence: 0.25,
      },
      position: { x: 40, y: 40 },
    },
    {
      node_id: "review",
      node_type: "pose_review_gate",
      parameters: {},
      position: { x: 360, y: 40 },
    },
    {
      node_id: "register",
      node_type: "register_trained_model",
      parameters: {},
      position: { x: 680, y: 40 },
    },
  ],
  edges: [],
};

const runDetail = {
  run: {
    id: "run-1",
    project_id: "project-1",
    workflow_graph_record_id: "graph-1",
    job_id: "job-1",
    status: "waiting_for_review",
    graph_sha256: "a".repeat(64),
    input_json: {},
    result_json: {},
    error_message: null,
    started_at: "2026-10-04T00:00:00Z",
    completed_at: null,
    created_at: "2026-10-04T00:00:00Z",
  },
  nodes: [
    {
      id: "node-run-pose",
      workflow_run_id: "run-1",
      node_id: "pose",
      node_type: "pose_inference",
      execution_order: 0,
      status: "succeeded",
      parameters_json: {},
      input_artifact_ids_json: [],
      output_artifact_ids_json: ["artifact-pose"],
      result_json: {},
      error_message: null,
      started_at: "2026-10-04T00:00:00Z",
      completed_at: "2026-10-04T00:00:01Z",
    },
    {
      id: "node-run-review",
      workflow_run_id: "run-1",
      node_id: "review",
      node_type: "pose_review_gate",
      execution_order: 1,
      status: "waiting_for_review",
      parameters_json: {},
      input_artifact_ids_json: ["artifact-pose"],
      output_artifact_ids_json: [],
      result_json: {},
      error_message: null,
      started_at: "2026-10-04T00:00:01Z",
      completed_at: null,
    },
  ],
  artifacts: [],
} as unknown as WorkflowRunDetail;

describe("WorkflowVisualEditor", () => {
  it("exposes explicit pose initialization and all five weight-free YOLO11 pose sizes", () => {
    const onChange = vi.fn();
    const poseGraph = {
      ...graph,
      nodes: [
        {
          node_id: "train",
          node_type: "pose_model_training",
          parameters: {
            initialization_mode: "random",
            architecture: "yolo11n-pose.yaml",
          },
        },
      ],
    };
    render(
      <WorkflowVisualEditor
        graph={poseGraph}
        registry={registry}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    expect(screen.getByLabelText("Initialization mode")).toHaveValue("random");
    const sizes = screen.getByLabelText(
      "Pose architecture",
    ) as HTMLSelectElement;
    expect(Array.from(sizes.options).map((option) => option.value)).toEqual([
      "yolo11n-pose.yaml",
      "yolo11s-pose.yaml",
      "yolo11m-pose.yaml",
      "yolo11l-pose.yaml",
      "yolo11x-pose.yaml",
    ]);
    fireEvent.change(sizes, { target: { value: "yolo11x-pose.yaml" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        nodes: [
          expect.objectContaining({
            parameters: expect.objectContaining({
              architecture: "yolo11x-pose.yaml",
              initialization_mode: "random",
            }),
          }),
        ],
      }),
    );
    fireEvent.change(screen.getByLabelText("Initialization mode"), {
      target: { value: "registered_model" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        nodes: [
          expect.objectContaining({
            parameters: expect.objectContaining({
              initialization_mode: "registered_model",
            }),
          }),
        ],
      }),
    );
  });

  it("distinguishes scientist review, live run state, and next-iteration feedback", () => {
    render(
      <WorkflowVisualEditor
        graph={graph}
        registry={registry}
        runDetail={runDetail}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Scientist review").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Waiting for scientist review"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Next iteration: trained model → inference"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("workflow-feedback-edge")).toBeInTheDocument();
  });

  it("provides scientist-friendly primitive controls while retaining advanced JSON", () => {
    const onChange = vi.fn();

    render(
      <WorkflowVisualEditor
        graph={graph}
        registry={registry}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Configure" })[0]);

    expect(screen.getByLabelText("device")).toHaveValue("auto");
    expect(screen.getByLabelText("confidence")).toHaveValue(0.25);
    expect(screen.getByText("Advanced parameter JSON")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("confidence"), {
      target: { value: "0.4" },
    });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        nodes: expect.arrayContaining([
          expect.objectContaining({
            node_id: "pose",
            parameters: expect.objectContaining({
              confidence: 0.4,
            }),
          }),
        ]),
      }),
    );
  });
});
