import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { getJob, type JobRecord } from "../../api/client";
import { ScheduledJobDetails } from "./ScheduledJobDetails";

vi.mock("../../api/client", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("../../api/client")>()),
  getJob: vi.fn(),
}));

const job: JobRecord = {
  id: "job-one",
  project_id: "reef",
  job_type: "workflow_run",
  status: "succeeded",
  request_json: { workflow_run_id: "run-one" },
  result_json: { stage: "complete" },
  progress_current: 3,
  progress_total: 3,
  error_message: null,
  created_at: "2026-11-20T12:00:00Z",
  started_at: null,
  completed_at: null,
};

function open(record: JobRecord) {
  vi.mocked(getJob).mockResolvedValue(record);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ScheduledJobDetails projectId="reef" jobId="job-one" runId="run-one" />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Open job" }));
}

it("opens the actual workflow job and its progress", async () => {
  open(job);
  expect(await screen.findByText("Progress 3 / 3")).toBeInTheDocument();
  expect(screen.getByText("complete")).toBeInTheDocument();
});

it("rejects a job from a different occurrence", async () => {
  open({ ...job, request_json: { workflow_run_id: "another-run" } });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "does not match this occurrence",
  );
  expect(screen.queryByText("Progress 3 / 3")).not.toBeInTheDocument();
});
