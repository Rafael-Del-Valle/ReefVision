import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { WorkflowGraphWorkspace } from "./WorkflowGraphWorkspace";

const project = { id: "reviewed-project" } as Project;
const packageSha = "a".repeat(64);
const imageSha = "b".repeat(64);
const waiting = {
  id: "run-1",
  project_id: project.id,
  job_id: "job-1",
  status: "waiting_for_review",
  graph_sha256: "c".repeat(64),
  input_json: {},
  result_json: {},
  error_message: null,
};
const pluginArtifact = {
  id: "measurement-artifact",
  workflow_run_id: waiting.id,
  producer_node_run_id: "measure-node",
  producer_port_id: "measurement",
  data_type: "scientific_record_collection",
  payload_sha256: "d".repeat(64),
  payload_json: {
    quantity: "green_fraction",
    value: 0.5,
    unit: "1",
    qc: "unassessed",
    plugin: { package_sha256: packageSha, image_sha256: imageSha },
  },
};

function renderWaiting(missing: boolean) {
  const review = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = new URL(input).pathname;
      const json = (object: unknown) =>
        new Response(JSON.stringify(object), {
          headers: { "Content-Type": "application/json" },
        });
      if (path.endsWith("/resume-review")) {
        review(JSON.parse(String(init?.body)));
        return json({ ...waiting, status: "queued" });
      }
      if (path.endsWith("/workflow-runs")) return json([waiting]);
      if (path.endsWith("/workflow-runs/run-1"))
        return json({
          run: waiting,
          nodes: [
            {
              id: "review-node",
              node_id: "review-measurement",
              node_type: "measurement_review_gate",
              status: "waiting_for_review",
              input_artifact_ids_json: [pluginArtifact.id],
              result_json: {},
            },
          ],
          artifacts: [
            {
              ...pluginArtifact,
              id: "another-measurement",
              payload_json: {
                ...pluginArtifact.payload_json,
                quantity: "different_quantity",
              },
            },
            ...(!missing ? [pluginArtifact] : []),
          ],
        });
      return json([]);
    }),
  );
  render(
    <QueryClientProvider client={client}>
      <WorkflowGraphWorkspace project={project} />
    </QueryClientProvider>,
  );
  return review;
}

afterEach(() => vi.unstubAllGlobals());

describe("Workflow plugin measurement review", () => {
  it("shows the saved gate input and keeps acknowledgement explicit", async () => {
    const review = renderWaiting(false);
    fireEvent.click(
      await screen.findByRole("button", { name: /^waiting_for_review/ }),
    );
    const input = await screen.findByRole("region", {
      name: "Measurement to review",
    });
    expect(within(input).getByText("green_fraction")).toBeVisible();
    expect(within(input).getByText("0.5 1")).toBeVisible();
    expect(within(input).getByText(imageSha)).toBeVisible();
    expect(within(input).getByText(packageSha)).toBeVisible();
    expect(
      within(input).getByText(/scientific qc remains unassessed/i),
    ).toBeVisible();
    expect(
      within(input).queryByText("different_quantity"),
    ).not.toBeInTheDocument();
    expect(review).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Resume after review" }),
    );
    await waitFor(() =>
      expect(review).toHaveBeenCalledExactlyOnceWith({
        reviewed_by: "local_user",
        note: "Approved from the workflow workspace after human review.",
      }),
    );
  });

  it("does not enable acknowledgement for a missing measurement input", async () => {
    const review = renderWaiting(true);
    fireEvent.click(
      await screen.findByRole("button", { name: /^waiting_for_review/ }),
    );
    expect(
      await screen.findByText(
        "The saved measurement to review is unavailable.",
      ),
    ).toBeVisible();
    const resume = screen.getByRole("button", { name: "Resume after review" });
    expect(resume).toBeDisabled();
    fireEvent.click(resume);
    expect(review).not.toHaveBeenCalled();
  });
});
