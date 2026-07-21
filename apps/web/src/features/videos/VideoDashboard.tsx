import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Project } from "../../api/client";
import {
  addVideoTrackObservation,
  analyzeVideo,
  archiveVideoTrack,
  calibrateVideo,
  cancelJob,
  correctVideoTrackIdentity,
  createVideoDataExport,
  createVideoRenderExport,
  createVideoTrack,
  createVideoTracking,
  createVideoZone,
  deleteVideoTrackObservation,
  deleteVideoZone,
  downloadUrl,
  evaluateVideoTracking,
  getJob,
  getModels,
  getVideoTrackingEvaluations,
  getVideoTracks,
  getVideoZones,
  getVideos,
  mergeVideoTracks,
  reassignVideoTrackObservations,
  restoreVideoTrackObservation,
  splitVideoTrack,
  updateVideoTrack,
  updateVideoTrackObservation,
  updateVideoZone,
  uploadVideo,
  type JobRecord,
  type VideoAnalytics,
  type VideoTrack,
  type VideoTrackKeyframe,
  type VideoTrackingEvaluation,
  type VideoZone,
} from "../phase456/api";

type TrackerKind = "bytetrack" | "botsort";
type DeviceKind = "auto" | "cpu" | "cuda";
type RenderKind = "annotated" | "trajectory" | "heatmap";

interface ObservationDraft {
  frame: string;
  xMin: string;
  yMin: string;
  xMax: string;
  yMax: string;
  confidence: string;
}

interface ZoneDraft {
  name: string;
  xMin: string;
  yMin: string;
  xMax: string;
  yMax: string;
}

const terminalJobStatuses = new Set(["succeeded", "failed", "cancelled"]);

function operationId(prefix: string): string {
  const random =
    globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `${prefix}-${random}`;
}

function emptyObservation(frame = 0): ObservationDraft {
  return {
    frame: String(frame),
    xMin: "10",
    yMin: "10",
    xMax: "60",
    yMax: "45",
    confidence: "",
  };
}

function emptyZone(): ZoneDraft {
  return {
    name: "",
    xMin: "0",
    yMin: "0",
    xMax: "100",
    yMax: "100",
  };
}

function activeObservations(track: VideoTrack): VideoTrackKeyframe[] {
  return track.keyframes
    .filter((item) => item.deleted_at === null)
    .sort((left, right) => left.frame_index - right.frame_index);
}

