import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { WorkflowGraphWorkspace } from "./WorkflowGraphWorkspace";
import type { WorkflowRun } from "./workflowGraphApi";

const project = { id: "project-1" } as Project;
const failed: WorkflowRun = {
  id: "run-1",
  project_id: project.id,
  workflow_graph_record_id: "graph-1",
  job_id: "parent-job-1",
  status: "failed",
  graph_sha256: "a".repeat(64),
  input_json: {},
  result_json: {},
  error_message: "Managed source video file is missing",
  started_at: null,
  completed_at: null,
  created_at: "2026-01-01T00:00:00Z",
};
const waiting: WorkflowRun = {
  ...failed,
  id: "run-2",
  job_id: "parent-job-2",
  status: "waiting_for_review",
  graph_sha256: "b".repeat(64),
  error_message: null,
};

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderWorkspace(onRetry: () => Promise<Response>) {
  let firstRun = failed;
  const requests = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/retry")) {
        const response = await onRetry();
        if (response.ok) {
          firstRun = { ...failed, status: "queued", error_message: null };
        }
        return response;
      }
      if (url.endsWith("/workflow-runs")) return json([firstRun, waiting]);
      if (url.endsWith("/workflow-runs/run-1")) {
        return json({ run: firstRun, nodes: [], artifacts: [] });
      }
      if (url.endsWith("/workflow-runs/run-2")) {
        return json({ run: waiting, nodes: [], artifacts: [] });
      }
      return json([]);
    });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <WorkflowGraphWorkspace project={project} />
    </QueryClientProvider>,
  );
  return { client, requests, unmount: view.unmount };
}

afterEach(() => vi.restoreAllMocks());

describe("Failed workflow recovery", () => {
  it("retries the inspected parent once and refreshes that run while another run is selected", async () => {
    const onRetry = vi.fn();
    let acknowledge: (response: Response) => void = () => undefined;
    onRetry.mockReturnValue(
      new Promise<Response>((resolve) => {
        acknowledge = resolve;
      }),
    );
    const view = renderWorkspace(onRetry);
    fireEvent.click(await screen.findByRole("button", { name: /^failed/ }));
    expect(await screen.findByText(failed.error_message!)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry failed workflow" }),
    );
    const retrying = await screen.findByRole("button", {
      name: "Retrying workflow…",
    });
    expect(retrying).toBeDisabled();
    fireEvent.click(retrying);
    fireEvent.click(
      screen.getByRole("button", { name: /^waiting_for_review/ }),
    );
    await screen.findByText(/this run is safely paused/i);
    expect(screen.queryByRole("button", { name: /^Retry/ })).toBeNull();

    acknowledge(json({ id: failed.job_id, status: "queued" }));
    fireEvent.click(await screen.findByRole("button", { name: /^queued/ }));
    await waitFor(() => {
      expect(
        view.client.getQueryData(["workflow-run", project.id, failed.id]),
      ).toMatchObject({
        run: { id: failed.id, job_id: failed.job_id, status: "queued" },
      });
      expect(screen.queryByRole("button", { name: /^Retry/ })).toBeNull();
    });
    expect(onRetry).toHaveBeenCalledOnce();
    expect(
      view.requests.mock.calls
        .filter(([, init]) => init?.method === "POST")
        .map(([url]) => String(url)),
    ).toEqual([expect.stringMatching(/\/jobs\/parent-job-1\/retry$/)]);
    view.unmount();
    view.client.clear();
  });

  it("keeps a refused retry associated with the failed run", async () => {
    const view = renderWorkspace(async () =>
      json({ detail: "The workflow could not be requeued." }, 409),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^failed/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry failed workflow" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The workflow could not be requeued.",
    );
    expect(screen.getByText(failed.error_message!)).toBeVisible();
    const action = await screen.findByRole("button", {
      name: "Retry failed workflow",
    });
    expect(action).toBeEnabled();

    fireEvent.click(
      screen.getByRole("button", { name: /^waiting_for_review/ }),
    );
    await screen.findByText(/this run is safely paused/i);
    expect(screen.queryByRole("alert")).toBeNull();
    view.unmount();
    view.client.clear();
  });
});
