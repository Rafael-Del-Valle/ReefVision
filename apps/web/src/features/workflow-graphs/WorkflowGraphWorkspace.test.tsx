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
});