function observationAtFrame(
  track: VideoTrack,
  frame: number,
): VideoTrackKeyframe | null {
  const observations = activeObservations(track);
  const exact = observations.find((item) => item.frame_index === frame);
  if (exact) return exact;
  const rightIndex = observations.findIndex((item) => item.frame_index > frame);
  if (rightIndex <= 0) return null;
  const left = observations[rightIndex - 1];
  const right = observations[rightIndex];
  if (!left || !right) return null;
  const frameDelta = right.frame_index - left.frame_index;
  if (frameDelta <= 0) return null;
  const ratio = (frame - left.frame_index) / frameDelta;
  const geometryRatio = track.interpolation === "hold" ? 0 : ratio;
  return {
    ...left,
    id: null,
    frame_index: frame,
    timestamp_seconds:
      left.timestamp_seconds !== null && right.timestamp_seconds !== null
        ? left.timestamp_seconds +
          (right.timestamp_seconds - left.timestamp_seconds) * ratio
        : null,
    x_min: left.x_min + (right.x_min - left.x_min) * geometryRatio,
    y_min: left.y_min + (right.y_min - left.y_min) * geometryRatio,
    x_max: left.x_max + (right.x_max - left.x_max) * geometryRatio,
    y_max: left.y_max + (right.y_max - left.y_max) * geometryRatio,
    centroid_x: null,
    centroid_y: null,
    source: "interpolated",
    manual_edit: false,
    automated_provenance: null,
    revision: 1,
  };
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function trackColor(project: Project, track: VideoTrack): string {
  return (
    project.label_classes.find((item) => item.id === track.label_class_id)
      ?.display_color ?? "#67e8cf"
  );
}

export function VideoDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const playerRef = useRef<HTMLVideoElement>(null);
  const refreshedJobId = useRef("");
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [selectedTrackId, setSelectedTrackId] = useState("");
  const [selectedObservationId, setSelectedObservationId] = useState("");
  const [secondaryTrackId, setSecondaryTrackId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [detectorId, setDetectorId] = useState("");
  const [tracker, setTracker] = useState<TrackerKind>("bytetrack");
  const [device, setDevice] = useState<DeviceKind>("auto");
  const [confidence, setConfidence] = useState(0.25);
  const [iou, setIou] = useState(0.45);
  const [everyNFrames, setEveryNFrames] = useState(1);
  const [trackHighThreshold, setTrackHighThreshold] = useState(0.25);
  const [trackLowThreshold, setTrackLowThreshold] = useState(0.1);
  const [trackBuffer, setTrackBuffer] = useState(30);
  const [gmcMethod, setGmcMethod] = useState("sparseOptFlow");
  const [activeJobId, setActiveJobId] = useState("");
  const [activeJobKind, setActiveJobKind] = useState<"tracking" | "render">(
    "tracking",
  );
  const [distancePerPixel, setDistancePerPixel] = useState("");
  const [physicalUnit, setPhysicalUnit] = useState("cm");
  const [trackName, setTrackName] = useState("");
  const [trackClassId, setTrackClassId] = useState("");
  const [groundTruth, setGroundTruth] = useState(false);
  const [observation, setObservation] = useState<ObservationDraft>(() =>
    emptyObservation(),
  );
  const [splitFrame, setSplitFrame] = useState(1);
  const [editingZoneId, setEditingZoneId] = useState("");
  const [zoneDraft, setZoneDraft] = useState<ZoneDraft>(() => emptyZone());
  const [heatmapBins, setHeatmapBins] = useState(20);
  const [activityThreshold, setActivityThreshold] = useState(1);
  const [confidenceComparisons, setConfidenceComparisons] =
    useState("0.25, 0.5");
  const [renderKind, setRenderKind] = useState<RenderKind>("annotated");
  const [showTrajectories, setShowTrajectories] = useState(true);
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
  });
  const zones = useQuery({
    queryKey: ["phase6_zones", selectedVideoId],
    queryFn: ({ signal }) => getVideoZones(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
  });
  const evaluations = useQuery({
    queryKey: ["phase6_evaluations", selectedVideoId],
    queryFn: ({ signal }) =>
      getVideoTrackingEvaluations(selectedVideoId, signal),
    enabled: Boolean(selectedVideoId),
  });
  const activeJob = useQuery({
    queryKey: ["phase6_job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId, signal),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const job = query.state.data as JobRecord | undefined;
      return job && terminalJobStatuses.has(job.status) ? false : 750;
    },
  });

  const selectedVideo = useMemo(
    () => videos.data?.find((video) => video.id === selectedVideoId) ?? null,
    [selectedVideoId, videos.data],
  );
  const detectors = useMemo(
    () =>
      models.data?.filter(
        (model) =>
          model.purpose === "detector" &&
          model.task === "detect" &&
          model.provider_name === "ultralytics",
      ) ?? [],
    [models.data],
  );
  const selectedTrack = useMemo(
    () => tracks.data?.find((track) => track.id === selectedTrackId) ?? null,
    [selectedTrackId, tracks.data],
  );
  const selectedObservation = useMemo(
    () =>
      selectedTrack?.keyframes.find(
        (item) => item.id === selectedObservationId,
      ) ?? null,
    [selectedObservationId, selectedTrack],
  );
  const otherTracks = useMemo(
    () => tracks.data?.filter((track) => track.id !== selectedTrackId) ?? [],
    [selectedTrackId, tracks.data],
  );

  useEffect(() => {
    const available = videos.data ?? [];
    if (!available.some((video) => video.id === selectedVideoId)) {
      setSelectedVideoId(available[0]?.id ?? "");
    }
  }, [selectedVideoId, videos.data]);

  useEffect(() => {
    if (!detectors.some((model) => model.id === detectorId)) {
      setDetectorId(detectors[0]?.id ?? "");
    }
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

  useEffect(() => {
    if (!selectedTrack) {
      setSelectedTrackId("");
      setSelectedObservationId("");
      setTrackName("");
      setTrackClassId("");
      setGroundTruth(false);
      return;
    }
    setTrackName(selectedTrack.name ?? `Track ${selectedTrack.track_number}`);
    setTrackClassId(selectedTrack.label_class_id ?? "");
    setGroundTruth(selectedTrack.is_ground_truth);
    if (
      selectedObservationId &&
      !selectedTrack.keyframes.some((item) => item.id === selectedObservationId)
    ) {
      setSelectedObservationId("");
    }
    if (!otherTracks.some((track) => track.id === secondaryTrackId)) {
      setSecondaryTrackId(otherTracks[0]?.id ?? "");
    }
  }, [otherTracks, secondaryTrackId, selectedObservationId, selectedTrack]);

  useEffect(() => {
    if (!selectedObservation) return;
    setObservation({
      frame: String(selectedObservation.frame_index),
      xMin: String(selectedObservation.x_min),
      yMin: String(selectedObservation.y_min),
      xMax: String(selectedObservation.x_max),
      yMax: String(selectedObservation.y_max),
      confidence:
        selectedObservation.confidence === null ||
        selectedObservation.confidence === undefined
          ? ""
          : String(selectedObservation.confidence),
    });
  }, [selectedObservation]);

  useEffect(() => {
    const job = activeJob.data;
    if (!job || !terminalJobStatuses.has(job.status)) return;
    if (refreshedJobId.current === job.id) return;
    refreshedJobId.current = job.id;
    if (activeJobKind === "tracking") {
      void queryClient.invalidateQueries({
        queryKey: ["phase6_tracks", selectedVideoId],
      });
    }
    setMessage(
      job.status === "succeeded"
        ? `${activeJobKind === "tracking" ? "Tracking" : "Rendered export"} completed.`
        : `${activeJobKind === "tracking" ? "Tracking" : "Rendered export"} ${job.status}.`,
    );
  }, [activeJob.data, activeJobKind, queryClient, selectedVideoId]);

  async function refreshTracks() {
    await queryClient.invalidateQueries({
      queryKey: ["phase6_tracks", selectedVideoId],
    });
  }

  async function refreshZones() {
    await queryClient.invalidateQueries({
      queryKey: ["phase6_zones", selectedVideoId],
    });
  }

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a video file first.");
      return uploadVideo(project.id, file);
    },
    onSuccess: async (result) => {
      changeVideo(result.video.id);
      setMessage(
        result.duplicate
          ? "Existing managed video selected."
          : "Video imported into managed storage.",
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
        throw new Error("Select a video and enter distance per pixel.");
      }
      return calibrateVideo(selectedVideoId, {
        distance_per_pixel: Number(distancePerPixel),
        unit: physicalUnit,
        source: "video dashboard",
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
        throw new Error("Choose a managed video and compatible detector.");
      }
      return createVideoTracking(selectedVideoId, {
        model_id: detectorId,
        tracker,
        device,
        confidence_threshold: confidence,
        iou_threshold: iou,
        every_n_frames: everyNFrames,
        replace_generated_tracks: true,
        tracker_options: {
          track_high_thresh: trackHighThreshold,
          track_low_thresh: trackLowThreshold,
          track_buffer: trackBuffer,
          ...(tracker === "botsort" ? { gmc_method: gmcMethod } : {}),
        },
      });
    },
    onSuccess: (job) => {
      refreshedJobId.current = "";
      setActiveJobKind("tracking");
      setActiveJobId(job.id);
      setMessage(`Tracking queued as job ${job.id}.`);
    },
  });
  const cancelActiveJob = useMutation({
    mutationFn: () => {
      if (!activeJobId) throw new Error("No active job can be cancelled.");
      return cancelJob(activeJobId);
    },
    onSuccess: (job) => {
      queryClient.setQueryData(["phase6_job", job.id], job);
      setMessage(
        `Cancellation ${job.status === "cancelled" ? "completed" : "requested"}.`,
      );
    },
  });
  const createManualTrack = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      const nextNumber =
        Math.max(0, ...(tracks.data?.map((item) => item.track_number) ?? [])) +
        1;
      return createVideoTrack(selectedVideoId, {
        video_id: selectedVideoId,
        operation_id: operationId("create-track"),
        track_number: nextNumber,
        name: trackName || `Manual track ${nextNumber}`,
        label_class_id: trackClassId || null,
        geometry_kind: "bounding_box",
        interpolation: "linear",
        status: "verified",
        is_ground_truth: groundTruth,
        keyframes: [observationPayload()],
      });
    },
    onSuccess: async (track) => {
      await refreshTracks();
      setSelectedTrackId(track.id);
      setMessage("Manual track created.");
    },
  });
  const saveTrackMetadata = useMutation({
    mutationFn: () => {
      if (!selectedTrack) throw new Error("Select a track.");
      return updateVideoTrack(selectedTrack.id, {
        operation_id: operationId("track-metadata"),
        expected_revision: selectedTrack.revision,
        name: trackName,
        label_class_id: trackClassId || null,
        status: groundTruth ? "verified" : selectedTrack.status,
        is_ground_truth: groundTruth,
      });
    },
    onSuccess: async () => {
      await refreshTracks();
      setMessage("Track label and review metadata saved.");
    },
  });
  const saveObservation = useMutation({
    mutationFn: () => {
      if (!selectedTrack) throw new Error("Select a track.");
      const common = {
        operation_id: operationId("observation"),
        expected_revision: selectedTrack.revision,
      };
      if (selectedObservation?.id) {
        return updateVideoTrackObservation(
          selectedTrack.id,
          selectedObservation.id,
          { ...common, ...observationPayload() },
        );
      }
      return addVideoTrackObservation(selectedTrack.id, {
        ...common,
        observation: observationPayload(),
      });
    },
    onSuccess: async (result) => {
      await refreshTracks();
      setSelectedTrackId(result.tracks[0]?.id ?? selectedTrackId);
      setSelectedObservationId("");
      setObservation(emptyObservation(currentFrame));
      setMessage("Observation saved with manual-edit provenance.");
    },
  });
  const toggleObservationDeleted = useMutation({
    mutationFn: () => {
      if (!selectedTrack || !selectedObservation?.id) {
        throw new Error("Select a persisted observation.");
      }
      const payload = {
        operation_id: operationId(
          selectedObservation.deleted_at
            ? "restore-observation"
            : "delete-observation",
        ),
        expected_revision: selectedTrack.revision,
      };
      return selectedObservation.deleted_at
        ? restoreVideoTrackObservation(
            selectedTrack.id,
            selectedObservation.id,
            payload,
          )
        : deleteVideoTrackObservation(
            selectedTrack.id,
            selectedObservation.id,
            payload,
          );
    },
    onSuccess: async () => {
      await refreshTracks();
      setMessage(
        selectedObservation?.deleted_at
          ? "Observation restored."
          : "Observation removed from the active trajectory.",
      );
    },
  });
  const archiveTrack = useMutation({
    mutationFn: () => {
      if (!selectedTrack) throw new Error("Select a track.");
      return archiveVideoTrack(selectedTrack.id, {
        operation_id: operationId("archive-track"),
        expected_revision: selectedTrack.revision,
      });
    },
    onSuccess: async () => {
      setSelectedTrackId("");
      await refreshTracks();
      setMessage("Track archived; its audit history remains available.");
    },
  });
  const splitTrack = useMutation({
    mutationFn: () => {
      if (!selectedTrack) throw new Error("Select a track.");
      return splitVideoTrack(selectedTrack.id, {
        operation_id: operationId("split-track"),
        expected_revision: selectedTrack.revision,
        split_frame: splitFrame,
        new_track_key: `${selectedTrack.name ?? `Track ${selectedTrack.track_number}`} continuation`,
      });
    },
    onSuccess: async () => {
      await refreshTracks();
      setMessage(`Track split at frame ${splitFrame}.`);
    },
  });
  const mergeTracks = useMutation({
    mutationFn: () => {
      const secondary = otherTracks.find(
        (item) => item.id === secondaryTrackId,
      );
      if (!selectedTrack || !secondary) throw new Error("Select two tracks.");
      return mergeVideoTracks({
        primary_track_id: selectedTrack.id,
        secondary_track_id: secondary.id,
        expected_primary_revision: selectedTrack.revision,
        expected_secondary_revision: secondary.revision,
        operation_id: operationId("merge-tracks"),
        conflict_policy: "highest_confidence",
      });
    },
    onSuccess: async () => {
      await refreshTracks();
      setMessage("Tracks merged without discarding correction history.");
    },
  });
  const identityCorrection = useMutation({
    mutationFn: () => {
      const secondary = otherTracks.find(
        (item) => item.id === secondaryTrackId,
      );
      if (!selectedTrack || !secondary) throw new Error("Select two tracks.");
      return correctVideoTrackIdentity({
        first_track_id: selectedTrack.id,
        second_track_id: secondary.id,
        after_frame: splitFrame,
        expected_first_revision: selectedTrack.revision,
        expected_second_revision: secondary.revision,
        operation_id: operationId("identity-switch"),
      });
    },
    onSuccess: async () => {
      await refreshTracks();
      setMessage(`Identity tails exchanged after frame ${splitFrame}.`);
    },
  });
  const reassignObservation = useMutation({
    mutationFn: () => {
      const secondary = otherTracks.find(
        (item) => item.id === secondaryTrackId,
      );
      if (!selectedTrack || !secondary || !selectedObservation?.id) {
        throw new Error("Select an observation and its destination track.");
      }
      return reassignVideoTrackObservations({
        source_track_id: selectedTrack.id,
        target_track_id: secondary.id,
        observation_ids: [selectedObservation.id],
        expected_source_revision: selectedTrack.revision,
        expected_target_revision: secondary.revision,
        operation_id: operationId("reassign-observation"),
      });
    },
    onSuccess: async () => {
      setSelectedObservationId("");
      await refreshTracks();
      setMessage("Observation reassigned to the selected track.");
    },
  });
  const saveZone = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      const payload = zonePayload();
      if (editingZoneId) {
        const existing = zones.data?.find((item) => item.id === editingZoneId);
        if (!existing)
          throw new Error("The selected zone is no longer available.");
        return updateVideoZone(editingZoneId, {
          ...payload,
          expected_revision: existing.revision,
        });
      }
      return createVideoZone(selectedVideoId, payload);
    },
    onSuccess: async () => {
      setEditingZoneId("");
      setZoneDraft(emptyZone());
      await refreshZones();
      setMessage("Analysis zone saved.");
    },
  });
  const removeZone = useMutation({
    mutationFn: (zone: VideoZone) => deleteVideoZone(zone.id, zone.revision),
    onSuccess: async () => {
      setEditingZoneId("");
      setZoneDraft(emptyZone());
      await refreshZones();
      setMessage("Analysis zone deleted.");
    },
  });
  const analytics = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      return analyzeVideo(selectedVideoId, {
        zones: [],
        include_saved_zones: true,
        heatmap_bins_x: heatmapBins,
        heatmap_bins_y: heatmapBins,
        activity_speed_threshold_pixels_per_second: activityThreshold,
        sampling: "interpolated",
        persist_result: true,
      });
    },
    onSuccess: () => setMessage("Behavior analysis completed and persisted."),
  });
  const evaluation = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      const thresholds = confidenceComparisons
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isFinite(value));
      return evaluateVideoTracking(selectedVideoId, {
        candidate_job_ids: [],
        confidence_thresholds: thresholds,
        minimum_iou: 0.5,
        include_archived_candidates: true,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["phase6_evaluations", selectedVideoId],
      });
      setMessage("Tracking comparison persisted.");
    },
  });
  const dataExport = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      return createVideoDataExport(selectedVideoId, {
        formats: ["csv", "json", "mot", "npz"],
        include_interpolated: true,
        include_analysis_runs: true,
        include_evaluation_runs: true,
      });
    },
    onSuccess: () => setMessage("Checksummed tracking data bundle created."),
  });
  const renderExport = useMutation({
    mutationFn: () => {
      if (!selectedVideoId) throw new Error("Choose a video.");
      return createVideoRenderExport(selectedVideoId, {
        export_kind: renderKind,
        track_ids: [],
        include_labels: true,
        include_confidence: true,
      });
    },
    onSuccess: ({ job }) => {
      refreshedJobId.current = "";
      setActiveJobKind("render");
      setActiveJobId(job.id);
      setMessage(`Rendered ${renderKind} export queued.`);
    },
  });

  function observationPayload(): Record<string, unknown> {
    return {
      frame_index: Number(observation.frame),
      x_min: Number(observation.xMin),
      y_min: Number(observation.yMin),
      x_max: Number(observation.xMax),
      y_max: Number(observation.yMax),
      confidence: observation.confidence
        ? Number(observation.confidence)
        : null,
    };
  }

  function zonePayload(): Record<string, unknown> {
    return {
      name: zoneDraft.name,
      x_min: Number(zoneDraft.xMin),
      y_min: Number(zoneDraft.yMin),
      x_max: Number(zoneDraft.xMax),
      y_max: Number(zoneDraft.yMax),
    };
  }

  function changeVideo(videoId: string) {
    setSelectedVideoId(videoId);
    setSelectedTrackId("");
    setSelectedObservationId("");
    setSecondaryTrackId("");
    setCurrentFrame(0);
    setActiveJobId("");
    setEditingZoneId("");
    setZoneDraft(emptyZone());
    setObservation(emptyObservation());
    setMessage(null);
    analytics.reset();
    evaluation.reset();
    dataExport.reset();
    renderExport.reset();
  }

  function seekToFrame(frame: number) {
    if (!selectedVideo) return;
    const bounded = Math.min(
      Math.max(0, Math.round(frame)),
      selectedVideo.frame_count - 1,
    );
    setCurrentFrame(bounded);
    if (playerRef.current) {
      playerRef.current.currentTime = bounded / selectedVideo.fps;
    }
  }

  function selectTrack(track: VideoTrack) {
    setSelectedTrackId(track.id);
    setSelectedObservationId("");
    setObservation(emptyObservation(currentFrame));
  }

  function selectZone(zone: VideoZone) {
    setEditingZoneId(zone.id);
    setZoneDraft({
      name: zone.name,
      xMin: String(zone.x_min),
      yMin: String(zone.y_min),
      xMax: String(zone.x_max),
      yMax: String(zone.y_max),
    });
  }

  const analysisResult =
    analytics.data?.video_id === selectedVideoId ? analytics.data : null;
  const evaluationResult: VideoTrackingEvaluation | null =
    evaluation.data?.video_id === selectedVideoId
      ? evaluation.data
      : (evaluations.data?.[0] ?? null);
  const exportResult =
    dataExport.data?.video_id === selectedVideoId ? dataExport.data : null;
  const jobRunning =
    Boolean(activeJob.data) &&
    !terminalJobStatuses.has(activeJob.data?.status ?? "");
  const mutationError =
    upload.error ??
    calibrate.error ??
    automaticTracking.error ??
    cancelActiveJob.error ??
    createManualTrack.error ??
    saveTrackMetadata.error ??
    saveObservation.error ??
    toggleObservationDeleted.error ??
    archiveTrack.error ??
    splitTrack.error ??
    mergeTracks.error ??
    identityCorrection.error ??
    reassignObservation.error ??
    saveZone.error ??
    removeZone.error ??
    analytics.error ??
    evaluation.error ??
    dataExport.error ??
    renderExport.error;
  const queryError =
    videos.error ??
    models.error ??
    tracks.error ??
    zones.error ??
    evaluations.error ??
    activeJob.error;
  const displayedError = errorMessage(mutationError ?? queryError);

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 6</p>
          <h3>Video and fish tracking</h3>
          <span>
            Managed source video → detector and tracker → correction →
            calibrated behavior → evaluation → export
          </span>
        </div>
        <span>{videos.data?.length ?? 0} managed videos</span>
      </div>
      {videos.isLoading && <p role="status">Loading managed videos…</p>}
      {!videos.isLoading && videos.data?.length === 0 && (
        <p className="form-warning">Import a managed video to begin Phase 6.</p>
      )}
      {message && <p className="form-success">{message}</p>}
      {displayedError && <p className="form-error">{displayedError}</p>}

      <div className="dashboard-layout video-dashboard-layout">
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
              {upload.isPending ? "Importing…" : "Import managed video"}
            </button>
            <label>
              Managed video
              <select
                aria-label="Managed video"
                value={selectedVideoId}
                disabled={videos.isLoading}
                onChange={(event) => changeVideo(event.target.value)}
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
            <p className="eyebrow">Automated tracking</p>
            <h4>Detector and tracker</h4>
            {models.isLoading && (
              <p role="status">Loading compatible detectors…</p>
            )}
            {!models.isLoading && detectors.length === 0 && (
              <p className="form-warning">
                Register a local Ultralytics detection model before tracking.
              </p>
            )}
            <label>
              Compatible detector
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
            <div className="dashboard-grid compact-grid">
              <label>
                Tracker
                <select
                  aria-label="Tracker"
                  value={tracker}
                  onChange={(event) =>
                    setTracker(event.target.value as TrackerKind)
                  }
                >
                  <option value="bytetrack">ByteTrack</option>
                  <option value="botsort">BoT-SORT</option>
                </select>
              </label>
              <label>
                Device
                <select
                  aria-label="Tracking device"
                  value={device}
                  onChange={(event) =>
                    setDevice(event.target.value as DeviceKind)
                  }
                >
                  <option value="auto">Automatic</option>
                  <option value="cpu">CPU</option>
                  <option value="cuda">CUDA</option>
                </select>
              </label>
              <label>
                Detector confidence
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
                Detector IoU
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
              <label>
                Track buffer
                <input
                  type="number"
                  min="1"
                  value={trackBuffer}
                  onChange={(event) =>
                    setTrackBuffer(Number(event.target.value))
                  }
                />
              </label>
              <label>
                High threshold
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={trackHighThreshold}
                  onChange={(event) =>
                    setTrackHighThreshold(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Low threshold
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={trackLowThreshold}
                  onChange={(event) =>
                    setTrackLowThreshold(Number(event.target.value))
                  }
                />
              </label>
              {tracker === "botsort" && (
                <label>
                  Camera-motion compensation
                  <select
                    value={gmcMethod}
                    onChange={(event) => setGmcMethod(event.target.value)}
                  >
                    <option value="sparseOptFlow">Sparse optical flow</option>
                    <option value="orb">ORB</option>
                    <option value="none">Disabled</option>
                  </select>
                </label>
              )}
            </div>
            <button
              type="button"
              disabled={
                !selectedVideoId ||
                !detectorId ||
                automaticTracking.isPending ||
                jobRunning
              }
              onClick={() => automaticTracking.mutate()}
            >
              {automaticTracking.isPending ? "Queuing…" : "Run fish tracking"}
            </button>
            {activeJobId && (
              <div className="job-status" role="status">
                <strong>
                  {activeJobKind === "tracking"
                    ? "Tracking"
                    : "Rendered export"}{" "}
                  job
                </strong>
                <span>{activeJob.data?.status ?? "loading"}</span>
                <progress
                  aria-label="Job progress"
                  value={activeJob.data?.progress_current ?? 0}
                  max={Math.max(activeJob.data?.progress_total ?? 1, 1)}
                />
                {activeJob.data?.error_message && (
                  <p className="form-error">{activeJob.data.error_message}</p>
                )}
                {jobRunning && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={cancelActiveJob.isPending}
                    onClick={() => cancelActiveJob.mutate()}
                  >
                    {cancelActiveJob.isPending ? "Cancelling…" : "Cancel job"}
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="dashboard-card">
            <p className="eyebrow">Physical calibration</p>
            <h4>Pixels to physical distance</h4>
            <p>
              Physical units remain unavailable until both timing metadata and
              this calibration are valid.
            </p>
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
                Physical unit
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
              {calibrate.isPending ? "Saving…" : "Save calibration"}
            </button>
          </div>
        </div>

        <div className="dashboard-main">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Playback and source-frame overlay</p>
                <h4>{selectedVideo?.original_filename ?? "Choose a video"}</h4>
              </div>
              {selectedVideo && (
                <span>
                  {selectedVideo.width_px}×{selectedVideo.height_px} ·{" "}
                  {selectedVideo.fps.toFixed(3)} fps ·{" "}
                  {selectedVideo.duration_seconds.toFixed(2)} s
                </span>
              )}
            </div>
            {selectedVideo ? (
              <>
                <div
                  className="video-stage"
                  style={{
                    aspectRatio: `${selectedVideo.width_px} / ${selectedVideo.height_px}`,
                  }}
                >
                  <video
                    key={selectedVideo.id}
                    ref={playerRef}
                    controls
                    preload="metadata"
                    className="research-video-player"
                    src={downloadUrl(`/videos/${selectedVideo.id}/content`)}
                    onTimeUpdate={(event) =>
                      setCurrentFrame(
                        Math.min(
                          selectedVideo.frame_count - 1,
                          Math.max(
                            0,
                            Math.floor(
                              event.currentTarget.currentTime *
                                selectedVideo.fps,
                            ),
                          ),
                        ),
                      )
                    }
                  />
                  <svg
                    className="video-track-overlay"
                    viewBox={`0 0 ${selectedVideo.width_px} ${selectedVideo.height_px}`}
                    preserveAspectRatio="none"
                    aria-label={`Track overlay for frame ${currentFrame}`}
                  >
                    {zones.data?.map((zone) => (
                      <rect
                        key={zone.id}
                        className="video-zone-box"
                        x={zone.x_min}
                        y={zone.y_min}
                        width={zone.x_max - zone.x_min}
                        height={zone.y_max - zone.y_min}
                      />
                    ))}
                    {showTrajectories &&
                      analysisResult?.tracks.map((track) => {
                        const sourceTrack = tracks.data?.find(
                          (item) => item.id === track.track_id,
                        );
                        return (
                          <polyline
                            key={track.track_id}
                            className="video-trajectory-line"
                            stroke={
                              sourceTrack
                                ? trackColor(project, sourceTrack)
                                : "#f5c542"
                            }
                            points={track.trajectory
                              .map(
                                (point) =>
                                  `${point.center_x_pixels},${point.center_y_pixels}`,
                              )
                              .join(" ")}
                          />
                        );
                      })}
                    {tracks.data?.map((track) => {
                      const item = observationAtFrame(track, currentFrame);
                      if (!item) return null;
                      const color = trackColor(project, track);
                      return (
                        <g
                          key={track.id}
                          className={`video-track-box ${
                            item.manual_edit ? "manual" : "automatic"
                          } ${selectedTrackId === track.id ? "selected" : ""}`}
                          role="button"
                          tabIndex={0}
                          aria-label={`Select track ${track.track_number} on frame ${currentFrame}`}
                          onClick={() => selectTrack(track)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              selectTrack(track);
                            }
                          }}
                        >
                          <rect
                            x={item.x_min}
                            y={item.y_min}
                            width={item.x_max - item.x_min}
                            height={item.y_max - item.y_min}
                            stroke={color}
                          />
                          <text
                            x={item.x_min}
                            y={Math.max(12, item.y_min - 4)}
                            fill={color}
                          >
                            {track.name ?? `Track ${track.track_number}`}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
                <label>
                  Source frame {currentFrame} of {selectedVideo.frame_count - 1}
                  <input
                    aria-label="Source frame"
                    type="range"
                    min="0"
                    max={Math.max(0, selectedVideo.frame_count - 1)}
                    value={currentFrame}
                    onChange={(event) =>
                      seekToFrame(Number(event.target.value))
                    }
                  />
                </label>
                <div className="version-actions">
                  <a
                    className="button-link secondary"
                    href={downloadUrl(
                      `/videos/${selectedVideo.id}/frames/${currentFrame}`,
                    )}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open exact frame JPEG
                  </a>
                  <label className="toggle-row">
                    <input
                      type="checkbox"
                      checked={showTrajectories}
                      onChange={(event) =>
                        setShowTrajectories(event.target.checked)
                      }
                    />
                    Show analyzed trajectories
                  </label>
                </div>
              </>
            ) : (
              <p>Select a managed video to load playback and frame overlays.</p>
            )}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Revision-safe track correction</p>
                <h4>{tracks.data?.length ?? 0} active tracks</h4>
              </div>
              {tracks.isLoading && <span role="status">Loading tracks…</span>}
            </div>
            {!tracks.isLoading &&
              selectedVideoId &&
              tracks.data?.length === 0 && (
                <p className="form-warning">
                  No tracks yet. Run a tracker or create a manual track from the
                  box fields below.
                </p>
              )}
            <div className="dashboard-list compact-list">
              {tracks.data?.map((track) => (
                <button
                  key={track.id}
                  type="button"
                  className={`track-select-row ${
                    selectedTrackId === track.id ? "selected" : ""
                  }`}
                  onClick={() => selectTrack(track)}
                >
                  <span
                    className="track-color"
                    style={{ background: trackColor(project, track) }}
                  />
                  <span>
                    <strong>
                      {track.name ?? `Track ${track.track_number}`}
                    </strong>
                    <small>
                      {track.source_type === "generated"
                        ? "automatic"
                        : "manual"}{" "}
                      · {activeObservations(track).length} observations ·
                      revision {track.revision}
                    </small>
                  </span>
                </button>
              ))}
            </div>

            <div className="dashboard-grid compact-grid">
              <label>
                Track name
                <input
                  value={trackName}
                  onChange={(event) => setTrackName(event.target.value)}
                  placeholder="Fish identity"
                />
              </label>
              <label>
                Class
                <select
                  value={trackClassId}
                  onChange={(event) => setTrackClassId(event.target.value)}
                >
                  <option value="">Unassigned</option>
                  {project.label_classes
                    .filter((item) => item.is_active)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={groundTruth}
                  onChange={(event) => setGroundTruth(event.target.checked)}
                />
                Verified ground truth
              </label>
            </div>
            <div className="version-actions">
              <button
                type="button"
                disabled={!selectedTrack || saveTrackMetadata.isPending}
                onClick={() => saveTrackMetadata.mutate()}
              >
                {saveTrackMetadata.isPending ? "Saving…" : "Save track details"}
              </button>
              <button
                type="button"
                className="danger-ghost"
                disabled={!selectedTrack || archiveTrack.isPending}
                onClick={() => archiveTrack.mutate()}
              >
                Archive track
              </button>
            </div>

            <h4>Observation editor</h4>
            {selectedTrack && (
              <div className="observation-list" aria-label="Track observations">
                {selectedTrack.keyframes.map((item) => (
                  <button
                    key={item.id ?? `${selectedTrack.id}-${item.frame_index}`}
                    type="button"
                    className={`${
                      selectedObservationId === item.id ? "selected" : ""
                    } ${item.deleted_at ? "deleted" : ""}`}
                    onClick={() => {
                      setSelectedObservationId(item.id ?? "");
                      seekToFrame(item.frame_index);
                    }}
                  >
                    Frame {item.frame_index} ·{" "}
                    {item.manual_edit ? "manual edit" : item.source}
                    {item.deleted_at ? " · deleted" : ""}
                  </button>
                ))}
              </div>
            )}
            <div className="dashboard-grid compact-grid observation-fields">
              <label>
                Frame number
                <input
                  type="number"
                  min="0"
                  max={
                    selectedVideo ? selectedVideo.frame_count - 1 : undefined
                  }
                  value={observation.frame}
                  onChange={(event) =>
                    setObservation((current) => ({
                      ...current,
                      frame: event.target.value,
                    }))
                  }
                />
              </label>
              {(
                [
                  ["xMin", "X min"],
                  ["yMin", "Y min"],
                  ["xMax", "X max"],
                  ["yMax", "Y max"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={observation[key]}
                    onChange={(event) =>
                      setObservation((current) => ({
                        ...current,
                        [key]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
              <label>
                Confidence (optional)
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="any"
                  value={observation.confidence}
                  onChange={(event) =>
                    setObservation((current) => ({
                      ...current,
                      confidence: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <div className="version-actions">
              <button
                type="button"
                className="secondary"
                disabled={!selectedVideo}
                onClick={() => {
                  setSelectedObservationId("");
                  setObservation(emptyObservation(currentFrame));
                }}
              >
                New observation at current frame
              </button>
              <button
                type="button"
                disabled={!selectedTrack || saveObservation.isPending}
                onClick={() => saveObservation.mutate()}
              >
                {saveObservation.isPending
                  ? "Saving…"
                  : selectedObservation
                    ? "Save observation edit"
                    : "Add observation"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedObservation?.id || toggleObservationDeleted.isPending
                }
                onClick={() => toggleObservationDeleted.mutate()}
              >
                {selectedObservation?.deleted_at
                  ? "Restore observation"
                  : "Delete observation"}
              </button>
              <button
                type="button"
                disabled={
                  Boolean(selectedTrack) ||
                  !selectedVideo ||
                  createManualTrack.isPending
                }
                onClick={() => createManualTrack.mutate()}
              >
                Create manual track
              </button>
            </div>

            <h4>Identity and continuity corrections</h4>
            <div className="dashboard-grid compact-grid">
              <label>
                Split / switch frame
                <input
                  type="number"
                  min="0"
                  value={splitFrame}
                  onChange={(event) =>
                    setSplitFrame(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Other track
                <select
                  aria-label="Other track"
                  value={secondaryTrackId}
                  onChange={(event) => setSecondaryTrackId(event.target.value)}
                >
                  <option value="">Choose track</option>
                  {otherTracks.map((track) => (
                    <option key={track.id} value={track.id}>
                      {track.name ?? `Track ${track.track_number}`}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="version-actions">
              <button
                type="button"
                className="secondary"
                disabled={!selectedTrack || splitTrack.isPending}
                onClick={() => splitTrack.mutate()}
              >
                Split selected track
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedTrack || !secondaryTrackId || mergeTracks.isPending
                }
                onClick={() => mergeTracks.mutate()}
              >
                Merge into selected track
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedTrack ||
                  !secondaryTrackId ||
                  identityCorrection.isPending
                }
                onClick={() => identityCorrection.mutate()}
              >
                Correct identity switch
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedObservation?.id ||
                  !secondaryTrackId ||
                  reassignObservation.isPending
                }
                onClick={() => reassignObservation.mutate()}
              >
                Reassign selected observation
              </button>
            </div>
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Zones and behavior</p>
                <h4>Calibrated trajectories and occupancy</h4>
              </div>
              <span>{zones.data?.length ?? 0} saved zones</span>
            </div>
            <div className="dashboard-grid compact-grid">
              <label>
                Zone name
                <input
                  value={zoneDraft.name}
                  onChange={(event) =>
                    setZoneDraft((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                />
              </label>
              {(
                [
                  ["xMin", "X min"],
                  ["yMin", "Y min"],
                  ["xMax", "X max"],
                  ["yMax", "Y max"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={zoneDraft[key]}
                    onChange={(event) =>
                      setZoneDraft((current) => ({
                        ...current,
                        [key]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
            <div className="version-actions">
              <button
                type="button"
                disabled={
                  !selectedVideo || !zoneDraft.name || saveZone.isPending
                }
                onClick={() => saveZone.mutate()}
              >
                {saveZone.isPending
                  ? "Saving…"
                  : editingZoneId
                    ? "Update zone"
                    : "Create zone"}
              </button>
              {editingZoneId && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setEditingZoneId("");
                    setZoneDraft(emptyZone());
                  }}
                >
                  Cancel zone edit
                </button>
              )}
            </div>
            <div className="dashboard-list compact-list">
              {zones.data?.map((zone) => (
                <article key={zone.id} className="dashboard-row">
                  <div>
                    <strong>{zone.name}</strong>
                    <small>
                      ({zone.x_min}, {zone.y_min}) → ({zone.x_max}, {zone.y_max}
                      )
                    </small>
                  </div>
                  <div className="dashboard-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => selectZone(zone)}
                    >
                      Edit zone
                    </button>
                    <button
                      type="button"
                      className="danger-ghost"
                      disabled={removeZone.isPending}
                      onClick={() => removeZone.mutate(zone)}
                    >
                      Delete zone
                    </button>
                  </div>
                </article>
              ))}
            </div>
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
              disabled={
                !selectedVideo || !tracks.data?.length || analytics.isPending
              }
              onClick={() => analytics.mutate()}
            >
              {analytics.isPending
                ? "Analyzing…"
                : "Calculate behavior metrics"}
            </button>
            {analysisResult?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            {analysisResult && (
              <>
                <div className="version-preview-metrics">
                  <span>Coordinates: pixels</span>
                  <span>
                    Timing: {analysisResult.timing_source.replaceAll("_", " ")}
                  </span>
                  <span>
                    Physical: {analysisResult.physical_unit ?? "not calibrated"}
                  </span>
                  <span>
                    {analysisResult.heatmap.length} occupied heatmap cells
                  </span>
                  <span>{analysisResult.zone_events.length} zone events</span>
                </div>
                <div className="dashboard-list">
                  {analysisResult.tracks.map((track) => (
                    <article
                      key={track.track_id}
                      className="dashboard-row behavior-row"
                    >
                      <div>
                        <strong>Track {track.tracker_id}</strong>
                        <p>
                          Path {track.total_path_length_pixels.toFixed(2)} px ·
                          displacement{" "}
                          {track.net_displacement_pixels.toFixed(2)} px · speed{" "}
                          {track.mean_speed_pixels_per_second.toFixed(2)} px/s
                        </p>
                        <small>
                          Acceleration{" "}
                          {track.mean_acceleration_pixels_per_second_squared.toFixed(
                            2,
                          )}{" "}
                          px/s² · turning{" "}
                          {track.mean_turning_angle_degrees?.toFixed(2) ??
                            "n/a"}
                          ° · tortuosity{" "}
                          {track.path_tortuosity?.toFixed(3) ?? "n/a"} · wall{" "}
                          {track.mean_distance_to_wall_pixels.toFixed(2)} px
                        </small>
                      </div>
                      <span>
                        {track.distance_physical !== null && track.physical_unit
                          ? `${track.distance_physical.toFixed(3)} ${track.physical_unit}`
                          : "Pixel-based"}
                      </span>
                    </article>
                  ))}
                </div>
                <div className="heatmap-summary" aria-label="Heatmap occupancy">
                  {analysisResult.heatmap.slice(0, 100).map((cell) => (
                    <span
                      key={`${cell.column}-${cell.row}`}
                      title={`Cell ${cell.column},${cell.row}: ${cell.occupancy_seconds.toFixed(3)} s`}
                      style={{
                        opacity: Math.min(1, 0.2 + cell.observation_count / 10),
                      }}
                    />
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Tracking evaluation</p>
                <h4>Tracker and confidence comparison</h4>
              </div>
              <span>{evaluations.data?.length ?? 0} saved evaluations</span>
            </div>
            <p>
              Metrics require tracks explicitly marked as verified ground truth.
              Synthetic fixtures establish software acceptance only, not
              fish-tracking validity.
            </p>
            <label>
              Confidence thresholds (comma separated)
              <input
                value={confidenceComparisons}
                onChange={(event) =>
                  setConfidenceComparisons(event.target.value)
                }
              />
            </label>
            <button
              type="button"
              disabled={!selectedVideo || evaluation.isPending}
              onClick={() => evaluation.mutate()}
            >
              {evaluation.isPending ? "Comparing…" : "Compare tracker results"}
            </button>
            {evaluationResult?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            {evaluationResult && !evaluationResult.ground_truth_available && (
              <p className="empty-state">
                No verified ground truth is available; scientific tracking
                scores are not reported.
              </p>
            )}
            {evaluationResult?.ranked_by_hota.length ? (
              <div className="phase-table-scroll">
                <table className="phase-metric-table">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>IoU</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>ID switches</th>
                      <th>Fragments</th>
                      <th>Continuity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluationResult.ranked_by_hota.map((item) => (
                      <tr key={item.candidate_name}>
                        <td>{item.candidate_name}</td>
                        <td>{percent(item.localization_iou)}</td>
                        <td>{percent(item.detection_precision)}</td>
                        <td>{percent(item.detection_recall)}</td>
                        <td>{item.identity_switch_count}</td>
                        <td>{item.fragmentation_count}</td>
                        <td>
                          {item.mean_track_continuity === null
                            ? "n/a"
                            : percent(item.mean_track_continuity)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Restart-safe exports</p>
                <h4>Data, provenance, and rendered video</h4>
              </div>
            </div>
            <div className="version-actions">
              <button
                type="button"
                disabled={
                  !selectedVideo || !tracks.data?.length || dataExport.isPending
                }
                onClick={() => dataExport.mutate()}
              >
                {dataExport.isPending
                  ? "Building bundle…"
                  : "Create CSV / JSON / MOT / NumPy bundle"}
              </button>
              {exportResult && (
                <a
                  className="button-link secondary"
                  href={downloadUrl(
                    `/artifacts/${exportResult.artifact_id}/content`,
                  )}
                >
                  Open checksummed bundle
                </a>
              )}
            </div>
            {exportResult && (
              <p>
                SHA-256 {exportResult.archive_sha256} ·{" "}
                {exportResult.archive_size_bytes} bytes
              </p>
            )}
            <div className="dashboard-grid compact-grid">
              <label>
                Rendered view
                <select
                  value={renderKind}
                  onChange={(event) =>
                    setRenderKind(event.target.value as RenderKind)
                  }
                >
                  <option value="annotated">Annotated boxes</option>
                  <option value="trajectory">Trajectories</option>
                  <option value="heatmap">Heatmap</option>
                </select>
              </label>
              <button
                type="button"
                disabled={
                  !selectedVideo ||
                  !tracks.data?.length ||
                  renderExport.isPending
                }
                onClick={() => renderExport.mutate()}
              >
                {renderExport.isPending ? "Queuing…" : "Queue rendered video"}
              </button>
            </div>
            {selectedVideo && (
              <div className="version-actions">
                <a
                  className="button-link secondary"
                  href={downloadUrl(
                    `/videos/${selectedVideo.id}/tracking-export?format=csv`,
                  )}
                >
                  Quick CSV
                </a>
                <a
                  className="button-link secondary"
                  href={downloadUrl(
                    `/videos/${selectedVideo.id}/tracking-export?format=mot`,
                  )}
                >
                  Quick MOT
                </a>
                <a
                  className="button-link secondary"
                  href={downloadUrl(
                    `/videos/${selectedVideo.id}/tracking-export?format=json`,
                  )}
                >
                  Quick ReefVision JSON
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
