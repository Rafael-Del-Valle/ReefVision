import { EnvironmentalSubjectInspector } from "../environmental-context/EnvironmentalSubjectInspector";
import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import { AnnotatedVideoExportPanel } from "./AnnotatedVideoExportPanel";
import { BehaviorDynamicsPanel } from "./BehaviorDynamicsPanel";
import { BiologicalMovementPanel } from "./BiologicalMovementPanel";
import { ReefPoseValidationPanel } from "./ReefPoseValidationPanel";
import { TemporalReefPosePanel } from "./TemporalReefPosePanel";
import { GeoreferencedMapPanel } from "./GeoreferencedMapPanel";
import { GeoreferencingSetupPanel } from "./GeoreferencingSetupPanel";
import { GeographicExportPanel } from "./GeographicExportPanel";
import { GeographicMovementAnalyticsPanel } from "./GeographicMovementAnalyticsPanel";
import { PoseActiveLearningPanel } from "./PoseActiveLearningPanel";
import { PoseIdentityReviewPanel } from "./PoseIdentityReviewPanel";
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
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  cancelJob,
  getClassVisibilityBundle,
  retryJob,
  type Project,
} from "../../api/client";
import { resolveClassVisibilityState } from "../annotation-editor/classVisibility";
import { useActionConfirmation } from "../../components/ui/ActionConfirmation";
import { PoseAnnotationEditor } from "../pose/PoseAnnotationEditor";
import { AnatomySkeletonDesigner } from "../pose/AnatomySkeletonDesigner";
import type { AnatomySchemaRevision } from "../pose/anatomyApi";
import type { PoseSaveRequest } from "../pose/types";
import {
  correctedVideoKeyframeFromPoseSave,
  editorSchemaForVideoTrack,
  poseInstanceFromVideoKeyframe,
  videoSchemaFromAnatomy,
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
  type VideoTrackRecord,
} from "./videoApi";
import { trackingBenchmarkCsv, trackingBenchmarkJson } from "./trackingReport";
import type {
  PoseEvidenceNavigation,
  VideoWorkspaceCommand,
  VideoWorkspaceContext,
  VideoWorkspaceTrackSource,
} from "./videoWorkspaceBridge";
import {
  frameIndexForVideoTime,
  videoTimeMatchesPendingSeek,
  type PendingVideoMapSeek,
} from "./videoMapSynchronization";
import { sortedKeyframes, useVideoTrackDraft } from "./useVideoTrackDraft";

interface VideoTrackingWorkspaceProps {
  project: Project;
  onWorkspaceContextChange?: (context: VideoWorkspaceContext | null) => void;
  workspaceCommand?: VideoWorkspaceCommand | null;
  onWorkspaceCommandHandled?: (commandId: number) => void;
}

const POSE_EXPORT_FORMATS = [
  ["nwb", "NWB"],
  ["coco", "COCO pose"],
  ["dlc_csv", "DeepLabCut CSV"],
  ["ultralytics_pose", "Ultralytics pose ZIP"],
] as const;

