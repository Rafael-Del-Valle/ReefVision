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

  it("fully fits high-resolution camera originals and preserves cursor zoom", () => {
    const frame = { width: 720, height: 480 };
    for (const image of [
      { width: 7952, height: 5304 },
      { width: 16384, height: 9216 },
    ]) {
      const fitted = fitTransform(image, frame);
      // The former 0.1 minimum zoom clipped both of these real-world camera
      // dimensions in a narrowed editor panel.
      expect(fitted.scale).toBeLessThan(0.1);
      expect(fitted.scale).toBeGreaterThan(0);
      const topLeft = imageToScreen({ x: 0, y: 0 }, fitted);
      const bottomRight = imageToScreen(
        { x: image.width, y: image.height },
        fitted,
      );
      expect(topLeft.x).toBeGreaterThanOrEqual(0);
      expect(topLeft.y).toBeGreaterThanOrEqual(0);
      expect(bottomRight.x).toBeLessThanOrEqual(frame.width);
      expect(bottomRight.y).toBeLessThanOrEqual(frame.height);

      const cursor = { x: frame.width / 2, y: frame.height / 2 };
      const zoomed = zoomAtPoint(fitted, cursor, fitted.scale * 1.08);
      expect(zoomed.scale).toBeCloseTo(fitted.scale * 1.08);
      const sourceBefore = screenToImage(cursor, fitted);
      const sourceAfter = screenToImage(cursor, zoomed);
      expect(sourceAfter.x).toBeCloseTo(sourceBefore.x, 6);
      expect(sourceAfter.y).toBeCloseTo(sourceBefore.y, 6);
    }
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
