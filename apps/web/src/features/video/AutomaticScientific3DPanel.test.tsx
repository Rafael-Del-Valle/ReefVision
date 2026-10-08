import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AutomaticScientific3DPanel } from "./AutomaticScientific3DPanel";
import * as scienceApi from "./videoScienceApi";

vi.mock("./videoScienceApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoScienceApi")>(
      "./videoScienceApi",
    );
  return {
    ...actual,
    createMetricDepth3DJob: vi.fn(),
    getMetricDepth3DJob: vi.fn(),
  };
});

const track = {
  id: "track-1",
  video_id: "video-1",
  label_class_id: "class-1",
  track_number: 1,
  geometry_kind: "bbox",
  keyframes_json: [],
  interpolation: "linear",
  status: "verified",
  source_model_id: null,
  source_job_id: null,
  metadata_json: {},
  revision: 1,
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AutomaticScientific3DPanel
        videoId="video-1"
        tracks={[track]}
        cameraReady
        classNames={new Map([["class-1", "Fish"]])}
      />
    </QueryClientProvider>,
  );
}

describe("AutomaticScientific3DPanel", () => {
  beforeEach(() => {
    vi.mocked(scienceApi.createMetricDepth3DJob).mockResolvedValue({
      id: "job-1",
      project_id: "project-1",
      job_type: "video_metric_depth_3d",
      status: "queued",
      progress_current: 0,
      progress_total: 3,
      request_json: {},
      result_json: {
        stage: "queued",
        depth_tier: "model_estimated_metric",
        physical_measurement_claim_allowed: false,
      },
      error_message: null,
      created_at: "2026-08-21T00:00:00Z",
      started_at: null,
      completed_at: null,
    });
    vi.mocked(scienceApi.getMetricDepth3DJob).mockResolvedValue({
      id: "job-1",
      project_id: "project-1",
      job_type: "video_metric_depth_3d",
      status: "running",
      progress_current: 1,
      progress_total: 3,
      request_json: {},
      result_json: {
        stage: "metric_depth_inference",
        depth_tier: "model_estimated_metric",
        physical_measurement_claim_allowed: false,
      },
      error_message: null,
      created_at: "2026-08-21T00:00:00Z",
      started_at: "2026-08-21T00:00:01Z",
      completed_at: null,
    });
  });

  it("requires a registered compatible depth model without offering acquisition", () => {
    renderPanel();
    expect(
      screen.getByText(/Model required — register a compatible/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Install.*from Models/)).not.toBeInTheDocument();
  });

  it("shows the model-estimated metric safety tier", () => {
    renderPanel();
    expect(screen.getByText("Video → Depth & 3D")).toBeInTheDocument();
    expect(screen.getByText("Model-estimated metric")).toBeInTheDocument();
    expect(
      screen.getByText(/Disabled — underwater validation required/),
    ).toBeInTheDocument();
  });

  it("queues selected tracks without silently downloading a model", async () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText("Track 1 — Fish"));
    fireEvent.click(
      screen.getByRole("button", { name: "Run automatic Depth & 3D" }),
    );

    await waitFor(() => {
      expect(scienceApi.createMetricDepth3DJob).toHaveBeenCalledWith(
        "video-1",
        expect.objectContaining({
          track_ids: ["track-1"],
          device: "auto",
          input_size: 518,
          max_res: 1280,
          core_fraction: 0.6,
          minimum_valid_fraction: 0.25,
          allow_model_download: false,
          allow_resolution_fallback: true,
        }),
      );
    });
  });
});