function parseMaskPolygons(
  value: string,
  sourceWidth: number,
  sourceHeight: number,
): [number, number][][] | null {
  if (!value.trim()) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Mask polygons must be valid JSON");
  }

  if (!Array.isArray(parsed)) {
    throw new Error("Mask polygons must be an array of polygons");
  }
  if (parsed.length === 0) return null;
  if (parsed.length > 30) {
    throw new Error("Mask keyframes support at most 30 polygons");
  }

  return parsed.map((polygon, polygonIndex) => {
    if (
      !Array.isArray(polygon) ||
      polygon.length < 3 ||
      polygon.length > 20000
    ) {
      throw new Error(
        `Mask polygon ${polygonIndex + 1} must contain 3–20000 points`,
      );
    }
    return polygon.map((point, pointIndex) => {
      if (
        !Array.isArray(point) ||
        point.length !== 2 ||
        !point.every(
          (coordinate) =>
            typeof coordinate === "number" && Number.isFinite(coordinate),
        )
      ) {
        throw new Error(
          `Mask polygon ${polygonIndex + 1}, point ${pointIndex + 1} must be [x, y]`,
        );
      }
      const [x, y] = point;
      if (x < 0 || x > sourceWidth || y < 0 || y > sourceHeight) {
        throw new Error(
          `Mask polygon ${polygonIndex + 1}, point ${pointIndex + 1} is outside the source image`,
        );
      }
      return [x, y] as [number, number];
    });
  });
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
  const [temporalReview, setTemporalReview] = useState<{
    videoId: string;
    identityRunId: string;
    animalIdentityId: string;
    frameIndex: number;
  } | null>(null);
  const queryClient = useQueryClient();
  const { confirm, confirmationDialog } = useActionConfirmation();
  const desktopMode =
    typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingMapSeekRef = useRef<PendingVideoMapSeek | null>(null);
  const mapSeekSequenceRef = useRef(0);
  const lastWorkspaceCommandIdRef = useRef(0);
  const previousSelectedVideoIdRef = useRef("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [telemetryFile, setTelemetryFile] = useState<File | null>(null);
  const [telemetryUtcOffsetMinutes, setTelemetryUtcOffsetMinutes] =
    useState("");
  const [telemetryUtcOffsetEvidence, setTelemetryUtcOffsetEvidence] =
    useState("");
  const [airdataFile, setAirdataFile] = useState<File | null>(null);
  const [airdataTimeOffsetSeconds, setAirdataTimeOffsetSeconds] = useState(0);
  const [airdataTimeOffsetEvidence, setAirdataTimeOffsetEvidence] =
    useState("");
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [everyNFrames, setEveryNFrames] = useState(1);
  const [frameIndex, setFrameIndex] = useState(0);
  const [selectedTrackId, setSelectedTrackId] = useState("");
  const [poseEvidence, setPoseEvidence] = useState<
    (PoseEvidenceNavigation & { id: number }) | null
  >(null);
  const [selectedAnatomySchema, setSelectedAnatomySchema] =
    useState<AnatomySchemaRevision | null>(null);
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
  const defaultClassId =
    project.label_classes.find((labelClass) => labelClass.is_active)?.id ?? "";
  const [poseImportClass, setPoseImportClass] = useState("");
  const poseImportClassId = poseImportClass || defaultClassId;
  const [visibility, setVisibility] = useState<{
    projectId: string;
    hidden?: string[];
    solo?: string;
  } | null>(null);
  const [maskEditError, setMaskEditError] = useState<string | null>(null);
  const [draftFormReset, setDraftFormReset] = useState(0);
  const [poseInteropImportFile, setPoseInteropImportFile] =
    useState<File | null>(null);
  const [poseInteropImportFormat, setPoseInteropImportFormat] =
    useState<PoseInteroperabilityFormat>("nwb");
  const [confirmPoseInteropFrameMapping, setConfirmPoseInteropFrameMapping] =
    useState(false);
  const [includeUnreviewedInPoseExport, setIncludeUnreviewedInPoseExport] =
    useState(false);

  const [trackingModelId, setTrackingModelId] = useState("");
  const [trackingMode, setTrackingMode] = useState<
    "auto" | "detect" | "segment" | "hybrid"
  >("auto");
  const [segmentationTrackingModelId, setSegmentationTrackingModelId] =
    useState("");
  const [hybridMatchIou, setHybridMatchIou] = useState(0.5);
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
  const [workflowReviewRound, setWorkflowReviewRound] = useState<{
    videoId: string;
    roundId?: string;
  } | null>(null);
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
    staleTime:
      workspaceCommand?.type === "open_workflow_pose_review" ? 0 : undefined,
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
  const draftContext = `${project.id}:${selectedVideoId}:${selectedTrackId}`;
  const draftContextRef = useRef(draftContext);
  useLayoutEffect(() => {
    draftContextRef.current = draftContext;
    setMaskEditError(null);
  }, [draftContext]);
  const trackDraft = useVideoTrackDraft(
    draftContext,
    selectedTrack,
    defaultClassId,
  );
  const {
    labelClassId,
    keyframes,
    interpolation,
    status: trackStatus,
  } = trackDraft.fields;
  const classVisibilityQuery = useQuery({
    queryKey: ["class-visibility", project.id],
    queryFn: ({ signal }) => getClassVisibilityBundle(project.id, signal),
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const sessionVisibility =
    visibility?.projectId === project.id ? visibility : null;
  const hiddenClassIds = useMemo(
    () =>
      resolveClassVisibilityState(
        "video_tracks",
        classVisibilityQuery.data,
        { video_tracks: sessionVisibility?.hidden },
        project.label_classes.map((labelClass) => labelClass.id),
      ).hiddenClassIds,
    [
      classVisibilityQuery.data,
      project.label_classes,
      sessionVisibility?.hidden,
    ],
  );
  const soloClassId = sessionVisibility?.solo;
  const classIsVisible = useCallback(
    (classId: string) =>
      soloClassId ? soloClassId === classId : !hiddenClassIds.includes(classId),
    [hiddenClassIds, soloClassId],
  );
  const selectedTrackHidden = Boolean(
    selectedTrack && !classIsVisible(selectedTrack.label_class_id),
  );
  const visibleTracks = useMemo(
    () =>
      (tracksQuery.data ?? []).filter((track) =>
        classIsVisible(track.label_class_id),
      ),
    [classIsVisible, tracksQuery.data],
  );
  const editableTrack =
    (!selectedTrackId || !!selectedTrack) && !selectedTrackHidden;
  const trackSelectionChanged =
    selectedTrack?.revision !== undefined &&
    selectedTrack.revision !== trackDraft.revision;
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
  const eligibleTrackingModels = useMemo(
    () =>
      (modelsQuery.data ?? []).filter((model) => {
        if (trackingMode === "hybrid" || trackingMode === "detect") {
          return model.task === "detect";
        }
        if (trackingMode === "segment") return model.task === "segment";
        return true;
      }),
    [modelsQuery.data, trackingMode],
  );
  const eligibleSegmentationModels = useMemo(
    () =>
      (modelsQuery.data ?? []).filter(
        (model) =>
          model.task === "segment" && model.provider_name === "ultralytics",
      ),
    [modelsQuery.data],
  );
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
  const hasVerifiedPoseTracks = tracksQuery.data?.some(
    (track) =>
      track.status === "verified" &&
      poseLandmarkSchemaFromMetadata(track.metadata_json) !== null &&
      track.keyframes_json.some(
        (frame) => frame.pose_observations || frame.keypoints,
      ),
  );
  const activeTrackPoseSchema =
    selectedTrackPoseSchema ??
    (selectedAnatomySchema
      ? videoSchemaFromAnatomy(selectedAnatomySchema)
      : null);

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
  useLayoutEffect(() => {
    const previousVideoId = previousSelectedVideoIdRef.current;
    previousSelectedVideoIdRef.current = selectedVideoId;
    // Initial video hydration can coincide with the first import interaction.
    if (!previousVideoId || previousVideoId === selectedVideoId) return;
    pendingMapSeekRef.current = null;
    setFrameIndex(0);
    setPreviewFrameIndex(0);
    setSelectedTrackId("");
    setMaskEditError(null);
    setGroundTruthTrackIds([]);
    setBenchmarkJobIds([]);
    setBenchmarkStartFrame(0);
    setBenchmarkEndFrame(0);
    setCopiedReport(null);
    setPoseInteropImportFile(null);
    setConfirmPoseInteropFrameMapping(false);
    setIncludeUnreviewedInPoseExport(false);
  }, [selectedVideoId]);
  useEffect(() => {
    if (selectedVideo) {
      setBenchmarkEndFrame(Math.max(0, selectedVideo.frame_count - 1));
    }
  }, [selectedVideo]);
  useEffect(() => {
    if (
      eligibleTrackingModels.length > 0 &&
      !eligibleTrackingModels.some((model) => model.id === trackingModelId)
    ) {
      setTrackingModelId(eligibleTrackingModels[0].id);
    } else if (
      modelsQuery.data &&
      eligibleTrackingModels.length === 0 &&
      trackingModelId
    ) {
      setTrackingModelId("");
    }
  }, [eligibleTrackingModels, modelsQuery.data, trackingModelId]);
  useEffect(() => {
    if (
      eligibleSegmentationModels.length > 0 &&
      !eligibleSegmentationModels.some(
        (model) => model.id === segmentationTrackingModelId,
      )
    ) {
      setSegmentationTrackingModelId(eligibleSegmentationModels[0].id);
    }
  }, [eligibleSegmentationModels, segmentationTrackingModelId]);
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
  const poseInteropImportMutation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video first");
      if (!poseInteropImportFile) {
        throw new Error("Choose a pose interoperability file first");
      }
      if (!poseImportClassId) throw new Error("Choose a target identity class");
      return importPoseInteroperability(
        selectedVideoId,
        poseInteropImportFormat,
        poseInteropImportFile,
        poseImportClassId,
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
      setTelemetryUtcOffsetMinutes("");
      setTelemetryUtcOffsetEvidence("");
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
      if (
        telemetryFile &&
        (telemetryUtcOffsetMinutes.trim() !== "" ||
          telemetryUtcOffsetEvidence.trim() !== "") &&
        (telemetryUtcOffsetMinutes.trim() === "" ||
          !telemetryUtcOffsetEvidence.trim())
      ) {
        throw new Error(
          "DJI SRT UTC alignment requires both a timezone offset and evidence",
        );
      }
      return importVideo(project.id, uploadFile, {
        telemetryFile,
        ...(telemetryUtcOffsetMinutes.trim() === ""
          ? {}
          : {
              telemetryUtcOffsetMinutes: Number(telemetryUtcOffsetMinutes),
              telemetryUtcOffsetEvidence,
            }),
        airdataFile,
        airdataTimeOffsetSeconds,
        airdataTimeOffsetEvidence,
      });
    },
    onSuccess: async (video) => {
      setSelectedVideoId(video.id);
      setUploadFile(null);
      setTelemetryFile(null);
      setTelemetryUtcOffsetMinutes("");
      setTelemetryUtcOffsetEvidence("");
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
    mutationFn: (_selection: { context: string; videoId: string }) => {
      if (
        !editableTrack ||
        !selectedVideoId ||
        !labelClassId ||
        keyframes.length === 0
      ) {
        throw new Error(
          "A video, class, and at least one keyframe are required",
        );
      }
      const normalized = sortedKeyframes(keyframes);
      if (selectedTrack && trackDraft.revision !== null) {
        return updateVideoTrack(selectedTrack.id, {
          base_revision: trackDraft.revision,
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
    onSuccess: async (track, selection) => {
      const queryKey = ["video-tracks", selection.videoId];
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueryData<VideoTrackRecord[]>(queryKey, (current = []) =>
        current.some((record) => record.id === track.id)
          ? current.map((record) => (record.id === track.id ? track : record))
          : [...current, track],
      );
      if (draftContextRef.current === selection.context) {
        trackDraft.reset();
        setSelectedTrackId(track.id);
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey,
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-track-interpolation", track.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-track-analytics", track.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-frame-spatial-metrics", selection.videoId],
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
      trackDraft.reset();
      await queryClient.invalidateQueries({
        queryKey: ["video-tracks", selectedVideoId],
      });
    },
  });
  const deleteMachineTracksMutation = useMutation({
    mutationFn: ({
      videoId,
    }: {
      videoId: string;
      context: string;
      selectedIsMachine: boolean;
    }) => deleteVideoTracks(videoId, true),
    onSuccess: async (_, { videoId, context, selectedIsMachine }) => {
      if (selectedIsMachine && draftContextRef.current === context) {
        setSelectedTrackId("");
        trackDraft.reset();
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["video-tracks", videoId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-frame-spatial-metrics", videoId],
        }),
      ]);
    },
  });
  const deleteModelMutation = useMutation({
    mutationFn: (modelId: string) => deleteTrackingModel(modelId),
    onSuccess: async (_, modelId) => {
      setTrackingModelId((current) => (current === modelId ? "" : current));
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
      if (
        trackingMode === "hybrid" &&
        (!segmentationTrackingModelId ||
          selectedTrackingModel?.provider_name !== "ultralytics")
      ) {
        throw new Error(
          "Hybrid tracking needs an Ultralytics detector and segmenter",
        );
      }
      if (
        trackingMode === "hybrid" &&
        (hybridMatchIou <= 0 || hybridMatchIou > 1)
      ) {
        throw new Error(
          "Hybrid overlap IoU must be greater than zero and at most one",
        );
      }
      return createVideoTrackingJob(selectedVideoId, {
        model_id: trackingModelId,
        tracking_mode: trackingMode,
        segmentation_model_id:
          trackingMode === "hybrid" ? segmentationTrackingModelId : null,
        hybrid_match_iou: hybridMatchIou,
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
  const poseFrame = selectedTrackHidden
    ? undefined
    : keyframes.find((frame) => frame.frame === previewFrameIndex);
  const selectedOverlayBox =
    poseFrame?.bbox ?? (trackDraft.dirty ? undefined : overlayFrame?.bbox);
  const visibleTrackIds = useMemo(
    () => new Set(visibleTracks.map((track) => track.id)),
    [visibleTracks],
  );
  const overlayObjects = (spatialMetricsQuery.data?.objects ?? []).filter(
    (object) =>
      visibleTrackIds.has(object.track_id) &&
      (object.track_id !== selectedTrackId ||
        (!trackDraft.dirty && !selectedOverlayBox)),
  );
  const maskOverlays = useMemo(
    () =>
      visibleTracks.flatMap((track) => {
        const trackKeyframes =
          track.id === selectedTrackId ? keyframes : track.keyframes_json;
        const keyframe = trackKeyframes.find(
          (candidate) => candidate.frame === previewFrameIndex,
        );
        return (keyframe?.mask_polygons ?? []).map((polygon, polygonIndex) => ({
          key: `${track.id}:${previewFrameIndex}:${polygonIndex}`,
          polygon,
          trackId: track.id,
          trackNumber: track.track_number,
          polygonIndex,
        }));
      }),
    [keyframes, previewFrameIndex, selectedTrackId, visibleTracks],
  );
  const poseEditorSchema = useMemo(
    () =>
      selectedTrack && activeTrackPoseSchema
        ? editorSchemaForVideoTrack(selectedTrack, activeTrackPoseSchema)
        : null,
    [activeTrackPoseSchema, selectedTrack],
  );
  const poseEditorPose = useMemo(
    () =>
      selectedTrack && poseFrame && activeTrackPoseSchema
        ? poseInstanceFromVideoKeyframe(
            selectedTrack,
            poseFrame,
            activeTrackPoseSchema,
          )
        : null,
    [activeTrackPoseSchema, poseFrame, selectedTrack],
  );
  const extractionStride = Number(
    selectedVideo?.metadata_json.extraction_every_n_frames ?? everyNFrames,
  );
  const error =
    uploadMutation.error ??
    extractionMutation.error ??
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
    if (!selectedTrack || !activeTrackPoseSchema || !poseFrame) {
      throw new Error("Select a persisted pose track keyframe first");
    }
    if (trackDraft.dirty || saveTrackMutation.isPending) {
      throw new Error(
        "Save or cancel track edits before saving a pose correction",
      );
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
      activeTrackPoseSchema,
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
      ...(selectedAnatomySchema && !selectedTrackPoseSchema
        ? {
            pose_schema_binding: {
              schema_id: selectedAnatomySchema.id,
              schema_revision: selectedAnatomySchema.revision,
              content_hash: selectedAnatomySchema.content_hash,
            },
          }
        : {}),
    });
    const persistedFrame = updatedTrack.keyframes_json.find(
      (frame) => frame.frame === poseFrame.frame,
    );
    if (!persistedFrame) {
      throw new Error("Saved track did not return the corrected pose keyframe");
    }

    trackDraft.reset();

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
      activeTrackPoseSchema,
    );
  }

  function updateKeyframe(
    index: number,
    field: "frame" | "x" | "y" | "width" | "height",
    value: number,
  ) {
    trackDraft.change((current) => {
      const keyframe = current.keyframes[index];
      if (!keyframe) return current;
      const keyframes = [...current.keyframes];
      if (field === "frame") {
        if (keyframe.frame === value) return current;
        keyframes[index] = { ...keyframe, frame: value };
      } else {
        const bbox = [...keyframe.bbox] as [number, number, number, number];
        const bboxIndex = { x: 0, y: 1, width: 2, height: 3 }[field];
        if (bbox[bboxIndex] === value) return current;
        bbox[bboxIndex] = value;
        keyframes[index] = { ...keyframe, bbox };
      }
      return { ...current, keyframes };
    });
  }

  function updateKeyframeMaskPolygons(index: number, value: string) {
    if (!selectedVideo) return;
    try {
      const maskPolygons = parseMaskPolygons(
        value,
        selectedVideo.width_px,
        selectedVideo.height_px,
      );
      trackDraft.change((current) => {
        const keyframe = current.keyframes[index];
        if (
          !keyframe ||
          JSON.stringify(maskPolygons ?? []) ===
            JSON.stringify(keyframe.mask_polygons ?? [])
        )
          return current;
        const keyframes = [...current.keyframes];
        keyframes[index] = { ...keyframe, mask_polygons: maskPolygons };
        return { ...current, keyframes };
      });
      setMaskEditError(null);
    } catch (error) {
      setMaskEditError(
        error instanceof Error ? error.message : "Invalid mask polygons",
      );
    }
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
    if (
      workspaceCommand.type === "select_model" &&
      !(modelsQuery.data ?? []).some(
        (model) => model.id === workspaceCommand.modelId,
      )
    ) {
      return;
    }

    if (
      (workspaceCommand.type === "select_video" ||
        workspaceCommand.type === "open_comparison_frame" ||
        workspaceCommand.type === "open_pose_evidence" ||
        workspaceCommand.type === "open_workflow_pose_review") &&
      videosQuery.data === undefined
    ) {
      return;
    }

    if (
      workspaceCommand.type === "open_pose_evidence" ||
      workspaceCommand.type === "open_comparison_frame" ||
      workspaceCommand.type === "open_workflow_pose_review"
    ) {
      const targetExists = videosQuery.data?.some(
        (video) => video.id === workspaceCommand.videoId,
      );
      if (targetExists && selectedVideo?.id !== workspaceCommand.videoId) {
        setSelectedVideoId(workspaceCommand.videoId);
        return;
      }
      if (
        targetExists &&
        (workspaceCommand.type === "open_workflow_pose_review" ||
          (workspaceCommand.type === "open_pose_evidence" &&
            workspaceCommand.sourceTrackId)) &&
        !tracksQuery.data
      )
        return;
      if (
        targetExists &&
        workspaceCommand.type === "open_workflow_pose_review" &&
        !tracksQuery.isFetchedAfterMount &&
        !tracksQuery.data?.some(
          (track) => track.id === workspaceCommand.trackId,
        )
      ) {
        // A replay can create another track while this recording's prior list is cached.
        return;
      }
    }

    lastWorkspaceCommandIdRef.current = workspaceCommand.id;

    if (
      workspaceCommand.type === "open_comparison_frame" &&
      selectedVideo?.id === workspaceCommand.videoId
    ) {
      const frame = Math.min(
        Math.max(
          0,
          workspaceCommand.frameIndex ??
            Math.round((workspaceCommand.seconds ?? 0) * selectedVideo.fps),
        ),
        Math.max(0, selectedVideo.frame_count - 1),
      );
      seekVideoFromMap(
        frame,
        workspaceCommand.seconds ??
          (selectedVideo.fps > 0 ? frame / selectedVideo.fps : 0),
      );
      setPreviewFrameIndex(frame);
    }

    if (
      workspaceCommand.type === "open_pose_evidence" &&
      selectedVideo?.id === workspaceCommand.videoId
    ) {
      const frame = Math.min(
        workspaceCommand.frameIndex,
        Math.max(0, selectedVideo.frame_count - 1),
      );
      seekVideoFromMap(
        frame,
        selectedVideo.fps > 0 ? frame / selectedVideo.fps : 0,
      );
      setPreviewFrameIndex(frame);
      if (
        tracksQuery.data?.some(
          (track) => track.id === workspaceCommand.sourceTrackId,
        )
      ) {
        setSelectedTrackId(workspaceCommand.sourceTrackId ?? "");
      }
      setPoseEvidence(workspaceCommand);
    }

    if (
      workspaceCommand.type === "open_workflow_pose_review" &&
      selectedVideo?.id === workspaceCommand.videoId &&
      tracksQuery.data?.some((track) => track.id === workspaceCommand.trackId)
    ) {
      setSelectedTrackId(workspaceCommand.trackId);
      setSourceOverlayEnabled(true);
      setWorkflowReviewRound({
        videoId: workspaceCommand.videoId,
        roundId: workspaceCommand.roundId,
      });
    }

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

    if (workspaceCommand.type === "select_model") {
      if (
        (modelsQuery.data ?? []).some(
          (model) => model.id === workspaceCommand.modelId,
        )
      ) {
        setTrackingModelId(workspaceCommand.modelId);
        setTrackingMode("auto");
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
    modelsQuery.data,
    selectedVideo,
    tracksQuery.data,
    tracksQuery.isFetchedAfterMount,
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
      {confirmationDialog}
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
      <AnatomySkeletonDesigner
        projectId={project.id}
        onSchemaSelected={setSelectedAnatomySchema}
      />
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
        {telemetryFile && (
          <div className="workspace-guide compact">
            <label>
              SRT wall-clock UTC offset (minutes, optional)
              <input
                type="number"
                min={-840}
                max={840}
                step={1}
                value={telemetryUtcOffsetMinutes}
                onChange={(event) =>
                  setTelemetryUtcOffsetMinutes(event.target.value)
                }
              />
            </label>
            <label>
              SRT timezone evidence
              <textarea
                value={telemetryUtcOffsetEvidence}
                onChange={(event) =>
                  setTelemetryUtcOffsetEvidence(event.target.value)
                }
                placeholder="Describe the field log or source metadata establishing this offset."
              />
            </label>
            <p className="annotation-helper">
              SRT wall-clock text has no timezone. ReefVision only derives UTC
              when both an explicit offset and independent evidence are saved;
              otherwise absolute UTC remains unavailable.
            </p>
          </div>
        )}
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
            disabled={trackDraft.dirty || saveTrackMutation.isPending}
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
            <p className="annotation-helper">
              Absolute SRT time:{" "}
              {selectedVideo.telemetry.utc_offset_minutes !== undefined &&
              selectedVideo.telemetry.utc_offset_minutes !== null
                ? `evidence-backed UTC offset ${selectedVideo.telemetry.utc_offset_minutes} min · ${selectedVideo.telemetry.wall_clock_sample_count ?? 0} wall-clock samples · ${selectedVideo.telemetry.utc_offset_evidence ?? "evidence unavailable"} · ${selectedVideo.telemetry.content_sha256?.slice(0, 12) ?? "unhashed"}…`
                : "unavailable; the SRT wall clock is not assigned a timezone without explicit evidence"}
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
                  {overlayObjects.map((object) => (
                    <rect
                      key={object.track_id}
                      data-track-id={object.track_id}
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
                  {editableTrack &&
                    selectedOverlayBox &&
                    !overlayObjects.some(
                      (object) => object.track_id === selectedTrackId,
                    ) && (
                      <rect
                        data-track-id={selectedTrackId || undefined}
                        x={selectedOverlayBox[0]}
                        y={selectedOverlayBox[1]}
                        width={selectedOverlayBox[2]}
                        height={selectedOverlayBox[3]}
                        fill="none"
                        stroke="var(--accent-color, #2563eb)"
                        strokeWidth={4}
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  {maskOverlays.map((mask) => (
                    <polygon
                      key={mask.key}
                      aria-label={`Segmentation mask ${mask.polygonIndex + 1} for track ${mask.trackNumber}`}
                      points={mask.polygon
                        .map(([x, y]) => `${x},${y}`)
                        .join(" ")}
                      fill={
                        mask.trackId === selectedTrackId
                          ? "rgba(37, 99, 235, 0.24)"
                          : "rgba(255, 212, 59, 0.18)"
                      }
                      stroke={
                        mask.trackId === selectedTrackId
                          ? "var(--accent-color, #2563eb)"
                          : "#ffd43b"
                      }
                      strokeWidth={mask.trackId === selectedTrackId ? 4 : 2}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
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
                {activeTrackPoseSchema && (
                  <p className="annotation-helper">
                    Landmark schema:{" "}
                    {activeTrackPoseSchema.groups
                      .map((group) => `${group.name} × ${group.count}`)
                      .join(" · ")}
                  </p>
                )}
              </>
            )}
            <PoseActiveLearningPanel
              key={`${selectedVideo.id}/${workflowReviewRound?.roundId ?? ""}`}
              projectId={project.id}
              videoId={selectedVideo.id}
              initialRoundId={
                workflowReviewRound?.videoId === selectedVideo.id
                  ? workflowReviewRound.roundId
                  : undefined
              }
              activeCandidateId={activePoseActiveLearningCandidate?.id ?? null}
              selectedTrack={selectedTrack ?? undefined}
              onOpenCandidate={(candidate) => {
                setActivePoseActiveLearningCandidate(candidate);
                setSelectedTrackId(candidate.video_track_id);
                setFrameIndex(candidate.focus_frame);
                setPreviewFrameIndex(candidate.focus_frame);
              }}
            />

            {selectedVideo.frame_directory_path &&
              selectedTrack &&
              activeTrackPoseSchema &&
              poseEditorSchema &&
              poseEditorPose &&
              poseFrame && (
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
            {selectedTrack && activeTrackPoseSchema && (
              <PoseTemporalReviewPanel
                trackId={selectedTrack.id}
                frameIndex={frameIndex}
                onFrameChange={(nextFrame) => {
                  setFrameIndex(nextFrame);
                  setPreviewFrameIndex(nextFrame);
                }}
              />
            )}
            {selectedTrack && activeTrackPoseSchema && (
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

      {selectedVideo &&
        (tracksQuery.data ?? []).some((track) =>
          Boolean(poseLandmarkSchemaFromMetadata(track.metadata_json)),
        ) && (
          <>
            <PoseIdentityReviewPanel
              key={`identity-${selectedVideo.id}-${poseEvidence?.videoId === selectedVideo.id ? poseEvidence.id : ""}`}
              evidence={
                poseEvidence?.videoId === selectedVideo.id ? poseEvidence : null
              }
              projectId={project.id}
              videoId={selectedVideo.id}
              frameIndex={frameIndex}
              tracks={tracksQuery.data ?? []}
              onFrameChange={(nextFrame) => {
                setFrameIndex(nextFrame);
                setPreviewFrameIndex(nextFrame);
              }}
            />
            <BiologicalMovementPanel
              key={`movement-${selectedVideo.id}-${poseEvidence?.videoId === selectedVideo.id ? poseEvidence.id : ""}-${temporalReview?.identityRunId ?? ""}`}
              evidence={
                temporalReview?.videoId === selectedVideo.id
                  ? temporalReview
                  : poseEvidence?.videoId === selectedVideo.id
                    ? poseEvidence
                    : null
              }
              projectId={project.id}
              videoId={selectedVideo.id}
              tracks={tracksQuery.data ?? []}
              onFrameChange={(nextFrame) => {
                setFrameIndex(nextFrame);
                setPreviewFrameIndex(nextFrame);
              }}
            />
            <ReefPoseValidationPanel
              key={project.id}
              projectId={project.id}
              videoId={selectedVideo.id}
              onFrameChange={(nextFrame) => {
                setFrameIndex(nextFrame);
                setPreviewFrameIndex(nextFrame);
              }}
            />
            <TemporalReefPosePanel
              key={`temporal-${project.id}-${selectedVideo.id}`}
              projectId={project.id}
              videoId={selectedVideo.id}
              onFrameChange={(nextFrame) => {
                setFrameIndex(nextFrame);
                setPreviewFrameIndex(nextFrame);
              }}
              onReviewed={(identityRunId, animalIdentityId) => {
                setTemporalReview({
                  videoId: selectedVideo.id,
                  identityRunId,
                  animalIdentityId,
                  frameIndex,
                });
                requestAnimationFrame(() => {
                  const target = document.querySelector<HTMLElement>(
                    '[aria-label="Biological movement analysis"]',
                  );
                  target?.setAttribute("tabindex", "-1");
                  target?.focus();
                  target?.scrollIntoView({ block: "start" });
                });
              }}
            />
          </>
        )}

      {selectedVideo && (
        <section className="management-card">
          <p className="eyebrow">Pose exchange</p>
          <h3>Pose interoperability</h3>
          <div className="workspace-guide compact">
            <div>
              <strong>Import/export safeguards</strong>
              <p className="annotation-helper">
                Import or export canonical pose data through neutral formats.
                ReefVision-exported files must match the target video checksum.
                For external text files, confirm that the frame indices match
                this video. NWB requires the optional interchange codec and a
                checksum that binds the pose data to its frame mapping.
              </p>
            </div>
            {selectedTrack && selectedTrackPoseSchema && (
              <>
                <p className="annotation-helper">
                  Exports include verified pose tracks for this video by
                  default. Include unreviewed tracks for archival transfer when
                  you need them. The bundle records each source track's review
                  status. Repeated semantic labels receive stable external node
                  names. NWB, COCO, DeepLabCut, and Ultralytics downloads are
                  ZIP bundles containing the standard native artifact plus a
                  ReefVision manifest for exact frame and identity restoration.
                  The full immutable association/correction audit history
                  remains in ReefVision.
                </p>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={includeUnreviewedInPoseExport}
                    onChange={(event) =>
                      setIncludeUnreviewedInPoseExport(event.target.checked)
                    }
                  />
                  Include unreviewed tracks in archival export
                </label>
                {!hasVerifiedPoseTracks && !includeUnreviewedInPoseExport ? (
                  <p className="annotation-helper">
                    No verified pose tracks are available. Review a track or
                    choose an archival export to include it.
                  </p>
                ) : (
                  <div className="workspace-actions">
                    {POSE_EXPORT_FORMATS.map(([format, label]) => (
                      <a
                        key={format}
                        href={poseInteroperabilityExportUrl(
                          selectedVideo.id,
                          format,
                          includeUnreviewedInPoseExport,
                        )}
                      >
                        {label}
                      </a>
                    ))}
                  </div>
                )}
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
                value={poseImportClassId}
                onChange={(event) => setPoseImportClass(event.target.value)}
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
                key={selectedVideo.id}
                aria-label="Pose interoperability import file"
                type="file"
                accept=".nwb,.json,.csv,.zip,application/zip"
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
              Choose an identity class and pose file to enable import. External
              tracked instances keep their grouping. Untracked instances are
              never auto-associated across frames.
            </p>
            <button
              type="button"
              onClick={() => poseInteropImportMutation.mutate()}
              disabled={
                !poseInteropImportFile ||
                !poseImportClassId ||
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
        {selectedVideo && project.label_classes.length > 0 && (
          <div
            className="annotation-selection-list"
            role="group"
            aria-label="Video track class visibility"
          >
            <strong>Class visibility</strong>
            <p className="annotation-helper">
              Controls the track picker and source-coordinate preview for this
              session. Exports include all active tracks.
            </p>
            {project.label_classes.map((labelClass) => {
              const id = labelClass.id;
              const visible = classIsVisible(id);
              return (
                <div key={id} className="annotation-selection-row">
                  <span>{labelClass.name}</span>
                  <button
                    type="button"
                    className="secondary"
                    aria-label={`${visible ? "Hide" : "Show"} class ${labelClass.name}`}
                    onClick={() => {
                      const hidden = soloClassId
                        ? project.label_classes
                            .filter((candidate) => candidate.id !== soloClassId)
                            .map((candidate) => candidate.id)
                        : hiddenClassIds;
                      setVisibility({
                        projectId: project.id,
                        hidden: visible
                          ? [...hidden, id]
                          : hidden.filter((classId) => classId !== id),
                      });
                    }}
                  >
                    {visible ? "Hide" : "Show"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    aria-label={`Solo class ${labelClass.name}`}
                    aria-pressed={soloClassId === id}
                    onClick={() =>
                      setVisibility({
                        projectId: project.id,
                        hidden: sessionVisibility?.hidden,
                        solo: soloClassId === id ? undefined : id,
                      })
                    }
                  >
                    Solo
                  </button>
                </div>
              );
            })}
            {sessionVisibility && (
              <button
                type="button"
                className="secondary"
                onClick={() => setVisibility(null)}
              >
                Reset class visibility
              </button>
            )}
          </div>
        )}
        <label>
          Existing track
          <select
            value={selectedTrackId}
            disabled={trackDraft.dirty || saveTrackMutation.isPending}
            onChange={(event) => setSelectedTrackId(event.target.value)}
          >
            <option value="">New track</option>
            {selectedTrackHidden && (
              <option value={selectedTrackId}>Selected track is hidden</option>
            )}
            {visibleTracks.map((track) => (
              <option key={track.id} value={track.id}>
                Track {track.track_number} —{" "}
                {project.label_classes.find(
                  (item) => item.id === track.label_class_id,
                )?.name ?? "Class unavailable"}{" "}
                — {track.status}
              </option>
            ))}
          </select>
        </label>
        {selectedTrackHidden && (
          <p role="status">
            Show the selected track’s class to continue editing it.
          </p>
        )}
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            className="secondary"
            disabled={
              !editableTrack ||
              !trackDraft.canUndo ||
              saveTrackMutation.isPending
            }
            onClick={() => {
              trackDraft.undo();
              setMaskEditError(null);
              setDraftFormReset((current) => current + 1);
            }}
          >
            Undo
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              !editableTrack ||
              !trackDraft.canRedo ||
              saveTrackMutation.isPending
            }
            onClick={() => {
              trackDraft.redo();
              setMaskEditError(null);
              setDraftFormReset((current) => current + 1);
            }}
          >
            Redo
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              saveTrackMutation.isPending ||
              (!trackDraft.dirty &&
                !trackDraft.canRedo &&
                !maskEditError &&
                !saveTrackMutation.isError)
            }
            onClick={() => {
              trackDraft.reset();
              setMaskEditError(null);
              setDraftFormReset((current) => current + 1);
              saveTrackMutation.reset();
              void tracksQuery.refetch();
            }}
          >
            Cancel track edits
          </button>
        </div>
        {trackSelectionChanged && (
          <p className="annotation-helper">
            A newer track revision is available. Cancel track edits to load it.
          </p>
        )}
        {saveTrackMutation.error && (
          <p role="alert" className="form-error">
            {saveTrackMutation.error.message}
          </p>
        )}
        <fieldset
          disabled={!editableTrack || saveTrackMutation.isPending}
          style={{ minWidth: 0 }}
        >
          <legend>Track details</legend>
          <label>
            Identity class
            <select
              value={labelClassId}
              onChange={(event) => {
                const value = event.target.value;
                trackDraft.change((current) =>
                  current.labelClassId === value
                    ? current
                    : { ...current, labelClassId: value },
                );
              }}
            >
              {project.label_classes
                .filter(
                  (labelClass) =>
                    labelClass.is_active ||
                    labelClass.id === selectedTrack?.label_class_id,
                )
                .map((labelClass) => (
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
              onChange={(event) => {
                const value = event.target.value === "hold" ? "hold" : "linear";
                trackDraft.change((current) =>
                  current.interpolation === value
                    ? current
                    : { ...current, interpolation: value },
                );
              }}
            >
              <option value="linear">Linear</option>
              <option value="hold">Hold previous box</option>
            </select>
          </label>
          <label>
            Status
            <select
              value={trackStatus}
              onChange={(event) => {
                const value = event.target.value;
                trackDraft.change((current) =>
                  current.status === value
                    ? current
                    : { ...current, status: value },
                );
              }}
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
            disabled={
              !selectedVideo ||
              keyframes.some((item) => item.frame === frameIndex)
            }
            onClick={() => {
              if (!selectedVideo) return;
              const x = Math.min(10, selectedVideo.width_px - 1);
              const y = Math.min(10, selectedVideo.height_px - 1);
              trackDraft.change((current) => ({
                ...current,
                keyframes: sortedKeyframes([
                  ...current.keyframes,
                  {
                    frame: frameIndex,
                    bbox: [
                      x,
                      y,
                      Math.min(50, selectedVideo.width_px - x),
                      Math.min(30, selectedVideo.height_px - y),
                    ],
                    confidence: null,
                  },
                ]),
              }));
            }}
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
                  <th>Mask polygons (source-pixel JSON)</th>
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
                          aria-label={`${field} for keyframe ${keyframe.frame}`}
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
                      <textarea
                        key={`${selectedTrackId}:${draftFormReset}:${keyframe.frame}:${JSON.stringify(keyframe.mask_polygons ?? null)}`}
                        aria-label={`Mask polygons for frame ${keyframe.frame}`}
                        defaultValue={JSON.stringify(
                          keyframe.mask_polygons ?? [],
                        )}
                        onBlur={(event) =>
                          updateKeyframeMaskPolygons(index, event.target.value)
                        }
                        rows={3}
                        style={{ minWidth: 240 }}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="danger-ghost"
                        onClick={() =>
                          trackDraft.change((current) => ({
                            ...current,
                            keyframes: current.keyframes.filter(
                              (_item, itemIndex) => itemIndex !== index,
                            ),
                          }))
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
          {maskEditError && (
            <p role="alert" className="annotation-helper">
              {maskEditError}
            </p>
          )}
          <div className="annotation-editor-inline-actions">
            <button
              type="button"
              disabled={
                saveTrackMutation.isPending ||
                (!trackDraft.dirty && !!selectedTrack) ||
                keyframes.length === 0 ||
                maskEditError !== null
              }
              onClick={() =>
                saveTrackMutation.mutate({
                  context: draftContext,
                  videoId: selectedVideoId,
                })
              }
            >
              {saveTrackMutation.isPending ? "Saving..." : "Save track"}
            </button>
            <button
              type="button"
              className="danger-ghost"
              disabled={
                !selectedTrackId ||
                trackDraft.dirty ||
                deleteTrackMutation.isPending
              }
              onClick={() => deleteTrackMutation.mutate()}
            >
              Delete track
            </button>
            <button
              type="button"
              className="danger-ghost"
              disabled={
                !selectedVideoId ||
                trackDraft.dirty ||
                deleteMachineTracksMutation.isPending ||
                !(tracksQuery.data ?? []).some((track) => track.source_job_id)
              }
              onClick={async () => {
                if (!selectedVideoId) return;
                const accepted = await confirm({
                  title: "Remove machine tracks?",
                  message:
                    "Remove all machine-generated tracks for this video? Manual tracks are preserved.",
                  confirmLabel: "Remove machine tracks",
                  destructive: true,
                });
                if (accepted && draftContextRef.current === draftContext) {
                  deleteMachineTracksMutation.mutate({
                    videoId: selectedVideoId,
                    context: draftContext,
                    selectedIsMachine: !!selectedTrack?.source_job_id,
                  });
                }
              }}
            >
              Remove machine tracks
            </button>
          </div>
        </fieldset>
      </section>

      <section className="management-card">
        <p className="eyebrow">Automated tracking</p>
        <h3>Detection / segmentation / hybrid video tracking</h3>
        <label>
          Tracking mode
          <select
            value={trackingMode}
            onChange={(event) =>
              setTrackingMode(
                event.target.value as "auto" | "detect" | "segment" | "hybrid",
              )
            }
          >
            <option value="auto">
              Single model (auto: detection, segmentation, or pose)
            </option>
            <option value="detect">Detection tracking</option>
            <option value="segment">Segmentation tracking</option>
            <option value="hybrid">Hybrid detection + segmentation</option>
          </select>
        </label>
        <label>
          {trackingMode === "hybrid" ? "Detection model" : "Tracking model"}
          <select
            value={trackingModelId}
            onChange={(event) => setTrackingModelId(event.target.value)}
          >
            {eligibleTrackingModels.length === 0 && (
              <option value="">No compatible models registered</option>
            )}
            {eligibleTrackingModels.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name} ({model.task})
              </option>
            ))}
          </select>
        </label>
        {trackingMode === "hybrid" && (
          <>
            <label>
              Segmentation model
              <select
                value={segmentationTrackingModelId}
                onChange={(event) =>
                  setSegmentationTrackingModelId(event.target.value)
                }
              >
                {eligibleSegmentationModels.length === 0 && (
                  <option value="">
                    Register an Ultralytics instance-segmentation model
                  </option>
                )}
                {eligibleSegmentationModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name} ({model.task})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Hybrid matching IoU
              <input
                type="number"
                min={0.05}
                max={1}
                step={0.05}
                value={hybridMatchIou}
                onChange={(event) =>
                  setHybridMatchIou(Number(event.target.value))
                }
              />
            </label>
            <p className="annotation-helper">
              Runs detector and segmenter on the same video and reconciles
              class-mapped tracks. Segment polygons are retained for matched
              observations; unmatched objects remain reviewable.
            </p>
          </>
        )}
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
            onClick={async () => {
              if (!trackingModelId) return;
              const model = (modelsQuery.data ?? []).find(
                (item) => item.id === trackingModelId,
              );
              if (
                await confirm({
                  title: "Remove tracking model?",
                  message: `Remove model "${model?.display_name ?? trackingModelId}" from this project?`,
                  confirmLabel: "Remove model",
                  destructive: true,
                })
              ) {
                deleteModelMutation.mutate(trackingModelId);
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
              <strong>Historical SLEAP-NN model unavailable</strong>
              <p className="annotation-helper">
                Active SLEAP-NN execution is retired pending an authoritative
                license resolution. ReefVision keeps this registration and its
                provenance readable; use native ReefPose or an audited neutral
                export for new work.
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
            sleapTrackingSelected ||
            (trackingMode === "hybrid" &&
              (!segmentationTrackingModelId ||
                selectedTrackingModel?.provider_name !== "ultralytics" ||
                !linkDetections)) ||
            (poseTrackingSelected && selectedModelPoseSchema === null)
          }
          onClick={() => trackingMutation.mutate()}
        >
          {trackingMutation.isPending
            ? "Queuing..."
            : sleapTrackingSelected
              ? "SLEAP-NN execution unavailable"
              : linkDetections
                ? trackingMode === "hybrid"
                  ? `Run hybrid + ${trackerLabel(trackerName)}`
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
                  <th>Mode</th>
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
                      <td>{run.tracking_mode ?? "auto"}</td>
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

      {selectedVideo && (
        <EnvironmentalSubjectInspector
          projectId={project.id}
          subject={{
            video_id: selectedVideo.id,
            frame_index: frameIndex,
            track_id: selectedTrackId || null,
          }}
        />
      )}

      <GeographicMovementAnalyticsPanel
        projectId={project.id}
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
              {benchmarkMutation.data.winner ? (
                <>
                  <strong>{benchmarkMutation.data.winner}</strong> ranked first.
                </>
              ) : (
                <strong>Multiple runs tied for first place.</strong>
              )}{" "}
              Runs are ranked by MOTA, recall, precision, identity switches,
              fragmentations, then center error. Equal scores share a rank.
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
