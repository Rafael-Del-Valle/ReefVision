import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { ModelRegistration } from "../../api/client";
import { ReviewedModelRuntime } from "./ReviewedModelRuntime";

const model: ModelRegistration = {
  id: "model",
  project_id: "project",
  purpose: "detector",
  display_name: "Archived coral detector",
  source_filename: "original.pt",
  managed_path: "models/original.pt",
  sha256: "2".repeat(64),
  file_size_bytes: 64,
  framework: "ultralytics",
  task: "detect",
  provider_name: "ultralytics",
  provider_version: "1",
  class_map_json: {},
  input_size_json: null,
  metadata_json: {},
  notes: null,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
};

afterEach(() => vi.unstubAllGlobals());

it("shows the original historical receipt and asks for a fresh local review", async () => {
  const digest = "1".repeat(64);
  const fetch = vi.fn(async (url: string) => {
    if (!url.endsWith("/model-runtime-selections"))
      throw new Error("Unexpected request");
    return Response.json([
      {
        id: "historic",
        model_id: model.id,
        content_sha256: digest,
        requires_re_review: true,
        snapshot: {
          display_name: model.display_name,
          checkpoint_sha256: model.sha256,
          task: "detect",
          provider_id: "ultralytics",
          provider_version: "1",
          runtime_id: "pytorch",
          runtime_version: "1",
          settings: {
            device: "cpu",
            confidence_threshold: 0.45,
            iou_threshold: 0.4,
          },
          prompt: "confidence 0.45",
        },
      },
    ]);
  });
  vi.stubGlobal("fetch", fetch);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <ReviewedModelRuntime projectId="project" models={[model]} />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", {
    name: /Archived coral detector.*review again/i,
  });
  fireEvent.change(screen.getByLabelText("Reviewed model configuration"), {
    target: { value: "historic" },
  });
  expect(screen.getByText(digest)).toBeInTheDocument();
  expect(screen.getAllByText(/Application not recorded/)).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: "Run reviewed inference" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Review configuration again" }),
  );
  expect(screen.getByLabelText("Registered checkpoint")).toHaveValue(model.id);
  expect(screen.getByLabelText("Configuration request (optional)")).toHaveValue(
    "confidence 0.45",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
