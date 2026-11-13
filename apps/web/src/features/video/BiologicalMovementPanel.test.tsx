import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BiologicalMovementPanel } from "./BiologicalMovementPanel";
import * as movementApi from "./biologicalMovementApi";
import * as identityApi from "./poseIdentityTrackingApi";
import type { VideoTrackRecord } from "./videoApi";

vi.mock("../../api/client", () => ({ cancelJob: vi.fn() }));
vi.mock("./poseIdentityTrackingApi", () => ({
  listPoseIdentityRuns: vi.fn(),
  getPoseIdentityIdentities: vi.fn(),
}));
vi.mock("./biologicalMovementApi", () => ({
  listMeasurementRuns: vi.fn(),
  createMeasurementRun: vi.fn(),
  listMeasurementSeries: vi.fn(),
  listMeasurementSamples: vi.fn(),
  listEventRuns: vi.fn(),
  createEventRun: vi.fn(),
  listBiologicalEvents: vi.fn(),
  correctBiologicalEvent: vi.fn(),
  biologicalMovementExportUrl: vi.fn(
    (runId: string, format: string) => `/movement/${runId}.${format}`,
  ),
}));

const identityRun = {
  id: "identity-run-1",
  project_id: "project-1",
  video_id: "video-1",
  status: "completed",
  revision: 4,
};
const reviewedIdentity = {
  id: "animal-1",
  stable_identity_key: "fish-0001",
  display_name: "Fish 1",
  verification_state: "scientist_confirmed",
};
const unreviewedIdentity = {
  id: "animal-2",
  stable_identity_key: "fish-0002",
  display_name: "Fish 2",
  verification_state: "unreviewed",
};
const measurementRun = {
  id: "measurement-run-1",
  project_id: "project-1",
  video_id: "video-1",
  source_identity_run_id: "identity-run-1",
  source_identity_run_revision: 4,
  source_job_id: "job-1",
  definitions_json: [],
  configuration_json: {},
  status: "completed",
  progress_json: { stage: "completed" },
  verification_state: "scientist_verified",
  result_sha256: "a".repeat(64),
};
const series = {
  id: "series-1",
  measurement_run_id: "measurement-run-1",
  animal_identity_id: "animal-1",
  definition_id: "gape",
  measurement_kind: "distance",
  display_name: "Gape distance",
  pixel_unit: "px",
  physical_unit: "mm",
  summary_json: {},
};
const eventRun = {
  id: "event-run-1",
  measurement_run_id: "measurement-run-1",
  source_job_id: "job-2",
  configuration_json: {},
  status: "completed",
  progress_json: { stage: "completed" },
  result_sha256: "b".repeat(64),
};
const completeEvent = {
  id: "event-1",
  event_series_id: "cycle-1",
  revision: 1,
  measurement_series_id: "series-1",
  animal_identity_id: "animal-1",
  start_frame: 2,
  peak_frame: 4,
  end_frame: 6,
  amplitude: 5,
  duration_s: 0.4,
  confidence: 0.9,
  cycle_state: "complete",
  review_state: "unreviewed",
  detection_source: "automatic",
  is_current: true,
};
const partialEvent = {
  ...completeEvent,
  id: "event-2",
  event_series_id: "cycle-2",
  start_frame: 8,
  peak_frame: null,
  end_frame: null,
  cycle_state: "partial",
};

const tracks = [
  {
    id: "track-1",
    video_id: "video-1",
    metadata_json: {
      pose_landmark_schema: {
        schema_version: "pose-landmarks-0001",
        schema_id: "schema-1",
        schema_revision: 3,
        content_hash: "c".repeat(64),
        groups: [],
        expanded_labels: ["upper-jaw", "lower-jaw", "eye"],
        keypoint_count: 3,
        allows_repeated_labels: false,
        landmarks: [
          { id: "upper-jaw", name: "Upper jaw" },
          { id: "lower-jaw", name: "Lower jaw" },
          { id: "eye", name: "Eye" },
        ],
        edges: [],
      },
    },
  } as unknown as VideoTrackRecord,
];

function renderPanel(onFrameChange = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BiologicalMovementPanel
        projectId="project-1"
        videoId="video-1"
        tracks={tracks}
        onFrameChange={onFrameChange}
      />
    </QueryClientProvider>,
  );
  return onFrameChange;
}

