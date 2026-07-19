import type {
  AnnotationSavePayload,
  AnnotationSaveResponse,
  AnnotationSession,
} from "../../api/client";
import type {
  AnnotationDocument,
  AnnotationEditorState,
  EditorAnnotation,
  EditorMaskAnnotation,
  EditorTool,
  MaskAnnotationRecord,
} from "./types";
import { toEditorAnnotation, toEditorMaskAnnotation } from "./types";

const HISTORY_LIMIT = 100;

interface MaskAnnotationDraftPayload {
  id: string;
  label_class_id: string;
  geometry_kind: "polygon";
  points: Array<{ x: number; y: number }>;
}

export interface ExtendedAnnotationSavePayload extends AnnotationSavePayload {
  mask_annotations?: MaskAnnotationDraftPayload[];
  deleted_mask_annotation_ids?: string[];
}

type ExtendedAnnotationSession = AnnotationSession & {
  mask_annotations?: MaskAnnotationRecord[];
};

type ExtendedAnnotationSaveResponse = AnnotationSaveResponse & {
  mask_annotations?: MaskAnnotationRecord[];
};

export const initialAnnotationEditorState: AnnotationEditorState = {
  baseRevision: 0,
  documentVersion: 0,
  lastCommittedVersion: 0,
  document: {
    annotation_status: "unannotated",
    annotations: [],
    maskAnnotations: [],
    deletedMaskAnnotationIds: [],
  },
  history: [],
  future: [],
  selectedIds: [],
  selectedMaskIds: [],
  activeClassId: null,
  hiddenClassIds: [],
  tool: "select",
  saveState: "idle",
  saveMessage: null,
};

type AnnotationEditorAction =
  | { type: "loadSession"; session: AnnotationSession }
  | { type: "setTool"; tool: EditorTool }
  | { type: "setSelection"; selection: string[] }
  | { type: "setMaskSelection"; selection: string[] }
  | { type: "setActiveClassId"; classId: string | null }
  | { type: "toggleHiddenClassId"; classId: string }
  | { type: "showAllClasses" }
  | { type: "hideAllClasses"; classIds: string[] }
  | { type: "invertHiddenClasses"; classIds: string[] }
  | { type: "soloClass"; classId: string; classIds: string[] }
  | { type: "resetVisibility" }
  | {
      type: "commitDocument";
      document: AnnotationDocument;
      selection?: string[];
      maskSelection?: string[];
    }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "saveStarted"; sentVersion: number }
  | { type: "saveConfirmed" }
  | {
      type: "saveSucceeded";
      sentVersion: number;
      response: AnnotationSaveResponse;
    }
  | {
      type: "saveFailed";
      message: string;
      conflict: boolean;
    };

function annotationsEqual(
  left: EditorAnnotation[],
  right: EditorAnnotation[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((annotation, index) => {
    const other = right[index];
    return (
      annotation.id === other.id &&
      annotation.label_class_id === other.label_class_id &&
      annotation.x_min === other.x_min &&
      annotation.y_min === other.y_min &&
      annotation.x_max === other.x_max &&
      annotation.y_max === other.y_max
    );
  });
}

function pointsEqual(
  left: EditorMaskAnnotation["points"],
  right: EditorMaskAnnotation["points"],
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right || left.length !== right.length) {
    return false;
  }
  return left.every(
    (point, index) => point.x === right[index].x && point.y === right[index].y,
  );
}

function maskAnnotationsEqual(
  left: EditorMaskAnnotation[],
  right: EditorMaskAnnotation[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((annotation, index) => {
    const other = right[index];
    return (
      annotation.id === other.id &&
      annotation.label_class_id === other.label_class_id &&
      annotation.geometry_kind === other.geometry_kind &&
      annotation.mask_path === other.mask_path &&
      annotation.x_min === other.x_min &&
      annotation.y_min === other.y_min &&
      annotation.x_max === other.x_max &&
      annotation.y_max === other.y_max &&
      annotation.area_pixels === other.area_pixels &&
      annotation.source_type === other.source_type &&
      pointsEqual(annotation.points, other.points)
    );
  });
}

function arraysEqual(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((item, index) => item === right[index])
  );
}

