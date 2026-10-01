import type { ImageSize, Point } from "../annotation-editor/types";
import type {
  PoseInstance,
  PoseLandmarkObservation,
  PoseLandmarkSchema,
  PoseSaveRequest,
} from "./types";

export interface PoseSkeletonSegment {
  key: string;
  from: PoseLandmarkObservation;
  to: PoseLandmarkObservation;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clonePose(pose: PoseInstance): PoseInstance {
  return {
    ...pose,
    observations: pose.observations.map((observation) => ({ ...observation })),
  };
}

export function placedCount(
  observations: PoseLandmarkObservation[],
  semanticLabel: string,
): number {
  return observations.filter(
    (observation) => observation.semantic_label === semanticLabel,
  ).length;
}

export function nextAvailableOccurrenceIndex(
  schema: PoseLandmarkSchema,
  observations: PoseLandmarkObservation[],
  semanticLabel: string,
): number | null {
  const group = schema.groups.find((item) => item.name === semanticLabel);
  if (!group || group.count <= 0) {
    return null;
  }

  const used = new Set(
    observations
      .filter((observation) => observation.semantic_label === semanticLabel)
      .map((observation) => observation.occurrence_index),
  );

  for (let index = 0; index < group.count; index += 1) {
    if (!used.has(index)) {
      return index;
    }
  }
  return null;
}

export function addPoseObservation(
  pose: PoseInstance,
  schema: PoseLandmarkSchema,
  semanticLabel: string,
  point: Point,
  imageSize: ImageSize,
  id: string,
): PoseInstance {
  const occurrenceIndex = nextAvailableOccurrenceIndex(
    schema,
    pose.observations,
    semanticLabel,
  );
  if (occurrenceIndex === null) {
    return pose;
  }

  return {
    ...pose,
    observations: [
      ...pose.observations,
      {
        id,
        semantic_label: semanticLabel,
        occurrence_index: occurrenceIndex,
        x: clamp(point.x, 0, imageSize.width),
        y: clamp(point.y, 0, imageSize.height),
        confidence: null,
        source: "manual",
      },
    ],
  };
}

export function movePoseObservation(
  pose: PoseInstance,
  observationId: string,
  point: Point,
  imageSize: ImageSize,
): PoseInstance {
  return {
    ...pose,
    observations: pose.observations.map((observation) =>
      observation.id === observationId
        ? {
            ...observation,
            x: clamp(point.x, 0, imageSize.width),
            y: clamp(point.y, 0, imageSize.height),
            source:
              observation.source === "model" ? "corrected" : observation.source,
          }
        : observation,
    ),
  };
}

export function removePoseObservation(
  pose: PoseInstance,
  observationId: string,
): PoseInstance {
  return {
    ...pose,
    observations: pose.observations.filter(
      (observation) => observation.id !== observationId,
    ),
  };
}

export function poseSkeletonSegments(
  pose: PoseInstance,
  schema: PoseLandmarkSchema,
): PoseSkeletonSegment[] {
  const segments: PoseSkeletonSegment[] = [];

  (schema.edges ?? []).forEach((edge, edgeIndex) => {
    const fromObservations = pose.observations.filter(
      (observation) => observation.semantic_label === edge.from,
    );
    const toObservations = pose.observations.filter(
      (observation) => observation.semantic_label === edge.to,
    );

    fromObservations.forEach((from) => {
      toObservations.forEach((to) => {
        if (from.id === to.id) {
          return;
        }
        segments.push({
          key: `${edgeIndex}:${from.id}:${to.id}`,
          from,
          to,
        });
      });
    });
  });

  return segments;
}

export function validatePoseAgainstSchema(
  pose: PoseInstance,
  schema: PoseLandmarkSchema,
): string[] {
  const errors: string[] = [];
  const knownGroups = new Map(
    schema.groups.map((group) => [group.name, group.count]),
  );
  const seenSlots = new Set<string>();

  pose.observations.forEach((observation) => {
    const count = knownGroups.get(observation.semantic_label);
    if (count === undefined) {
      errors.push(`Unknown landmark group: ${observation.semantic_label}`);
      return;
    }
    if (
      observation.occurrence_index < 0 ||
      observation.occurrence_index >= count
    ) {
      errors.push(
        `Occurrence index out of range for ${observation.semantic_label}: ${observation.occurrence_index}`,
      );
      return;
    }
    const slot = `${observation.semantic_label}:${observation.occurrence_index}`;
    if (seenSlots.has(slot)) {
      errors.push(`Duplicate landmark slot: ${slot}`);
      return;
    }
    seenSlots.add(slot);
  });

  schema.groups.forEach((group) => {
    if (!group.required) {
      return;
    }
    const count = placedCount(pose.observations, group.name);
    if (count < group.count) {
      errors.push(
        `Missing required landmarks for ${group.name}: ${count}/${group.count}`,
      );
    }
  });

  return errors;
}

export function buildPoseSaveRequest(
  persistedPose: PoseInstance,
  draftPose: PoseInstance,
  schema: PoseLandmarkSchema,
): PoseSaveRequest {
  return {
    pose_id: draftPose.id,
    base_revision: persistedPose.revision,
    schema_id: schema.id,
    schema_revision: schema.revision,
    observations: draftPose.observations.map((observation) => ({
      ...observation,
    })),
  };
}