describe("BiologicalMovementPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(identityApi.listPoseIdentityRuns).mockResolvedValue([
      identityRun as never,
    ]);
    vi.mocked(identityApi.getPoseIdentityIdentities).mockResolvedValue([
      reviewedIdentity as never,
      unreviewedIdentity as never,
    ]);
    vi.mocked(movementApi.listMeasurementRuns).mockResolvedValue([
      measurementRun,
    ]);
    vi.mocked(movementApi.listMeasurementSeries).mockResolvedValue([series]);
    vi.mocked(movementApi.listMeasurementSamples).mockResolvedValue([
      {
        frame_index: 0,
        time_s: 0,
        pixel_value: 3,
        physical_value: 1.5,
        confidence: 0.9,
        valid: true,
        quality_flags_json: [],
      },
      {
        frame_index: 1,
        time_s: 0.1,
        pixel_value: null,
        physical_value: null,
        confidence: null,
        valid: false,
        quality_flags_json: ["missing_landmark"],
      },
      {
        frame_index: 2,
        time_s: 0.2,
        pixel_value: 8,
        physical_value: 4,
        confidence: 0.8,
        valid: true,
        quality_flags_json: [],
      },
    ]);
    vi.mocked(movementApi.listEventRuns).mockResolvedValue([eventRun]);
    vi.mocked(movementApi.listBiologicalEvents).mockImplementation(
      async (_runId, includeHistory) =>
        includeHistory
          ? [completeEvent, partialEvent]
          : [completeEvent, partialEvent],
    );
    vi.mocked(movementApi.createMeasurementRun).mockResolvedValue({
      id: "job-3",
      status: "queued",
      progress_current: 0,
      progress_total: 1,
      result_json: { run_id: "measurement-run-2" },
      error_message: null,
    });
    vi.mocked(movementApi.createEventRun).mockResolvedValue({
      id: "job-4",
      status: "queued",
      progress_current: 0,
      progress_total: 1,
      result_json: { run_id: "event-run-2" },
      error_message: null,
    });
    vi.mocked(movementApi.correctBiologicalEvent).mockResolvedValue({
      ...completeEvent,
      revision: 2,
      review_state: "confirmed",
    });
  });

  it("configures stable landmarks and renders scientific signals, gaps, events, and exports", async () => {
    const onFrameChange = renderPanel();

    expect(
      await screen.findByText("Gape distance time series"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Fish 2/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("Anatomical measurement time series"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Orange gaps are invalid/)).toBeInTheDocument();
    expect(screen.getByTestId("measurement-status")).toHaveTextContent(
      "scientist_verified",
    );
    expect(screen.getByTestId("event-status")).toHaveTextContent(
      "Confirmed complete cycles: 0",
    );

    fireEvent.click(screen.getByRole("button", { name: "Go to event frame" }));
    expect(onFrameChange).toHaveBeenCalledWith(4);
    fireEvent.click(screen.getByRole("button", { name: "Confirm complete" }));
    await waitFor(() =>
      expect(movementApi.correctBiologicalEvent).toHaveBeenCalledWith(
        "event-1",
        expect.objectContaining({ action: "confirm" }),
      ),
    );
    expect(screen.getByRole("link", { name: "Reviewed JSON" })).toHaveAttribute(
      "href",
      "/movement/event-run-1.json",
    );
    expect(
      screen.getByText(/Event revision history \(2\)/),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Calculate measurements" }),
    );
    await waitFor(() =>
      expect(movementApi.createMeasurementRun).toHaveBeenCalledWith(
        "project-1",
        expect.objectContaining({
          source_identity_run_revision: 4,
          identity_ids: ["animal-1"],
          verification_mode: "scientific",
          definitions: [
            expect.objectContaining({
              kind: "distance",
              landmark_ids: ["upper-jaw", "lower-jaw"],
            }),
          ],
        }),
      ),
    );
  });

  it("rejects invalid thresholds and never offers confirmation for partial cycles", async () => {
    renderPanel();
    await screen.findByText("Gape distance time series");

    fireEvent.change(screen.getByLabelText("Open threshold"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Detect cycles" }));
    expect(
      await screen.findByText(
        "Open threshold must be greater than close threshold",
      ),
    ).toBeInTheDocument();
    expect(movementApi.createEventRun).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Event candidate"), {
      target: { value: "event-2" },
    });
    expect(
      screen.getByRole("button", { name: "Confirm complete" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Partial or unreviewed cycles are never reported/),
    ).toBeInTheDocument();
  });
});
