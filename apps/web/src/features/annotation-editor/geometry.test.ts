import { describe, expect, it } from "vitest";

import {
  createBoxFromPoints,
  fitTransform,
  resizeAnnotation,
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
  });
});
