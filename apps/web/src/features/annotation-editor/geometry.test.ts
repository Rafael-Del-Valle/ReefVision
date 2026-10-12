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
