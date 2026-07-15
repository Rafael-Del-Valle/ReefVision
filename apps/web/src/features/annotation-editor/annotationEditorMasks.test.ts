import { describe, expect, it } from "vitest";

import type { AnnotationSession } from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  toAnnotationSavePayload,
} from "./annotationEditorReducer";
import type { MaskAnnotationRecord } from "./types";

const polygonMask: MaskAnnotationRecord = {
  id: "mask-polygon",
  image_id: "image-1",
  label_class_id: "class-1",
  geometry_kind: "polygon",
  mask_path: null,
  polygon_json: [
    [10, 10],
    [30, 10],
    [30, 25],
    [10, 25],
  ],
  x_min: 10,
  y_min: 10,
  x_max: 30,
  y_max: 25,
  area_pixels: 300,
  source_type: "human",
  provenance_json: null,
  status: "verified",
  created_by: "local_user",
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
  deleted_at: null,
  revision: 1,
};

const rasterMask: MaskAnnotationRecord = {
  ...polygonMask,
  id: "mask-raster",
  geometry_kind: "raster_mask",
  mask_path: "projects/project-1/masks/image-1/mask-raster.png",
  polygon_json: null,
  source_type: "assist_mask",
};

const session: AnnotationSession & {
  mask_annotations: MaskAnnotationRecord[];
} = {
  image: {
    id: "image-1",
    project_id: "project-1",
    original_filename: "reef.png",
    managed_path: "projects/project-1/images/reef.png",
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
    annotation_revision: 4,
    annotation_count: 0,
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
  },
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Coral",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#2A9D8F",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-15T00:00:00Z",
      updated_at: "2026-07-15T00:00:00Z",
    },
  ],
  annotations: [],
  counts_by_class: [{ label_class_id: "class-1", count: 0 }],
  previous_image_id: null,
  next_image_id: null,
  mask_annotations: [polygonMask, rasterMask],
};

describe("annotation editor mask state", () => {
  it("loads raster and polygon masks but serializes only editable polygons", () => {
    const state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });

    expect(state.document.maskAnnotations).toHaveLength(2);
    expect(state.document.maskAnnotations[0].points).toEqual([
      { x: 10, y: 10 },
      { x: 30, y: 10 },
      { x: 30, y: 25 },
      { x: 10, y: 25 },
    ]);
    expect(toAnnotationSavePayload(state)).toMatchObject({
      base_revision: 4,
      mask_annotations: [
        {
          id: "mask-polygon",
          label_class_id: "class-1",
          geometry_kind: "polygon",
          points: [
            { x: 10, y: 10 },
            { x: 30, y: 10 },
            { x: 30, y: 25 },
            { x: 10, y: 25 },
          ],
        },
      ],
    });
  });

  it("tracks explicit mask deletion through undo and redo", () => {
    let state = annotationEditorReducer(initialAnnotationEditorState, {
      type: "loadSession",
      session,
    });
    state = annotationEditorReducer(state, {
      type: "commitDocument",
      document: {
        ...state.document,
        maskAnnotations: state.document.maskAnnotations.filter(
          (mask) => mask.id !== "mask-polygon",
        ),
        deletedMaskAnnotationIds: ["mask-polygon"],
      },
      maskSelection: [],
    });

    expect(toAnnotationSavePayload(state).deleted_mask_annotation_ids).toEqual([
      "mask-polygon",
    ]);

    state = annotationEditorReducer(state, { type: "undo" });
    expect(state.document.maskAnnotations).toHaveLength(2);
    expect(state.document.deletedMaskAnnotationIds).toEqual([]);

    state = annotationEditorReducer(state, { type: "redo" });
    expect(state.document.maskAnnotations.map((mask) => mask.id)).toEqual([
      "mask-raster",
    ]);
    expect(state.document.deletedMaskAnnotationIds).toEqual(["mask-polygon"]);
  });
});
