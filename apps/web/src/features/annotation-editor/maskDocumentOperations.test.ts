import { describe, expect, it } from "vitest";

import {
  addMaskAnnotation,
  changeMaskAnnotationClass,
  deleteMaskAnnotations,
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

  it("changes the class for all selected masks", () => {
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
});
