export interface VideoWorkspaceVideoOption {
  id: string;
  filename: string;
  status: string;
  frameCount: number;
  fps: number;
  durationSeconds: number;
}

export type VideoWorkspaceTrackSource = "manual" | "machine" | "imported";

export interface VideoWorkspaceTrackOption {
  id: string;
  trackNumber: number;
  status: string;
  source: VideoWorkspaceTrackSource;
  hasPose: boolean;
  keyframeCount: number;
}

export interface VideoWorkspacePoseGroup {
  name: string;
  count: number;
}

export interface VideoWorkspaceContext {
  projectId: string;
  videos: VideoWorkspaceVideoOption[];

  selectedVideoId: string | null;
  selectedVideoFilename: string | null;
  selectedVideoStatus: string | null;

  frameIndex: number;
  frameCount: number;
  fps: number;
  durationSeconds: number;

  tracks: VideoWorkspaceTrackOption[];

  selectedTrackId: string | null;
  selectedTrackNumber: number | null;
  selectedTrackStatus: string | null;
  selectedTrackSource: VideoWorkspaceTrackSource | null;
  selectedTrackHasPose: boolean;
  selectedTrackKeyframeFrames: number[];

  poseGroups: VideoWorkspacePoseGroup[];
  currentPoseObservationCount: number;
  currentPoseVisibleCount: number;
  currentPoseMeanConfidence: number | null;

  activeTrackingRunCount: number;
  latestTrackingRunStatus: string | null;
  latestTrackingRunStage: string | null;
}

export type VideoWorkspaceCommand =
  | {
      id: number;
      type: "select_video";
      videoId: string;
    }
  | {
      id: number;
      type: "seek_frame";
      frameIndex: number;
    }
  | {
      id: number;
      type: "select_track";
      trackId: string;
    };
