import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  analyzeVideo,
  calibrateVideo,
  createVideoTrack,
  createVideoTrackingJob,
  deleteVideoTrack,
  extractVideoFrames,
  getTrackingModels,
  getVideoTrackAnalytics,
  getVideoTrackInterpolation,
  getVideoTracks,
  getVideos,
  importVideo,
  updateVideoTrack,
  videoContentUrl,
  videoExportUrl,
  videoFrameUrl,
  type VideoTrackerConfig,
  type VideoTrackKeyframe,
  type VideoZone,
} from "./videoApi";

interface VideoTrackingWorkspaceProps {
  project: Project;
}

function sortedKeyframes(items: VideoTrackKeyframe[]): VideoTrackKeyframe[] {
  return [...items].sort((first, second) => first.frame - second.frame);
}

export function VideoTrackingWorkspace({
  project,
}: VideoTrackingWorkspaceProps) {
  const queryClient = useQueryClient();
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [everyNFrames, setEveryNFrames] = useState(1);
  const [frameIndex, setFrameIndex] = useState(0);
  const [selectedTrackId, setSelectedTrackId] = useState("");
  const [labelClassId, setLabelClassId] = useState(
    project.label_classes[0]?.id ?? "",
  );
  const [interpolation, setInterpolation] = useState<"linear" | "hold">(
    "linear",
  );
  const [trackStatus, setTrackStatus] = useState("verified");
  const [keyframes, setKeyframes] = useState<VideoTrackKeyframe[]>([]);
  const [trackingModelId, setTrackingModelId] = useState("");
  const [tracker, setTracker] = useState<VideoTrackerConfig>("bytetrack.yaml");
  const [distancePerPixel, setDistancePerPixel] = useState("");
  const [physicalUnit, setPhysicalUnit] = useState("cm");
  const [activityThreshold, setActivityThreshold] = useState(1);
  const [zoneName, setZoneName] = useState("");
  const [zoneXMin, setZoneXMin] = useState(0);
  const [zoneYMin, setZoneYMin] = useState(0);
  const [zoneXMax, setZoneXMax] = useState(0);
  const [zoneYMax, setZoneYMax] = useState(0);

  const videosQuery = useQuery({
    queryKey: ["videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
    refetchInterval: 3000,
  });
  const selectedVideo = videosQuery.data?.find(
    (video) => video.id === selectedVideoId,
  );
  const tracksQuery = useQuery({
    queryKey: ["video-tracks", selectedVideoId],
    queryFn: ({ signal }) => getVideoTracks(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
    refetchInterval: 3000,
  });
  const selectedTrack = tracksQuery.data?.find(
    (track) => track.id === selectedTrackId,
  );
  const interpolationQuery = useQuery({
    queryKey: ["video-track-interpolation", selectedTrackId],
    queryFn: ({ signal }) =>
      getVideoTrackInterpolation(selectedTrackId, signal),
    enabled: Boolean(selectedTrackId),
  });
  const analyticsQuery = useQuery({
    queryKey: ["video-track-analytics", selectedTrackId],
    queryFn: ({ signal }) => getVideoTrackAnalytics(selectedTrackId, signal),
    enabled: Boolean(selectedTrackId),
  });
  const modelsQuery = useQuery({
    queryKey: ["video-tracking-models", project.id],
    queryFn: ({ signal }) => getTrackingModels(project.id, signal),
  });

  useEffect(() => {
    if (!selectedVideoId && videosQuery.data?.[0]) {
      setSelectedVideoId(videosQuery.data[0].id);
    }
  }, [selectedVideoId, videosQuery.data]);

  useEffect(() => {
    setFrameIndex(0);
    setSelectedTrackId("");
    setKeyframes([]);
  }, [selectedVideoId]);

  useEffect(() => {
    if (!trackingModelId && modelsQuery.data?.[0]) {
      setTrackingModelId(modelsQuery.data[0].id);
    }
  }, [modelsQuery.data, trackingModelId]);

  useEffect(() => {
    if (!selectedTrack) {
      setKeyframes([]);
      setTrackStatus("verified");
      return;
    }
    setLabelClassId(selectedTrack.label_class_id);
    setInterpolation(
      selectedTrack.interpolation === "hold" ? "hold" : "linear",
    );
    setTrackStatus(selectedTrack.status);
    setKeyframes(sortedKeyframes(selectedTrack.keyframes_json));
  }, [selectedTrack]);

  useEffect(() => {
    const calibration = selectedVideo?.metadata_json.calibration;
    if (calibration && typeof calibration === "object") {
      const record = calibration as Record<string, unknown>;
      setDistancePerPixel(String(record.distance_per_pixel ?? ""));
      setPhysicalUnit(String(record.unit ?? "cm"));
    } else {
      setDistancePerPixel("");
      setPhysicalUnit("cm");
    }
    if (selectedVideo) {
      setZoneXMin(0);
      setZoneYMin(0);
      setZoneXMax(selectedVideo.width_px);
      setZoneYMax(selectedVideo.height_px);
    }
  }, [selectedVideo]);

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!uploadFile) throw new Error("Choose a video file first");
      return importVideo(project.id, uploadFile);
    },
    onSuccess: async (video) => {
      setSelectedVideoId(video.id);
      setUploadFile(null);
      await queryClient.invalidateQueries({ queryKey: ["videos", project.id] });
    },
  });

  const calibrationMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId || !distancePerPixel) {
        throw new Error("Select a video and enter distance per pixel");
      }
      return calibrateVideo(selectedVideoId, {
        distance_per_pixel: Number(distancePerPixel),
        unit: physicalUnit,
        source: "video workspace",
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["videos", project.id] });
    },
  });

  const extractionMutation = useMutation({
    mutationFn: () => extractVideoFrames(selectedVideoId, everyNFrames),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["videos", project.id] });
    },
  });

  const saveTrackMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId || !labelClassId || keyframes.length === 0) {
        throw new Error(
          "A video, class, and at least one keyframe are required",
        );
      }
      const normalized = sortedKeyframes(keyframes);
      if (selectedTrack) {
        return updateVideoTrack(selectedTrack.id, {
          base_revision: selectedTrack.revision,
          label_class_id: labelClassId,
          keyframes: normalized,
          interpolation,
          status: trackStatus,
        });
      }
      return createVideoTrack(selectedVideoId, {
        label_class_id: labelClassId,
        geometry_kind: "bbox",
        keyframes: normalized,
        interpolation,
        status: trackStatus,
      });
    },
    onSuccess: async (track) => {
      setSelectedTrackId(track.id);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["video-tracks", selectedVideoId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-track-interpolation", track.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-track-analytics", track.id],
        }),
      ]);
    },
  });

  const deleteTrackMutation = useMutation({
    mutationFn: () => {
      if (!selectedTrackId) throw new Error("Select a track first");
      return deleteVideoTrack(selectedTrackId);
    },
    onSuccess: async () => {
      setSelectedTrackId("");
      setKeyframes([]);
      await queryClient.invalidateQueries({
        queryKey: ["video-tracks", selectedVideoId],
      });
    },
  });

  const trackingMutation = useMutation({
    mutationFn: () =>
      createVideoTrackingJob(selectedVideoId, {
        model_id: trackingModelId,
        tracker,
        confidence: 0.25,
        iou: 0.5,
        device: "auto",
        minimum_track_frames: 2,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["videos", project.id] });
    },
  });

  const behaviorMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Select a video first");
      const zones: VideoZone[] = zoneName.trim()
        ? [
            {
              name: zoneName.trim(),
              x_min: zoneXMin,
              y_min: zoneYMin,
              x_max: zoneXMax,
              y_max: zoneYMax,
            },
          ]
        : [];
      return analyzeVideo(selectedVideoId, {
        zones,
        heatmap_bins_x: 10,
        heatmap_bins_y: 10,
        activity_speed_threshold_pixels_per_second: activityThreshold,
      });
    },
  });

  const overlayFrame = useMemo(
    () =>
      interpolationQuery.data?.frames.find(
        (frame) => frame.frame === frameIndex,
      ),
    [frameIndex, interpolationQuery.data?.frames],
  );
  const extractionStride = Number(
    selectedVideo?.metadata_json.extraction_every_n_frames ?? everyNFrames,
  );
  const calibration =
    selectedVideo?.metadata_json.calibration &&
    typeof selectedVideo.metadata_json.calibration === "object"
      ? (selectedVideo.metadata_json.calibration as Record<string, unknown>)
      : null;
  const selectedBehaviorTrack = behaviorMutation.data?.tracks.find(
    (item) => item.track_id === selectedTrackId,
  );
  const schoolingFrames = behaviorMutation.data?.school_by_frame ?? [];
  const schoolingFramesWithPairs = schoolingFrames.filter(
    (item) => item.mean_nearest_neighbor_pixels !== null,
  );
  const meanSchoolSpread =
    schoolingFramesWithPairs.length > 0
      ? schoolingFramesWithPairs.reduce(
          (sum, item) => sum + (item.school_spread_pixels ?? 0),
          0,
        ) / schoolingFramesWithPairs.length
      : null;
  const error =
    uploadMutation.error ??
    calibrationMutation.error ??
    extractionMutation.error ??
    saveTrackMutation.error ??
    deleteTrackMutation.error ??
    trackingMutation.error ??
    behaviorMutation.error;

  function updateKeyframe(
    index: number,
    field: "frame" | "x" | "y" | "width" | "height",
    value: number,
  ) {
    setKeyframes((current) =>
      current.map((keyframe, keyframeIndex) => {
        if (keyframeIndex !== index) return keyframe;
        if (field === "frame") return { ...keyframe, frame: value };
        const bbox = [...keyframe.bbox] as [number, number, number, number];
        const bboxIndex = { x: 0, y: 1, width: 2, height: 3 }[field];
        bbox[bboxIndex] = value;
        return { ...keyframe, bbox };
      }),
    );
  }

  return (
    <div className="management-grid" data-testid="video-tracking-workspace">
      <section className="management-card">
        <p className="eyebrow">Phase 6</p>
        <h3>Managed videos</h3>
        <input
          type="file"
          accept="video/*,.avi,.m4v,.mkv,.mov,.mp4,.webm"
          onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          disabled={!uploadFile || uploadMutation.isPending}
          onClick={() => uploadMutation.mutate()}
        >
          {uploadMutation.isPending ? "Importing..." : "Import video"}
        </button>
        <label>
          Video
          <select
            value={selectedVideoId}
            onChange={(event) => setSelectedVideoId(event.target.value)}
          >
            {(videosQuery.data ?? []).map((video) => (
              <option key={video.id} value={video.id}>
                {video.original_filename} — {video.status}
              </option>
            ))}
          </select>
        </label>
        {selectedVideo && (
          <>
            <video
              controls
              src={videoContentUrl(selectedVideo.id)}
              style={{ width: "100%", maxHeight: 360 }}
            />
            <p className="annotation-helper">
              {selectedVideo.width_px}×{selectedVideo.height_px} |{" "}
              {selectedVideo.frame_count.toLocaleString()} frames |{" "}
              {selectedVideo.fps.toFixed(3)} fps |{" "}
              {selectedVideo.duration_seconds.toFixed(2)} s
            </p>
            <label>
              Extract every N frames
              <input
                type="number"
                min={1}
                value={everyNFrames}
                onChange={(event) =>
                  setEveryNFrames(Number(event.target.value))
                }
              />
            </label>
            <button
              type="button"
              disabled={extractionMutation.isPending}
              onClick={() => extractionMutation.mutate()}
            >
              {extractionMutation.isPending
                ? "Queuing..."
                : "Extract review frames"}
            </button>
          </>
        )}
      </section>

      <section className="management-card">
        <p className="eyebrow">Physical calibration</p>
        <h3>Pixels to real distance</h3>
        <label>
          Distance per pixel
          <input
            type="number"
            min={0}
            step="any"
            value={distancePerPixel}
            onChange={(event) => setDistancePerPixel(event.target.value)}
          />
        </label>
        <label>
          Unit
          <input
            value={physicalUnit}
            onChange={(event) => setPhysicalUnit(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={
            !selectedVideoId ||
            !distancePerPixel ||
            calibrationMutation.isPending
          }
          onClick={() => calibrationMutation.mutate()}
        >
          {calibrationMutation.isPending ? "Saving..." : "Save calibration"}
        </button>
        <p className="annotation-helper">
          {calibration
            ? `Current scale: ${String(calibration.distance_per_pixel)} ${String(
                calibration.unit ?? "units",
              )}/px`
            : "No physical calibration saved. Pixel measurements remain available."}
        </p>
      </section>

      <section className="management-card">
        <p className="eyebrow">Frame review</p>
        <h3>Source-coordinate overlay</h3>
        {selectedVideo ? (
          <>
            <label>
              Frame {frameIndex}
              <input
                type="range"
                min={0}
                max={Math.max(0, selectedVideo.frame_count - 1)}
                step={Math.max(1, extractionStride)}
                value={frameIndex}
                onChange={(event) => setFrameIndex(Number(event.target.value))}
              />
            </label>
            {selectedVideo.frame_directory_path ? (
              <div
                style={{
                  position: "relative",
                  width: "100%",
                  aspectRatio: `${selectedVideo.width_px} / ${selectedVideo.height_px}`,
                }}
              >
                <img
                  src={videoFrameUrl(selectedVideo.id, frameIndex)}
                  alt={`Frame ${frameIndex}`}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                  }}
                />
                {overlayFrame && (
                  <svg
                    viewBox={`0 0 ${selectedVideo.width_px} ${selectedVideo.height_px}`}
                    preserveAspectRatio="none"
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                    }}
                  >
                    <rect
                      x={overlayFrame.bbox[0]}
                      y={overlayFrame.bbox[1]}
                      width={overlayFrame.bbox[2]}
                      height={overlayFrame.bbox[3]}
                      fill="none"
                      stroke="#ffd43b"
                      strokeWidth={3}
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                )}
              </div>
            ) : (
              <p className="annotation-helper">
                Extract frames to review keyframes against still images.
              </p>
            )}
          </>
        ) : (
          <p className="annotation-helper">Import a video to begin.</p>
        )}
      </section>

      <section className="management-card">
        <p className="eyebrow">Track editor</p>
        <h3>Identities and keyframes</h3>
        <label>
          Existing track
          <select
            value={selectedTrackId}
            onChange={(event) => setSelectedTrackId(event.target.value)}
          >
            <option value="">New track</option>
            {(tracksQuery.data ?? []).map((track) => (
              <option key={track.id} value={track.id}>
                Track {track.track_number} — {track.status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Identity class
          <select
            value={labelClassId}
            onChange={(event) => setLabelClassId(event.target.value)}
          >
            {project.label_classes.map((labelClass) => (
              <option key={labelClass.id} value={labelClass.id}>
                {labelClass.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Interpolation
          <select
            value={interpolation}
            onChange={(event) =>
              setInterpolation(
                event.target.value === "hold" ? "hold" : "linear",
              )
            }
          >
            <option value="linear">Linear</option>
            <option value="hold">Hold previous box</option>
          </select>
        </label>
        <label>
          Status
          <select
            value={trackStatus}
            onChange={(event) => setTrackStatus(event.target.value)}
          >
            <option value="verified">Verified</option>
            <option value="draft">Draft</option>
            <option value="machine_generated">Machine generated</option>
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          disabled={!selectedVideo}
          onClick={() =>
            setKeyframes((current) =>
              sortedKeyframes([
                ...current.filter((item) => item.frame !== frameIndex),
                {
                  frame: frameIndex,
                  bbox: [10, 10, 50, 30],
                  confidence: null,
                },
              ]),
            )
          }
        >
          Add keyframe at frame {frameIndex}
        </button>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Frame</th>
                <th>X</th>
                <th>Y</th>
                <th>Width</th>
                <th>Height</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keyframes.map((keyframe, index) => (
                <tr key={`${keyframe.frame}-${index}`}>
                  {[
                    ["frame", keyframe.frame],
                    ["x", keyframe.bbox[0]],
                    ["y", keyframe.bbox[1]],
                    ["width", keyframe.bbox[2]],
                    ["height", keyframe.bbox[3]],
                  ].map(([field, value]) => (
                    <td key={field}>
                      <input
                        type="number"
                        min={0}
                        value={value}
                        onChange={(event) =>
                          updateKeyframe(
                            index,
                            field as "frame" | "x" | "y" | "width" | "height",
                            Number(event.target.value),
                          )
                        }
                        style={{ width: 76 }}
                      />
                    </td>
                  ))}
                  <td>
                    <button
                      type="button"
                      className="danger-ghost"
                      onClick={() =>
                        setKeyframes((current) =>
                          current.filter(
                            (_item, itemIndex) => itemIndex !== index,
                          ),
                        )
                      }
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            disabled={saveTrackMutation.isPending || keyframes.length === 0}
            onClick={() => saveTrackMutation.mutate()}
          >
            {saveTrackMutation.isPending ? "Saving..." : "Save track"}
          </button>
          <button
            type="button"
            className="danger-ghost"
            disabled={!selectedTrackId || deleteTrackMutation.isPending}
            onClick={() => deleteTrackMutation.mutate()}
          >
            Delete track
          </button>
        </div>
      </section>

      <section className="management-card">
        <p className="eyebrow">Automated tracking</p>
        <h3>Detector + tracker</h3>
        <label>
          Detection model
          <select
            value={trackingModelId}
            onChange={(event) => setTrackingModelId(event.target.value)}
          >
            {(modelsQuery.data ?? []).map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tracker
          <select
            value={tracker}
            onChange={(event) =>
              setTracker(event.target.value as VideoTrackerConfig)
            }
          >
            <option value="bytetrack.yaml">ByteTrack</option>
            <option value="botsort.yaml">BoT-SORT</option>
          </select>
        </label>
        <button
          type="button"
          disabled={
            !selectedVideoId || !trackingModelId || trackingMutation.isPending
          }
          onClick={() => trackingMutation.mutate()}
        >
          {trackingMutation.isPending
            ? "Queuing..."
            : `Track fish with ${tracker === "botsort.yaml" ? "BoT-SORT" : "ByteTrack"}`}
        </button>
        {trackingMutation.data && (
          <p className="annotation-helper">
            Tracking job {trackingMutation.data.id.slice(0, 8)} queued. Machine
            tracks remain editable and must be reviewed.
          </p>
        )}
        {analyticsQuery.data && (
          <div className="annotation-selection-list">
            <div className="annotation-selection-row">
              <strong>Path length</strong>
              <span>
                {analyticsQuery.data.path_length_pixels.toFixed(2)} px
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Mean speed</strong>
              <span>
                {analyticsQuery.data.mean_speed_pixels_per_second.toFixed(2)}{" "}
                px/s
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Maximum speed</strong>
              <span>
                {analyticsQuery.data.maximum_speed_pixels_per_second.toFixed(2)}{" "}
                px/s
              </span>
            </div>
            <div className="annotation-selection-row">
              <strong>Displacement</strong>
              <span>
                {analyticsQuery.data.displacement_pixels.toFixed(2)} px
              </span>
            </div>
          </div>
        )}
      </section>

      <section className="management-card">
        <p className="eyebrow">Behavior analytics</p>
        <h3>Activity, occupancy, and schooling</h3>
        <label>
          Active speed threshold (px/s)
          <input
            type="number"
            min={0}
            step="any"
            value={activityThreshold}
            onChange={(event) => setActivityThreshold(Number(event.target.value))}
          />
        </label>
        <label>
          Optional zone name
          <input
            value={zoneName}
            placeholder="e.g. feeding area"
            onChange={(event) => setZoneName(event.target.value)}
          />
        </label>
        <div className="annotation-editor-inline-actions">
          <label>
            X min
            <input
              type="number"
              min={0}
              value={zoneXMin}
              onChange={(event) => setZoneXMin(Number(event.target.value))}
            />
          </label>
          <label>
            Y min
            <input
              type="number"
              min={0}
              value={zoneYMin}
              onChange={(event) => setZoneYMin(Number(event.target.value))}
            />
          </label>
          <label>
            X max
            <input
              type="number"
              min={0}
              value={zoneXMax}
              onChange={(event) => setZoneXMax(Number(event.target.value))}
            />
          </label>
          <label>
            Y max
            <input
              type="number"
              min={0}
              value={zoneYMax}
              onChange={(event) => setZoneYMax(Number(event.target.value))}
            />
          </label>
        </div>
        <button
          type="button"
          disabled={!selectedVideoId || behaviorMutation.isPending}
          onClick={() => behaviorMutation.mutate()}
        >
          {behaviorMutation.isPending ? "Calculating..." : "Analyze behavior"}
        </button>
        {behaviorMutation.data && (
          <>
            {behaviorMutation.data.warnings.map((warning) => (
              <p key={warning} className="annotation-helper">
                {warning}
              </p>
            ))}
            <div className="annotation-selection-list">
              <div className="annotation-selection-row">
                <strong>Tracks analyzed</strong>
                <span>{behaviorMutation.data.tracks.length}</span>
              </div>
              <div className="annotation-selection-row">
                <strong>Occupied heatmap cells</strong>
                <span>{behaviorMutation.data.heatmap.length}</span>
              </div>
              <div className="annotation-selection-row">
                <strong>Schooling frames</strong>
                <span>{schoolingFramesWithPairs.length}</span>
              </div>
              <div className="annotation-selection-row">
                <strong>Mean school spread</strong>
                <span>
                  {meanSchoolSpread === null
                    ? "n/a"
                    : `${meanSchoolSpread.toFixed(2)} px`}
                </span>
              </div>
              {selectedBehaviorTrack && (
                <>
                  <div className="annotation-selection-row">
                    <strong>Selected track active time</strong>
                    <span>
                      {selectedBehaviorTrack.active_time_seconds.toFixed(2)} s
                    </span>
                  </div>
                  <div className="annotation-selection-row">
                    <strong>Selected track inactive time</strong>
                    <span>
                      {selectedBehaviorTrack.inactive_time_seconds.toFixed(2)} s
                    </span>
                  </div>
                  <div className="annotation-selection-row">
                    <strong>Selected track physical distance</strong>
                    <span>
                      {selectedBehaviorTrack.distance_physical === null
                        ? "not calibrated"
                        : `${selectedBehaviorTrack.distance_physical.toFixed(3)} ${selectedBehaviorTrack.physical_unit ?? "units"}`}
                    </span>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </section>

      <section className="management-card">
        <p className="eyebrow">Research exports</p>
        <h3>Trajectory data</h3>
        <p className="annotation-helper">
          Export interpolated source-coordinate tracks for spreadsheets,
          MOTChallenge-compatible tools, or ReefVision-preserving JSON.
        </p>
        {selectedVideoId ? (
          <div className="annotation-editor-inline-actions">
            <a href={videoExportUrl(selectedVideoId, "csv")} download>
              CSV
            </a>
            <a href={videoExportUrl(selectedVideoId, "mot")} download>
              MOT
            </a>
            <a href={videoExportUrl(selectedVideoId, "json")} download>
              ReefVision JSON
            </a>
          </div>
        ) : (
          <p className="annotation-helper">Select a video to export tracks.</p>
        )}
      </section>

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </div>
  );
}
