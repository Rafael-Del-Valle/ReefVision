import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../../api/client";
import { WorkflowGraphWorkspace } from "./WorkflowGraphWorkspace";

afterEach(() => vi.restoreAllMocks());
describe("pose architecture training workflow", () => {
  it("binds the chosen immutable pose dataset without introducing a seed model", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        const payload = url.includes("pose-training-datasets")
          ? [
              {
                id: "dataset-1",
                name: "Verified coral landmarks",
                item_count: 12,
                pose_schema_revision: 3,
                manifest_sha256: "a".repeat(64),
                status: "complete",
              },
            ]
          : url.endsWith("/validate")
            ? { valid: true, issues: [], topological_order: [] }
            : [];
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <WorkflowGraphWorkspace
          project={{ id: "project-1" } as Project}
          initialPoseArchitecture="yolo11l-pose.yaml"
        />
      </QueryClientProvider>,
    );
    await screen.findByRole("option", { name: /Verified coral landmarks/ });
    fireEvent.change(screen.getByLabelText("Frozen pose dataset"), {
      target: { value: "dataset-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.some(([input]) =>
          String(input).endsWith("/validate"),
        ),
      ).toBe(true),
    );
    const request = fetchSpy.mock.calls.find(([input]) =>
      String(input).endsWith("/validate"),
    )!;
    const graph = JSON.parse(String(request[1]?.body));
    expect(
      graph.nodes.find(
        (node: { node_type: string }) =>
          node.node_type === "pose_training_dataset",
      ).parameters.dataset_id,
    ).toBe("dataset-1");
    expect(
      graph.nodes.find(
        (node: { node_type: string }) =>
          node.node_type === "pose_model_training",
      ).parameters,
    ).toMatchObject({
      architecture: "yolo11l-pose.yaml",
      initialization_mode: "random",
    });
    expect(
      graph.edges.some(
        (edge: { target_port_id: string }) =>
          edge.target_port_id === "initial_model",
      ),
    ).toBe(false);
    client.clear();
  });

  it("binds the guided native workflow to separate frozen datasets and an original recording", async () => {
    const datasets = ["train", "validation"].map((name, index) => ({
      id: `dataset-${name}`,
      name,
      status: "complete",
      item_count: 12,
      manifest_sha256: (index ? "b" : "a").repeat(64),
      pose_schema_revision: 2,
      pose_schema_id: "schema-1",
      pose_schema_content_hash: "c".repeat(64),
    }));
    const recording = {
      id: "video-3",
      original_filename: "held-out.mp4",
      sha256: "d".repeat(64),
    };
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const endpoint = String(input);
        const payload = endpoint.endsWith("/pose-training-datasets")
          ? datasets
          : endpoint.endsWith("/videos")
            ? [recording]
            : endpoint.endsWith("/validate")
              ? { valid: true, issues: [], topological_order: [] }
              : [];
        return new Response(JSON.stringify(payload), { status: 200 });
      });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <WorkflowGraphWorkspace project={{ id: "project-1" } as Project} />
      </QueryClientProvider>,
    );
    const template = screen.getByRole("combobox", {
      name: "Template",
    });
    expect(
      screen.getByRole("option", {
        name: "Native ReefPose training and reviewed export",
      }),
    ).toBeInTheDocument();
    fireEvent.change(template, {
      target: { value: "reefpose-native-reviewed-workflow" },
    });
    await screen.findAllByRole("option", {
      name: /validation.*12 observations/,
    });
    fireEvent.change(
      screen.getByRole("combobox", { name: /Frozen training dataset/ }),
      { target: { value: datasets[0].id } },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: /Frozen validation dataset/ }),
      { target: { value: datasets[1].id } },
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: /Held-out recording/ }),
      { target: { value: recording.id } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.some(([input]) =>
          String(input).endsWith("/validate"),
        ),
      ).toBe(true),
    );
    const graph = JSON.parse(
      String(
        fetchSpy.mock.calls.find(([input]) =>
          String(input).endsWith("/validate"),
        )![1]?.body,
      ),
    );
    expect(graph.nodes).toHaveLength(14);
    expect(graph.nodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          node_type: "pose_training_dataset",
          parameters: {
            dataset_id: datasets[0].id,
            manifest_sha256: datasets[0].manifest_sha256,
          },
        }),
        expect.objectContaining({
          node_type: "pose_training_dataset",
          parameters: {
            dataset_id: datasets[1].id,
            manifest_sha256: datasets[1].manifest_sha256,
          },
        }),
        expect.objectContaining({
          node_type: "project_video_source",
          parameters: {
            video_id: recording.id,
            video_sha256: recording.sha256,
          },
        }),
        expect.objectContaining({ node_type: "pose_review_gate" }),
        expect.objectContaining({
          node_type: "pose_active_learning_review_gate",
        }),
      ]),
    );
    client.clear();
  });

  it("invalidates Model Hub data when a workflow registers its completed model", async () => {
    let modelHubRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      let payload: unknown = [];
      let status = 200;

      if (url.endsWith("/model-hub/bootstrap")) {
        modelHubRequests += 1;
      } else if (url.endsWith("/plan") && method === "POST") {
        payload = { valid: true, executable: true, issues: [] };
      } else if (url.endsWith("/workflow-graphs") && method === "POST") {
        payload = { id: "graph-1" };
        status = 201;
      } else if (url.endsWith("/workflow-runs") && method === "POST") {
        payload = { id: "run-1" };
        status = 202;
      } else if (url.endsWith("/workflow-runs/run-1")) {
        payload = {
          run: {
            id: "run-1",
            project_id: "project-1",
            status: "succeeded",
            result_json: {},
          },
          nodes: [],
          artifacts: [],
        };
      }

      return new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["model_hub_bootstrap", "project-1"], {
      models: [],
    });
    client.setQueryData(["video-tracking-models", "project-1"], []);
    render(
      <QueryClientProvider client={client}>
        <WorkflowGraphWorkspace
          project={{ id: "project-1" } as Project}
          initialPoseArchitecture="reefpose-s"
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save & run" }));

    await screen.findByText("Status:");
    await waitFor(() => expect(modelHubRequests).toBeGreaterThanOrEqual(2));
    expect(
      client.getQueryState(["video-tracking-models", "project-1"])
        ?.isInvalidated,
    ).toBe(true);
    client.clear();
  });

  it.each([
    [
      "pose_review_gate",
      "pose_temporal_tracks",
      { track_ids: ["track-7"] },
      "Review temporal associations",
      undefined,
    ],
    [
      "pose_active_learning_review_gate",
      "pose_active_learning_round",
      { source_track_ids: ["track-7"], round_id: "round-5" },
      "Open pose acquisition review",
      "round-5",
    ],
  ])(
    "links waiting %s to the precise local review",
    async (nodeType, dataType, source, action, roundId) => {
      vi.spyOn(globalThis, "fetch").mockImplementation(
        async (input) =>
          new Response(
            JSON.stringify(
              String(input).endsWith("/workflow-runs/run-3")
                ? {
                    run: {
                      id: "run-3",
                      project_id: "project-1",
                      status: "waiting_for_review",
                      result_json: {},
                    },
                    nodes: [
                      {
                        id: "node-2",
                        node_id: "review",
                        node_type: nodeType,
                        status: "waiting_for_review",
                        result_json: {
                          review: { source_artifact_id: "artifact-4" },
                        },
                      },
                    ],
                    artifacts: [
                      {
                        id: "artifact-4",
                        data_type: dataType,
                        payload_sha256: "a".repeat(64),
                        payload_json: {
                          project_id: "project-1",
                          video_id: "video-6",
                          ...source,
                        },
                      },
                    ],
                  }
                : [],
            ),
            { status: 200 },
          ),
      );
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const openReview = vi.fn();
      render(
        <QueryClientProvider client={client}>
          <WorkflowGraphWorkspace
            project={{ id: "project-1" } as Project}
            initialRunId="run-3"
            onOpenPoseReview={openReview}
          />
        </QueryClientProvider>,
      );
      fireEvent.click(await screen.findByRole("button", { name: action }));
      expect(openReview).toHaveBeenCalledWith({
        runId: "run-3",
        videoId: "video-6",
        trackId: "track-7",
        roundId,
      });
      client.clear();
    },
  );
});
