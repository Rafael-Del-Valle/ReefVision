import type {
  PoseInstance,
  PoseLandmarkObservation,
  PoseLandmarkSchema,
  PoseSaveRequest,
} from "../pose/types";
import type {
  PoseLandmarkSchema as VideoPoseLandmarkSchema,
  VideoTrackKeyframe,
  VideoTrackRecord,
} from "./videoApi";

function occurrenceIndexes(labels: string[]): number[] {
  const counts = new Map<string, number>();
  return labels.map((label) => {
    const index = counts.get(label) ?? 0;
    counts.set(label, index + 1);
    return index;
  });
}

export function editorSchemaForVideoTrack(
  track: VideoTrackRecord,
  schema: VideoPoseLandmarkSchema,
): PoseLandmarkSchema {
  return {
    id: `video-track:${track.id}:${schema.schema_version}`,
    revision: 1,
    groups: schema.groups.map((group) => ({
      name: group.name,
      count: group.count,
    })),
  };
}

export function poseInstanceFromVideoKeyframe(
  track: VideoTrackRecord,
  keyframe: VideoTrackKeyframe,
  schema: VideoPoseLandmarkSchema,
): PoseInstance {
  const editorSchema = editorSchemaForVideoTrack(track, schema);
  const persisted = keyframe.pose_observations;
  if (persisted && persisted.length > 0) {
    return {
      id: `${track.id}:frame:${keyframe.frame}`,
      revision: track.revision,
      schema_id: editorSchema.id,
      schema_revision: editorSchema.revision,
      observations: persisted.map((observation) => ({ ...observation })),
    };
  }

  const indexes = occurrenceIndexes(schema.expanded_labels);
  const observations: PoseLandmarkObservation[] = [];
  for (const [index, point] of (keyframe.keypoints ?? []).entries()) {
    const semanticLabel =
      schema.expanded_labels[index] ?? `landmark_${index + 1}`;
    const confidence = point[2];
    if (confidence <= 0) {
      continue;
    }
    observations.push({
      id: `${track.id}:${keyframe.frame}:${index}`,
      semantic_label: semanticLabel,
      occurrence_index: indexes[index] ?? 0,
      x: point[0],
      y: point[1],
      confidence,
      status: "visible",
      source: track.source_model_id || track.source_job_id ? "model" : "manual",
    });
  }

  return {
    id: `${track.id}:frame:${keyframe.frame}`,
    revision: track.revision,
    schema_id: editorSchema.id,
    schema_revision: editorSchema.revision,
    observations,
  };
}

function observationForSlot(
  observations: PoseLandmarkObservation[],
  semanticLabel: string,
  occurrenceIndex: number,
): PoseLandmarkObservation | undefined {
  return observations.find(
    (observation) =>
      observation.semantic_label === semanticLabel &&
      observation.occurrence_index === occurrenceIndex,
  );
}

export function correctedVideoKeyframeFromPoseSave(
  keyframe: VideoTrackKeyframe,
  schema: VideoPoseLandmarkSchema,
  request: PoseSaveRequest,
): VideoTrackKeyframe {
  const indexes = occurrenceIndexes(schema.expanded_labels);
  const keypoints = schema.expanded_labels.map((semanticLabel, index) => {
    const observation = observationForSlot(
      request.observations,
      semanticLabel,
      indexes[index] ?? 0,
    );
    if (!observation || observation.status === "absent") {
      return [0, 0, 0] as [number, number, number];
    }
    return [
      observation.x,
      observation.y,
      observation.confidence ?? 1,
    ] as [number, number, number];
  });

  return {
    ...keyframe,
    keypoints,
    pose_observations: request.observations.map((observation) => ({
      ...observation,
      source:
        observation.source === "model"
          ? "model"
          : observation.source === "manual"
            ? "manual"
            : "corrected",
    })),
  };
}
