import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  benchmarkVideoTracking,
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
  videoFrameUrl,
  type VideoTrackKeyframe,
} from "./videoApi";

interface VideoTrackingWorkspaceProps {
  project: Project;
}

interface TrackingRunSummary {
  jobId: string;
  tracker: string;
  modelId: string | null;
  trackCount: number;
}

function sortedKeyframes(items: VideoTrackKeyframe[]): VideoTrackKeyframe[] {
  return [...items].sort((first, second) => first.frame - second.frame);
}

function trackerLabel(value: string): string {
  if (value.toLowerCase().includes("botsort")) return "BoT-SORT";
  if (value.toLowerCase().includes("bytetrack")) return "ByteTrack";
  return value.replace(/\.ya?ml$/i, "");
}

function toggleSelection(
  current: string[],
  value: string,
  checked: boolean,
): string[] {
  if (checked) return current.includes(value) ? current : [...current, value];
  return current.filter((item) => item !== value);
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
  const [trackerName, setTrackerName] = useState("bytetrack.yaml");
  const [groundTruthTrackIds, setGroundTruthTrackIds] = useState<string[]>([]);
  const [benchmarkJobIds, setBenchmarkJobIds] = useState<string[]>([]);
  const [benchmarkIou, setBenchmarkIou] = useState(0.5);
  const [benchmarkClassAware, setBenchmarkClassAware] = useState(true);

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

  const manualGroundTruthTracks = useMemo(
    () =>
      (tracksQuery.data ?? []).filter(
        (track) => !track.source_job_id && track.status === "verified",
      ),
    [tracksQuery.data],
  );
  const trackingRuns = useMemo(() => {
    const byJob = new Map<string, TrackingRunSummary>();
    for (const track of tracksQuery.data ?? []) {
      if (!track.source_job_id) continue;
      const rawTracker = track.metadata_json?.tracker;
      const tracker = typeof rawTracker === "string" ? rawTracker : "tracker";
      const existing = byJob.get(track.source_job_id);
      if (existing) {
        existing.trackCount += 1;
      } else {
        byJob.set(track.source_job_id, {
          jobId: track.source_job_id,
          tracker,
          modelId: track.source_model_id,
          trackCount: 1,
        });
      }
    }
    return [...byJob.values()].sort((first, second) =>
      first.jobId.localeCompare(second.jobId),
    );
  }, [tracksQuery.data]);

  useEffect(() => {
    if (!selectedVideoId && videosQuery.data?.[0]) {
      setSelectedVideoId(videosQuery.data[0].id);
    }
  }, [selectedVideoId, videosQuery.data]);
  useEffect(() => {
    setFrameIndex(0);
    setSelectedTrackId("");
    setKeyframes([]);
    setGroundTruthTrackIds([]);
    setBenchmarkJobIds([]);
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
        tracker: trackerName,
        confidence: 0.25,
        iou: 0.5,
        device: "auto",
        minimum_track_frames: 2,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["videos", project.id] });
    },
  });
  const benchmarkMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Select a video first");
      if (groundTruthTrackIds.length === 0) {
        throw new Error("Select at least one verified manual ground-truth track");
      }
      if (benchmarkJobIds.length < 2) {
        throw new Error("Select at least two machine tracking runs to compare");
      }
      const byJob = new Map(trackingRuns.map((run) => [run.jobId, run]));
      return benchmarkVideoTracking(selectedVideoId, {
        ground_truth_track_ids: groundTruthTrackIds,
        candidates: benchmarkJobIds.map((jobId) => {
          const run = byJob.get(jobId);
          return {
            name: `${trackerLabel(run?.tracker ?? "Tracker")} · ${jobId.slice(0, 8)}`,
            source_job_id: jobId,
          };
        }),
        iou_threshold: benchmarkIou,
        class_aware: benchmarkClassAware,
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
  const error =
    uploadMutation.error ??
    extractionMutation.error ??
    saveTrackMutation.error ??
    deleteTrackMutation.error ??
    trackingMutation.error ??
    benchmarkMutation.error;

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
              {selectedVideo.fps.toFixed(3)} fps
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
            value={trackerName}
            onChange={(event) => setTrackerName(event.target.value)}
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
            : `Run ${trackerLabel(trackerName)}`}
        </button>
        {trackingMutation.data && (
          <p className="annotation-helper">
            {trackerLabel(trackerName)} job {trackingMutation.data.id.slice(0, 8)}
            {" "}queued. Its tracks remain independent from other tracker runs.
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
        <p className="eyebrow">Scientific validation</p>
        <h3>Tracker benchmark</h3>
        <p className="annotation-helper">
          Compare independent tracker jobs against the same verified manual tracks.
          Ground-truth interpolation is honored; model tracks only receive credit for
          persisted observations.
        </p>
        <strong>Ground-truth tracks</strong>
        {manualGroundTruthTracks.length === 0 ? (
          <p className="annotation-helper">
            Create and verify at least one manual track before benchmarking.
          </p>
        ) : (
          <div className="annotation-selection-list">
            {manualGroundTruthTracks.map((track) => (
              <label key={track.id} className="annotation-selection-row">
                <input
                  type="checkbox"
                  checked={groundTruthTrackIds.includes(track.id)}
                  onChange={(event) =>
                    setGroundTruthTrackIds((current) =>
                      toggleSelection(current, track.id, event.target.checked),
                    )
                  }
                />
                <span>Track {track.track_number}</span>
              </label>
            ))}
          </div>
        )}
        <strong>Machine tracking runs</strong>
        {trackingRuns.length === 0 ? (
          <p className="annotation-helper">
            Run ByteTrack and BoT-SORT to create benchmark candidates.
          </p>
        ) : (
          <div className="annotation-selection-list">
            {trackingRuns.map((run) => (
              <label key={run.jobId} className="annotation-selection-row">
                <input
                  type="checkbox"
                  checked={benchmarkJobIds.includes(run.jobId)}
                  onChange={(event) =>
                    setBenchmarkJobIds((current) =>
                      toggleSelection(current, run.jobId, event.target.checked),
                    )
                  }
                />
                <span>
                  {trackerLabel(run.tracker)} · {run.jobId.slice(0, 8)} ·{" "}
                  {run.trackCount} tracks
                </span>
              </label>
            ))}
          </div>
        )}
        <label>
          Match IoU threshold
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={benchmarkIou}
            onChange={(event) => setBenchmarkIou(Number(event.target.value))}
          />
        </label>
        <label className="annotation-selection-row">
          <input
            type="checkbox"
            checked={benchmarkClassAware}
            onChange={(event) => setBenchmarkClassAware(event.target.checked)}
          />
          <span>Require matching identity class</span>
        </label>
        <button
          type="button"
          disabled={
            benchmarkMutation.isPending ||
            groundTruthTrackIds.length === 0 ||
            benchmarkJobIds.length < 2
          }
          onClick={() => benchmarkMutation.mutate()}
        >
          {benchmarkMutation.isPending ? "Evaluating..." : "Compare tracker runs"}
        </button>
        {benchmarkMutation.data && (
          <>
            <p className="annotation-helper">
              Winner: <strong>{benchmarkMutation.data.winner}</strong>. Ranking uses
              MOTA, then recall, precision, identity/fragmentation errors, and center
              error as deterministic tie-breakers.
            </p>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Run</th>
                    <th>MOTA</th>
                    <th>Recall</th>
                    <th>Precision</th>
                    <th>ID switches</th>
                    <th>Fragments</th>
                    <th>Mean IoU</th>
                    <th>Center error</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmarkMutation.data.results.map((result) => (
                    <tr key={result.name}>
                      <td>{result.rank}</td>
                      <td>{result.name}</td>
                      <td>{result.evaluation.mota.toFixed(3)}</td>
                      <td>{result.evaluation.recall.toFixed(3)}</td>
                      <td>{result.evaluation.precision.toFixed(3)}</td>
                      <td>{result.evaluation.id_switches}</td>
                      <td>{result.evaluation.fragmentations}</td>
                      <td>
                        {result.evaluation.mean_iou?.toFixed(3) ?? "—"}
                      </td>
                      <td>
                        {result.evaluation.mean_center_error_pixels === null
                          ? "—"
                          : `${result.evaluation.mean_center_error_pixels.toFixed(2)} px`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </div>
  );
}
