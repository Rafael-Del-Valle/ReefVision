import { describe, expect, it } from "vitest";

import {
  rotatedBoxFromDrag,
  rotatedBoxMaskFromPoints,
  rotatedBoxPoints,
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
});