function documentsEqual(
  left: AnnotationDocument,
  right: AnnotationDocument,
): boolean {
  return (
    left.annotation_status === right.annotation_status &&
    annotationsEqual(left.annotations, right.annotations) &&
    maskAnnotationsEqual(left.maskAnnotations, right.maskAnnotations) &&
    arraysEqual(left.deletedMaskAnnotationIds, right.deletedMaskAnnotationIds)
  );
}

function validSelection(
  document: AnnotationDocument,
  selection: string[],
): string[] {
  const ids = new Set(document.annotations.map((annotation) => annotation.id));
  return Array.from(new Set(selection)).filter((id) => ids.has(id));
}

function validMaskSelection(
  document: AnnotationDocument,
  selection: string[],
): string[] {
  const ids = new Set(
    document.maskAnnotations.map((annotation) => annotation.id),
  );
  return Array.from(new Set(selection)).filter((id) => ids.has(id));
}

export function isDirty(state: AnnotationEditorState): boolean {
  return state.documentVersion > state.lastCommittedVersion;
}

export function documentFromSession(
  session: AnnotationSession,
): AnnotationDocument {
  const extendedSession = session as ExtendedAnnotationSession;
  return {
    annotation_status: session.image.annotation_status,
    annotations: session.annotations.map(toEditorAnnotation),
    maskAnnotations: (extendedSession.mask_annotations ?? []).map(
      toEditorMaskAnnotation,
    ),
    deletedMaskAnnotationIds: [],
  };
}

function documentFromSaveResponse(
  response: AnnotationSaveResponse,
  current: AnnotationDocument,
): AnnotationDocument {
  const extendedResponse = response as ExtendedAnnotationSaveResponse;
  return {
    annotation_status: response.image.annotation_status,
    annotations: response.annotations.map(toEditorAnnotation),
    maskAnnotations:
      extendedResponse.mask_annotations?.map(toEditorMaskAnnotation) ??
      current.maskAnnotations,
    deletedMaskAnnotationIds: [],
  };
}

function nextHistory(
  history: AnnotationDocument[],
  current: AnnotationDocument,
) {
  const withCurrent = [...history, current];
  return withCurrent.slice(-HISTORY_LIMIT);
}

export function toAnnotationSavePayload(
  state: AnnotationEditorState,
): ExtendedAnnotationSavePayload {
  const payload: ExtendedAnnotationSavePayload = {
    base_revision: state.baseRevision,
    annotation_status: state.document.annotation_status,
    annotations: state.document.annotations.map((annotation) => ({
      id: annotation.id,
      label_class_id: annotation.label_class_id,
      x_min: annotation.x_min,
      y_min: annotation.y_min,
      x_max: annotation.x_max,
      y_max: annotation.y_max,
    })),
  };
  const editableMasks = state.document.maskAnnotations.filter(
    (
      annotation,
    ): annotation is EditorMaskAnnotation & {
      label_class_id: string;
      points: Array<{ x: number; y: number }>;
    } =>
      annotation.geometry_kind === "polygon" &&
      annotation.label_class_id !== null &&
      annotation.points !== null &&
      annotation.points.length >= 3,
  );
  if (editableMasks.length > 0) {
    payload.mask_annotations = editableMasks.map((annotation) => ({
      id: annotation.id,
      label_class_id: annotation.label_class_id,
      geometry_kind: "polygon",
      points: annotation.points.map((point) => ({ ...point })),
    }));
  }
  if (state.document.deletedMaskAnnotationIds.length > 0) {
    payload.deleted_mask_annotation_ids = [
      ...state.document.deletedMaskAnnotationIds,
    ];
  }
  return payload;
}

