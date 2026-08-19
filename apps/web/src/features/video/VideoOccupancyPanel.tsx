import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { getVideoTracks, getVideos } from "./videoApi";
import { getVideoOccupancy } from "./videoOccupancyApi";
import {
  occupancyCellsCsv,
  occupancyReportJson,
  occupancyTracksCsv,
} from "./videoOccupancyReport";

interface VideoOccupancyPanelProps {
  project: Project;
}

type CopiedOccupancyReport = "json" | "cells_csv" | "tracks_csv" | null;

function toggleSelection(
  current: string[],
  value: string,
  checked: boolean,
): string[] {
  if (checked) return current.includes(value) ? current : [...current, value];
  return current.filter((item) => item !== value);
}

export function VideoOccupancyPanel({ project }: VideoOccupancyPanelProps) {
  const [videoId, setVideoId] = useState("");
  const [trackIds, setTrackIds] = useState<string[]>([]);
  const [gridRows, setGridRows] = useState(3);
  const [gridColumns, setGridColumns] = useState(3);
  const [startFrame, setStartFrame] = useState(0);
  const [endFrame, setEndFrame] = useState(0);
  const [copiedReport, setCopiedReport] = useState<CopiedOccupancyReport>(null);

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

  useEffect(() => {
    if (!videoId && videosQuery.data?.[0]) setVideoId(videosQuery.data[0].id);
  }, [videoId, videosQuery.data]);

  useEffect(() => {
    setTrackIds([]);
    setStartFrame(0);
    setEndFrame(Math.max(0, (selectedVideo?.frame_count ?? 1) - 1));
    setCopiedReport(null);
  }, [videoId, selectedVideo?.frame_count]);

  const classNames = useMemo(
    () => new Map(project.label_classes.map((item) => [item.id, item.name])),
    [project.label_classes],
  );

  const occupancyMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (trackIds.length === 0) throw new Error("Select at least one track");
      if (
        gridRows < 1 ||
        gridRows > 50 ||
        gridColumns < 1 ||
        gridColumns > 50
      ) {
        throw new Error("Occupancy grid dimensions must be between 1 and 50");
      }
      if (endFrame < startFrame) {
        throw new Error(
          "Occupancy end frame must be at or after the start frame",
        );
      }
      return getVideoOccupancy(videoId, {
        track_ids: trackIds,
        grid_rows: gridRows,
        grid_columns: gridColumns,
        start_frame: startFrame,
        end_frame: endFrame,
      });
    },
    onSuccess: () => setCopiedReport(null),
  });

  async function copyReport(kind: Exclude<CopiedOccupancyReport, null>) {
    const report = occupancyMutation.data;
    if (!report) return;
    const content =
      kind === "json"
        ? occupancyReportJson(report)
        : kind === "cells_csv"
          ? occupancyCellsCsv(report)
          : occupancyTracksCsv(report);
    await navigator.clipboard.writeText(content);
    setCopiedReport(kind);
  }

  const error =
    videosQuery.error ?? tracksQuery.error ?? occupancyMutation.error;

  return (
    <section className="management-card" data-testid="video-occupancy-panel">
      <p className="eyebrow">Space use</p>
      <h3>Occupancy analysis</h3>
      <p className="annotation-helper">
        Divide the image plane into a configurable grid and summarize fish-frame
        observations, occupied-frame frequency, unique tracks, and dwell time
        per cell. Each interpolated track-frame contributes one occupancy
        observation.
      </p>
      <label>
        Video
        <select
          value={videoId}
          onChange={(event) => setVideoId(event.target.value)}
        >
          {(videosQuery.data ?? []).map((video) => (
            <option key={video.id} value={video.id}>
              {video.original_filename}
            </option>
          ))}
        </select>
      </label>
      <div className="annotation-selection-list">
        {(tracksQuery.data ?? []).map((track) => (
          <label key={track.id} className="annotation-selection-row">
            <input
              type="checkbox"
              checked={trackIds.includes(track.id)}
              onChange={(event) =>
                setTrackIds((current) =>
                  toggleSelection(current, track.id, event.target.checked),
                )
              }
            />
            <span>
              Track {track.track_number} —{" "}
              {classNames.get(track.label_class_id) ?? "Unknown class"}
            </span>
          </label>
        ))}
      </div>
      <label>
        Grid rows
        <input
          type="number"
          min={1}
          max={50}
          value={gridRows}
          onChange={(event) => setGridRows(Number(event.target.value))}
        />
      </label>
      <label>
        Grid columns
        <input
          type="number"
          min={1}
          max={50}
          value={gridColumns}
          onChange={(event) => setGridColumns(Number(event.target.value))}
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
        disabled={occupancyMutation.isPending || trackIds.length === 0}
        onClick={() => occupancyMutation.mutate()}
      >
        {occupancyMutation.isPending ? "Calculating..." : "Calculate occupancy"}
      </button>

      {occupancyMutation.data && (
        <>
          <div className="annotation-selection-list">
            <div className="annotation-selection-row">
              <strong>Frames with selected tracks</strong>
              <span>{occupancyMutation.data.frames_with_tracks}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Track-frame observations</strong>
              <span>{occupancyMutation.data.track_frame_observations}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Total fish-seconds</strong>
              <span>
                {occupancyMutation.data.total_track_seconds.toFixed(3)} s
              </span>
            </div>
          </div>
          <div className="annotation-editor-inline-actions">
            <button
              type="button"
              className="secondary"
              onClick={() => void copyReport("json")}
            >
              {copiedReport === "json" ? "JSON copied" : "Copy occupancy JSON"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void copyReport("cells_csv")}
            >
              {copiedReport === "cells_csv"
                ? "Cell CSV copied"
                : "Copy cell CSV"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void copyReport("tracks_csv")}
            >
              {copiedReport === "tracks_csv"
                ? "Track CSV copied"
                : "Copy track CSV"}
            </button>
          </div>
          <details>
            <summary>Grid cells</summary>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Cell</th>
                    <th>Observations</th>
                    <th>Observation %</th>
                    <th>Occupied frames</th>
                    <th>Tracks</th>
                    <th>Dwell</th>
                  </tr>
                </thead>
                <tbody>
                  {occupancyMutation.data.cells.map((cell) => (
                    <tr key={`${cell.row}-${cell.column}`}>
                      <td>
                        r{cell.row + 1} c{cell.column + 1}
                      </td>
                      <td>{cell.observation_count}</td>
                      <td>{(cell.observation_fraction * 100).toFixed(1)}%</td>
                      <td>
                        {cell.occupied_frame_count} (
                        {(cell.occupied_frame_fraction * 100).toFixed(1)}%)
                      </td>
                      <td>{cell.unique_track_count}</td>
                      <td>{cell.dwell_seconds.toFixed(3)} s</td>
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
