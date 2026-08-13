import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { getVideoTracks, getVideos } from "./videoApi";
import { getVideoTrackActivity } from "./videoActivityApi";
import { getVideoCalibration } from "./videoScienceApi";

interface VideoActivityPanelProps {
  project: Project;
}

export function VideoActivityPanel({ project }: VideoActivityPanelProps) {
  const [videoId, setVideoId] = useState("");
  const [trackId, setTrackId] = useState("");
  const [speedThreshold, setSpeedThreshold] = useState(1);
  const [minimumBoutSeconds, setMinimumBoutSeconds] = useState(0);
  const [startFrame, setStartFrame] = useState(0);
  const [endFrame, setEndFrame] = useState(0);

  const videosQuery = useQuery({
    queryKey: ["videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
  });
  const selectedVideo = videosQuery.data?.find((video) => video.id === videoId);
  const tracksQuery = useQuery({
    queryKey: ["video-tracks", videoId],
    queryFn: ({ signal }) => getVideoTracks(videoId, signal),
    enabled: Boolean(videoId),
  });
  const calibrationQuery = useQuery({
    queryKey: ["video-calibration", videoId],
    queryFn: ({ signal }) => getVideoCalibration(videoId, signal),
    enabled: Boolean(videoId),
  });

  useEffect(() => {
    if (!videoId && videosQuery.data?.[0]) setVideoId(videosQuery.data[0].id);
  }, [videoId, videosQuery.data]);

  useEffect(() => {
    setTrackId("");
    setStartFrame(0);
    setEndFrame(Math.max(0, (selectedVideo?.frame_count ?? 1) - 1));
  }, [videoId, selectedVideo?.frame_count]);

  const classNames = useMemo(
    () => new Map(project.label_classes.map((item) => [item.id, item.name])),
    [project.label_classes],
  );

  const activityMutation = useMutation({
    mutationFn: () => {
      if (!trackId) throw new Error("Select a track first");
      if (!calibrationQuery.data) {
        throw new Error("Set a spatial calibration before activity analysis");
      }
      if (speedThreshold < 0 || minimumBoutSeconds < 0) {
        throw new Error("Activity thresholds cannot be negative");
      }
      if (endFrame <= startFrame) {
        throw new Error("Activity end frame must be after the start frame");
      }
      return getVideoTrackActivity(trackId, {
        speed_threshold_per_second: speedThreshold,
        start_frame: startFrame,
        end_frame: endFrame,
        minimum_active_bout_seconds: minimumBoutSeconds,
      });
    },
  });

  const error =
    videosQuery.error ??
    tracksQuery.error ??
    calibrationQuery.error ??
    activityMutation.error;

  return (
    <section className="management-card" data-testid="video-activity-panel">
      <p className="eyebrow">Behavior</p>
      <h3>Activity and movement bouts</h3>
      <p className="annotation-helper">
        Classify calibrated trajectory intervals as active or resting using a physical
        speed threshold. Short active bursts can be suppressed with a minimum bout
        duration before activity fraction and bout statistics are summarized.
      </p>
      <label>
        Video
        <select value={videoId} onChange={(event) => setVideoId(event.target.value)}>
          {(videosQuery.data ?? []).map((video) => (
            <option key={video.id} value={video.id}>
              {video.original_filename}
            </option>
          ))}
        </select>
      </label>
      <label>
        Track
        <select value={trackId} onChange={(event) => setTrackId(event.target.value)}>
          <option value="">Select a track</option>
          {(tracksQuery.data ?? []).map((track) => (
            <option key={track.id} value={track.id}>
              Track {track.track_number} — {classNames.get(track.label_class_id) ?? "Unknown class"}
            </option>
          ))}
        </select>
      </label>
      {calibrationQuery.data ? (
        <p className="annotation-helper">
          Threshold unit: {calibrationQuery.data.unit}/s. Current scale:{" "}
          {calibrationQuery.data.pixels_per_unit.toFixed(4)} px/
          {calibrationQuery.data.unit}.
        </p>
      ) : (
        <p className="annotation-helper">
          Save a spatial calibration in the Video science panel before calculating
          physical activity metrics.
        </p>
      )}
      <label>
        Active speed threshold ({calibrationQuery.data?.unit ?? "unit"}/s)
        <input
          type="number"
          min={0}
          step="any"
          value={speedThreshold}
          onChange={(event) => setSpeedThreshold(Number(event.target.value))}
        />
      </label>
      <label>
        Minimum active bout duration (s)
        <input
          type="number"
          min={0}
          step="any"
          value={minimumBoutSeconds}
          onChange={(event) => setMinimumBoutSeconds(Number(event.target.value))}
        />
      </label>
      <label>
        Start frame
        <input
          type="number"
          min={0}
          max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
          value={startFrame}
          onChange={(event) => setStartFrame(Number(event.target.value))}
        />
      </label>
      <label>
        End frame
        <input
          type="number"
          min={0}
          max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
          value={endFrame}
          onChange={(event) => setEndFrame(Number(event.target.value))}
        />
      </label>
      <button
        type="button"
        disabled={activityMutation.isPending || !trackId || !calibrationQuery.data}
        onClick={() => activityMutation.mutate()}
      >
        {activityMutation.isPending ? "Calculating..." : "Calculate activity"}
      </button>

      {activityMutation.data && (
        <>
          <div className="annotation-selection-list">
            <div className="annotation-selection-row">
              <strong>Active fraction</strong>
              <span>{(activityMutation.data.active_fraction * 100).toFixed(1)}%</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Active / rest time</strong>
              <span>
                {activityMutation.data.active_seconds.toFixed(3)} s /{" "}
                {activityMutation.data.rest_seconds.toFixed(3)} s
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Active bouts</strong>
              <span>{activityMutation.data.active_bout_count}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Mean active bout</strong>
              <span>
                {activityMutation.data.mean_active_bout_seconds === null
                  ? "—"
                  : `${activityMutation.data.mean_active_bout_seconds.toFixed(3)} s`}
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Maximum active bout</strong>
              <span>
                {activityMutation.data.maximum_active_bout_seconds === null
                  ? "—"
                  : `${activityMutation.data.maximum_active_bout_seconds.toFixed(3)} s`}
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Mean active speed</strong>
              <span>
                {activityMutation.data.mean_active_speed_per_second === null
                  ? "—"
                  : `${activityMutation.data.mean_active_speed_per_second.toFixed(3)} ${activityMutation.data.distance_unit}/s`}
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Maximum speed</strong>
              <span>
                {activityMutation.data.maximum_speed_per_second === null
                  ? "—"
                  : `${activityMutation.data.maximum_speed_per_second.toFixed(3)} ${activityMutation.data.distance_unit}/s`}
              </span>
            </div>
          </div>
          <details>
            <summary>Bout details</summary>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>State</th>
                    <th>Frames</th>
                    <th>Duration</th>
                    <th>Intervals</th>
                  </tr>
                </thead>
                <tbody>
                  {activityMutation.data.bouts.map((bout, index) => (
                    <tr key={`${bout.state}-${bout.start_frame}-${index}`}>
                      <td>{bout.state}</td>
                      <td>
                        {bout.start_frame}–{bout.end_frame}
                      </td>
                      <td>{bout.duration_seconds.toFixed(3)} s</td>
                      <td>{bout.interval_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
