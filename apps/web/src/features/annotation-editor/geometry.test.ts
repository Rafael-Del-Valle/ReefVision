import { describe, expect, it } from "vitest";

import {
  actualSizeTransform,
  createBoxFromPoints,
  fitTransform,
  imageToScreen,
  resizeAnnotation,
  screenToImage,
  translateAnnotations,
  zoomAtPoint,
} from "./geometry";

describe("annotation editor geometry", () => {
  it("creates normalized source-pixel boxes from any drag direction", () => {
    expect(
      createBoxFromPoints(
        { x: 160, y: 110 },
        { x: 10, y: 20 },
        { width: 200, height: 120 },
      ),
    ).toEqual({
      x_min: 10,
      y_min: 20,
      x_max: 160,
      y_max: 110,
    });
  });

  it("keeps multi-selection moves inside the image bounds", () => {
    expect(
      translateAnnotations(
        [
          {
            id: "a",
            label_class_id: "class-1",
            x_min: 10,
            y_min: 10,
            x_max: 20,
            y_max: 20,
          },
          {
            id: "b",
            label_class_id: "class-1",
            x_min: 85,
            y_min: 85,
            x_max: 100,
            y_max: 100,
          },
        ],
        { x: 20, y: 30 },
        { width: 100, height: 100 },
      ),
    ).toEqual([
      {
        id: "a",
        label_class_id: "class-1",
        x_min: 10,
        y_min: 10,
        x_max: 20,
        y_max: 20,
      },
      {
        id: "b",
        label_class_id: "class-1",
        x_min: 85,
        y_min: 85,
        x_max: 100,
        y_max: 100,
      },
    ]);
  });

  it("moves 200,000 coral boxes without an argument spread", () => {
    const originals = Array.from({ length: 200_000 }, (_, index) => {
      const x_min = 10 + (index % 1000);
      const y_min = 10 + Math.floor(index / 1000);
      return {
        id: `coral-${index}`,
        label_class_id: "swiftia",
        x_min,
        y_min,
        x_max: x_min + 3,
        y_max: y_min + 3,
      };
    });

    const moved = translateAnnotations(
      originals,
      { x: 500, y: -500 },
      { width: 1100, height: 300 },
    );

    expect(moved).toHaveLength(originals.length);
    // Entire selection moves as one group, constrained by its extreme boxes.
    expect(moved[0]).toEqual({
      ...originals[0],
      x_min: 98,
      x_max: 101,
      y_min: 0,
      y_max: 3,
    });
    expect(moved[199_999].x_max).toBe(1100);
    expect(moved[123_456].id).toBe(originals[123_456].id);
    // Neither source records nor their taxonomic class are rewritten.
    expect(originals[0].x_min).toBe(10);
    expect(originals[199_999].x_max).toBe(1012);
    expect(moved[123_456].label_class_id).toBe("swiftia");
  });

  it("refuses a whole group move when any imported box has impossible geometry", () => {
    const valid = {
      id: "valid-swiftia",
      label_class_id: "swiftia",
      x_min: 5,
      y_min: 6,
      x_max: 15,
      y_max: 16,
    };
    for (const malformed of [
      { ...valid, id: "nan-coordinate", x_min: Number.NaN },
      { ...valid, id: "infinite-coordinate", y_max: Infinity },
      { ...valid, id: "inverted-box", x_min: 16 },
      { ...valid, id: "off-image", x_max: 101 },
      { ...valid, id: "negative-coordinate", y_min: -1 },
    ]) {
      const selection = [valid, malformed];
      expect(
        translateAnnotations(
          selection,
          { x: 30, y: -30 },
          { width: 100, height: 100 },
        ),
      ).toBe(selection);
      expect(valid.x_min).toBe(5);
    }
  });

  it("keeps dense valid records intact when the last selected box is corrupt", () => {
    const selection = Array.from({ length: 20_000 }, (_, index) => ({
      id: `coral-${index}`,
      label_class_id: "swiftia",
      x_min: 10 + (index % 100),
      y_min: 10 + Math.floor(index / 100),
      x_max: 12 + (index % 100),
      y_max: 12 + Math.floor(index / 100),
    }));
    const original = selection[0];
    selection[selection.length - 1] = {
      ...selection[selection.length - 1],
      x_min: Number.NaN,
    };
    expect(
      translateAnnotations(
        selection,
        { x: 40, y: 40 },
        { width: 200, height: 300 },
      ),
    ).toBe(selection);
    expect(selection[0]).toBe(original);
    expect(selection[0].x_min).toBe(10);
  });

  it("rejects invalid image dimensions or pointer deltas before changing coordinates", () => {
    const selection = [
      {
        id: "source-coral",
        label_class_id: "swiftia",
        x_min: 10,
        y_min: 20,
        x_max: 15,
        y_max: 25,
      },
    ];
    for (const imageSize of [
      { width: 0, height: 100 },
      { width: 100, height: Infinity },
      { width: Number.NaN, height: 100 },
    ]) {
      expect(translateAnnotations(selection, { x: 10, y: 20 }, imageSize)).toBe(
        selection,
      );
    }
    for (const delta of [
      { x: Number.NaN, y: 0 },
      { x: 10, y: Infinity },
    ]) {
      expect(
        translateAnnotations(selection, delta, { width: 100, height: 100 }),
      ).toBe(selection);
    }
    expect(selection[0].x_min).toBe(10);
  });

  it("returns an empty selection without attempting geometry reduction", () => {
    expect(
      translateAnnotations(
        [],
        { x: 200, y: -200 },
        { width: 1100, height: 300 },
      ),
    ).toEqual([]);
  });

  it("resizes boxes while respecting image bounds and minimum area", () => {
    expect(
      resizeAnnotation(
        {
          id: "annotation-1",
          label_class_id: "class-1",
          x_min: 20,
          y_min: 30,
          x_max: 100,
          y_max: 120,
        },
        "nw",
        { x: -50, y: 119 },
        { width: 200, height: 200 },
      ),
    ).toEqual({
      id: "annotation-1",
      label_class_id: "class-1",
      x_min: 0,
      y_min: 119,
      x_max: 100,
      y_max: 120,
    });
  });

  it("refuses malformed single-object resize without modifying the imported observation", () => {
    const valid = {
      id: "deep-coral",
      label_class_id: "swiftia",
      x_min: 10,
      y_min: 20,
      x_max: 30,
      y_max: 40,
    };
    const imageSize = { width: 100, height: 100 };
    for (const imported of [
      { ...valid, x_min: Number.NaN },
      { ...valid, y_max: Infinity },
      { ...valid, x_min: -1 },
      { ...valid, x_max: 110 },
      { ...valid, x_min: 31 },
      { ...valid, y_min: 40 },
      { ...valid, x_max: 10.5 },
    ]) {
      expect(
        resizeAnnotation(imported, "se", { x: 50, y: 60 }, imageSize),
      ).toBe(imported);
    }
    expect(valid.x_min).toBe(10);
    expect(valid.label_class_id).toBe("swiftia");
  });

  it("refuses impossible resize pointers, canvas dimensions and minimum sizes", () => {
    const annotation = {
      id: "original-measurement",
      label_class_id: "swiftia",
      x_min: 10,
      y_min: 20,
      x_max: 30,
      y_max: 40,
    };
    for (const point of [
      { x: Number.NaN, y: 50 },
      { x: 50, y: Infinity },
    ]) {
      expect(
        resizeAnnotation(annotation, "se", point, { width: 100, height: 100 }),
      ).toBe(annotation);
    }
    for (const size of [
      { width: 0, height: 100 },
      { width: Infinity, height: 100 },
      { width: 100, height: Number.NaN },
      { width: 25, height: 100 },
    ]) {
      expect(
        resizeAnnotation(annotation, "se", { x: 50, y: 50 }, size),
      ).toBe(annotation);
    }
    for (const minimumSize of [0, -1, Infinity, Number.NaN, 101, 21]) {
      expect(
        resizeAnnotation(
          annotation,
          "se",
          { x: 50, y: 50 },
          { width: 100, height: 100 },
          minimumSize,
        ),
      ).toBe(annotation);
    }
    expect(annotation.x_max).toBe(30);
  });

  it("resumes bounded resizing after invalid pointer input without changing source identity", () => {
    const annotation = {
      id: "source-coral",
      label_class_id: "swiftia",
      x_min: 10,
      y_min: 10,
      x_max: 20,
      y_max: 20,
    };
    expect(
      resizeAnnotation(
        annotation,
        "se",
        { x: Number.NaN, y: 200 },
        { width: 100, height: 100 },
      ),
    ).toBe(annotation);
    expect(
      resizeAnnotation(
        annotation,
        "se",
        { x: 200, y: -10 },
        { width: 100, height: 100 },
      ),
    ).toEqual({
      ...annotation,
      x_max: 100,
      y_max: 11,
    });
    expect(annotation.x_max).toBe(20);
  });

  it("fits and zooms the viewport around the cursor", () => {
    const fit = fitTransform(
      { width: 400, height: 200 },
      { width: 1000, height: 700 },
    );

    expect(fit.scale).toBeGreaterThan(0);

    const zoomed = zoomAtPoint(fit, { x: 500, y: 350 }, fit.scale * 1.5);
    expect(zoomed.scale).toBeCloseTo(fit.scale * 1.5);
    expect(screenToImage({ x: 500, y: 350 }, zoomed)).toEqual(
      screenToImage({ x: 500, y: 350 }, fit),
    );
  });

  it("round-trips source-image edge coordinates through arbitrary views", () => {
    const sourcePoints = [
      { x: 0, y: 0 },
      { x: 8192, y: 0 },
      { x: 0, y: 5464 },
      { x: 8192, y: 5464 },
      { x: 4096.25, y: 2732.75 },
    ];
    const transform = { scale: 7.25, offsetX: -9123.5, offsetY: 407.75 };

    for (const source of sourcePoints) {
      const restored = screenToImage(
        imageToScreen(source, transform),
        transform,
      );
      expect(restored.x).toBeCloseTo(source.x, 8);
      expect(restored.y).toBeCloseTo(source.y, 8);
    }
  });

  it("centers actual-size pixels without changing the one-to-one scale", () => {
    expect(
      actualSizeTransform(
        { width: 1600, height: 1200 },
        { width: 1200, height: 780 },
      ),
    ).toEqual({ scale: 1, offsetX: -200, offsetY: -210 });
  });
});
