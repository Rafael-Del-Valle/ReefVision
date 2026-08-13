import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { getVideoTracks, getVideos } from "./videoApi";
import {
  clearVideoCalibration,
  getCalibratedTrackAnalytics,
  getSchoolingAnalytics,
  getVideoCalibration,
  setVideoCalibration,
  type VideoDistanceUnit,
} from "./videoScienceApi";

interface VideoSciencePanelProps {
  project: Project;
}

function toggleSelection(current: string[], value: string, checked: boolean): string[] {
  if (checked) return current.includes(value) ? current : [...current, value];
  return current.filter((item) => item !== value);
}

export function VideoSciencePanel({ project }: VideoSciencePanelProps) {
  const queryClient = useQueryClient();
  const [videoId, setVideoId] = useState("");
  const [unit, setUnit] = useState<VideoDistanceUnit>("cm");
  const [referenceDistance, setReferenceDistance] = useState(10);
  const [referencePixels, setReferencePixels] = useState(100);
  const [method, setMethod] = useState("known_length");
  const [referenceLabel, setReferenceLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [selectedTrackId, setSelectedTrackId] = useState("");
  const [schoolTrackIds, setSchoolTrackIds] = useState<string[]>([]);
  const [schoolStartFrame, setSchoolStartFrame] = useState(0);
  const [schoolEndFrame, setSchoolEndFrame] = useState(0);

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
  const calibratedTrackQuery = useQuery({
    queryKey: ["video-calibrated-track", selectedTrackId],
    queryFn: ({ signal }) => getCalibratedTrackAnalytics(selectedTrackId, signal),
    enabled: Boolean(selectedTrackId && calibrationQuery.data),
  });

  useEffect(() => {
    if (!videoId && videosQuery.data?.[0]) {
      setVideoId(videosQuery.data[0].id);
    }
  }, [videoId, videosQuery.data]);

  useEffect(() => {
    setSelectedTrackId("");
    setSchoolTrackIds([]);
    setSchoolStartFrame(0);
    setSchoolEndFrame(Math.max(0, (selectedVideo?.frame_count ?? 1) - 1));
  }, [videoId, selectedVideo?.frame_count]);

  useEffect(() => {
    const calibration = calibrationQuery.data;
    if (!calibration) return;
    setUnit(calibration.unit);
    setReferenceDistance(calibration.reference_distance);
    setReferencePixels(calibration.reference_pixels);
    setMethod(calibration.method);
    setReferenceLabel(calibration.reference_label ?? "");
    setNotes(calibration.notes ?? "");
  }, [calibrationQuery.data]);

  const calibrationMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (referenceDistance <= 0 || referencePixels <= 0) {
        throw new Error("Reference distance and pixels must both be positive");
      }
      return setVideoCalibration(videoId, {
        unit,
        reference_distance: referenceDistance,
        reference_pixels: referencePixels,
        method: method.trim() || "known_length",
        reference_label: referenceLabel.trim() || null,
        notes: notes.trim() || null,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["video-calibration", videoId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["video-calibrated-track"],
      });
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => clearVideoCalibration(videoId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["video-calibration", videoId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["video-calibrated-track"],
      });
    },
  });

  const schoolingMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (!calibrationQuery.data) {
        throw new Error("Set a spatial calibration before schooling analysis");
      }
      if (schoolTrackIds.length < 2) {
        throw new Error("Select at least two tracks for schooling analysis");
      }
      if (schoolEndFrame < schoolStartFrame) {
        throw new Error("Schooling end frame must be at or after the start frame");
      }
      return getSchoolingAnalytics(videoId, {
        track_ids: schoolTrackIds,
        start_frame: schoolStartFrame,
        end_frame: schoolEndFrame,
      });
    },
  });

  const classNames = useMemo(
    () => new Map(project.label_classes.map((item) => [item.id, item.name])),
    [project.label_classes],
  );
  const error =
    videosQuery.error ??
    tracksQuery.error ??
    calibrationQuery.error ??
    calibratedTrackQuery.error ??
    calibrationMutation.error ??
    clearMutation.error ??
    schoolingMutation.error;

  return (
    <section className="management-card" data-testid="video-science-panel">
      <p className="eyebrow">Video science</p>
      <h3>Calibration and schooling metrics</h3>
      <p className="annotation-helper">
        Convert pixel trajectories into physical distance and speed with a known-length
        calibration, then summarize group spacing, nearest-neighbor distance, centroid
        spread, movement speed, and polarization.
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

      <h4>Spatial calibration</h4>
      <div className="annotation-selection-list">
        <label>
          Physical unit
          <select
            value={unit}
            onChange={(event) => setUnit(event.target.value as VideoDistanceUnit)}
          >
            <option value="mm">Millimeters</option>
            <option value="cm">Centimeters</option>
            <option value="m">Meters</option>
          </select>
        </label>
        <label>
          Known reference distance
          <input
            type="number"
            min={0.000001}
            step="any"
            value={referenceDistance}
            onChange={(event) => setReferenceDistance(Number(event.target.value))}
          />
        </label>
        <label>
          Reference length in pixels
          <input
            type="number"
            min={0.000001}
            step="any"
            value={referencePixels}
            onChange={(event) => setReferencePixels(Number(event.target.value))}
          />
        </label>
        <label>
          Calibration method
          <input value={method} onChange={(event) => setMethod(event.target.value)} />
        </label>
        <label>
          Reference label
          <input
            value={referenceLabel}
            onChange={(event) => setReferenceLabel(event.target.value)}
            placeholder="e.g. 10 cm tank ruler"
          />
        </label>
        <label>
          Notes
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
        </label>
      </div>
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          disabled={!videoId || calibrationMutation.isPending}
          onClick={() => calibrationMutation.mutate()}
        >
          {calibrationMutation.isPending ? "Saving..." : "Save calibration"}
        </button>
        <button
          type="button"
          className="danger-ghost"
          disabled={!videoId || !calibrationQuery.data || clearMutation.isPending}
          onClick={() => clearMutation.mutate()}
        >
          Clear calibration
        </button>
      </div>
      {calibrationQuery.data && (
        <p className="annotation-helper">
          Scale: {calibrationQuery.data.pixels_per_unit.toFixed(4)} px/
          {calibrationQuery.data.unit} ({calibrationQuery.data.units_per_pixel.toFixed(6)}{" "}
          {calibrationQuery.data.unit}/px), video revision {calibrationQuery.data.video_revision}.
        </p>
      )}

      <h4>Calibrated track metrics</h4>
      <label>
        Track
        <select
          value={selectedTrackId}
          onChange={(event) => setSelectedTrackId(event.target.value)}
        >
          <option value="">Select a track</option>
          {(tracksQuery.data ?? []).map((track) => (
            <option key={track.id} value={track.id}>
              Track {track.track_number} — {classNames.get(track.label_class_id) ?? "Unknown class"}
            </option>
          ))}
        </select>
      </label>
      {calibratedTrackQuery.data && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Path length</strong>
            <span>
              {calibratedTrackQuery.data.path_length.toFixed(3)}{" "}
              {calibratedTrackQuery.data.distance_unit}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean speed</strong>
            <span>
              {calibratedTrackQuery.data.mean_speed_per_second.toFixed(3)}{" "}
              {calibratedTrackQuery.data.distance_unit}/s
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Maximum speed</strong>
            <span>
              {calibratedTrackQuery.data.maximum_speed_per_second.toFixed(3)}{" "}
              {calibratedTrackQuery.data.distance_unit}/s
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Displacement</strong>
            <span>
              {calibratedTrackQuery.data.displacement.toFixed(3)}{" "}
              {calibratedTrackQuery.data.distance_unit}
            </span>
          </div>
        </div>
      )}

      <h4>Group schooling analysis</h4>
      <p className="annotation-helper">
        Polarization ranges from 0 (headings cancel) to 1 (fully aligned movement).
        Distances and speeds use the saved video calibration.
      </p>
      <div className="annotation-selection-list">
        {(tracksQuery.data ?? []).map((track) => (
          <label key={track.id} className="annotation-selection-row">
            <input
              type="checkbox"
              checked={schoolTrackIds.includes(track.id)}
              onChange={(event) =>
                setSchoolTrackIds((current) =>
                  toggleSelection(current, track.id, event.target.checked),
                )
              }
            />
            <span>
              Track {track.track_number} — {classNames.get(track.label_class_id) ?? "Unknown class"}
            </span>
          </label>
        ))}
      </div>
      <label>
        Start frame
        <input
          type="number"
          min={0}
          max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
          value={schoolStartFrame}
          onChange={(event) => setSchoolStartFrame(Number(event.target.value))}
        />
      </label>
      <label>
        End frame
        <input
          type="number"
          min={0}
          max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
          value={schoolEndFrame}
          onChange={(event) => setSchoolEndFrame(Number(event.target.value))}
        />
      </label>
      <button
        type="button"
        disabled={
          schoolingMutation.isPending ||
          schoolTrackIds.length < 2 ||
          !calibrationQuery.data
        }
        onClick={() => schoolingMutation.mutate()}
      >
        {schoolingMutation.isPending ? "Calculating..." : "Calculate schooling metrics"}
      </button>
      {schoolingMutation.data && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Frames evaluated</strong>
            <span>{schoolingMutation.data.frames_evaluated}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean group size</strong>
            <span>{schoolingMutation.data.mean_group_size.toFixed(2)}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean pairwise distance</strong>
            <span>
              {schoolingMutation.data.mean_pairwise_distance.toFixed(3)}{" "}
              {schoolingMutation.data.distance_unit}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean nearest-neighbor distance</strong>
            <span>
              {schoolingMutation.data.mean_nearest_neighbor_distance.toFixed(3)}{" "}
              {schoolingMutation.data.distance_unit}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean centroid spread</strong>
            <span>
              {schoolingMutation.data.mean_distance_to_centroid.toFixed(3)}{" "}
              {schoolingMutation.data.distance_unit}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean speed</strong>
            <span>
              {schoolingMutation.data.mean_speed_per_second === null
                ? "—"
                : `${schoolingMutation.data.mean_speed_per_second.toFixed(3)} ${schoolingMutation.data.distance_unit}/s`}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean polarization</strong>
            <span>
              {schoolingMutation.data.mean_polarization === null
                ? "—"
                : schoolingMutation.data.mean_polarization.toFixed(3)}
            </span>
          </div>
        </div>
      )}
      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
