import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as jobs from "../../api/client";
import * as api from "./temporalReefPoseApi";
import { TemporalReefPosePanel } from "./TemporalReefPosePanel";

afterEach(() => vi.restoreAllMocks());

it("keeps refinement unverified until a frame decision is explicitly confirmed", async () => {
  const run: api.TemporalRun = {
    id: "refinement",
    kind: "inference",
    status: "succeeded",
    job_id: null,
    result: null,
    review_revision: 2,
  };
  const point = {
    landmark_id: "mouth",
    x: 12,
    y: 15,
    confidence: 0.7,
    visibility: "visible",
  };
  vi.spyOn(api, "getTemporalInputs").mockResolvedValue({
    frame_tracks: [],
    reviewed_tracks: [],
    identities: [],
    temporal_models: [],
    frame_models: [],
  });
  vi.spyOn(api, "getTemporalDatasets").mockResolvedValue([]);
  vi.spyOn(api, "getTemporalRuns").mockResolvedValue([run]);
  vi.spyOn(api, "getTemporalFrames").mockResolvedValue({
    items: [
      {
        frame_index: 4,
        timestamp_seconds: 0.2,
        frame_points: null,
        refined_points: [point, null],
        future_frames: 0,
        future_seconds: 0,
      },
    ],
    offset: 0,
    limit: 25,
    total: 1,
  });
  const save = vi.spyOn(api, "reviewTemporalFrames").mockResolvedValue({
    id: "review",
    revision: 3,
    identity_run_id: "identity-run",
    identity_id: "animal",
    accepted_frame_count: 1,
    source_stale: false,
  });
  vi.spyOn(jobs, "getJob");
  const setFrame = vi.fn();
  const openMeasurements = vi.fn();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <TemporalReefPosePanel
        projectId="project-a"
        videoId="fish"
        onFrameChange={setFrame}
        onReviewed={openMeasurements}
      />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: /inference.*succeeded/ });
  fireEvent.change(screen.getByLabelText("Saved temporal runs"), {
    target: { value: "refinement" },
  });
  fireEvent.click(await screen.findByText(/Frame 4 ·/));
  const frame = screen.getByRole("table", { name: "Landmarks at frame 4" });
  expect(within(frame).getByText("Missing")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Show source frame" }));
  expect(setFrame).toHaveBeenCalledWith(4);
  fireEvent.change(screen.getByLabelText("Review decision for frame 4"), {
    target: { value: "refined" },
  });
  expect(
    screen.getByRole("button", { name: "Save pose review revision" }),
  ).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Correct landmark coordinates"));
  fireEvent.change(screen.getByLabelText("mouth X (px)"), {
    target: { value: "14" },
  });
  fireEvent.click(
    screen.getByLabelText(
      "I confirmed these pose choices against the recording",
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save pose review revision" }),
  );
  const measurement = await screen.findByRole("button", {
    name: "Open in biological measurements",
  });
  expect(save).toHaveBeenCalledWith("project-a", "refinement", {
    base_revision: 2,
    confirmed: true,
    note: undefined,
    frames: [
      {
        frame_index: 4,
        source: "refined",
        corrections: [{ landmark_id: "mouth", x: 14, y: 15 }],
      },
    ],
  });
  fireEvent.click(measurement);
  expect(openMeasurements).toHaveBeenCalledWith("identity-run", "animal");
});
