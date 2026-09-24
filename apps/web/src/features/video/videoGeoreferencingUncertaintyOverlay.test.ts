import { describe, expect, it } from "vitest";

import { projectHorizontal95Radius } from "./videoGeoreferencingUncertaintyOverlay";

const points = [
  { latitude_deg: 32.75, longitude_deg: -79.93 },
  { latitude_deg: 32.751, longitude_deg: -79.929 },
];

const center = { x: 320, y: 180 };
const viewport = { width: 640, height: 360, padding: 36 };

function project(radius: number | null | undefined) {
  return projectHorizontal95Radius(points, 32.75, radius, center, viewport);
}

describe("Task 17E geographic uncertainty overlay", () => {
  it("uses separate horizontal and vertical geographic scales", () => {
    const result = project(10);

    expect(result).not.toBeNull();
    expect(result?.radiusMeters).toBe(10);
    expect(result?.cx).toBe(320);
    expect(result?.cy).toBe(180);
    expect(result?.rx).toBeGreaterThan(0);
    expect(result?.ry).toBeGreaterThan(0);
    expect(result?.rx).not.toBeCloseTo(result?.ry ?? 0);
  });

  it("scales geometry linearly with the supplied radius", () => {
    const five = project(5);
    const ten = project(10);

    expect(ten?.rx).toBeCloseTo((five?.rx ?? 0) * 2);
    expect(ten?.ry).toBeCloseTo((five?.ry ?? 0) * 2);
  });

  it("does not invent a radius when none is supplied", () => {
    for (const radius of [
      null,
      undefined,
      0,
      -1,
      Number.NaN,
      Number.POSITIVE_INFINITY,
    ]) {
      expect(project(radius)).toBeNull();
    }
  });

  it("does not use a fabricated single-observation map extent", () => {
    expect(
      projectHorizontal95Radius([points[0]], 32.75, 10, center, viewport),
    ).toBeNull();
  });

  it("rejects an antimeridian-crossing extent the map cannot represent", () => {
    expect(
      projectHorizontal95Radius(
        [
          { latitude_deg: 0, longitude_deg: 179.99 },
          { latitude_deg: 0.001, longitude_deg: -179.99 },
        ],
        0,
        10,
        center,
        viewport,
      ),
    ).toBeNull();
  });
});
