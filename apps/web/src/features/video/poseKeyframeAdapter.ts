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
import type { AnatomySchemaRevision } from "../pose/anatomyApi";

function occurrenceIndexes(labels: string[]): number[] {
  const counts = new Map<string, number>();
  return labels.map((label) => {
    const index = counts.get(label) ?? 0;
    counts.set(label, index + 1);
    return index;
  });
}

export function videoSchemaFromAnatomy(
  schema: AnatomySchemaRevision,
): VideoPoseLandmarkSchema {
  return {
    schema_version: "pose-landmarks-0001",
    schema_id: schema.id,
    schema_revision: schema.revision,
    content_hash: schema.content_hash,
    groups: schema.groups,
    expanded_labels: schema.expanded_labels,
    keypoint_count: schema.keypoint_count,
    allows_repeated_labels: schema.allows_repeated_labels,
    landmarks: schema.landmarks,
    edges: schema.edges,
  };
}

export function editorSchemaForVideoTrack(
  track: VideoTrackRecord,
  schema: VideoPoseLandmarkSchema,
): PoseLandmarkSchema {
  return {
    id: schema.schema_id ?? `video-track:${track.id}:${schema.schema_version}`,
    revision: schema.schema_revision ?? 1,
    groups: schema.groups.map((group) => ({
      name: group.name,
      count: group.count,
    })),
    landmarks: schema.landmarks?.map((landmark) => ({ ...landmark })),
    edges: schema.edges?.map((edge) => ({
      from: edge.from_id,
      to: edge.to_id,
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
    const indexes = occurrenceIndexes(schema.expanded_labels);
    return {
      id: `${track.id}:frame:${keyframe.frame}`,
      revision: track.revision,
      schema_id: editorSchema.id,
      schema_revision: editorSchema.revision,
      observations: persisted.map((observation) => {
        if (observation.landmark_id || !schema.landmarks) {
          return { ...observation };
        }
        const schemaIndex = schema.expanded_labels.findIndex(
          (label, index) =>
            label === observation.semantic_label &&
            indexes[index] === observation.occurrence_index,
        );
        return {
          ...observation,
          landmark_id:
            schemaIndex >= 0 ? schema.landmarks[schemaIndex]?.id : undefined,
        };
      }),
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
      landmark_id: schema.landmarks?.[index]?.id,
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
  landmarkId?: string,
): PoseLandmarkObservation | undefined {
  return observations.find((observation) =>
    landmarkId && observation.landmark_id
      ? observation.landmark_id === landmarkId
      : observation.semantic_label === semanticLabel &&
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
      schema.landmarks?.[index]?.id,
    );
    if (
      !observation ||
      observation.status === "absent" ||
      observation.status === "out_of_frame"
    ) {
      return [0, 0, 0] as [number, number, number];
    }
    return [observation.x, observation.y, observation.confidence ?? 1] as [
      number,
      number,
      number,
    ];
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
