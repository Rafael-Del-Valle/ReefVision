import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
﻿import { AnnotatedVideoExportPanel } from "./AnnotatedVideoExportPanel";
import { GeoreferencedMapPanel } from "./GeoreferencedMapPanel";
import { GeoreferencingSetupPanel } from "./GeoreferencingSetupPanel";
import { GeographicExportPanel } from "./GeographicExportPanel";
import { GeographicMovementAnalyticsPanel } from "./GeographicMovementAnalyticsPanel";
import { useGeographicMovementAnalytics } from "./useGeographicMovementAnalytics";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { cancelJob, retryJob, type Project } from "../../api/client";
import {
  benchmarkVideoTracking,
  createVideoTrack,
  createVideoTrackingJob,
  deleteVideoTrack,
  extractVideoFrames,
  getTrackingModels,
  getVideoGeoreferencingReadiness,
  getVideoTrackAnalytics,
  getVideoTrackInterpolation,
  getVideoTrackingRuns,
  getVideoTracks,
  getVideos,
  importVideo,
  importVideoPath,
  updateVideoTrack,
  videoContentUrl,
  videoFrameUrl,
  type VideoTrackKeyframe,
} from "./videoApi";
import { trackingBenchmarkCsv, trackingBenchmarkJson } from "./trackingReport";
import {
  frameIndexForVideoTime,
  videoTimeMatchesPendingSeek,
  type PendingVideoMapSeek,
} from "./videoMapSynchronization";

interface VideoTrackingWorkspaceProps {
  project: Project;
}

function sortedKeyframes(items: VideoTrackKeyframe[]): VideoTrackKeyframe[] {
  return [...items].sort((first, second) => first.frame - second.frame);
}

function trackerLabel(value: string): string {
  if (value.toLowerCase().includes("botsort")) return "BoT-SORT";
  if (value.toLowerCase().includes("bytetrack")) return "ByteTrack";
  return value.replace(/\.ya?ml$/i, "");
}

function georeferencingReadinessLabel(state: string): string {
  const labels: Record<string, string> = {
    ready: "Ready",
    missing_calibration: "Missing calibration",
    invalid_calibration: "Invalid calibration",
    missing_surface_reference: "Missing datum",
    missing_telemetry: "Missing telemetry",
    alignment_problem: "Alignment problem",
    synchronization_problem: "Synchronization problem",
    zoom_mismatch: "Zoom mismatch",
  };
  return labels[state] ?? state;
}

