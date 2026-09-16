import { describe, expect, it } from "vitest";

import {
  rotatedBoxFitsImage,
  rotatedBoxFromAnnotation,
  rotatedBoxFromDrag,
  rotatedBoxMaskFromPoints,
  rotatedBoxPoints,
  rotationAngleForPoint,
} from "./RotatedBoxLayer";

describe("rotated box geometry", () => {
  it("creates a four-corner oriented geometry record", () => {
    const box = rotatedBoxFromDrag(
      { x: 10, y: 20 },
      { x: 50, y: 60 },
      "class-1",
      "box-1",
    );
    expect(box.geometry_kind).toBe("rotated_box");
    expect(box.points).toHaveLength(4);
    expect(box.area_pixels).toBe(1600);
  });

  it("preserves width and height after rotation", () => {
    const points = rotatedBoxPoints({ x: 100, y: 100 }, 40, 20, Math.PI / 4);
    const mask = rotatedBoxMaskFromPoints(points, "class-1", "box-1", false);
    const [first, second, third] = mask.points ?? [];
    expect(Math.hypot(second.x - first.x, second.y - first.y)).toBeCloseTo(40);
    expect(Math.hypot(third.x - second.x, third.y - second.y)).toBeCloseTo(20);
  });

  it("promotes a normal box to same-size rotated geometry only when rotation is used", () => {
    const annotation = {
      id: "annotation-1",
      label_class_id: "class-1",
      x_min: 20,
      y_min: 30,
      x_max: 120,
      y_max: 80,
    };
    const angle = Math.PI / 6;
    const box = rotatedBoxFromAnnotation(annotation, angle, "rotated-1");
    const points = box.points ?? [];
    expect(points).toHaveLength(4);
    expect(box.geometry_kind).toBe("rotated_box");
    expect(box.label_class_id).toBe("class-1");
    expect(Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y)).toBeCloseTo(100);
    expect(Math.hypot(points[2].x - points[1].x, points[2].y - points[1].y)).toBeCloseTo(50);
    expect(rotatedBoxFitsImage(points, 200, 200)).toBe(true);
  });

  it("treats the top-center rotation handle as zero degrees", () => {
    const center = { x: 100, y: 100 };
    expect(rotationAngleForPoint(center, { x: 100, y: 50 })).toBeCloseTo(0);
    expect(rotationAngleForPoint(center, { x: 150, y: 100 })).toBeCloseTo(
      Math.PI / 2,
    );
  });
});
