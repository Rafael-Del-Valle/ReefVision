import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import { AnnotatedVideoExportPanel } from "./AnnotatedVideoExportPanel";
import { BehaviorDynamicsPanel } from "./BehaviorDynamicsPanel";
import { GeoreferencedMapPanel } from "./GeoreferencedMapPanel";
import { GeoreferencingSetupPanel } from "./GeoreferencingSetupPanel";
import { GeographicExportPanel } from "./GeographicExportPanel";
import { GeographicMovementAnalyticsPanel } from "./GeographicMovementAnalyticsPanel";
import { PoseActiveLearningPanel } from "./PoseActiveLearningPanel";
import {
  reviewPoseActiveLearningCandidate,
  type PoseActiveLearningCandidate,
} from "./poseActiveLearningApi";
import { PoseTemporalReviewPanel } from "./PoseTemporalReviewPanel";
import { PoseVisualizationPanel } from "./PoseVisualizationPanel";
import {
  importPoseInteroperability,
  poseInteroperabilityExportUrl,
  type PoseInteroperabilityFormat,
} from "./poseInteroperabilityApi";
import { useGeographicMovementAnalytics } from "./useGeographicMovementAnalytics";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { cancelJob, retryJob, type Project } from "../../api/client";
import { PoseAnnotationEditor } from "../pose/PoseAnnotationEditor";
import type { PoseSaveRequest } from "../pose/types";
import {
  correctedVideoKeyframeFromPoseSave,
  editorSchemaForVideoTrack,
  poseInstanceFromVideoKeyframe,
} from "./poseKeyframeAdapter";
import {
  benchmarkVideoTracking,
  createVideoTrack,
  createVideoTrackingJob,
  deleteTrackingModel,
  deleteVideoTrack,
  deleteVideoTracks,
  extractVideoFrames,
  getTrackingModels,
  getVideoFrameSpatialMetrics,
  getVideoGeoreferencingReadiness,
  getVideoTrackAnalytics,
  getVideoTrackInterpolation,
  getVideoTrackingRuns,
  getVideoTracks,
  getVideos,
  importVideo,
  importVideoPath,
  poseLandmarkSchemaFromMetadata,
  setPoseLandmarkSchema,
  updateVideoTrack,
  videoContentUrl,
  videoFrameUrl,
  type PoseLandmarkGroup,
  type VideoTrackKeyframe,
} from "./videoApi";
import { trackingBenchmarkCsv, trackingBenchmarkJson } from "./trackingReport";
import type {
  VideoWorkspaceCommand,
  VideoWorkspaceContext,
  VideoWorkspaceTrackSource,
} from "./videoWorkspaceBridge";
import {
  frameIndexForVideoTime,
  videoTimeMatchesPendingSeek,
  type PendingVideoMapSeek,
} from "./videoMapSynchronization";

