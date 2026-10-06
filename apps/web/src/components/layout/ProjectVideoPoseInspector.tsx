import type {
  VideoWorkspaceContext,
  VideoWorkspaceTrackOption,
} from "../../features/video/videoWorkspaceBridge";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "00:00.000";
  }

  const minutes = Math.floor(seconds / 60);
  const remaining = seconds - minutes * 60;

  return `${String(minutes).padStart(2, "0")}:${remaining
    .toFixed(3)
    .padStart(6, "0")}`;
}

function trackLabel(track: VideoWorkspaceTrackOption): string {
  const pose = track.hasPose ? " · pose" : "";
  return `Track ${track.trackNumber} · ${track.status}${pose}`;
}

function previousKeyframe(
  frames: number[],
  currentFrame: number,
): number | null {
  const previous = frames.filter((frame) => frame < currentFrame);
  return previous.length > 0 ? previous[previous.length - 1] : null;
}

function nextKeyframe(frames: number[], currentFrame: number): number | null {
  return frames.find((frame) => frame > currentFrame) ?? null;
}

export function ProjectVideoPoseInspector({
  context,
  onSelectVideo,
  onSeekFrame,
  onSelectTrack,
}: {
  context: VideoWorkspaceContext | null;
  onSelectVideo: (videoId: string) => void;
  onSeekFrame: (frameIndex: number) => void;
  onSelectTrack: (trackId: string) => void;
}) {
  if (!context || !context.selectedVideoId) {
    return (
      <section
        className="rv-inspector-card rv-video-pose-inspector"
        aria-label="Video timeline and pose controls"
      >
        <div className="rv-inspector-card-heading">
          <strong>Video timeline & pose</strong>
          <span>No video selected</span>
        </div>

        <div className="rv-inspector-empty-control">
          <strong>Select or import a video</strong>
          <p>
            The canonical Video & Tracking workspace owns media selection,
            tracking, pose editing, behavior analysis, and scientific exports.
          </p>
        </div>
      </section>
    );
  }

  const maximumFrame = Math.max(0, context.frameCount - 1);
  const frameTime = context.fps > 0 ? context.frameIndex / context.fps : 0;

  const previousPoseFrame = previousKeyframe(
    context.selectedTrackKeyframeFrames,
    context.frameIndex,
  );

  const nextPoseFrame = nextKeyframe(
    context.selectedTrackKeyframeFrames,
    context.frameIndex,
  );

  const selectedTrack =
    context.tracks.find((track) => track.id === context.selectedTrackId) ??
    null;

  return (
    <section
      className="rv-inspector-card rv-video-pose-inspector"
      aria-label="Video timeline and pose controls"
    >
      <div className="rv-inspector-card-heading">
        <strong>Video timeline & pose</strong>
        <span>
          {context.activeTrackingRunCount > 0
            ? `${context.activeTrackingRunCount} tracking active`
            : "Review controls"}
        </span>
      </div>

      <p>
        Timeline and track selection mirror the canonical Video & Tracking
        workspace. Pose identity, corrections, temporal review, behavior, and
        visualization remain owned by that workspace.
      </p>

      {context.videos.length > 1 && (
        <label>
          Managed video
          <select
            aria-label="Managed video"
            value={context.selectedVideoId}
            onChange={(event) => onSelectVideo(event.target.value)}
          >
            {context.videos.map((video) => (
              <option key={video.id} value={video.id}>
                {video.filename} · {video.status}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="rv-video-inspector-summary">
        <strong>{context.selectedVideoFilename}</strong>
        <span>
          {context.frameCount.toLocaleString()} frames ·{" "}
          {context.fps.toFixed(3)} fps
        </span>
        <span>
          {formatTime(frameTime)} / {formatTime(context.durationSeconds)}
        </span>
      </div>

      <div className="rv-video-timeline">
        <div>
          <span>Frame</span>
          <strong>
            {context.frameIndex} / {maximumFrame}
          </strong>
        </div>

        <input
          type="range"
          aria-label="Video frame timeline"
          min={0}
          max={maximumFrame}
          step={1}
          value={Math.min(context.frameIndex, maximumFrame)}
          onChange={(event) => onSeekFrame(Number(event.target.value))}
        />

        <div className="rv-video-timeline-actions">
          <button
            type="button"
            className="secondary"
            disabled={context.frameIndex <= 0}
            onClick={() => onSeekFrame(context.frameIndex - 1)}
          >
            Previous frame
          </button>

          <button
            type="button"
            className="secondary"
            disabled={context.frameIndex >= maximumFrame}
            onClick={() => onSeekFrame(context.frameIndex + 1)}
          >
            Next frame
          </button>
        </div>
      </div>

      <div className="rv-video-tracking-state">
        <div>
          <span>Latest tracking run</span>
          <strong>
            {context.latestTrackingRunStatus
              ? context.latestTrackingRunStatus.replaceAll("_", " ")
              : "None"}
          </strong>
        </div>

        {context.latestTrackingRunStage && (
          <div>
            <span>Stage</span>
            <strong>
              {context.latestTrackingRunStage.replaceAll("_", " ")}
            </strong>
          </div>
        )}
      </div>

      <label>
        Track / identity
        <select
          aria-label="Track / identity"
          value={context.selectedTrackId ?? ""}
          onChange={(event) => onSelectTrack(event.target.value)}
        >
          <option value="">No track selected</option>

          {context.tracks.map((track) => (
            <option key={track.id} value={track.id}>
              {trackLabel(track)}
            </option>
          ))}
        </select>
      </label>

      {selectedTrack ? (
        <>
          <div className="rv-video-track-summary">
            <div>
              <span>Identity</span>
              <strong>Track {selectedTrack.trackNumber}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{selectedTrack.status.replaceAll("_", " ")}</strong>
            </div>
            <div>
              <span>Source</span>
              <strong>{selectedTrack.source}</strong>
            </div>
            <div>
              <span>Keyframes</span>
              <strong>{selectedTrack.keyframeCount}</strong>
            </div>
          </div>

          {context.selectedTrackHasPose ? (
            <div className="rv-pose-inspector-section">
              <div className="rv-pose-inspector-heading">
                <strong>Pose identity</strong>
                <span>Canonical pose schema</span>
              </div>

              <div className="rv-pose-schema-chips">
                {context.poseGroups.map((group) => (
                  <span key={group.name}>
                    {group.name} × {group.count}
                  </span>
                ))}
              </div>

              <div className="rv-pose-frame-summary">
                <div>
                  <span>Landmarks on frame</span>
                  <strong>{context.currentPoseObservationCount}</strong>
                </div>
                <div>
                  <span>Visible / uncertain</span>
                  <strong>{context.currentPoseVisibleCount}</strong>
                </div>
                <div>
                  <span>Mean confidence</span>
                  <strong>
                    {context.currentPoseMeanConfidence === null
                      ? "—"
                      : context.currentPoseMeanConfidence.toFixed(3)}
                  </strong>
                </div>
              </div>

              <div className="rv-video-timeline-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={previousPoseFrame === null}
                  onClick={() => {
                    if (previousPoseFrame !== null) {
                      onSeekFrame(previousPoseFrame);
                    }
                  }}
                >
                  Previous pose keyframe
                </button>

                <button
                  type="button"
                  className="secondary"
                  disabled={nextPoseFrame === null}
                  onClick={() => {
                    if (nextPoseFrame !== null) {
                      onSeekFrame(nextPoseFrame);
                    }
                  }}
                >
                  Next pose keyframe
                </button>
              </div>

              <p className="annotation-helper">
                Use the central Pose Annotation Editor for landmark corrections,
                repeated-landmark identity, occlusion state, verification, and
                persisted track revisions.
              </p>
            </div>
          ) : (
            <div className="rv-inspector-empty-control">
              <strong>Selected track has no pose schema</strong>
              <p>
                Object-track timeline controls remain available. Select a
                canonical pose track to expose landmark/keyframe navigation.
              </p>
            </div>
          )}
        </>
      ) : (
        <div className="rv-inspector-empty-control">
          <strong>No identity selected</strong>
          <p>
            Choose a persisted track to inspect track status and pose keyframes.
          </p>
        </div>
      )}

      <div className="rv-inference-boundary">
        <strong>Temporal scientific boundary</strong>
        <p>
          Timeline navigation changes presentation only. Automated tracks, model
          landmarks, pose associations, and behavior classifications remain
          reviewable evidence until explicitly verified or corrected.
        </p>
      </div>
    </section>
  );
}