function trackingPercent(current: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, (current / total) * 100);
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
  const desktopMode =
    typeof window !== "undefined" &&
    "__TAURI_INTERNALS__" in window;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingMapSeekRef = useRef<PendingVideoMapSeek | null>(null);
  const mapSeekSequenceRef = useRef(0);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [telemetryFile, setTelemetryFile] = useState<File | null>(null);
  const [airdataFile, setAirdataFile] = useState<File | null>(null);
  const [airdataTimeOffsetSeconds, setAirdataTimeOffsetSeconds] = useState(0);
  const [airdataTimeOffsetEvidence, setAirdataTimeOffsetEvidence] =
    useState("");
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [everyNFrames, setEveryNFrames] = useState(1);
  const [frameIndex, setFrameIndex] = useState(0);
  const [selectedTrackId, setSelectedTrackId] = useState("");

  // Task 16E: load only for the explicitly selected track.
  // Playback-active map tracks do not drive this request.
  const {
    state: geographicMovementAnalyticsState,
    reload: reloadGeographicMovementAnalytics,
  } = useGeographicMovementAnalytics(selectedTrackId || null);
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
  const [trackingConfidence, setTrackingConfidence] = useState(0.25);
  const [trackingIou, setTrackingIou] = useState(0.5);
  const [trackingDevice, setTrackingDevice] = useState("auto");
  const [minimumTrackFrames, setMinimumTrackFrames] = useState(2);

  const [groundTruthTrackIds, setGroundTruthTrackIds] = useState<string[]>([]);
  const [benchmarkJobIds, setBenchmarkJobIds] = useState<string[]>([]);
  const [benchmarkIou, setBenchmarkIou] = useState(0.5);
  const [benchmarkClassAware, setBenchmarkClassAware] = useState(true);
  const [benchmarkStartFrame, setBenchmarkStartFrame] = useState(0);
  const [benchmarkEndFrame, setBenchmarkEndFrame] = useState(0);
  const [copiedReport, setCopiedReport] = useState<"json" | "csv" | null>(null);

  const videosQuery = useQuery({
    queryKey: ["videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
    refetchInterval: 3000,
  });
  const selectedVideo = videosQuery.data?.find(
    (video) => video.id === selectedVideoId,
  );
  const georeferencingReadinessQuery = useQuery({
    queryKey: ["video-georeferencing-readiness", selectedVideoId],
    queryFn: ({ signal }) =>
      getVideoGeoreferencingReadiness(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
    refetchInterval: 3000,
  });
  const tracksQuery = useQuery({
    queryKey: ["video-tracks", selectedVideoId],
    queryFn: ({ signal }) => getVideoTracks(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
    refetchInterval: 3000,
  });
  const trackingRunsQuery = useQuery({
    queryKey: ["video-tracking-runs", selectedVideoId],
    queryFn: ({ signal }) => getVideoTrackingRuns(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
    refetchInterval: 1000,
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
  const succeededTrackingRuns = useMemo(
    () =>
      (trackingRunsQuery.data ?? []).filter(
        (run) => run.status === "succeeded",
      ),
    [trackingRunsQuery.data],
  );

  useEffect(() => {
    if (!selectedVideoId && videosQuery.data?.[0]) {
      setSelectedVideoId(videosQuery.data[0].id);
    }
  }, [selectedVideoId, videosQuery.data]);
  useEffect(() => {
    pendingMapSeekRef.current = null;
    setFrameIndex(0);
    setSelectedTrackId("");
    setKeyframes([]);
    setGroundTruthTrackIds([]);
    setBenchmarkJobIds([]);
    setBenchmarkStartFrame(0);
    setBenchmarkEndFrame(0);
    setCopiedReport(null);
  }, [selectedVideoId]);
  useEffect(() => {
    if (selectedVideo) {
      setBenchmarkEndFrame(Math.max(0, selectedVideo.frame_count - 1));
    }
  }, [selectedVideo]);
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

  const desktopPathMutation = useMutation({
    mutationFn: (sourcePath: string) =>
      importVideoPath(project.id, sourcePath),
    onSuccess: async (video) => {
      setSelectedVideoId(video.id);
      setUploadFile(null);
      setTelemetryFile(null);
      setAirdataFile(null);
      setAirdataTimeOffsetSeconds(0);
      setAirdataTimeOffsetEvidence("");
      await queryClient.invalidateQueries({
        queryKey: ["videos", project.id],
      });
    },
  });

  async function chooseDesktopVideo(): Promise<void> {
    const selection = await openFileDialog({
      multiple: false,
      directory: false,
      filters: [
        {
          name: "Video",
          extensions: [
            "avi",
            "m4v",
            "mkv",
            "mov",
            "mp4",
            "webm",
          ],
        },
      ],
    });

    if (typeof selection !== "string") {
      return;
    }

    desktopPathMutation.mutate(selection);
  }

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!uploadFile) throw new Error("Choose a video file first");
      if (
        airdataFile &&
        airdataTimeOffsetSeconds !== 0 &&
        !airdataTimeOffsetEvidence.trim()
      ) {
        throw new Error(
          "Nonzero AirData time offsets require alignment evidence",
        );
      }
      return importVideo(project.id, uploadFile, {
        telemetryFile,
        airdataFile,
        airdataTimeOffsetSeconds,
        airdataTimeOffsetEvidence,
      });
    },
    onSuccess: async (video) => {
      setSelectedVideoId(video.id);
      setUploadFile(null);
      setTelemetryFile(null);
      setAirdataFile(null);
      setAirdataTimeOffsetSeconds(0);
      setAirdataTimeOffsetEvidence("");
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
    mutationFn: () => {
      if (trackingConfidence < 0 || trackingConfidence > 1) {
        throw new Error("Tracking confidence must be between 0 and 1");
      }
      if (trackingIou < 0 || trackingIou > 1) {
        throw new Error("Tracking IoU must be between 0 and 1");
      }
      if (minimumTrackFrames < 1) {
        throw new Error("Minimum track frames must be at least 1");
      }
      return createVideoTrackingJob(selectedVideoId, {
        model_id: trackingModelId,
        tracker: trackerName,
        confidence: trackingConfidence,
        iou: trackingIou,
        device: trackingDevice,
        minimum_track_frames: minimumTrackFrames,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["videos", project.id] }),
        queryClient.invalidateQueries({
          queryKey: ["video-tracking-runs", selectedVideoId],
        }),
      ]);
    },
  });
  const cancelTrackingMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["video-tracking-runs", selectedVideoId],
      });
    },
  });
  const retryTrackingMutation = useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["video-tracking-runs", selectedVideoId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["videos", project.id],
        }),
      ]);
    },
  });
  const benchmarkMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Select a video first");
      if (groundTruthTrackIds.length === 0) {
        throw new Error(
          "Select at least one verified manual ground-truth track",
        );
      }
      if (benchmarkJobIds.length < 2) {
        throw new Error(
          "Select at least two succeeded tracking runs to compare",
        );
      }
      if (benchmarkEndFrame < benchmarkStartFrame) {
        throw new Error(
          "Benchmark end frame must be at or after the start frame",
        );
      }
      const byJob = new Map(
        succeededTrackingRuns.map((run) => [run.job_id, run]),
      );
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
        start_frame: benchmarkStartFrame,
        end_frame: benchmarkEndFrame,
      });
    },
    onSuccess: () => setCopiedReport(null),
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
    cancelTrackingMutation.error ??
    retryTrackingMutation.error ??
    benchmarkMutation.error ??
    trackingRunsQuery.error;

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

  async function copyBenchmarkReport(kind: "json" | "csv") {
    if (!benchmarkMutation.data) return;
    const content =
      kind === "json"
        ? trackingBenchmarkJson(benchmarkMutation.data)
        : trackingBenchmarkCsv(benchmarkMutation.data);
    await navigator.clipboard.writeText(content);
    setCopiedReport(kind);
  }

  function synchronizeFrameFromVideoTime(currentTimeSeconds: number) {
    if (!selectedVideo) return;

    const pending = pendingMapSeekRef.current;

    if (
      !videoTimeMatchesPendingSeek(
        pending,
        currentTimeSeconds,
        selectedVideo.fps,
      )
    ) {
      return;
    }

    if (pending) {
      pendingMapSeekRef.current = null;
    }

    setFrameIndex(
      frameIndexForVideoTime(
        currentTimeSeconds,
        selectedVideo.fps,
        selectedVideo.frame_count,
      ),
    );
  }

  function seekVideoFromMap(
    selectedFrameIndex: number,
    frameTimeSeconds: number,
  ) {
    if (!selectedVideo) return;

    mapSeekSequenceRef.current += 1;

    pendingMapSeekRef.current = {
      sequence: mapSeekSequenceRef.current,
      frameIndex: selectedFrameIndex,
      frameTimeSeconds,
    };

    setFrameIndex(
      Math.min(
        Math.max(0, selectedFrameIndex),
        Math.max(0, selectedVideo.frame_count - 1),
      ),
    );

    const video = videoRef.current;

    if (!video || !Number.isFinite(frameTimeSeconds)) {
      return;
    }

    const maximumTime =
      selectedVideo.duration_seconds > 0
        ? selectedVideo.duration_seconds
        : frameTimeSeconds;

    video.currentTime = Math.min(Math.max(0, frameTimeSeconds), maximumTime);
  }

  const handleGeographicFrameSelect: (
    frameIndex: number,
    frameTimeSeconds: number,
  ) => void = (selectedFrameIndex, frameTimeSeconds) => {
    seekVideoFromMap(selectedFrameIndex, frameTimeSeconds);
  };

  return (
    <div
      className="management-grid"
      data-testid="video-tracking-workspace"

      data-geographic-analytics-status={geographicMovementAnalyticsState.status}
      data-geographic-analytics-track-id={
        geographicMovementAnalyticsState.trackId ?? ""
      }
    >
      <section className="management-card workspace-guide-card">
        <div>
          <p className="eyebrow">Video &amp; tracking</p>
          <h3>From video to reviewed tracks</h3>
          <p className="muted-copy">
            Import once, extract only the frames you need for review, run
            automated tracking, then verify/edit tracks before using behavior or
            benchmark metrics.
          </p>
        </div>
        <div
          className="workspace-guide compact"
          aria-label="Video tracking workflow"
        >
          <div className="workspace-guide-step">
            <span>1</span>
            <div>
              <strong>Import</strong>
              <small>Select a managed video.</small>
            </div>
          </div>
          <div className="workspace-guide-step">
            <span>2</span>
            <div>
              <strong>Track</strong>
              <small>Run or edit object tracks.</small>
            </div>
          </div>
          <div className="workspace-guide-step">
            <span>3</span>
            <div>
              <strong>Review</strong>
              <small>Verify keyframes and identities.</small>
            </div>
          </div>
          <div className="workspace-guide-step">
            <span>4</span>
            <div>
              <strong>Analyze</strong>
              <small>Use science and benchmark outputs.</small>
            </div>
          </div>
        </div>
      </section>
      <section className="management-card">
        <p className="eyebrow">Research workflow</p>
        <h3>Managed videos</h3>
        {desktopMode && (
          <div className="workspace-guide compact">
            <div>
              <strong>Automatic telemetry import</strong>
              <p className="annotation-helper">
                Select a local video and ReefVision will automatically
                attach its matching DJI SRT and the single valid sibling
                AirData CSV when available. Manual inputs below remain
                available as overrides.
              </p>
              <button
                type="button"
                onClick={() => void chooseDesktopVideo()}
                disabled={desktopPathMutation.isPending}
              >
                {desktopPathMutation.isPending
                  ? "Importing video..."
                  : "Choose video ? auto SRT/AirData"}
              </button>
              {desktopPathMutation.error && (
                <p className="form-error">
                  {desktopPathMutation.error.message}
                </p>
              )}
            </div>
          </div>
        )}
        <label>
          Video file
          <input
            type="file"
            accept="video/*,.avi,.m4v,.mkv,.mov,.mp4,.webm"
            onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          DJI SRT telemetry (optional)
          <input
            type="file"
            accept=".srt,text/plain,application/x-subrip"
            onChange={(event) =>
              setTelemetryFile(event.target.files?.[0] ?? null)
            }
          />
        </label>
        <label>
          AirData CSV telemetry (optional)
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) =>
              setAirdataFile(event.target.files?.[0] ?? null)
            }
          />
        </label>
        {airdataFile && (
          <div className="workspace-guide compact">
            <label>
              AirData time offset (seconds)
              <input
                type="number"
                step="0.01"
                value={airdataTimeOffsetSeconds}
                onChange={(event) =>
                  setAirdataTimeOffsetSeconds(Number(event.target.value))
                }
              />
            </label>
            <label>
              Alignment evidence
              <textarea
                value={airdataTimeOffsetEvidence}
                onChange={(event) =>
                  setAirdataTimeOffsetEvidence(event.target.value)
                }
                placeholder="Describe how this AirData/video offset was established."
              />
            </label>
            <p className="annotation-helper">
              Use 0 when AirData time already matches video-relative time. Any
              nonzero offset requires evidence and is persisted with the video.
            </p>
          </div>
        )}
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
              ref={videoRef}
              controls
              src={videoContentUrl(selectedVideo.id)}
              onTimeUpdate={(event) =>
                synchronizeFrameFromVideoTime(event.currentTarget.currentTime)
              }
              onSeeked={(event) =>
                synchronizeFrameFromVideoTime(event.currentTarget.currentTime)
              }
              style={{ width: "100%", maxHeight: 360 }}
            />
            <p className="annotation-helper">
              {selectedVideo.width_px}×{selectedVideo.height_px} |{" "}
              {selectedVideo.frame_count.toLocaleString()} frames |{" "}
              {selectedVideo.fps.toFixed(3)} fps
            </p>
            <p className="annotation-helper">
              SRT:{" "}
              {selectedVideo.telemetry.available
                ? `${selectedVideo.telemetry.sample_count.toLocaleString()} samples`
                : "not available"}{" "}
              | AirData:{" "}
              {selectedVideo.airdata_telemetry.available
                ? `${selectedVideo.airdata_telemetry.sample_count.toLocaleString()} samples`
                : "not available"}
              {selectedVideo.airdata_telemetry.available
                ? ` | offset ${selectedVideo.airdata_alignment.time_offset_s.toFixed(2)} s`
                : ""}
            </p>
            <div
              className="workspace-guide compact"
              aria-label="Georeferencing readiness"
            >
              <div>
                <strong>Georeferencing</strong>
                {georeferencingReadinessQuery.isLoading && (
                  <p className="annotation-helper">Checking readiness...</p>
                )}
                {georeferencingReadinessQuery.error && (
                  <p className="error-copy">
                    {georeferencingReadinessQuery.error.message}
                  </p>
                )}
                {georeferencingReadinessQuery.data && (
                  <>
                    <p className="annotation-helper">
                      Status:{" "}
                      <strong>
                        {georeferencingReadinessLabel(
                          georeferencingReadinessQuery.data.state,
                        )}
                      </strong>
                    </p>
                    <p className="annotation-helper">
                      Sync:{" "}
                      {
                        georeferencingReadinessQuery.data
                          .synchronized_frame_count
                      }
                      /{georeferencingReadinessQuery.data.sampled_frame_count}{" "}
                      representative frames
                      {georeferencingReadinessQuery.data
                        .maximum_sync_error_s !== null
                        ? ` | max ${(
                            georeferencingReadinessQuery.data
                              .maximum_sync_error_s * 1000
                          ).toFixed(1)} ms`
                        : ""}
                    </p>
                    {georeferencingReadinessQuery.data.issues.length > 0 && (
                      <ul>
                        {georeferencingReadinessQuery.data.issues.map(
                          (issue) => (
                            <li key={issue.code}>{issue.message}</li>
                          ),
                        )}
                      </ul>
                    )}
                  </>
                )}
              </div>
            </div>
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

      {selectedVideo && (
        <GeoreferencingSetupPanel project={project} video={selectedVideo} />
      )}

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

      {selectedVideo && (
        <GeoreferencedMapPanel
          key={selectedVideo.id}
          videoId={selectedVideo.id}
          activeFrameIndex={frameIndex}
          onFrameSelect={handleGeographicFrameSelect}
        />
      )}

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
        <label>
          Detection confidence
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={trackingConfidence}
            onChange={(event) =>
              setTrackingConfidence(Number(event.target.value))
            }
          />
        </label>
        <label>
          Detector IoU
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={trackingIou}
            onChange={(event) => setTrackingIou(Number(event.target.value))}
          />
        </label>
        <label>
          Device
          <select
            value={trackingDevice}
            onChange={(event) => setTrackingDevice(event.target.value)}
          >
            <option value="auto">Auto</option>
            <option value="cpu">CPU</option>
            <option value="0">CUDA device 0</option>
          </select>
        </label>
        <label>
          Minimum observations per retained track
          <input
            type="number"
            min={1}
            step={1}
            value={minimumTrackFrames}
            onChange={(event) =>
              setMinimumTrackFrames(Number(event.target.value))
            }
          />
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
            Tracking job {trackingMutation.data.id.slice(0, 8)} queued. Run
            history retains independent ByteTrack and BoT-SORT outputs,
            including zero-track results.
          </p>
        )}
        {(trackingRunsQuery.data ?? []).length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Tracker</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Detections</th>
                  <th>Observations</th>
                  <th>Tracks</th>
                  <th>Confidence</th>
                  <th>IoU</th>
                  <th>Device</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(trackingRunsQuery.data ?? []).map((run) => {
                  const active =
                    run.status === "queued" ||
                    run.status === "running" ||
                    run.status === "cancel_requested";
                  return (
                    <tr key={run.job_id}>
                      <td>{run.job_id.slice(0, 8)}</td>
                      <td>{trackerLabel(run.tracker)}</td>
                      <td>
                        {run.stale ? <strong>Stalled</strong> : run.stage}
                        {run.stale && (
                          <div className="form-error">
                            No heartbeat for more than two minutes.
                          </div>
                        )}
                      </td>
                      <td>
                        <div>
                          {run.progress_current.toLocaleString()} /{" "}
                          {run.progress_total.toLocaleString()}
                        </div>
                        <progress
                          value={run.progress_current}
                          max={Math.max(1, run.progress_total)}
                        />
                        <div>
                          {trackingPercent(
                            run.progress_current,
                            run.progress_total,
                          ).toFixed(1)}
                          %
                        </div>
                      </td>
                      <td>{run.live_detection_count.toLocaleString()}</td>
                      <td>
                        {(active
                          ? run.live_observation_count
                          : run.observation_count
                        ).toLocaleString()}
                      </td>
                      <td>
                        {(active
                          ? run.live_tracks_seen
                          : run.track_count
                        ).toLocaleString()}
                      </td>
                      <td>{run.confidence.toFixed(2)}</td>
                      <td>{run.iou.toFixed(2)}</td>
                      <td>{run.device}</td>
                      <td>
                        {active && run.status !== "cancel_requested" && (
                          <button
                            type="button"
                            className="danger-ghost"
                            disabled={cancelTrackingMutation.isPending}
                            onClick={() =>
                              cancelTrackingMutation.mutate(run.job_id)
                            }
                          >
                            Cancel
                          </button>
                        )}
                        {run.status === "failed" && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={retryTrackingMutation.isPending}
                            onClick={() =>
                              retryTrackingMutation.mutate(run.job_id)
                            }
                          >
                            Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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

      <GeographicMovementAnalyticsPanel
        state={geographicMovementAnalyticsState}
        onReload={reloadGeographicMovementAnalytics}
        activeFrameIndex={frameIndex}
        onFrameSelect={handleGeographicFrameSelect}
      />

      <GeographicExportPanel
        videoId={selectedVideoId || null}
        selectedTrackId={selectedTrackId || null}
      />

      <AnnotatedVideoExportPanel
        videoId={selectedVideoId || null}
        trackingRuns={trackingRunsQuery.data ?? []}
      />

      <section className="management-card">
        <p className="eyebrow">Scientific validation</p>
        <h3>Tracker benchmark</h3>
        <p className="annotation-helper">
          Compare independent tracking jobs against the same verified manual
          tracks. Manual ground truth may interpolate between keyframes; machine
          tracks only receive credit for observations actually produced by the
          tracker.
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
        <strong>Succeeded machine tracking runs</strong>
        {succeededTrackingRuns.length === 0 ? (
          <p className="annotation-helper">
            Run ByteTrack and BoT-SORT to create benchmark candidates.
          </p>
        ) : (
          <div className="annotation-selection-list">
            {succeededTrackingRuns.map((run) => (
              <label key={run.job_id} className="annotation-selection-row">
                <input
                  type="checkbox"
                  checked={benchmarkJobIds.includes(run.job_id)}
                  onChange={(event) =>
                    setBenchmarkJobIds((current) =>
                      toggleSelection(
                        current,
                        run.job_id,
                        event.target.checked,
                      ),
                    )
                  }
                />
                <span>
                  {trackerLabel(run.tracker)} · {run.job_id.slice(0, 8)} ·{" "}
                  {run.track_count} tracks / {run.observation_count}{" "}
                  observations
                </span>
              </label>
            ))}
          </div>
        )}
        <label>
          Benchmark start frame
          <input
            type="number"
            min={0}
            max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
            value={benchmarkStartFrame}
            onChange={(event) =>
              setBenchmarkStartFrame(Number(event.target.value))
            }
          />
        </label>
        <label>
          Benchmark end frame
          <input
            type="number"
            min={0}
            max={Math.max(0, (selectedVideo?.frame_count ?? 1) - 1)}
            value={benchmarkEndFrame}
            onChange={(event) =>
              setBenchmarkEndFrame(Number(event.target.value))
            }
          />
        </label>
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
          {benchmarkMutation.isPending
            ? "Evaluating..."
            : "Compare tracker runs"}
        </button>
        {benchmarkMutation.data && (
          <>
            <p className="annotation-helper">
              Winner: <strong>{benchmarkMutation.data.winner}</strong>. Ranking
              uses MOTA, then recall, precision, identity/fragmentation errors,
              and center error as deterministic tie-breakers.
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
                      <td>{result.evaluation.mean_iou?.toFixed(3) ?? "—"}</td>
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
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => void copyBenchmarkReport("json")}
              >
                {copiedReport === "json"
                  ? "JSON copied"
                  : "Copy benchmark JSON"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void copyBenchmarkReport("csv")}
              >
                {copiedReport === "csv" ? "CSV copied" : "Copy benchmark CSV"}
              </button>
            </div>
            <details>
              <summary>Reproducibility details</summary>
              <pre style={{ overflowX: "auto", whiteSpace: "pre-wrap" }}>
                {trackingBenchmarkJson(benchmarkMutation.data)}
              </pre>
            </details>
          </>
        )}
      </section>

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </div>
  );
}
