import { describe, expect, it } from "vitest";

import {
  cullViewportItems,
  cullViewportMasks,
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

  it("culls dense masks without dropping uncertain geometry", () => {
    const masks = Array.from({ length: 10_000 }, (_, index) => ({
      id: `mask-${index}`,
      x_min: index * 10,
      y_min: 10,
      x_max: index * 10 + 4,
      y_max: 14,
    }));
    const legacy = {
      id: "legacy-mask",
      x_min: null,
      y_min: null,
      x_max: null,
      y_max: null,
    };
    const malformed = {
      id: "malformed-mask",
      x_min: NaN,
      y_min: 10,
      x_max: 20,
      y_max: 14,
    };
    const imported = [...masks, legacy, malformed];
    const bounds = viewportImageBounds(
      { scale: 1, offsetX: 0, offsetY: 0 },
      { width: 100, height: 100 },
      0,
    );

    const visible = cullViewportMasks(imported, bounds);
    expect(visible).toHaveLength(13);
    expect(visible.map((mask) => mask.id)).toContain("mask-10");
    expect(visible.map((mask) => mask.id)).not.toContain("mask-11");
    expect(visible).toContain(legacy);
    expect(visible).toContain(malformed);
    expect(imported).toHaveLength(10_002);
    expect(imported[9]).toBe(masks[9]);
    expect(cullViewportMasks(imported, null)).toBe(imported);

    // A corrupt imported null cannot be drawn; other records must survive.
    const withNull = [null, ...imported] as unknown as typeof imported;
    expect(cullViewportMasks(withNull, null)).toEqual(imported);
    expect(cullViewportMasks(withNull, bounds)).toEqual(visible);
  });

  it("keeps touching and incomplete raster masks", () => {
    const bounds = { x_min: 10, y_min: 20, x_max: 30, y_max: 40 };
    const touching = {
      x_min: 30,
      y_min: 25,
      x_max: 50,
      y_max: 35,
    };
    const outside = {
      x_min: 31,
      y_min: 25,
      x_max: 50,
      y_max: 35,
    };
    const incomplete = {
      x_min: 31,
      y_min: null,
      x_max: 50,
      y_max: 35,
    };
    const items = [touching, outside, incomplete];
    expect(cullViewportMasks(items, bounds)).toEqual([touching, incomplete]);
    expect(cullViewportMasks(items, { ...bounds, x_max: 10 })).toBe(items);
  });
  it("culls dense polygon overlays using vertices when saved bounds are absent", () => {
    const polygons = Array.from({ length: 10_000 }, (_, index) => ({
      id: `polygon-${index}`,
      geometry_kind: "polygon",
      points: [
        { x: index * 10, y: 10 },
        { x: index * 10 + 4, y: 10 },
        { x: index * 10 + 4, y: 14 },
      ],
      x_min: null,
      y_min: null,
      x_max: null,
      y_max: null,
    }));
    const bounds = { x_min: 0, y_min: 0, x_max: 100, y_max: 100 };
    const visible = cullViewportMasks(polygons, bounds);
    expect(visible).toHaveLength(11);
    expect(visible[10]).toBe(polygons[10]);
    expect(polygons).toHaveLength(10_000);
    expect(polygons[999].x_min).toBeNull();
    expect(cullViewportMasks(polygons, null)).toBe(polygons);
  });

  it("trusts drawn polygon vertices over stale bounds and keeps invalid geometry", () => {
    const bounds = { x_min: 0, y_min: 0, x_max: 100, y_max: 100 };
    const pointsInside = [
      { x: 5, y: 5 },
      { x: 15, y: 5 },
      { x: 15, y: 15 },
    ];
    const pointsOutside = [
      { x: 200, y: 5 },
      { x: 215, y: 5 },
      { x: 215, y: 15 },
    ];
    const visibleDespiteStaleBounds = {
      geometry_kind: "polygon",
      points: pointsInside,
      x_min: 200,
      y_min: 200,
      x_max: 215,
      y_max: 215,
    };
    const hiddenDespiteStaleBounds = {
      geometry_kind: "polygon",
      points: pointsOutside,
      x_min: 0,
      y_min: 0,
      x_max: 15,
      y_max: 15,
    };
    const malformed = {
      geometry_kind: "polygon",
      points: [{ x: NaN, y: 0 }, ...pointsOutside.slice(1)],
      x_min: 200,
      y_min: 0,
      x_max: 215,
      y_max: 15,
    };
    const rasterWithUnreliableBounds = {
      geometry_kind: "raster_mask",
      mask_path: "mask.png",
      points: pointsOutside,
      x_min: null,
      y_min: null,
      x_max: null,
      y_max: null,
    };
    const rasterOutside = {
      ...rasterWithUnreliableBounds,
      x_min: 200,
      y_min: 0,
      x_max: 215,
      y_max: 15,
    };
    const masks = [
      visibleDespiteStaleBounds,
      hiddenDespiteStaleBounds,
      malformed,
      rasterWithUnreliableBounds,
      rasterOutside,
    ];
    expect(cullViewportMasks(masks, bounds)).toEqual([
      visibleDespiteStaleBounds,
      malformed,
      rasterWithUnreliableBounds,
    ]);
    expect(masks[0]).toBe(visibleDespiteStaleBounds);
    expect(masks[1]).toBe(hiddenDespiteStaleBounds);
  });
});
