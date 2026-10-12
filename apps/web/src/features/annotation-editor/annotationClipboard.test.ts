import { describe, expect, it } from "vitest";

import {
  copyAnnotations,
  pasteAnnotations,
  type AnnotationClipboard,
} from "./annotationClipboard";
import type { AnnotationDocument } from "./types";

const document: AnnotationDocument = {
  annotation_status: "in_progress",
  annotations: [
    {
      id: "box-1",
      label_class_id: "class-coral",
      x_min: 80,
      y_min: 70,
      x_max: 100,
      y_max: 90,
    },
  ],
  maskAnnotations: [
    {
      id: "polygon-1",
      label_class_id: "class-coral",
      geometry_kind: "polygon",
      points: [
        { x: 90, y: 10 },
        { x: 100, y: 15 },
        { x: 95, y: 30 },
      ],
      mask_path: null,
      x_min: 90,
      y_min: 10,
      x_max: 100,
      y_max: 30,
      area_pixels: 100,
      source_type: "assist_mask",
      persisted: true,
      revision: 7,
    },
    {
      id: "raster-1",
      label_class_id: "class-coral",
      geometry_kind: "raster_mask",
      points: null,
      mask_path: "projects/p/masks/i/raster-1-r4.png",
      x_min: 1,
      y_min: 2,
      x_max: 20,
      y_max: 30,
      area_pixels: 240,
      source_type: "human_brush",
      persisted: true,
      revision: 4,
    },
  ],
  deletedMaskAnnotationIds: [],
};

describe("annotationClipboard", () => {
  it("copies only selected editable geometry into an internal clipboard", () => {
    const clipboard = copyAnnotations(
      document,
      ["box-1"],
      ["polygon-1", "raster-1"],
      {
        id: "image-1",
        projectId: "project-1",
        width: 100,
        height: 100,
      },
    );

    expect(clipboard.items.map((item) => item.kind)).toEqual([
      "box",
      "polygon",
    ]);
    expect(clipboard.skippedRasterCount).toBe(1);
    expect(clipboard.rasterMaskIds).toEqual(["raster-1"]);
    expect(clipboard.items[1]).not.toHaveProperty("source_type");
    expect(clipboard.items[1]).not.toHaveProperty("revision");
  });

  it("pastes source-pixel geometry without rescaling and clamps one shared translation", () => {
    const clipboard = copyAnnotations(document, ["box-1"], ["polygon-1"], {
      id: "image-1",
      projectId: "project-1",
      width: 100,
      height: 100,
    });
    const ids = ["new-box", "new-polygon"];
    const result = pasteAnnotations(
      clipboard,
      {
        id: "image-1",
        projectId: "project-1",
        width: 100,
        height: 100,
      }
      () => ids.shift() as string,
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.annotations[0]).toEqual({
      id: "new-box",
      label_class_id: "class-coral",
      x_min: 80,
      y_min: 80,
      x_max: 100,
      y_max: 100,
    });
    // The shared translation is clamped to zero because both selected objects
    // already touch the right edge. Geometry is never squeezed or rescaled.
    expect(result.annotations[0].y_max).toBe(100);
    expect(result.maskAnnotations[0]).toMatchObject({
      id: "new-polygon",
      label_class_id: "class-coral",
      geometry_kind: "polygon",
      source_type: "human",
      persisted: false,
      verification_status: "draft",
      mask_path: null,
    });
    expect(result.maskAnnotations[0]).not.toHaveProperty("revision");
    expect(result.maskAnnotations[0].points).toEqual([
      { x: 90, y: 20 },
      { x: 100, y: 25 },
      { x: 95, y: 40 },
    ]);
  });

  it("rejects a cross-image paste when source dimensions differ", () => {
    const clipboard = copyAnnotations(document, ["box-1"], [], {
      id: "image-1",
      projectId: "project-1",
      width: 100,
      height: 100,
    });

    expect(
      pasteAnnotations(
        clipboard,
        { id: "image-2", projectId: "project-1", width: 200, height: 100 },
        () => "new-id",
      ),
    ).toEqual({
      ok: false,
      reason:
        "Clipboard geometry uses 100×100 source pixels; the current image is 200×100. ReefVision will not rescale scientific geometry.",
    });
  });

  it("blocks cross-project annotation pastes even when image dimensions match", () => {
    const clipboard = copyAnnotations(document, ["box-1"], ["polygon-1"], {
      id: "image-1",
      projectId: "project-a",
      width: 100,
      height: 100,
    });
    expect(
      pasteAnnotations(
        clipboard,
        { id: "image-2", projectId: "project-b", width: 100, height: 100 },
        () => "never-create-an-id",
      ),
    ).toEqual({
      ok: false,
      reason:
        "Clipboard annotations belong to a different project. ReefVision will not transfer class IDs or scientific provenance between projects.",
    });
  });

  it("rejects empty and malformed clipboard content", () => {
    const empty: AnnotationClipboard = {
      sourceImage: {
        id: "image-1",
        projectId: "project-1",
        width: 100,
        height: 100,
      },
      items: [],
      rasterMaskIds: [],
      pasteCount: 0,
      skippedRasterCount: 0,
    };
    expect(pasteAnnotations(empty, empty.sourceImage, () => "new-id")).toEqual({
      ok: false,
      reason: "Copy an annotation before pasting.",
    });
  });
});
