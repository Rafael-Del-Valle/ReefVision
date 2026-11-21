import { describe, expect, it } from "vitest";

import {
  addMaskAnnotation,
  changeMaskAnnotationClass,
  deleteMaskAnnotations,
  deleteSelectedAnnotations,
  updateMaskAnnotation,
} from "./maskDocumentOperations";
import { polygonMaskFromPoints } from "./PolygonMaskLayer";
import type { AnnotationDocument, EditorMaskAnnotation } from "./types";

const persistedMask: EditorMaskAnnotation = {
  ...polygonMaskFromPoints(
    [
      { x: 10, y: 10 },
      { x: 30, y: 10 },
      { x: 30, y: 25 },
    ],
    "class-1",
    "persisted-mask",
    true,
  ),
};

const persistedRasterMask: EditorMaskAnnotation = {
  id: "persisted-raster-mask",
  label_class_id: "class-1",
  geometry_kind: "raster_mask",
  points: null,
  mask_path: "projects/project-1/masks/image-1/raster-r1.png",
  x_min: 5,
  y_min: 5,
  x_max: 25,
  y_max: 25,
  area_pixels: 200,
  source_type: "human_brush",
  persisted: true,
  revision: 1,
};

const emptyDocument: AnnotationDocument = {
  annotation_status: "in_progress",
  annotations: [],
  maskAnnotations: [],
  deletedMaskAnnotationIds: [],
};

describe("mask document operations", () => {
  it("adds and updates polygon masks without changing unrelated document data", () => {
    const newMask = polygonMaskFromPoints(
      [
        { x: 0, y: 0 },
        { x: 20, y: 0 },
        { x: 20, y: 10 },
      ],
      "class-1",
      "new-mask",
    );
    const added = addMaskAnnotation(emptyDocument, newMask);
    expect(added.maskAnnotations).toEqual([newMask]);

    const moved = {
      ...newMask,
      points: [
        { x: 2, y: 2 },
        { x: 20, y: 0 },
        { x: 20, y: 10 },
      ],
    };
    const updated = updateMaskAnnotation(added, moved);
    expect(updated.maskAnnotations).toEqual([moved]);
    expect(updated.annotation_status).toBe("in_progress");
  });

  it("does not issue a server deletion for an unsaved new mask", () => {
    const newMask = polygonMaskFromPoints(
      [
        { x: 0, y: 0 },
        { x: 20, y: 0 },
        { x: 20, y: 10 },
      ],
      "class-1",
      "new-mask",
    );
    const deleted = deleteMaskAnnotations(
      {
        ...emptyDocument,
        maskAnnotations: [newMask],
      },
      [newMask.id],
    );

    expect(deleted.maskAnnotations).toEqual([]);
    expect(deleted.deletedMaskAnnotationIds).toEqual([]);
  });

  it("tracks persisted masks for explicit server deletion", () => {
    const deleted = deleteMaskAnnotations(
      {
        ...emptyDocument,
        maskAnnotations: [persistedMask],
      },
      [persistedMask.id],
    );

    expect(deleted.maskAnnotations).toEqual([]);
    expect(deleted.deletedMaskAnnotationIds).toEqual([persistedMask.id]);
  });

  it("changes the class for selected polygon masks", () => {
    const changed = changeMaskAnnotationClass(
      {
        ...emptyDocument,
        maskAnnotations: [persistedMask],
      },
      [persistedMask.id],
      "class-2",
    );
    expect(changed.maskAnnotations[0].label_class_id).toBe("class-2");
    expect(changed.maskAnnotations[0].persisted).toBe(true);
  });

  it("does not pretend a raster class-only change can be batch-saved", () => {
    const changed = changeMaskAnnotationClass(
      {
        ...emptyDocument,
        maskAnnotations: [persistedRasterMask],
      },
      [persistedRasterMask.id],
      "class-2",
    );

    expect(changed.maskAnnotations[0].label_class_id).toBe("class-1");
  });

  it("deletes dense multi-class selections with indexed membership, preserving original evidence", () => {
    const annotations = Array.from({ length: 20_000 }, (_, index) => ({
      id: `box-${index}`,
      label_class_id: "class-1",
      x_min: index,
      y_min: 0,
      x_max: index + 1,
      y_max: 1,
    }));
    const selected = annotations.map((item) => item.id);
    const guardedSelection = new Proxy(selected, {
      get(target, key, receiver) {
        if (key === "includes") {
          throw new Error("Quadratic per-annotation selection search");
        }
        return Reflect.get(target, key, receiver);
      },
    });
    const original = { ...emptyDocument, annotations };
    const deleted = deleteSelectedAnnotations(original, guardedSelection, []);
    expect(deleted.annotations).toHaveLength(0);
    expect(deleted.maskAnnotations).toBe(original.maskAnnotations);
    expect(deleted.deletedMaskAnnotationIds).toBe(
      original.deletedMaskAnnotationIds,
    );
    expect(original.annotations).toHaveLength(20_000);
    expect(selected).toHaveLength(20_000);
  });

  it("preserves persisted mask deletion evidence and skips unsaved mask tombstones", () => {
    const unsavedMask = polygonMaskFromPoints(
      [
        { x: 3, y: 3 },
        { x: 13, y: 3 },
        { x: 13, y: 13 },
      ],
      "class-1",
      "unsaved-mask",
    );
    const original = {
      ...emptyDocument,
      annotations: [
        {
          id: "box-1",
          label_class_id: "class-1",
          x_min: 1,
          y_min: 1,
          x_max: 3,
          y_max: 3,
        },
      ],
      maskAnnotations: [persistedMask, persistedRasterMask, unsavedMask],
      deletedMaskAnnotationIds: ["prior-delete"],
    };
    const deleted = deleteSelectedAnnotations(
      original,
      ["box-1", "box-1", "missing-box"],
      [persistedMask.id, unsavedMask.id, "missing-mask"],
    );
    expect(deleted.annotations).toHaveLength(0);
    expect(deleted.maskAnnotations).toEqual([persistedRasterMask]);
    expect(deleted.deletedMaskAnnotationIds).toEqual([
      "prior-delete",
      persistedMask.id,
    ]);
    expect(original.maskAnnotations).toHaveLength(3);
    expect(original.deletedMaskAnnotationIds).toEqual(["prior-delete"]);
  });

  it("returns original document for selections containing only stale IDs", () => {
    const original = {
      ...emptyDocument,
      maskAnnotations: [persistedMask],
    };
    expect(
      deleteSelectedAnnotations(original, ["missing-box"], ["missing-mask"]),
    ).toBe(original);
    expect(deleteSelectedAnnotations(original, [], [])).toBe(original);
  });
});
