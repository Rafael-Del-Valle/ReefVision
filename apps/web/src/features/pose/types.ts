export interface PoseLandmarkGroup {
  name: string;
  count: number;
  required?: boolean;
}

export interface PoseLandmarkSchema {
  id: string;
  revision: number;
  groups: PoseLandmarkGroup[];
}

export interface PoseLandmarkObservation {
  id: string;
  semantic_label: string;
  occurrence_index: number;
  x: number;
  y: number;
  confidence: number | null;
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
