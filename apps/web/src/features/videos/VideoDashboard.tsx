import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  analyzeVideo,
  calibrateVideo,
  createVideoTrack,
  createVideoTracking,
  deleteVideoTrack,
  downloadUrl,
  getModels,
  getVideoTracks,
  getVideos,
  updateVideoTrack,
  uploadVideo,
  type VideoTrack,
} from "../phase456/api";

const defaultTrackJson = JSON.stringify(
  {
    track_number: 1,
    label_class_id: null,
    interpolation: "linear",
    status: "verified",
    keyframes: [
      {
        frame_index: 0,
        x_min: 10,
        y_min: 10,
        x_max: 50,
        y_max: 40,
      },
    ],
  },
  null,
  2,
);

const defaultZonesJson = JSON.stringify(
  [
    {
      name: "left wall",
      x_min: 0,
      y_min: 0,
      x_max: 100,
      y_max: 1080,
    },
  ],
  null,
  2,
);

export function VideoDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [detectorId, setDetectorId] = useState("");
  const [tracker, setTracker] = useState<"bytetrack" | "botsort">("bytetrack");
  const [confidence, setConfidence] = useState(0.25);
  const [iou, setIou] = useState(0.45);
  const [everyNFrames, setEveryNFrames] = useState(1);
  const [distancePerPixel, setDistancePerPixel] = useState("");
  const [physicalUnit, setPhysicalUnit] = useState("cm");
  const [trackJson, setTrackJson] = useState(defaultTrackJson);
  const [editingTrackId, setEditingTrackId] = useState<string | null>(null);
  const [zonesJson, setZonesJson] = useState(defaultZonesJson);
  const [heatmapBins, setHeatmapBins] = useState(20);
  const [activityThreshold, setActivityThreshold] = useState(1);
  const [parseError, setParseError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const videos = useQuery({
    queryKey: ["phase6_videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
  });
  const models = useQuery({
    queryKey: ["phase6_models", project.id],
    queryFn: ({ signal }) => getModels(project.id, signal),
  });
  const tracks = useQuery({
    queryKey: ["phase6_tracks", selectedVideoId],
    queryFn: ({ signal }) => getVideoTracks(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
    refetchInterval: 5000,
  });
  const selectedVideo = useMemo(
    () => videos.data?.find((video) => video.id === selectedVideoId) ?? null,
    [selectedVideoId, videos.data],
  );
  const detectors = useMemo(
    () =>
      models.data?.filter(
        (model) => model.purpose === "detector" && model.task === "detect",
      ) ?? [],
    [models.data],
  );

  useEffect(() => {
    if (!selectedVideoId && videos.data?.length) {
      setSelectedVideoId(videos.data[0].id);
    }
  }, [selectedVideoId, videos.data]);

  useEffect(() => {
    if (!detectorId && detectors.length) setDetectorId(detectors[0].id);
  }, [detectorId, detectors]);

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
  }, [selectedVideo]);

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a video file first");
      return uploadVideo(project.id, file);
    },
    onSuccess: async (result) => {
      setSelectedVideoId(result.video.id);
      setMessage(
        result.duplicate
          ? "Existing managed video selected."
          : "Video imported.",
      );
      setFile(null);
      await queryClient.invalidateQueries({
        queryKey: ["phase6_videos", project.id],
      });
    },
  });
  const calibrate = useMutation({
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
      setMessage("Video calibration saved.");
      await queryClient.invalidateQueries({
        queryKey: ["phase6_videos", project.id],
      });
    },
  });
  const automaticTracking = useMutation({
    mutationFn: () => {
      if (!selectedVideoId || !detectorId) {
        throw new Error("Choose a managed video and detector");
      }
      return createVideoTracking(selectedVideoId, {
        model_id: detectorId,
        tracker,
        device: "auto",
        confidence_threshold: confidence,
        iou_threshold: iou,
        every_n_frames: everyNFrames,
        replace_generated_tracks: true,
      });
    },
    onSuccess: (job) => setMessage(`Tracking queued as job ${job.id}.`),
  });
  const saveTrack = useMutation({
    mutationFn: async () => {
      if (!selectedVideoId) throw new Error("Choose a video");
      const parsed = JSON.parse(trackJson) as Record<string, unknown>;
      setParseError(null);
      if (editingTrackId) return updateVideoTrack(editingTrackId, parsed);
      return createVideoTrack(selectedVideoId, {
        video_id: selectedVideoId,
        geometry_kind: "bounding_box",
        ...parsed,
      });
    },
    onSuccess: async () => {
      setTrackJson(defaultTrackJson);
      setEditingTrackId(null);
      setMessage("Track saved.");
      await queryClient.invalidateQueries({
        queryKey: ["phase6_tracks", selectedVideoId],
      });
    },
    onError: (error) => {
      if (error instanceof SyntaxError) setParseError(error.message);
    },
  });
  const removeTrack = useMutation({
    mutationFn: (trackId: string) => deleteVideoTrack(trackId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["phase6_tracks", selectedVideoId],
      });
    },
  });
  const analytics = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video");
      const zones = JSON.parse(zonesJson) as unknown[];
      setParseError(null);
      return analyzeVideo(selectedVideoId, {
        zones,
        heatmap_bins_x: heatmapBins,
        heatmap_bins_y: heatmapBins,
        activity_speed_threshold_pixels_per_second: activityThreshold,
      });
    },
    onError: (error) => {
      if (error instanceof SyntaxError) setParseError(error.message);
    },
  });

  function editTrack(track: VideoTrack) {
    setEditingTrackId(track.id);
    setTrackJson(
      JSON.stringify(
        {
          label_class_id: track.label_class_id,
          interpolation: track.interpolation,
          status: track.status,
          keyframes: track.keyframes,
        },
        null,
        2,
      ),
    );
  }

  const actionError =
    upload.error ??
    calibrate.error ??
    automaticTracking.error ??
    saveTrack.error ??
    removeTrack.error ??
    analytics.error;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 6</p>
          <h3>Video and fish tracking</h3>
          <span>
            Managed source video → ByteTrack/BoT-SORT → correction → behavior
            analytics
          </span>
        </div>
        <span>{videos.data?.length ?? 0} managed videos</span>
      </div>
      {message && <p className="form-success">{message}</p>}
      {(parseError || actionError) && (
        <p className="form-error">{parseError ?? actionError?.message}</p>
      )}

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div className="dashboard-card">
            <p className="eyebrow">Managed media</p>
            <h4>Import and select video</h4>
            <label>
              Video file
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,.m4v"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button
              type="button"
              disabled={!file || upload.isPending}
              onClick={() => upload.mutate()}
            >
              {upload.isPending ? "Importing..." : "Import managed video"}
            </button>
            <label>
              Video
              <select
                value={selectedVideoId}
                onChange={(event) => setSelectedVideoId(event.target.value)}
              >
                <option value="">Choose video</option>
                {videos.data?.map((video) => (
                  <option key={video.id} value={video.id}>
                    {video.original_filename} · {video.frame_count} frames
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="dashboard-card">
            <p className="eyebrow">Physical calibration</p>
            <h4>Pixels to real distance</h4>
            <div className="dashboard-grid compact-grid">
              <label>
                Distance per pixel
                <input
                  type="number"
                  min="0"
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
            </div>
            <button
              type="button"
              disabled={
                !selectedVideoId || !distancePerPixel || calibrate.isPending
              }
              onClick={() => calibrate.mutate()}
            >
              Save calibration
            </button>
          </div>

          <div className="dashboard-card">
            <p className="eyebrow">Automated tracking</p>
            <h4>Detector plus tracker</h4>
            <label>
              Detector
              <select
                value={detectorId}
                onChange={(event) => setDetectorId(event.target.value)}
              >
                <option value="">Choose detector</option>
                {detectors.map((model) => (
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
                  setTracker(event.target.value as "bytetrack" | "botsort")
                }
              >
                <option value="bytetrack">ByteTrack</option>
                <option value="botsort">BoT-SORT</option>
              </select>
            </label>
            <div className="dashboard-grid compact-grid">
              <label>
                Confidence
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={confidence}
                  onChange={(event) =>
                    setConfidence(Number(event.target.value))
                  }
                />
              </label>
              <label>
                IoU
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={iou}
                  onChange={(event) => setIou(Number(event.target.value))}
                />
              </label>
              <label>
                Frame stride
                <input
                  type="number"
                  min="1"
                  value={everyNFrames}
                  onChange={(event) =>
                    setEveryNFrames(Number(event.target.value))
                  }
                />
              </label>
            </div>
            <button
              type="button"
              disabled={
                !selectedVideoId || !detectorId || automaticTracking.isPending
              }
              onClick={() => automaticTracking.mutate()}
            >
              {automaticTracking.isPending ? "Queuing..." : "Run fish tracking"}
            </button>
          </div>
        </div>

        <div className="dashboard-main">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Playback</p>
                <h4>{selectedVideo?.original_filename ?? "Choose a video"}</h4>
              </div>
              {selectedVideo && (
                <span>
                  {selectedVideo.width_px}×{selectedVideo.height_px} ·{" "}
                  {selectedVideo.fps.toFixed(2)} fps ·{" "}
                  {selectedVideo.duration_seconds.toFixed(2)} s
                </span>
              )}
            </div>
            {selectedVideo && (
              <video
                controls
                preload="metadata"
                className="research-video-player"
                src={downloadUrl(`/videos/${selectedVideo.id}/content`)}
              />
            )}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Track correction</p>
                <h4>{tracks.data?.length ?? 0} tracks</h4>
              </div>
              {editingTrackId && <span>Editing existing track</span>}
            </div>
            <p>
              Keyframes remain editable. Linear or hold interpolation generates
              the intermediate trajectory without modifying the source video.
            </p>
            <label>
              Track JSON
              <textarea
                rows={14}
                value={trackJson}
                onChange={(event) => setTrackJson(event.target.value)}
              />
            </label>
            <div className="version-actions">
              <button
                type="button"
                disabled={!selectedVideoId || saveTrack.isPending}
                onClick={() => saveTrack.mutate()}
              >
                {saveTrack.isPending
                  ? "Saving..."
                  : editingTrackId
                    ? "Update track"
                    : "Create manual track"}
              </button>
              {editingTrackId && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setEditingTrackId(null);
                    setTrackJson(defaultTrackJson);
                  }}
                >
                  Cancel edit
                </button>
              )}
            </div>
            <div className="dashboard-list">
              {tracks.data?.map((track) => (
                <article key={track.id} className="dashboard-row">
                  <div>
                    <strong>Track {track.track_number}</strong>
                    <p>
                      {track.status} · {track.interpolation} ·{" "}
                      {track.keyframes.length} keyframes
                    </p>
                    <small>
                      {String(
                        track.metadata_json.tracker ??
                          track.metadata_json.source ??
                          "unknown source",
                      )}
                    </small>
                  </div>
                  <div className="dashboard-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => editTrack(track)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="danger-ghost"
                      disabled={removeTrack.isPending}
                      onClick={() => removeTrack.mutate(track.id)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Behavior analytics</p>
                <h4>Movement, schooling, occupancy, and activity</h4>
              </div>
              {selectedVideo && (
                <div className="version-actions">
                  <a
                    className="button-link secondary"
                    href={downloadUrl(
                      `/videos/${selectedVideo.id}/tracking-export?format=csv`,
                    )}
                  >
                    CSV
                  </a>
                  <a
                    className="button-link secondary"
                    href={downloadUrl(
                      `/videos/${selectedVideo.id}/tracking-export?format=mot`,
                    )}
                  >
                    MOT
                  </a>
                  <a
                    className="button-link secondary"
                    href={downloadUrl(
                      `/videos/${selectedVideo.id}/tracking-export?format=json`,
                    )}
                  >
                    ReefVision JSON
                  </a>
                </div>
              )}
            </div>
            <label>
              Zones JSON
              <textarea
                rows={9}
                value={zonesJson}
                onChange={(event) => setZonesJson(event.target.value)}
              />
            </label>
            <div className="dashboard-grid compact-grid">
              <label>
                Heatmap bins
                <input
                  type="number"
                  min="2"
                  max="100"
                  value={heatmapBins}
                  onChange={(event) =>
                    setHeatmapBins(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Active speed threshold (px/s)
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={activityThreshold}
                  onChange={(event) =>
                    setActivityThreshold(Number(event.target.value))
                  }
                />
              </label>
            </div>
            <button
              type="button"
              disabled={!selectedVideoId || analytics.isPending}
              onClick={() => analytics.mutate()}
            >
              {analytics.isPending
                ? "Analyzing..."
                : "Calculate behavior metrics"}
            </button>
            {analytics.data?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            <div className="dashboard-list">
              {analytics.data?.tracks.map((track) => (
                <article key={track.track_id} className="dashboard-row">
                  <div>
                    <strong>Track {track.tracker_id}</strong>
                    <p>
                      {track.distance_pixels.toFixed(2)} px · mean{" "}
                      {track.mean_speed_pixels_per_second.toFixed(2)} px/s · max{" "}
                      {track.maximum_speed_pixels_per_second.toFixed(2)} px/s
                    </p>
                    <small>
                      Active {track.active_time_seconds.toFixed(2)} s · inactive{" "}
                      {track.inactive_time_seconds.toFixed(2)} s
                      {track.distance_physical !== null
                        ? ` · ${track.distance_physical.toFixed(3)} ${track.physical_unit}`
                        : ""}
                    </small>
                  </div>
                  <span>
                    {Object.entries(track.zone_time_seconds)
                      .map(
                        ([zone, seconds]) => `${zone}: ${seconds.toFixed(2)} s`,
                      )
                      .join(" · ") || "No zone occupancy"}
                  </span>
                </article>
              ))}
            </div>
            {analytics.data && (
              <div className="version-preview-metrics">
                <span>
                  {analytics.data.school_by_frame.length} school frames
                </span>
                <span>
                  {analytics.data.heatmap.length} occupied heatmap cells
                </span>
                <span>
                  {
                    analytics.data.school_by_frame.filter(
                      (item) => item.active_track_count > 1,
                    ).length
                  }{" "}
                  multi-fish frames
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