interface VideoTrackingWorkspaceProps {
  project: Project;
  onWorkspaceContextChange?: (context: VideoWorkspaceContext | null) => void;
  workspaceCommand?: VideoWorkspaceCommand | null;
  onWorkspaceCommandHandled?: (commandId: number) => void;
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
  onWorkspaceContextChange,
  workspaceCommand = null,
  onWorkspaceCommandHandled,
}: VideoTrackingWorkspaceProps) {
  const queryClient = useQueryClient();
  const desktopMode =
    typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingMapSeekRef = useRef<PendingVideoMapSeek | null>(null);
  const mapSeekSequenceRef = useRef(0);
  const lastWorkspaceCommandIdRef = useRef(0);
  const previousSelectedVideoIdRef = useRef("");
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
  const [
    activePoseActiveLearningCandidate,
    setActivePoseActiveLearningCandidate,
  ] = useState<PoseActiveLearningCandidate | null>(null);

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
  const [poseInteropImportFile, setPoseInteropImportFile] =
    useState<File | null>(null);
  const [poseInteropImportFormat, setPoseInteropImportFormat] =
    useState<PoseInteroperabilityFormat>("slp");
  const [confirmPoseInteropFrameMapping, setConfirmPoseInteropFrameMapping] =
    useState(false);

  const [trackingModelId, setTrackingModelId] = useState("");
  const [trackerName, setTrackerName] = useState("bytetrack.yaml");
  const [trackingConfidence, setTrackingConfidence] = useState(0.25);
  const [trackingIou, setTrackingIou] = useState(0.5);
  const [trackingDevice, setTrackingDevice] = useState("auto");
  const [minimumTrackFrames, setMinimumTrackFrames] = useState(2);
  const [linkDetections, setLinkDetections] = useState(true);
  const [poseLandmarkGroups, setPoseLandmarkGroups] = useState<
    PoseLandmarkGroup[]
  >([]);
  const [showMovementLines, setShowMovementLines] = useState(true);
  const [sourceOverlayEnabled, setSourceOverlayEnabled] = useState(false);
  const [previewFrameIndex, setPreviewFrameIndex] = useState(0);

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
    enabled: Boolean(selectedTrackId) && sourceOverlayEnabled,
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
  const selectedTrackingModel = modelsQuery.data?.find(
    (model) => model.id === trackingModelId,
  );
  const poseTrackingSelected = selectedTrackingModel?.task === "pose";
  const sleapTrackingSelected =
    selectedTrackingModel?.provider_name === "sleap_nn";
  const selectedModelPoseSchema = poseLandmarkSchemaFromMetadata(
    selectedTrackingModel?.metadata_json,
  );
  const rawPoseKeypointShape =
    selectedTrackingModel?.metadata_json.pose_keypoint_shape;
  const poseExpectedLandmarkCount =
    Array.isArray(rawPoseKeypointShape) &&
    typeof rawPoseKeypointShape[0] === "number"
      ? rawPoseKeypointShape[0]
      : null;
  const poseConfiguredLandmarkCount = poseLandmarkGroups.reduce(
    (total, group) => total + group.count,
    0,
  );
  const poseLandmarkSchemaValid =
    poseLandmarkGroups.length > 0 &&
    poseLandmarkGroups.every(
      (group) => group.name.trim().length > 0 && group.count >= 1,
    ) &&
    (poseExpectedLandmarkCount === null ||
      poseConfiguredLandmarkCount === poseExpectedLandmarkCount);
  const selectedTrackPoseSchema = poseLandmarkSchemaFromMetadata(
    selectedTrack?.metadata_json,
  );

  const videoWorkspaceContext = useMemo<VideoWorkspaceContext>(() => {
    const videos = (videosQuery.data ?? []).map((video) => ({
      id: video.id,
      filename: video.original_filename,
      status: video.status,
      frameCount: video.frame_count,
      fps: video.fps,
      durationSeconds: video.duration_seconds,
    }));

    const sourceForTrack = (
      track: NonNullable<typeof tracksQuery.data>[number],
    ): VideoWorkspaceTrackSource => {
      if (
        track.status.toLowerCase().includes("imported") ||
        track.metadata_json?.imported === true
      ) {
        return "imported";
      }

      return track.source_job_id ? "machine" : "manual";
    };

    const tracks = (tracksQuery.data ?? []).map((track) => ({
      id: track.id,
      trackNumber: track.track_number,
      status: track.status,
      source: sourceForTrack(track),
      hasPose: poseLandmarkSchemaFromMetadata(track.metadata_json) !== null,
      keyframeCount: track.keyframes_json.length,
    }));

    const selectedFrame =
      selectedTrack?.keyframes_json.find(
        (keyframe) => keyframe.frame === frameIndex,
      ) ?? null;

    const observations = selectedFrame?.pose_observations ?? [];
    const keypoints = selectedFrame?.keypoints ?? [];

    const confidenceValues =
      observations.length > 0
        ? observations
            .map((observation) => observation.confidence)
            .filter(
              (confidence): confidence is number =>
                typeof confidence === "number" && Number.isFinite(confidence),
            )
        : keypoints
            .map((point) => point[2])
            .filter(
              (confidence) =>
                typeof confidence === "number" &&
                Number.isFinite(confidence) &&
                confidence > 0,
            );

    const currentPoseObservationCount =
      observations.length > 0 ? observations.length : keypoints.length;

    const currentPoseVisibleCount =
      observations.length > 0
        ? observations.filter(
            (observation) =>
              observation.status === "visible" ||
              observation.status === "uncertain",
          ).length
        : keypoints.filter((point) => point[2] > 0).length;

    const currentPoseMeanConfidence =
      confidenceValues.length > 0
        ? confidenceValues.reduce((total, value) => total + value, 0) /
          confidenceValues.length
        : null;

    const sortedRuns = [...(trackingRunsQuery.data ?? [])].sort(
      (left, right) =>
        new Date(right.created_at).getTime() -
        new Date(left.created_at).getTime(),
    );

    const activeTrackingRuns = sortedRuns.filter(
      (run) =>
        !["succeeded", "failed", "cancelled"].includes(
          run.status.toLowerCase(),
        ),
    );

    return {
      projectId: project.id,
      videos,

      selectedVideoId: selectedVideo?.id ?? null,
      selectedVideoFilename: selectedVideo?.original_filename ?? null,
      selectedVideoStatus: selectedVideo?.status ?? null,

      frameIndex,
      frameCount: selectedVideo?.frame_count ?? 0,
      fps: selectedVideo?.fps ?? 0,
      durationSeconds: selectedVideo?.duration_seconds ?? 0,

      tracks,

      selectedTrackId: selectedTrack?.id ?? null,
      selectedTrackNumber: selectedTrack?.track_number ?? null,
      selectedTrackStatus: selectedTrack?.status ?? null,
      selectedTrackSource: selectedTrack ? sourceForTrack(selectedTrack) : null,
      selectedTrackHasPose: selectedTrackPoseSchema !== null,
      selectedTrackKeyframeFrames: selectedTrack
        ? selectedTrack.keyframes_json
            .map((keyframe) => keyframe.frame)
            .sort((left, right) => left - right)
        : [],

      poseGroups:
        selectedTrackPoseSchema?.groups.map((group) => ({
          name: group.name,
          count: group.count,
        })) ?? [],

      currentPoseObservationCount,
      currentPoseVisibleCount,
      currentPoseMeanConfidence,

      activeTrackingRunCount: activeTrackingRuns.length,
      latestTrackingRunStatus: sortedRuns[0]?.status ?? null,
      latestTrackingRunStage: sortedRuns[0]?.stage ?? null,
    };
  }, [
    frameIndex,
    project.id,
    selectedTrack,
    selectedVideo,
    trackingRunsQuery.data,
    tracksQuery.data,
    videosQuery.data,
  ]);

  useEffect(() => {
    onWorkspaceContextChange?.(videoWorkspaceContext);
  }, [onWorkspaceContextChange, videoWorkspaceContext]);

  useEffect(
    () => () => {
      onWorkspaceContextChange?.(null);
    },
    [onWorkspaceContextChange, project.id],
  );
  const spatialMetricsQuery = useQuery({
    queryKey: [
      "video-frame-spatial-metrics",
      selectedVideoId,
      previewFrameIndex,
    ],
    queryFn: ({ signal }) =>
      getVideoFrameSpatialMetrics(selectedVideoId, previewFrameIndex, signal),
    enabled: Boolean(selectedVideoId) && sourceOverlayEnabled,
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

  const trackClassById = useMemo(
    () =>
      Object.fromEntries(
        (tracksQuery.data ?? []).map((track) => [
          track.id,
          track.label_class_id,
        ]),
      ),
    [tracksQuery.data],
  );

  useEffect(() => {
    if (!selectedVideoId && videosQuery.data?.[0]) {
      setSelectedVideoId(videosQuery.data[0].id);
    }
  }, [selectedVideoId, videosQuery.data]);
  useEffect(() => {
    const previousVideoId = previousSelectedVideoIdRef.current;
    previousSelectedVideoIdRef.current = selectedVideoId;
    // The first asynchronously loaded video is not a user-initiated switch.
    // Do not clear a pose file or its explicit frame-mapping confirmation if
    // the user starts interacting as soon as the initial video appears.
    if (!previousVideoId || previousVideoId === selectedVideoId) return;
    pendingMapSeekRef.current = null;
    setFrameIndex(0);
    setPreviewFrameIndex(0);
    setSelectedTrackId("");
    setKeyframes([]);
    setGroundTruthTrackIds([]);
    setBenchmarkJobIds([]);
    setBenchmarkStartFrame(0);
    setBenchmarkEndFrame(0);
    setCopiedReport(null);
    setPoseInteropImportFile(null);
    setConfirmPoseInteropFrameMapping(false);
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
    if (!poseTrackingSelected) {
      setPoseLandmarkGroups([]);
      return;
    }
    const schema = poseLandmarkSchemaFromMetadata(
      selectedTrackingModel?.metadata_json,
    );
    setPoseLandmarkGroups(schema?.groups ?? []);
  }, [
    poseTrackingSelected,
    selectedTrackingModel?.id,
    selectedTrackingModel?.updated_at,
  ]);

  useEffect(() => {
    if (!sourceOverlayEnabled) return;
    const timer = window.setTimeout(() => {
      const stride = Math.max(
        1,
        Number(
          selectedVideo?.metadata_json.extraction_every_n_frames ??
            everyNFrames,
        ),
      );
      const maximumFrame = Math.max(0, (selectedVideo?.frame_count ?? 1) - 1);
      const snappedFrame = Math.min(
        maximumFrame,
        Math.max(0, Math.round(frameIndex / stride) * stride),
      );
      setPreviewFrameIndex(snappedFrame);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [
    everyNFrames,
    frameIndex,
    selectedVideo?.frame_count,
    selectedVideo?.metadata_json.extraction_every_n_frames,
    sourceOverlayEnabled,
  ]);
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

  const poseInteropImportMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video first");
      if (!poseInteropImportFile) {
        throw new Error("Choose a pose interoperability file first");
      }
      if (!labelClassId) throw new Error("Choose a target identity class");
      return importPoseInteroperability(
        selectedVideoId,
        poseInteropImportFormat,
        poseInteropImportFile,
        labelClassId,
        confirmPoseInteropFrameMapping,
      );
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["video-tracks", selectedVideoId],
      });
      setPoseInteropImportFile(null);
      setConfirmPoseInteropFrameMapping(false);
      setSelectedTrackId(result.created_track_ids[0] ?? "");
    },
  });

  const desktopPathMutation = useMutation({
    mutationFn: (sourcePath: string) => importVideoPath(project.id, sourcePath),
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
          extensions: ["avi", "m4v", "mkv", "mov", "mp4", "webm"],
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
  const deleteMachineTracksMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Select a video first");
      return deleteVideoTracks(selectedVideoId, true);
    },
    onSuccess: async () => {
      setSelectedTrackId("");
      setKeyframes([]);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["video-tracks", selectedVideoId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-frame-spatial-metrics", selectedVideoId],
        }),
      ]);
    },
  });
  const deleteModelMutation = useMutation({
    mutationFn: () => {
      if (!trackingModelId) throw new Error("Select a model first");
      return deleteTrackingModel(trackingModelId);
    },
    onSuccess: async () => {
      setTrackingModelId("");
      await queryClient.invalidateQueries({
        queryKey: ["video-tracking-models", project.id],
      });
    },
  });
  const poseSchemaMutation = useMutation({
    mutationFn: () => {
      if (!trackingModelId || !poseTrackingSelected) {
        throw new Error("Select a pose model first");
      }
      if (!poseLandmarkSchemaValid) {
        throw new Error(
          "Landmark groups must be named and match the checkpoint keypoint count",
        );
      }
      return setPoseLandmarkSchema(
        trackingModelId,
        poseLandmarkGroups.map((group) => ({
          name: group.name.trim(),
          count: group.count,
        })),
      );
    },
    onSuccess: async (model) => {
      const schema = poseLandmarkSchemaFromMetadata(model.metadata_json);
      setPoseLandmarkGroups(schema?.groups ?? []);
      await queryClient.invalidateQueries({
        queryKey: ["video-tracking-models", project.id],
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
      if (linkDetections && minimumTrackFrames < 1) {
        throw new Error("Minimum track frames must be at least 1");
      }
      if (poseTrackingSelected && selectedModelPoseSchema === null) {
        throw new Error(
          "Save a ReefVision landmark schema before running pose inference",
        );
      }
      return createVideoTrackingJob(selectedVideoId, {
        model_id: trackingModelId,
        tracker: trackerName,
        confidence: trackingConfidence,
        iou: trackingIou,
        device: trackingDevice,
        minimum_track_frames: linkDetections ? minimumTrackFrames : 1,
        link_detections: linkDetections,
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
        (frame) => frame.frame === previewFrameIndex,
      ),
    [previewFrameIndex, interpolationQuery.data?.frames],
  );
  const poseFrame = useMemo(
    () => keyframes.find((frame) => frame.frame === previewFrameIndex),
    [keyframes, previewFrameIndex],
  );
  const poseEditorSchema = useMemo(
    () =>
      selectedTrack && selectedTrackPoseSchema
        ? editorSchemaForVideoTrack(selectedTrack, selectedTrackPoseSchema)
        : null,
    [selectedTrack, selectedTrackPoseSchema],
  );
  const poseEditorPose = useMemo(
    () =>
      selectedTrack && poseFrame && selectedTrackPoseSchema
        ? poseInstanceFromVideoKeyframe(
            selectedTrack,
            poseFrame,
            selectedTrackPoseSchema,
          )
        : null,
    [poseFrame, selectedTrack, selectedTrackPoseSchema],
  );
  const extractionStride = Number(
    selectedVideo?.metadata_json.extraction_every_n_frames ?? everyNFrames,
  );
  const error =
    uploadMutation.error ??
    extractionMutation.error ??
    saveTrackMutation.error ??
    deleteTrackMutation.error ??
    deleteMachineTracksMutation.error ??
    deleteModelMutation.error ??
    poseSchemaMutation.error ??
    spatialMetricsQuery.error ??
    trackingMutation.error ??
    cancelTrackingMutation.error ??
    retryTrackingMutation.error ??
    benchmarkMutation.error ??
    trackingRunsQuery.error;

  async function savePoseFrameReview(request: PoseSaveRequest) {
    if (!selectedTrack || !selectedTrackPoseSchema || !poseFrame) {
      throw new Error("Select a persisted pose track keyframe first");
    }

    if (
      activePoseActiveLearningCandidate &&
      (activePoseActiveLearningCandidate.video_track_id !== selectedTrack.id ||
        activePoseActiveLearningCandidate.focus_frame !== poseFrame.frame)
    ) {
      throw new Error(
        "The active pose Active Learning candidate no longer matches the selected track/frame",
      );
    }

    const correctedFrame = correctedVideoKeyframeFromPoseSave(
      poseFrame,
      selectedTrackPoseSchema,
      request,
    );
    const correctedFrames = sortedKeyframes(
      keyframes.map((frame) =>
        frame.frame === poseFrame.frame ? correctedFrame : frame,
      ),
    );
    const updatedTrack = await updateVideoTrack(selectedTrack.id, {
      base_revision: request.base_revision,
      label_class_id: selectedTrack.label_class_id,
      keyframes: correctedFrames,
      interpolation: selectedTrack.interpolation === "hold" ? "hold" : "linear",
      status: selectedTrack.status,
    });
    const persistedFrame = updatedTrack.keyframes_json.find(
      (frame) => frame.frame === poseFrame.frame,
    );
    if (!persistedFrame) {
      throw new Error("Saved track did not return the corrected pose keyframe");
    }

    setKeyframes(sortedKeyframes(updatedTrack.keyframes_json));

    if (activePoseActiveLearningCandidate) {
      try {
        await reviewPoseActiveLearningCandidate(
          activePoseActiveLearningCandidate.id,
          {
            action: "verify",
            reviewed_by: "local_user",
            verified_track_revision: updatedTrack.revision,
            note: "Verified through the ReefVision Pose Annotation Editor.",
          },
        );
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: [
              "pose-active-learning-candidates",
              activePoseActiveLearningCandidate.round_id,
            ],
          }),
          queryClient.invalidateQueries({
            queryKey: [
              "pose-active-learning-rounds",
              project.id,
              selectedVideoId,
            ],
          }),
        ]);
        setActivePoseActiveLearningCandidate(null);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Unknown pose Active Learning verification error";
        throw new Error(
          `Pose saved as track revision ${updatedTrack.revision}, but Active Learning verification failed: ${message}`,
        );
      }
    }

    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["video-tracks", selectedVideoId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["video-track-interpolation", selectedTrack.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["video-track-analytics", selectedTrack.id],
      }),
    ]);
    return poseInstanceFromVideoKeyframe(
      updatedTrack,
      persistedFrame,
      selectedTrackPoseSchema,
    );
  }

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

  useEffect(() => {
    if (
      !workspaceCommand ||
      lastWorkspaceCommandIdRef.current === workspaceCommand.id
    ) {
      return;
    }

    lastWorkspaceCommandIdRef.current = workspaceCommand.id;

    if (workspaceCommand.type === "select_video") {
      if (
        (videosQuery.data ?? []).some(
          (video) => video.id === workspaceCommand.videoId,
        )
      ) {
        setSelectedVideoId(workspaceCommand.videoId);
      }
    }

    if (workspaceCommand.type === "select_track") {
      if (
        workspaceCommand.trackId === "" ||
        (tracksQuery.data ?? []).some(
          (track) => track.id === workspaceCommand.trackId,
        )
      ) {
        setSelectedTrackId(workspaceCommand.trackId);
      }
    }

    if (workspaceCommand.type === "seek_frame" && selectedVideo) {
      const clampedFrame = Math.min(
        Math.max(0, Math.round(workspaceCommand.frameIndex)),
        Math.max(0, selectedVideo.frame_count - 1),
      );

      const frameTimeSeconds =
        selectedVideo.fps > 0 ? clampedFrame / selectedVideo.fps : 0;

      seekVideoFromMap(clampedFrame, frameTimeSeconds);
      setPreviewFrameIndex(clampedFrame);
    }

    onWorkspaceCommandHandled?.(workspaceCommand.id);
  }, [
    onWorkspaceCommandHandled,
    selectedVideo,
    tracksQuery.data,
    videosQuery.data,
    workspaceCommand,
  ]);

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
                Select a local video and ReefVision will automatically attach
                its matching DJI SRT and the single valid sibling AirData CSV
                when available. Manual inputs below remain available as
                overrides.
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
        <label className="annotation-selection-row">
          <input
            type="checkbox"
            checked={sourceOverlayEnabled}
            onChange={(event) => {
              setSourceOverlayEnabled(event.target.checked);
              if (event.target.checked) setPreviewFrameIndex(frameIndex);
            }}
          />
          <span>Enable source-coordinate overlay</span>
        </label>
        <p className="annotation-helper">
          Disabled by default to avoid repeatedly loading full-resolution still
          frames while the video or frame slider is moving. Preview loads are
          debounced while enabled.
        </p>
        {selectedVideo && sourceOverlayEnabled ? (
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
            {previewFrameIndex !== frameIndex && (
              <p className="annotation-helper">
                Loading preview for frame {frameIndex}…
              </p>
            )}
            {selectedVideo.frame_directory_path ? (
              <div
                style={{
                  position: "relative",
                  width: "100%",
                  aspectRatio: `${selectedVideo.width_px} / ${selectedVideo.height_px}`,
                }}
              >
                <img
                  src={videoFrameUrl(selectedVideo.id, previewFrameIndex)}
                  alt={`Frame ${previewFrameIndex}`}
                  loading="lazy"
                  decoding="async"
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                  }}
                />
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
                  {(spatialMetricsQuery.data?.objects ?? []).map((object) => (
                    <rect
                      key={object.track_id}
                      x={object.bbox[0]}
                      y={object.bbox[1]}
                      width={object.bbox[2]}
                      height={object.bbox[3]}
                      fill="none"
                      stroke={
                        object.track_id === selectedTrackId
                          ? "var(--accent-color, #2563eb)"
                          : "#ffd43b"
                      }
                      strokeWidth={object.track_id === selectedTrackId ? 4 : 2}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                  {overlayFrame &&
                    !(spatialMetricsQuery.data?.objects ?? []).some(
                      (object) => object.track_id === selectedTrackId,
                    ) && (
                      <rect
                        x={overlayFrame.bbox[0]}
                        y={overlayFrame.bbox[1]}
                        width={overlayFrame.bbox[2]}
                        height={overlayFrame.bbox[3]}
                        fill="none"
                        stroke="var(--accent-color, #2563eb)"
                        strokeWidth={4}
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  {(poseFrame?.keypoints ?? []).map((point, index) =>
                    point[2] > 0 ? (
                      <circle
                        key={`pose-${previewFrameIndex}-${index}`}
                        cx={point[0]}
                        cy={point[1]}
                        r={5}
                        fill="var(--accent-color, #2563eb)"
                        stroke="white"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      >
                        <title>
                          {`${
                            selectedTrackPoseSchema?.expanded_labels[index] ??
                            `landmark ${index + 1}`
                          } · confidence ${point[2].toFixed(3)}`}
                        </title>
                      </circle>
                    ) : null,
                  )}
                </svg>
              </div>
            ) : (
              <p className="annotation-helper">
                Extract frames to review keyframes against still images.
              </p>
            )}
            {(poseFrame?.keypoints?.length ?? 0) > 0 && (
              <>
                <p className="annotation-helper">
                  Pose landmarks on this frame:{" "}
                  {poseFrame?.keypoints?.length ?? 0}
                </p>
                {selectedTrackPoseSchema && (
                  <p className="annotation-helper">
                    Landmark schema:{" "}
                    {selectedTrackPoseSchema.groups
                      .map((group) => `${group.name} × ${group.count}`)
                      .join(" · ")}
                  </p>
                )}
              </>
            )}
            <PoseActiveLearningPanel
              projectId={project.id}
              videoId={selectedVideo.id}
              activeCandidateId={activePoseActiveLearningCandidate?.id ?? null}
              onOpenCandidate={(candidate) => {
                setActivePoseActiveLearningCandidate(candidate);
                setSelectedTrackId(candidate.video_track_id);
                setFrameIndex(candidate.focus_frame);
                setPreviewFrameIndex(candidate.focus_frame);
              }}
            />

            {selectedVideo.frame_directory_path &&
              selectedTrack &&
              selectedTrackPoseSchema &&
              poseEditorSchema &&
              poseEditorPose &&
              ((poseFrame?.keypoints?.length ?? 0) > 0 ||
                (poseFrame?.pose_observations?.length ?? 0) > 0) && (
                <div className="workspace-guide compact">
                  <div>
                    <strong>Pose review editor</strong>
                    <p className="annotation-helper">
                      Model landmarks are editable here. Moving a model landmark
                      marks it corrected; saving writes both compatible
                      keypoints and the richer corrected observation record back
                      to this track keyframe.
                    </p>
                  </div>
                  <PoseAnnotationEditor
                    key={`${selectedTrack.id}:${poseFrame?.frame}`}
                    imageUrl={videoFrameUrl(
                      selectedVideo.id,
                      previewFrameIndex,
                    )}
                    imageWidth={selectedVideo.width_px}
                    imageHeight={selectedVideo.height_px}
                    schema={poseEditorSchema}
                    poses={[poseEditorPose]}
                    viewportWidth={800}
                    viewportHeight={520}
                    onSave={savePoseFrameReview}
                  />
                </div>
              )}
            {selectedTrack && selectedTrackPoseSchema && (
              <PoseTemporalReviewPanel
                trackId={selectedTrack.id}
                frameIndex={frameIndex}
                onFrameChange={(nextFrame) => {
                  setFrameIndex(nextFrame);
                  setPreviewFrameIndex(nextFrame);
                }}
              />
            )}
            {selectedTrack && selectedTrackPoseSchema && (
              <PoseVisualizationPanel
                trackId={selectedTrack.id}
                frameIndex={previewFrameIndex}
              />
            )}
            {selectedTrack && (
              <BehaviorDynamicsPanel
                projectId={project.id}
                trackId={selectedTrack.id}
                frameIndex={previewFrameIndex}
                onFrameChange={(nextFrame) => {
                  setFrameIndex(nextFrame);
                  setPreviewFrameIndex(nextFrame);
                }}
              />
            )}
            {spatialMetricsQuery.data && (
              <div className="annotation-selection-list">
                <div className="annotation-selection-row">
                  <strong>Objects on frame</strong>
                  <span>{spatialMetricsQuery.data.object_count}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Mean nearest neighbor</strong>
                  <span>
                    {spatialMetricsQuery.data
                      .mean_nearest_neighbor_distance_pixels === null
                      ? "—"
                      : `${spatialMetricsQuery.data.mean_nearest_neighbor_distance_pixels.toFixed(2)} px`}
                    {spatialMetricsQuery.data
                      .mean_nearest_neighbor_distance_meters === null
                      ? ""
                      : ` · ${spatialMetricsQuery.data.mean_nearest_neighbor_distance_meters.toFixed(2)} m`}
                  </span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Minimum nearest neighbor</strong>
                  <span>
                    {spatialMetricsQuery.data
                      .minimum_nearest_neighbor_distance_pixels === null
                      ? "—"
                      : `${spatialMetricsQuery.data.minimum_nearest_neighbor_distance_pixels.toFixed(2)} px`}
                    {spatialMetricsQuery.data
                      .minimum_nearest_neighbor_distance_meters === null
                      ? ""
                      : ` · ${spatialMetricsQuery.data.minimum_nearest_neighbor_distance_meters.toFixed(2)} m`}
                  </span>
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="annotation-helper">
            Enable the overlay when you need frame-level box and spacing review.
          </p>
        )}
      </section>

      {selectedVideo && (
        <section className="management-card">
          <p className="eyebrow">Pose exchange</p>
          <h3>Pose interoperability</h3>
          <div className="workspace-guide compact">
            <div>
              <strong>Import/export safeguards</strong>
              <p className="annotation-helper">
                Import or export canonical pose data through SLEAP-IO.
                ReefVision-exported files must match the target video checksum.
                External files without ReefVision provenance require explicit
                confirmation that frame indices correspond to this video.
              </p>
            </div>
            {selectedTrack && selectedTrackPoseSchema && (
              <>
                <p className="annotation-helper">
                  Exports use the scientist-reviewed canonical pose state.
                  Repeated semantic labels receive stable external node names.
                  SLP is exported natively; NWB, COCO, DeepLabCut, and
                  Ultralytics downloads are ZIP bundles containing the standard
                  native artifact plus a ReefVision manifest for exact frame and
                  identity restoration. The full immutable
                  association/correction audit history remains in ReefVision.
                </p>
                <div className="workspace-actions">
                  <a
                    href={poseInteroperabilityExportUrl(
                      selectedVideo.id,
                      "slp",
                    )}
                  >
                    SLEAP SLP
                  </a>
                  <a
                    href={poseInteroperabilityExportUrl(
                      selectedVideo.id,
                      "nwb",
                    )}
                  >
                    NWB
                  </a>
                  <a
                    href={poseInteroperabilityExportUrl(
                      selectedVideo.id,
                      "coco",
                    )}
                  >
                    COCO pose
                  </a>
                  <a
                    href={poseInteroperabilityExportUrl(
                      selectedVideo.id,
                      "dlc_csv",
                    )}
                  >
                    DeepLabCut CSV
                  </a>
                  <a
                    href={poseInteroperabilityExportUrl(
                      selectedVideo.id,
                      "ultralytics_pose",
                    )}
                  >
                    Ultralytics pose ZIP
                  </a>
                </div>
              </>
            )}
            <label>
              Import format
              <select
                aria-label="Pose interoperability import format"
                value={poseInteropImportFormat}
                onChange={(event) =>
                  setPoseInteropImportFormat(
                    event.target.value as PoseInteroperabilityFormat,
                  )
                }
              >
                <option value="slp">SLEAP SLP</option>
                <option value="nwb">NWB</option>
                <option value="coco">COCO pose JSON</option>
                <option value="dlc_csv">DeepLabCut CSV</option>
                <option value="ultralytics_pose">Ultralytics pose ZIP</option>
              </select>
            </label>
            <label>
              Target identity class
              <select
                aria-label="Pose interoperability target identity class"
                value={labelClassId}
                onChange={(event) => setLabelClassId(event.target.value)}
              >
                {project.label_classes
                  .filter((labelClass) => labelClass.is_active)
                  .map((labelClass) => (
                    <option key={labelClass.id} value={labelClass.id}>
                      {labelClass.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Pose file
              <input
                aria-label="Pose interoperability import file"
                type="file"
                accept=".slp,.nwb,.json,.csv,.zip,application/zip"
                onChange={(event) =>
                  setPoseInteropImportFile(event.target.files?.[0] ?? null)
                }
              />
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmPoseInteropFrameMapping}
                onChange={(event) =>
                  setConfirmPoseInteropFrameMapping(event.target.checked)
                }
              />
              I confirm external frame indices correspond to this video when the
              file has no ReefVision provenance
            </label>
            <p className="annotation-helper">
              Imported instances use the current Identity class selected in the
              Track editor. External tracked instances keep their grouping;
              untracked instances are never auto-associated across frames.
            </p>
            <button
              type="button"
              onClick={() => poseInteropImportMutation.mutate()}
              disabled={
                !poseInteropImportFile ||
                !labelClassId ||
                poseInteropImportMutation.isPending
              }
            >
              {poseInteropImportMutation.isPending
                ? "Importing pose..."
                : "Import pose"}
            </button>
            {poseInteropImportMutation.error && (
              <p className="form-error">
                {poseInteropImportMutation.error.message}
              </p>
            )}
            {poseInteropImportMutation.data && (
              <p className="annotation-helper">
                Imported {poseInteropImportMutation.data.track_count} track
                {poseInteropImportMutation.data.track_count === 1
                  ? ""
                  : "s"}{" "}
                with {poseInteropImportMutation.data.keyframe_count} pose
                keyframes. Review is required before treating imported
                identities as verified.
              </p>
            )}
            {poseInteropImportMutation.data?.warnings.map((warning) => (
              <p key={warning} className="annotation-helper">
                {warning}
              </p>
            ))}
          </div>
        </section>
      )}

      {selectedVideo && (
        <GeoreferencedMapPanel
          key={selectedVideo.id}
          videoId={selectedVideo.id}
          activeFrameIndex={frameIndex}
          showTrackLines={showMovementLines}
          onFrameSelect={handleGeographicFrameSelect}
          classOptions={project.label_classes.map((labelClass) => ({
            id: labelClass.id,
            name: labelClass.name,
          }))}
          trackClassById={trackClassById}
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
            <option value="imported_review_required">
              Imported — review required
            </option>
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
          <button
            type="button"
            className="danger-ghost"
            disabled={
              !selectedVideoId ||
              deleteMachineTracksMutation.isPending ||
              !(tracksQuery.data ?? []).some((track) => track.source_job_id)
            }
            onClick={() => {
              if (
                window.confirm(
                  "Remove all machine-generated tracks for this video? Manual tracks are preserved.",
                )
              ) {
                deleteMachineTracksMutation.mutate();
              }
            }}
          >
            Remove machine tracks
          </button>
        </div>
      </section>

      <section className="management-card">
        <p className="eyebrow">Automated tracking</p>
        <h3>Detection / pose + tracker</h3>
        <label>
          Detection or pose model
          <select
            value={trackingModelId}
            onChange={(event) => setTrackingModelId(event.target.value)}
          >
            {(modelsQuery.data ?? []).map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name} ({model.task})
              </option>
            ))}
          </select>
        </label>
        {poseTrackingSelected && (
          <div className="workspace-guide compact">
            <div>
              <strong>Pose landmark schema</strong>
              <p className="annotation-helper">
                Define semantic landmark types once. Use Count &gt; 1 for
                repeatable structures, such as tentacle × 8. Repeated landmarks
                share the same biological label instead of requiring artificial
                names such as tentacle_1 through tentacle_8.
              </p>
              {poseExpectedLandmarkCount !== null && (
                <p className="annotation-helper">
                  Checkpoint landmarks: {poseExpectedLandmarkCount} ·
                  configured: {poseConfiguredLandmarkCount}
                </p>
              )}
              {poseLandmarkGroups.map((group, index) => (
                <div
                  key={`pose-landmark-group-${index}`}
                  className="annotation-editor-inline-actions"
                >
                  <label>
                    Landmark type
                    <input
                      type="text"
                      value={group.name}
                      placeholder="e.g. tentacle"
                      onChange={(event) =>
                        setPoseLandmarkGroups((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index
                              ? { ...item, name: event.target.value }
                              : item,
                          ),
                        )
                      }
                    />
                  </label>
                  <label>
                    Count
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      step={1}
                      value={group.count}
                      onChange={(event) =>
                        setPoseLandmarkGroups((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index
                              ? {
                                  ...item,
                                  count: Math.max(
                                    1,
                                    Number(event.target.value) || 1,
                                  ),
                                }
                              : item,
                          ),
                        )
                      }
                      style={{ width: 88 }}
                    />
                  </label>
                  <button
                    type="button"
                    className="danger-ghost"
                    onClick={() =>
                      setPoseLandmarkGroups((current) =>
                        current.filter(
                          (_item, itemIndex) => itemIndex !== index,
                        ),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
              ))}
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    setPoseLandmarkGroups((current) => [
                      ...current,
                      { name: "", count: 1 },
                    ])
                  }
                >
                  Add landmark type
                </button>
                <button
                  type="button"
                  disabled={
                    !poseLandmarkSchemaValid || poseSchemaMutation.isPending
                  }
                  onClick={() => poseSchemaMutation.mutate()}
                >
                  {poseSchemaMutation.isPending
                    ? "Saving landmark schema..."
                    : "Save landmark schema"}
                </button>
              </div>
              {!poseLandmarkSchemaValid && poseLandmarkGroups.length > 0 && (
                <p className="annotation-helper">
                  Every landmark type needs a name
                  {poseExpectedLandmarkCount !== null
                    ? ` and the counts must total ${poseExpectedLandmarkCount}`
                    : ""}
                  .
                </p>
              )}
            </div>
          </div>
        )}
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            className="danger-ghost"
            disabled={!trackingModelId || deleteModelMutation.isPending}
            onClick={() => {
              const model = (modelsQuery.data ?? []).find(
                (item) => item.id === trackingModelId,
              );
              if (
                window.confirm(
                  `Remove model "${model?.display_name ?? trackingModelId}" from this project?`,
                )
              ) {
                deleteModelMutation.mutate();
              }
            }}
          >
            Remove selected model
          </button>
        </div>
        <label className="annotation-selection-row">
          <input
            type="checkbox"
            checked={linkDetections}
            onChange={(event) => setLinkDetections(event.target.checked)}
          />
          <span>Link detections across frames (movement tracking)</span>
        </label>
        <p className="annotation-helper">
          Turn this off for independent per-frame instance detection. Each
          detection remains reviewable, but ReefVision will not assign a
          cross-frame animal identity or movement trajectory.
          {poseTrackingSelected
            ? " Pose checkpoints retain model-native landmark coordinates and confidence values for every retained observation. ReefVision then performs canonical repeated-landmark temporal association inside each retained animal track."
            : ""}
        </p>
        {sleapTrackingSelected ? (
          <div className="workspace-guide compact">
            <div>
              <strong>SLEAP-NN animal-instance tracking</strong>
              <p className="annotation-helper">
                {linkDetections
                  ? "ReefVision uses SLEAP-NN fixed-window OKS/Hungarian tracking for animal instances. ByteTrack, BoT-SORT, and detector IoU do not apply to this provider."
                  : "Animal-instance linking is disabled. Each SLEAP-NN instance is retained independently for review."}
              </p>
            </div>
          </div>
        ) : (
          <label>
            Tracker
            <select
              value={trackerName}
              disabled={!linkDetections}
              onChange={(event) => setTrackerName(event.target.value)}
            >
              <option value="bytetrack.yaml">ByteTrack</option>
              <option value="botsort.yaml">BoT-SORT</option>
            </select>
          </label>
        )}
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
        {!sleapTrackingSelected && (
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
        )}
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
            disabled={!linkDetections}
            value={linkDetections ? minimumTrackFrames : 1}
            onChange={(event) =>
              setMinimumTrackFrames(Number(event.target.value))
            }
          />
        </label>
        <button
          type="button"
          disabled={
            !selectedVideoId ||
            !trackingModelId ||
            trackingMutation.isPending ||
            (poseTrackingSelected && selectedModelPoseSchema === null)
          }
          onClick={() => trackingMutation.mutate()}
        >
          {trackingMutation.isPending
            ? "Queuing..."
            : linkDetections
              ? sleapTrackingSelected
                ? "Run SLEAP-NN pose + instance tracking"
                : poseTrackingSelected
                  ? `Run pose + ${trackerLabel(trackerName)}`
                  : `Run ${trackerLabel(trackerName)}`
              : poseTrackingSelected
                ? "Run pose inference"
                : "Run instance detection"}
        </button>
        <label className="annotation-selection-row">
          <input
            type="checkbox"
            checked={showMovementLines}
            onChange={(event) => setShowMovementLines(event.target.checked)}
          />
          <span>Show movement lines on geographic maps</span>
        </label>
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
                      <td>
                        {run.link_detections
                          ? trackerLabel(run.tracker)
                          : "Instances only"}
                      </td>
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
