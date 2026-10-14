import { describe, expect, it } from "vitest";

import type { AnnotationSession } from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
  toAnnotationSavePayload,
} from "./annotationEditorReducer";

const session: AnnotationSession = {
  image: {
    id: "image-1",
    project_id: "project-1",
    original_filename: "reef.png",
    managed_path: "managed",
    thumbnail_path: null,
    sha256: "a".repeat(64),
    width_px: 400,
    height_px: 300,
    file_size_bytes: 100,
    media_type: "image/png",
    import_source: null,
    capture_timestamp: null,
    group_key: null,
    metadata_json: {},
    annotation_status: "in_progress",
    annotation_revision: 3,
    annotation_count: 1,
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
  },
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
    {
      id: "class-2",
      project_id: "project-1",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#2A9D8F",
      is_active: false,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
  annotations: [
    {
      id: "annotation-1",
      image_id: "image-1",
      label_class_id: "class-1",
      x_min: 10,
      y_min: 12,
      x_max: 22,
      y_max: 30,
      source_type: "human",
      source_model_id: null,
      source_prediction_id: null,
      created_by: "local_user",
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
      deleted_at: null,
      revision: 1,
    },
  ],
  counts_by_class: [
    { label_class_id: "class-1", count: 1 },
    { label_class_id: "class-2", count: 0 },
  ],
  previous_image_id: null,
  next_image_id: null,
};

describe("annotationEditorReducer", () => {
  it("loads a session and tracks dirty edits with undo and redo", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    expect(state.baseRevision).toBe(3);
    expect(state.activeClassId).toBe("class-1");
    expect(isDirty(state)).toBe(false);

    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: [
          {
            ...state.document.annotations[0],
            x_min: 20,
          },
        ],
      },
      selection: ["annotation-1"],
    });

    expect(isDirty(state)).toBe(true);
    expect(state.history).toHaveLength(1);
    expect(state.selectedIds).toEqual(["annotation-1"]);

    state = annotationEditorReducer(state, { type: "undo" });
    expect(state.document.annotations[0].x_min).toBe(10);

    state = annotationEditorReducer(state, { type: "redo" });
    expect(state.document.annotations[0].x_min).toBe(20);
  });

  it("invalidates review after geometry edits and permits re-review", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session: {
        ...session,
        image: { ...session.image, annotation_status: "reviewed" },
      },
    });

    const newBox = {
      ...state.document.annotations[0],
      id: "draft-box-2",
      x_min: 40,
      x_max: 50,
    };
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: [...state.document.annotations, newBox],
      },
    });
    expect(state.document.annotation_status).toBe("in_progress");
    expect(toAnnotationSavePayload(state).annotation_status).toBe(
      "in_progress",
    );

    state = annotationEditorReducer(state, { type: "undo" });
    expect(state.document.annotation_status).toBe("reviewed");
    expect(state.document.annotations).toHaveLength(1);
    state = annotationEditorReducer(state, { type: "redo" });
    expect(state.document.annotation_status).toBe("in_progress");

    // Reviewer explicitly completes review after evaluating the changed content.
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: { ...state.document, annotation_status: "reviewed" },
    });
    expect(state.document.annotation_status).toBe("reviewed");

    // Edits to existing geometry also invalidate the re-review.
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: state.document.annotations.map((annotation) =>
          annotation.id === newBox.id
            ? { ...annotation, label_class_id: "class-2" }
            : annotation,
        ),
      },
    });
    expect(state.document.annotation_status).toBe("in_progress");
  });

  it("keeps newer local edits dirty after an older save succeeds", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: [
          {
            ...state.document.annotations[0],
            x_min: 20,
          },
        ],
      },
    });
    const sentVersion = state.documentVersion;

    state = annotationEditorReducer(state, {
      type: "saveStarted",
      sentVersion,
    });
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: [
          {
            ...state.document.annotations[0],
            x_min: 24,
          },
        ],
      },
    });
    state = annotationEditorReducer(state, {
      type: "saveSucceeded",
      sentVersion,
      response: {
        image: {
          ...session.image,
          annotation_revision: 4,
          annotation_status: "in_progress",
        },
        annotations: [
          {
            ...session.annotations[0],
            x_min: 20,
          },
        ],
        counts_by_class: session.counts_by_class,
      },
    });

    expect(state.baseRevision).toBe(4);
    expect(state.document.annotations[0].x_min).toBe(24);
    expect(state.saveState).toBe("dirty");
  });

  it("serializes the current document into the API save payload", () => {
    const state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    expect(toAnnotationSavePayload(state)).toEqual({
      base_revision: 3,
      annotation_status: "in_progress",
      annotations: [
        {
          id: "annotation-1",
          label_class_id: "class-1",
          x_min: 10,
          y_min: 12,
          x_max: 22,
          y_max: 30,
        },
      ],
    });
  });

  it("keeps a newly committed box on its original class when the active class changes in box mode", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    state = annotationEditorReducer(state, {
      type: "setTool",
      tool: "box",
    });
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        annotations: [
          ...state.document.annotations,
          {
            id: "annotation-2",
            label_class_id: "class-1",
            x_min: 40,
            y_min: 44,
            x_max: 96,
            y_max: 112,
          },
        ],
      },
      selection: ["annotation-2"],
    });
    state = annotationEditorReducer(state, {
      type: "setActiveClassId",
      classId: "class-2",
    });

    expect(state.tool).toBe("box");
    expect(state.activeClassId).toBe("class-2");
    expect(state.selectedIds).toEqual(["annotation-2"]);
    expect(
      state.document.annotations.find(
        (annotation) => annotation.id === "annotation-2",
      ),
    ).toMatchObject({
      id: "annotation-2",
      label_class_id: "class-1",
    });
  });

  it("supports hide-all, invert, solo, and reset visibility actions", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    state = annotationEditorReducer(state, {
      type: "hideAllClasses",
      classIds: ["class-1", "class-2"],
    });
    expect(state.hiddenClassIds).toEqual(["class-1", "class-2"]);

    state = annotationEditorReducer(state, {
      type: "invertHiddenClasses",
      classIds: ["class-1", "class-2"],
    });
    expect(state.hiddenClassIds).toEqual([]);

    state = annotationEditorReducer(state, {
      type: "soloClass",
      classId: "class-2",
      classIds: ["class-1", "class-2"],
    });
    expect(state.hiddenClassIds).toEqual(["class-1"]);

    state = annotationEditorReducer(state, { type: "resetVisibility" });
    expect(state.hiddenClassIds).toEqual([]);
  });
});
