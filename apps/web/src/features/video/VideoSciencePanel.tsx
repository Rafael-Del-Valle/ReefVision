import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { AutomaticScientific3DPanel } from "./AutomaticScientific3DPanel";
import { getVideoTracks, getVideos } from "./videoApi";
import {
  clearVideoCalibration,
  clearVideoCameraIntrinsics,
  getCalibratedTrackAnalytics,
  getDepthTrackAnalytics,
  getSchoolingAnalytics,
  getVideoCalibration,
  getVideoCameraIntrinsics,
  setVideoCalibration,
  setVideoCameraIntrinsics,
  type VideoDepthSample,
  type VideoDistanceUnit,
} from "./videoScienceApi";

interface VideoSciencePanelProps {
  project: Project;
}

interface TrackIdentity {
  id: string;
  track_number: number;
}

function toggleSelection(
  current: string[],
  value: string,
  checked: boolean,
): string[] {
  if (checked) return current.includes(value) ? current : [...current, value];
  return current.filter((item) => item !== value);
}

function parseDepthSamples(
  text: string,
  tracks: TrackIdentity[],
): VideoDepthSample[] {
  const byNumber = new Map(
    tracks.map((track) => [String(track.track_number), track.id]),
  );
  const knownIds = new Set(tracks.map((track) => track.id));
  const samples: VideoDepthSample[] = [];
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const [index, line] of lines.entries()) {
    const columns = line.split(",").map((value) => value.trim());
    if (
      index === 0 &&
      columns[0]?.toLowerCase().includes("track") &&
      columns[1]?.toLowerCase().includes("frame")
    ) {
      continue;
    }
    if (columns.length < 3) {
      throw new Error(
        `Depth row ${index + 1} must contain track, frame, and depth columns.`,
      );
    }
    const trackToken = columns[0];
    const trackId =
      byNumber.get(trackToken) ??
      (knownIds.has(trackToken) ? trackToken : null);
    if (!trackId) {
      throw new Error(
        `Depth row ${index + 1} references unknown track ${trackToken}.`,
      );
    }
    const frame = Number(columns[1]);
    const depth = Number(columns[2]);
    const confidence = columns[3] ? Number(columns[3]) : null;
    if (!Number.isInteger(frame) || frame < 0) {
      throw new Error(`Depth row ${index + 1} has an invalid frame.`);
    }
    if (!Number.isFinite(depth) || depth <= 0) {
      throw new Error(`Depth row ${index + 1} has an invalid positive depth.`);
    }
    if (
      confidence !== null &&
      (!Number.isFinite(confidence) || confidence < 0 || confidence > 1)
    ) {
      throw new Error(
        `Depth row ${index + 1} confidence must be between 0 and 1.`,
      );
    }
    samples.push({ track_id: trackId, frame, depth, confidence });
  }

  if (samples.length < 2) {
    throw new Error("Provide at least two metric depth samples.");
  }
  return samples;
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
  const [cameraFx, setCameraFx] = useState(1000);
  const [cameraFy, setCameraFy] = useState(1000);
  const [cameraCx, setCameraCx] = useState(0);
  const [cameraCy, setCameraCy] = useState(0);
  const [cameraMethod, setCameraMethod] = useState("camera_calibration");
  const [cameraNotes, setCameraNotes] = useState("");
  const [depthUnit, setDepthUnit] = useState<VideoDistanceUnit>("m");
  const [depthSamplesText, setDepthSamplesText] = useState(
    "track,frame,depth,confidence\n",
  );
  const [maximumFrameGap, setMaximumFrameGap] = useState("");

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
  const cameraQuery = useQuery({
    queryKey: ["video-camera-intrinsics", videoId],
    queryFn: ({ signal }) => getVideoCameraIntrinsics(videoId, signal),
    enabled: Boolean(videoId),
  });
  const calibratedTrackQuery = useQuery({
    queryKey: ["video-calibrated-track", selectedTrackId],
    queryFn: ({ signal }) =>
      getCalibratedTrackAnalytics(selectedTrackId, signal),
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
    if (!cameraQuery.data && selectedVideo) {
      const focalGuess = Math.max(
        selectedVideo.width_px,
        selectedVideo.height_px,
        1,
      );
      setCameraFx(focalGuess);
      setCameraFy(focalGuess);
      setCameraCx(selectedVideo.width_px / 2);
      setCameraCy(selectedVideo.height_px / 2);
    }
  }, [videoId, selectedVideo, cameraQuery.data]);

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

  useEffect(() => {
    const camera = cameraQuery.data;
    if (!camera) return;
    setCameraFx(camera.fx_px);
    setCameraFy(camera.fy_px);
    setCameraCx(camera.cx_px);
    setCameraCy(camera.cy_px);
    setCameraMethod(camera.method);
    setCameraNotes(camera.notes ?? "");
  }, [cameraQuery.data]);

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
        throw new Error(
          "Schooling end frame must be at or after the start frame",
        );
      }
      return getSchoolingAnalytics(videoId, {
        track_ids: schoolTrackIds,
        start_frame: schoolStartFrame,
        end_frame: schoolEndFrame,
      });
    },
  });

  const cameraMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (cameraFx <= 0 || cameraFy <= 0) {
        throw new Error("Camera focal lengths must be positive");
      }
      return setVideoCameraIntrinsics(videoId, {
        fx_px: cameraFx,
        fy_px: cameraFy,
        cx_px: cameraCx,
        cy_px: cameraCy,
        method: cameraMethod.trim() || "camera_calibration",
        notes: cameraNotes.trim() || null,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["video-camera-intrinsics", videoId],
      });
    },
  });

  const clearCameraMutation = useMutation({
    mutationFn: () => clearVideoCameraIntrinsics(videoId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["video-camera-intrinsics", videoId],
      });
    },
  });

  const depthAnalyticsMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (!cameraQuery.data) {
        throw new Error("Save camera intrinsics before 3D trajectory analysis");
      }
      const samples = parseDepthSamples(
        depthSamplesText,
        tracksQuery.data ?? [],
      );
      const frameGap = maximumFrameGap.trim()
        ? Number.parseInt(maximumFrameGap, 10)
        : null;
      if (frameGap !== null && (!Number.isInteger(frameGap) || frameGap < 1)) {
        throw new Error("Maximum frame gap must be a positive integer");
      }
      return getDepthTrackAnalytics(videoId, {
        unit: depthUnit,
        samples,
        maximum_frame_gap: frameGap,
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
    cameraQuery.error ??
    calibratedTrackQuery.error ??
    calibrationMutation.error ??
    clearMutation.error ??
    schoolingMutation.error ??
    cameraMutation.error ??
    clearCameraMutation.error ??
    depthAnalyticsMutation.error;

  return (
    <section className="management-card" data-testid="video-science-panel">
      <p className="eyebrow">Video science</p>
      <h3>Calibration, schooling, and 3D movement</h3>
      <p className="annotation-helper">
        Convert pixel trajectories into physical distance and speed, quantify
        schooling, and back-project verified metric depth samples into
        calibrated 3D fish trajectories.
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

      <h4>Spatial calibration</h4>
      <div className="annotation-selection-list">
        <label>
          Physical unit
          <select
            value={unit}
            onChange={(event) =>
              setUnit(event.target.value as VideoDistanceUnit)
            }
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
            onChange={(event) =>
              setReferenceDistance(Number(event.target.value))
            }
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
          <input
            value={method}
            onChange={(event) => setMethod(event.target.value)}
          />
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
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
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
          disabled={
            !videoId || !calibrationQuery.data || clearMutation.isPending
          }
          onClick={() => clearMutation.mutate()}
        >
          Clear calibration
        </button>
      </div>
      {calibrationQuery.data && (
        <p className="annotation-helper">
          Scale: {calibrationQuery.data.pixels_per_unit.toFixed(4)} px/
          {calibrationQuery.data.unit} (
          {calibrationQuery.data.units_per_pixel.toFixed(6)}{" "}
          {calibrationQuery.data.unit}/px), video revision{" "}
          {calibrationQuery.data.video_revision}.
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
              Track {track.track_number} —{" "}
              {classNames.get(track.label_class_id) ?? "Unknown class"}
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
        Polarization ranges from 0 (headings cancel) to 1 (fully aligned
        movement). Distances and speeds use the saved video calibration.
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
              Track {track.track_number} —{" "}
              {classNames.get(track.label_class_id) ?? "Unknown class"}
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
        {schoolingMutation.isPending
          ? "Calculating..."
          : "Calculate schooling metrics"}
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

      <AutomaticScientific3DPanel
        videoId={videoId}
        tracks={tracksQuery.data ?? []}
        cameraReady={Boolean(cameraQuery.data)}
        classNames={classNames}
      />

      <h4>Metric depth / 3D trajectories</h4>
      <p className="annotation-helper">
        Use calibrated metric depth from stereo, RGB-D, or another validated
        metric source. Relative Depth Anything values are not physical distances
        unless independently calibrated. ReefVision combines each depth sample
        with the interpolated track center and camera intrinsics to reconstruct
        X/Y/Z movement.
      </p>
      <div className="annotation-selection-list">
        <label>
          fx (pixels)
          <input
            type="number"
            min={0.000001}
            step="any"
            value={cameraFx}
            onChange={(event) => setCameraFx(Number(event.target.value))}
          />
        </label>
        <label>
          fy (pixels)
          <input
            type="number"
            min={0.000001}
            step="any"
            value={cameraFy}
            onChange={(event) => setCameraFy(Number(event.target.value))}
          />
        </label>
        <label>
          cx (pixels)
          <input
            type="number"
            step="any"
            value={cameraCx}
            onChange={(event) => setCameraCx(Number(event.target.value))}
          />
        </label>
        <label>
          cy (pixels)
          <input
            type="number"
            step="any"
            value={cameraCy}
            onChange={(event) => setCameraCy(Number(event.target.value))}
          />
        </label>
        <label>
          Intrinsics method
          <input
            value={cameraMethod}
            onChange={(event) => setCameraMethod(event.target.value)}
          />
        </label>
        <label>
          Intrinsics notes
          <textarea
            value={cameraNotes}
            onChange={(event) => setCameraNotes(event.target.value)}
          />
        </label>
      </div>
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          disabled={!videoId || cameraMutation.isPending}
          onClick={() => cameraMutation.mutate()}
        >
          {cameraMutation.isPending ? "Saving..." : "Save camera intrinsics"}
        </button>
        <button
          type="button"
          className="danger-ghost"
          disabled={!cameraQuery.data || clearCameraMutation.isPending}
          onClick={() => clearCameraMutation.mutate()}
        >
          Clear intrinsics
        </button>
      </div>
      {cameraQuery.data && (
        <p className="annotation-helper">
          Saved intrinsics: fx {cameraQuery.data.fx_px.toFixed(2)}, fy{" "}
          {cameraQuery.data.fy_px.toFixed(2)}, principal point (
          {cameraQuery.data.cx_px.toFixed(2)},{" "}
          {cameraQuery.data.cy_px.toFixed(2)}) px.
        </p>
      )}
      <label>
        Depth unit
        <select
          value={depthUnit}
          onChange={(event) =>
            setDepthUnit(event.target.value as VideoDistanceUnit)
          }
        >
          <option value="mm">Millimeters</option>
          <option value="cm">Centimeters</option>
          <option value="m">Meters</option>
        </select>
      </label>
      <label>
        Metric depth samples (CSV)
        <textarea
          rows={8}
          value={depthSamplesText}
          onChange={(event) => setDepthSamplesText(event.target.value)}
          placeholder="track,frame,depth,confidence\n1,0,1.25,0.98\n1,10,1.30,0.97"
        />
      </label>
      <p className="annotation-helper">
        The first column may be the visible track number or the full track ID.
        Confidence is optional. Available tracks:{" "}
        {(tracksQuery.data ?? [])
          .map((track) => track.track_number)
          .join(", ") || "none"}
        .
      </p>
      <label>
        Maximum frame gap to bridge (optional)
        <input
          type="number"
          min={1}
          step={1}
          value={maximumFrameGap}
          onChange={(event) => setMaximumFrameGap(event.target.value)}
          placeholder="Leave blank to use every consecutive sample pair"
        />
      </label>
      <button
        type="button"
        disabled={!cameraQuery.data || depthAnalyticsMutation.isPending}
        onClick={() => depthAnalyticsMutation.mutate()}
      >
        {depthAnalyticsMutation.isPending
          ? "Reconstructing..."
          : "Calculate 3D trajectories"}
      </button>
      {depthAnalyticsMutation.data && (
        <div className="annotation-selection-list">
          {depthAnalyticsMutation.data.tracks.map((track) => (
            <div key={track.track_id} className="panel-card">
              <strong>
                Track {track.track_number} —{" "}
                {classNames.get(track.label_class_id) ?? "Unknown class"}
              </strong>
              <dl className="metric-list">
                <div>
                  <dt>3D path</dt>
                  <dd>
                    {track.path_length_3d.toFixed(4)}{" "}
                    {depthAnalyticsMutation.data.unit}
                  </dd>
                </div>
                <div>
                  <dt>3D displacement</dt>
                  <dd>
                    {track.displacement_3d.toFixed(4)}{" "}
                    {depthAnalyticsMutation.data.unit}
                  </dd>
                </div>
                <div>
                  <dt>Mean 3D speed</dt>
                  <dd>
                    {track.mean_speed_3d_per_second.toFixed(4)}{" "}
                    {depthAnalyticsMutation.data.unit}/s
                  </dd>
                </div>
                <div>
                  <dt>Maximum 3D speed</dt>
                  <dd>
                    {track.maximum_speed_3d_per_second.toFixed(4)}{" "}
                    {depthAnalyticsMutation.data.unit}/s
                  </dd>
                </div>
                <div>
                  <dt>Mean depth</dt>
                  <dd>
                    {track.mean_depth.toFixed(4)}{" "}
                    {depthAnalyticsMutation.data.unit}
                  </dd>
                </div>
                <div>
                  <dt>Samples</dt>
                  <dd>{track.observed_frame_count}</dd>
                </div>
              </dl>
            </div>
          ))}
          {depthAnalyticsMutation.data.warnings.map((warning) => (
            <p key={warning} className="annotation-helper">
              {warning}
            </p>
          ))}
        </div>
      )}

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