export function annotationEditorReducer(
  state: AnnotationEditorState,
  action: AnnotationEditorAction,
): AnnotationEditorState {
  switch (action.type) {
    case "loadSession": {
      const nextDocument = documentFromSession(action.session);
      const activeClassId =
        action.session.label_classes.find((item) => item.is_active)?.id ??
        action.session.label_classes[0]?.id ??
        null;
      return {
        ...initialAnnotationEditorState,
        baseRevision: action.session.image.annotation_revision,
        document: nextDocument,
        activeClassId,
        saveState: "saved",
        saveMessage: "Saved",
      };
    }
    case "setTool":
      return {
        ...state,
        tool: action.tool,
      };
    case "setSelection":
      return {
        ...state,
        selectedIds: validSelection(state.document, action.selection),
      };
    case "setMaskSelection":
      return {
        ...state,
        selectedMaskIds: validMaskSelection(state.document, action.selection),
      };
    case "setActiveClassId":
      return {
        ...state,
        activeClassId: action.classId,
      };
    case "toggleHiddenClassId": {
      const hidden = state.hiddenClassIds.includes(action.classId)
        ? state.hiddenClassIds.filter((item) => item !== action.classId)
        : [...state.hiddenClassIds, action.classId];
      return {
        ...state,
        hiddenClassIds: hidden,
      };
    }
    case "showAllClasses":
      return {
        ...state,
        hiddenClassIds: [],
      };
    case "hideAllClasses":
      return {
        ...state,
        hiddenClassIds: Array.from(new Set(action.classIds)),
      };
    case "invertHiddenClasses": {
      const hidden = new Set(state.hiddenClassIds);
      return {
        ...state,
        hiddenClassIds: action.classIds.filter(
          (classId) => !hidden.has(classId),
        ),
      };
    }
    case "soloClass":
      return {
        ...state,
        hiddenClassIds: action.classIds.filter(
          (classId) => classId !== action.classId,
        ),
      };
    case "resetVisibility":
      return {
        ...state,
        hiddenClassIds: [],
      };
    case "commitDocument": {
      const nextDocument = action.document;
      const nextSelection = validSelection(
        nextDocument,
        action.selection ?? state.selectedIds,
      );
      const nextMaskSelection = validMaskSelection(
        nextDocument,
        action.maskSelection ?? state.selectedMaskIds,
      );
      if (documentsEqual(state.document, nextDocument)) {
        return {
          ...state,
          selectedIds: nextSelection,
          selectedMaskIds: nextMaskSelection,
        };
      }
      return {
        ...state,
        document: nextDocument,
        history: nextHistory(state.history, state.document),
        future: [],
        selectedIds: nextSelection,
        selectedMaskIds: nextMaskSelection,
        documentVersion: state.documentVersion + 1,
        saveState: state.saveState === "saving" ? "saving" : "dirty",
        saveMessage: null,
      };
    }
    case "undo": {
      const previous = state.history[state.history.length - 1];
      if (!previous) {
        return state;
      }
      return {
        ...state,
        document: previous,
        history: state.history.slice(0, -1),
        future: [state.document, ...state.future],
        selectedIds: validSelection(previous, state.selectedIds),
        selectedMaskIds: validMaskSelection(previous, state.selectedMaskIds),
        documentVersion: state.documentVersion + 1,
        saveState: state.saveState === "saving" ? "saving" : "dirty",
        saveMessage: null,
      };
    }
    case "redo": {
      const next = state.future[0];
      if (!next) {
        return state;
      }
      return {
        ...state,
        document: next,
        history: nextHistory(state.history, state.document),
        future: state.future.slice(1),
        selectedIds: validSelection(next, state.selectedIds),
        selectedMaskIds: validMaskSelection(next, state.selectedMaskIds),
        documentVersion: state.documentVersion + 1,
        saveState: state.saveState === "saving" ? "saving" : "dirty",
        saveMessage: null,
      };
    }
    case "saveStarted":
      return {
        ...state,
        saveState: "saving",
        saveMessage: null,
      };
    case "saveConfirmed":
      return {
        ...state,
        saveState: "saved",
        saveMessage: "Saved",
      };
    case "saveSucceeded": {
      const currentHasNewerChanges = state.documentVersion > action.sentVersion;
      const nextDocument = documentFromSaveResponse(
        action.response,
        state.document,
      );
      const document = currentHasNewerChanges ? state.document : nextDocument;
      return {
        ...state,
        baseRevision: action.response.image.annotation_revision,
        lastCommittedVersion: Math.max(
          state.lastCommittedVersion,
          action.sentVersion,
        ),
        document,
        selectedIds: validSelection(document, state.selectedIds),
        selectedMaskIds: validMaskSelection(document, state.selectedMaskIds),
        saveState: currentHasNewerChanges ? "dirty" : "saved",
        saveMessage: currentHasNewerChanges ? null : "Saved",
      };
    }
    case "saveFailed":
      return {
        ...state,
        saveState: action.conflict ? "conflict" : "error",
        saveMessage: action.message,
      };
    default:
      return state;
  }
}
