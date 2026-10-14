import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ImprovePredictionsPanel } from "./ImprovePredictionsPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const report = {
  ready: true,
  blockers: [],
  warnings: [],
  reviewed_image_count: 10,
  eligible_object_count: 40,
  per_class_counts: [
    {
      label_class_id: "coral",
      class_name: "Coral",
      count: 40,
      train_count: 32,
      validation_count: 8,
    },
  ],
  split_counts: { train: 8, validation: 2 },
  latest_run: null,
  promotion_policy: "Candidate only; explicit selection required.",
};
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <ImprovePredictionsPanel
        projectId="project-1"
        onClose={() => undefined}
      />
    </QueryClientProvider>,
  );
}
function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

it("explains insufficient verified data and does not queue training", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/models?purpose=detector")) return json([]);
      return json({
        ...report,
        ready: false,
        blockers: ["Need at least 10 reviewed images; found 1."],
      });
    });
  mount();
  expect(
    await screen.findByText("Need at least 10 reviewed images; found 1."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "Train candidate from verified annotations",
    }),
  ).toBeDisabled();
  expect(
    fetch.mock.calls.some(([url]) => String(url).endsWith("/learning/improve")),
  ).toBe(false);
});

it("queues an immutable candidate only after an explicit action and exposes cancellation", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const run = { id: "training-1", status: "queued" };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    requests.push({ url, init });
    if (url.endsWith("/learning/status")) return json(report);
    if (url.includes("/models?purpose=detector")) return json([]);
    if (url.endsWith("/learning/improve"))
      return json({
        readiness: report,
        run,
        dataset_version: { id: "frozen-1", name: "Verified project learning" },
        preflight: null,
      });
    if (url.endsWith("/training-runs/training-1/cancel"))
      return json({ ...run, status: "cancelling" });
    if (url.endsWith("/training-runs/training-1")) return json(run);
    throw new Error(`Unexpected request ${url}`);
  });
  mount();
  await screen.findByText("10 reviewed images · 40 eligible objects");
  expect(requests.some((item) => item.url.endsWith("/learning/improve"))).toBe(
    false,
  );
  await userEvent.click(
    screen.getByRole("button", {
      name: "Train candidate from verified annotations",
    }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Cancel candidate training" }),
  );
  await waitFor(() =>
    expect(
      requests.some((item) =>
        item.url.endsWith("/training-runs/training-1/cancel"),
      ),
    ).toBe(true),
  );
  const payload = JSON.parse(
    String(
      requests.find((item) => item.url.endsWith("/learning/improve"))?.init
        ?.body,
    ),
  );
  expect(payload).toMatchObject({
    task: "detect",
    device: "cpu",
    minimum_images: 10,
    minimum_objects_per_class: 20,
  });
  expect(payload).not.toHaveProperty("automatic_promotion");
});

it("requires held-out evaluation before explicit promotion and supports rollback", async () => {
  const requests: string[] = [];
  const candidate = {
    id: "candidate-1",
    display_name: "Coral candidate",
    metadata_json: {
      source_training_run_id: "run-1",
      source_dataset_version_id: "version-1",
    },
  };
  let active = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    requests.push(url);
    if (url.endsWith("/learning/status")) return json(report);
    if (url.includes("/models?purpose=detector"))
      return json([
        {
          ...candidate,
          metadata_json: {
            ...candidate.metadata_json,
            active_for_predictions: active,
          },
        },
      ]);
    if (url.endsWith("/learning/evaluations") && init?.method === "POST")
      return json({
        id: "eval-1",
        status: "waiting",
        candidate_metrics: null,
        incumbent_metrics: null,
        promotion_eligible: false,
        blockers: [],
      });
    if (url.endsWith("/learning/evaluations/eval-1"))
      return json({
        id: "eval-1",
        status: "completed",
        candidate_metrics: {
          map50: 0.8,
          precision: 0.75,
          recall: 0.7,
          mean_absolute_count_error: 0.2,
        },
        incumbent_metrics: null,
        promotion_eligible: true,
        blockers: [],
      });
    if (url.endsWith("/learning/evaluations/eval-1/promote")) {
      active = true;
      return json({
        id: "deployment-1",
        active_model_id: candidate.id,
        previous_model_id: null,
        evaluation_id: "eval-1",
      });
    }
    if (url.endsWith("/learning/deployments/deployment-1/rollback")) {
      active = false;
      return json({
        id: "rollback-1",
        active_model_id: null,
        previous_model_id: candidate.id,
        evaluation_id: "eval-1",
      });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  mount();
  await screen.findByRole("option", { name: candidate.display_name });
  await userEvent.selectOptions(
    screen.getByLabelText("Registered training candidate"),
    candidate.id,
  );
  expect(
    screen.getByRole("button", { name: "Promote evaluated candidate" }),
  ).toBeDisabled();
  await userEvent.click(
    screen.getByRole("button", { name: "Evaluate on frozen holdout" }),
  );
  await screen.findByText("0.800");
  await userEvent.click(
    screen.getByRole("button", { name: "Promote evaluated candidate" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Rollback model selection" }),
  );
  await waitFor(() =>
    expect(requests.some((url) => url.endsWith("/rollback"))).toBe(true),
  );
});

it("registers a completed learning run as an evaluable candidate", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const completed = {
    id: "training-complete",
    status: "completed",
    result_checkpoint_path: "projects/project-1/training/best.pt",
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    requests.push({ url, init });
    if (url.endsWith("/learning/status"))
      return json({ ...report, latest_run: completed });
    if (url.endsWith("/training-runs/training-complete"))
      return json(completed);
    if (url.endsWith("/models?purpose=detector")) return json([]);
    if (url.endsWith("/models/register-from-run") && init?.method === "POST")
      return json({
        id: "candidate-new",
        display_name: "Verified project learning best",
        metadata_json: {
          source_training_run_id: completed.id,
          source_dataset_version_id: "version-new",
        },
      });
    throw new Error(`Unexpected request ${url}`);
  });
  mount();
  await userEvent.click(
    await screen.findByRole("button", {
      name: "Register completed candidate checkpoint",
    }),
  );
  await waitFor(() =>
    expect(
      requests.some(
        (request) =>
          request.url.endsWith("/models/register-from-run") &&
          JSON.parse(String(request.init?.body)).training_run_id ===
            completed.id,
      ),
    ).toBe(true),
  );
});
