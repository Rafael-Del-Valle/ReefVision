import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VideoWorkspaceContext } from "../../features/video/videoWorkspaceBridge";
import { ProjectVideoPoseInspector } from "./ProjectVideoPoseInspector";

const context: VideoWorkspaceContext = {
  projectId: "project-1",
  videos: [
    {
      id: "video-1",
      filename: "jellyfish.mp4",
      status: "frames_ready",
      frameCount: 300,
      fps: 30,
      durationSeconds: 10,
    },
    {
      id: "video-2",
      filename: "jellyfish-2.mp4",
      status: "ready",
      frameCount: 600,
      fps: 60,
      durationSeconds: 10,
    },
  ],

  selectedVideoId: "video-1",
  selectedVideoFilename: "jellyfish.mp4",
  selectedVideoStatus: "frames_ready",

  frameIndex: 30,
  frameCount: 300,
  fps: 30,
  durationSeconds: 10,

  tracks: [
    {
      id: "track-7",
      trackNumber: 7,
      status: "machine_generated",
      source: "machine",
      hasPose: true,
      keyframeCount: 3,
    },
    {
      id: "track-8",
      trackNumber: 8,
      status: "verified",
      source: "manual",
      hasPose: false,
      keyframeCount: 2,
    },
  ],

  selectedTrackId: "track-7",
  selectedTrackNumber: 7,
  selectedTrackStatus: "machine_generated",
  selectedTrackSource: "machine",
  selectedTrackHasPose: true,
  selectedTrackKeyframeFrames: [10, 30, 60],

  poseGroups: [
    { name: "bell_center", count: 1 },
    { name: "tentacle", count: 8 },
  ],

  currentPoseObservationCount: 9,
  currentPoseVisibleCount: 7,
  currentPoseMeanConfidence: 0.842,

  activeTrackingRunCount: 1,
  latestTrackingRunStatus: "running",
  latestTrackingRunStage: "tracking",
};

function renderInspector(
  overrides: Partial<{
    context: VideoWorkspaceContext | null;
    onSelectVideo: (videoId: string) => void;
    onSeekFrame: (frameIndex: number) => void;
    onSelectTrack: (trackId: string) => void;
  }> = {},
) {
  const props = {
    context,
    onSelectVideo: vi.fn(),
    onSeekFrame: vi.fn(),
    onSelectTrack: vi.fn(),
    ...overrides,
  };

  render(<ProjectVideoPoseInspector {...props} />);

  return props;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProjectVideoPoseInspector", () => {
  it("shows canonical video timeline, track, and pose context", () => {
    renderInspector();

    expect(screen.getByText("jellyfish.mp4")).toBeInTheDocument();
    expect(screen.getByText("300 frames · 30.000 fps")).toBeInTheDocument();
    expect(screen.getByText("00:01.000 / 00:10.000")).toBeInTheDocument();
    expect(screen.getByText("30 / 299")).toBeInTheDocument();

    expect(screen.getByText("Track 7")).toBeInTheDocument();
    expect(screen.getByText("machine generated")).toBeInTheDocument();

    expect(screen.getByText("bell_center × 1")).toBeInTheDocument();
    expect(screen.getByText("tentacle × 8")).toBeInTheDocument();

    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("0.842")).toBeInTheDocument();

    expect(screen.getByText("1 tracking active")).toBeInTheDocument();
  });

  it("sends frame navigation back to the canonical video workspace", async () => {
    const handlers = renderInspector();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Next frame",
      }),
    );

    expect(handlers.onSeekFrame).toHaveBeenCalledWith(31);

    await userEvent
      .clear(
        screen.getByRole("slider", {
          name: "Video frame timeline",
        }),
      )
      .catch(() => undefined);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Previous frame",
      }),
    );

    expect(handlers.onSeekFrame).toHaveBeenCalledWith(29);
  });

  it("jumps between pose keyframes and changes track through bridge commands", async () => {
    const handlers = renderInspector();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Previous pose keyframe",
      }),
    );

    expect(handlers.onSeekFrame).toHaveBeenCalledWith(10);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Next pose keyframe",
      }),
    );

    expect(handlers.onSeekFrame).toHaveBeenCalledWith(60);

    await userEvent.selectOptions(
      screen.getByLabelText("Track / identity"),
      "track-8",
    );

    expect(handlers.onSelectTrack).toHaveBeenCalledWith("track-8");

    await userEvent.selectOptions(
      screen.getByLabelText("Managed video"),
      "video-2",
    );

    expect(handlers.onSelectVideo).toHaveBeenCalledWith("video-2");
  });

  it("does not invent temporal state when no video is active", () => {
    renderInspector({ context: null });

    expect(screen.getByText("Select or import a video")).toBeInTheDocument();

    expect(
      screen.queryByRole("slider", {
        name: "Video frame timeline",
      }),
    ).not.toBeInTheDocument();
  });
});
