import { describe, expect, it } from "vitest";

import {
  cullViewportItems,
  intersectsViewport,
  viewportImageBounds,
} from "./viewportCulling";

describe("dense-object viewport culling", () => {
  it("uses image coordinates and includes edge-touching boxes with padding", () => {
    const bounds = viewportImageBounds(
      { scale: 2, offsetX: -100, offsetY: -200 },
      { width: 400, height: 200 },
      20,
    );
    expect(bounds).toEqual({
      x_min: 40,
      y_min: 90,
      x_max: 260,
      y_max: 210,
    });
    expect(
      intersectsViewport(
        { x_min: 260, y_min: 150, x_max: 300, y_max: 170 },
        bounds,
      ),
    ).toBe(true);
    expect(
      intersectsViewport(
        { x_min: 261, y_min: 150, x_max: 300, y_max: 170 },
        bounds,
      ),
    ).toBe(false);
  });

  it("retains objects when viewport or imported bounds are unreliable", () => {
    expect(viewportImageBounds(null, { width: 500, height: 500 })).toBeNull();
    expect(
      viewportImageBounds(
        { scale: 0, offsetX: 0, offsetY: 0 },
        { width: 500, height: 500 },
      ),
    ).toBeNull();
    expect(
      viewportImageBounds(
        { scale: 1, offsetX: 0, offsetY: 0 },
        { width: 0, height: 500 },
      ),
    ).toBeNull();
    const bounds = viewportImageBounds(
      { scale: 1, offsetX: 0, offsetY: 0 },
      { width: 500, height: 500 },
    );
    expect(
      intersectsViewport({ x_min: NaN, y_min: 1, x_max: 2, y_max: 3 }, bounds),
    ).toBe(true);
    expect(
      intersectsViewport({ x_min: 5, y_min: 1, x_max: 2, y_max: 3 }, bounds),
    ).toBe(true);
  });

  it("limits SVG nodes for dense images without mutating or dropping saved objects", () => {
    const items = Array.from({ length: 10_000 }, (_, index) => ({
      id: `object-${index}`,
      x_min: index * 10,
      y_min: 10,
      x_max: index * 10 + 4,
      y_max: 14,
    }));
    const bounds = viewportImageBounds(
      { scale: 1, offsetX: 0, offsetY: 0 },
      { width: 100, height: 100 },
      0,
    );
    const visible = cullViewportItems(items, bounds);
    expect(visible).toHaveLength(11);
    expect(items).toHaveLength(10_000);
    expect(items[0].id).toBe("object-0");
    expect(cullViewportItems(items, null)).toBe(items);
  });
});
