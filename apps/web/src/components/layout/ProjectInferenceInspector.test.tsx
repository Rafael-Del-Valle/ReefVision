import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ModelRegistration } from "../../api/client";
import { ProjectInferenceInspector } from "./ProjectInferenceInspector";

const model: ModelRegistration = {
  id: "model-best",
  project_id: "project-1",
  purpose: "detector",
  display_name: "Coral best.pt",
  source_filename: "best.pt",
  managed_path: "projects/project-1/models/best.pt",
  sha256: "d".repeat(64),
  file_size_bytes: 1234,
  framework: "ultralytics",
  task: "detect",
  provider_name: "ultralytics",
  provider_version: "8.4.19",
  class_map_json: {},
  input_size_json: null,
  metadata_json: {},
  notes: null,
  created_at: "2026-09-16T00:00:00Z",
  updated_at: "2026-09-16T00:00:00Z",
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderInspector(
  selectedImageIds: string[] = ["image-1"],
  onOpenModelHub = vi.fn(),
  onOpenAdvancedProviders = vi.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProjectInferenceInspector
        projectId="project-1"
        selectedImageIds={selectedImageIds}
        onOpenModelHub={onOpenModelHub}
        onOpenAdvancedProviders={onOpenAdvancedProviders}
      />
    </QueryClientProvider>,
  );

  return { onOpenModelHub, onOpenAdvancedProviders };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProjectInferenceInspector", () => {
  it("runs the existing project inference API for the Gallery selection", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });

      if (url.includes("/projects/project-1/models?purpose=detector")) {
        return jsonResponse([model]);
      }

      if (
        url.endsWith("/projects/project-1/inference-jobs") &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "job-1",
          project_id: "project-1",
          job_type: "inference",
          status: "queued",
          progress_current: 0,
          progress_total: 1,
          request_json: {},
          result_json: null,
          error_message: null,
          created_at: "2026-10-05T00:00:00Z",
          started_at: null,
          completed_at: null,
        });
      }

      if (url.includes("/jobs/job-1?poll=")) {
        return jsonResponse({
          id: "job-1",
          project_id: "project-1",
          job_type: "inference",
          status: "succeeded",
          progress_current: 1,
          progress_total: 1,
          request_json: {},
          result_json: {},
          error_message: null,
          created_at: "2026-10-05T00:00:00Z",
          started_at: "2026-10-05T00:00:01Z",
          completed_at: "2026-10-05T00:00:02Z",
        });
      }

      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderInspector(["image-1"]);

    expect(
      await screen.findByText("1 detector registered"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Detector model")).toHaveValue("model-best");
    expect(screen.getByLabelText("Confidence threshold")).toHaveValue(0.25);
    expect(screen.getByLabelText("Device")).toHaveValue("cpu");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Run model on selected images",
      }),
    );

    await waitFor(() => {
      const request = requests.find(
        (entry) =>
          entry.url.endsWith("/projects/project-1/inference-jobs") &&
          entry.init?.method === "POST",
      );

      expect(request).toBeDefined();

      expect(JSON.parse(String(request?.init?.body))).toEqual({
        model_id: "model-best",
        image_ids: ["image-1"],
        confidence_threshold: 0.25,
        device: "cpu",
      });
    });

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("1/1")).toBeInTheDocument();
  });

  it("blocks execution until at least one Gallery image is selected", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/projects/project-1/models?purpose=detector")) {
        return jsonResponse([model]);
      }

      throw new Error(`Unhandled request GET ${url}`);
    });

    renderInspector([]);

    expect(
      await screen.findByText("1 detector registered"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Run model on selected images",
      }),
    ).toBeDisabled();

    expect(
      screen.getByText("Select Gallery images to enable inference"),
    ).toBeInTheDocument();
  });

  it("routes model management and provider inference to canonical workspaces", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/projects/project-1/models?purpose=detector")) {
        return jsonResponse([model]);
      }

      throw new Error(`Unhandled request GET ${url}`);
    });

    const handlers = renderInspector();

    await screen.findByText("1 detector registered");

    await userEvent.click(
      screen.getByRole("button", {
        name: /Model Hub/,
      }),
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: /Advanced Provider Lab/,
      }),
    );

    expect(handlers.onOpenModelHub).toHaveBeenCalledTimes(1);
    expect(handlers.onOpenAdvancedProviders).toHaveBeenCalledTimes(1);
  });
});
