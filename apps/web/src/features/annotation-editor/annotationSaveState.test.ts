import { describe, expect, it } from "vitest";

import type { AnnotationSession } from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
} from "./annotationEditorReducer";

const session: AnnotationSession = {
  image: {
    id: "image-1",
    project_id: "project-1",
    original_filename: "coral.png",
    managed_path: "projects/project-1/images/coral.png",
    thumbnail_path: null,
    sha256: "a".repeat(64),
    width_px: 100,
    height_px: 100,
    file_size_bytes: 100,
    media_type: "image/png",
    import_source: null,
    capture_timestamp: null,
    group_key: null,
    metadata_json: {},
    annotation_status: "in_progress",
    annotation_revision: 2,
    annotation_count: 0,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  },
  label_classes: [],
  annotations: [],
  counts_by_class: [],
  previous_image_id: null,
  next_image_id: null,
};

describe("annotation save state", () => {
  it("reports a clean server-loaded document as saved", () => {
    const state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    expect(isDirty(state)).toBe(false);
    expect(state.saveState).toBe("saved");
    expect(state.saveMessage).toBe("Saved");
  });
});
