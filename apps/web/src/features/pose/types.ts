export interface PoseLandmarkGroup {
  name: string;
  count: number;
  required?: boolean;
}

export interface PoseSkeletonEdge {
  from: string;
  to: string;
}

export interface PoseLandmarkSchema {
  id: string;
  revision: number;
  groups: PoseLandmarkGroup[];
  edges?: PoseSkeletonEdge[];
}

export type PoseLandmarkStatus =
  | "visible"
  | "occluded"
  | "out_of_frame"
  | "uncertain"
  | "absent";

export interface PoseLandmarkObservation {
  id: string;
  semantic_label: string;
  occurrence_index: number;
  x: number;
  y: number;
  confidence: number | null;
  status: PoseLandmarkStatus;
  source: string;
}

export interface PoseInstance {
  id: string;
  revision: number;
  schema_id: string;
  schema_revision: number;
  observations: PoseLandmarkObservation[];
}

export interface PoseSaveRequest {
  pose_id: string;
  base_revision: number;
  schema_id: string;
  schema_revision: number;
  observations: PoseLandmarkObservation[];
}
