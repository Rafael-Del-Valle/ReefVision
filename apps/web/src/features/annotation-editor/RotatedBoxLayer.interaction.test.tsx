import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  RotatedBoxLayer,
  rotatedBoxFromDrag,
  rotatedBoxMaskFromPoints,
  rotatedBoxPoints,
} from "./RotatedBoxLayer";

beforeAll(() => {
  Object.defineProperty(SVGElement.prototype, "setPointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(SVGElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(SVGElement.prototype, "hasPointerCapture", {
    configurable: true,
    value: vi.fn(() => true),
  });
});

function renderLayer(
  masks: ReturnType<typeof rotatedBoxFromDrag>[],
  onCreate = vi.fn(),
  onUpdate = vi.fn(),
) {
  render(
    <RotatedBoxLayer
      width={800}
      height={600}
      masks={masks}
      classColors={{ "class-1": "#2a9d8f" }}
      activeClassId="class-1"
      selectedMaskIds={masks.map((mask) => mask.id)}
      onCreate={onCreate}
      onUpdate={onUpdate}
      onSelectionChange={vi.fn()}
    />,
  );
  const canvas = screen.getByTestId(
    "rotated-box-layer",
  ) as unknown as SVGSVGElement;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  });
  return canvas;
}

describe("RotatedBoxLayer pointer integrity", () => {
  it("does not create an observation from a cancelled draw, and permits recovery", () => {
    const onCreate = vi.fn();
    const canvas = renderLayer([], onCreate);
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 1,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 1,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerCancel(canvas, { pointerId: 1 });
    expect(onCreate).not.toHaveBeenCalled();
    expect(canvas.querySelectorAll("polygon")).toHaveLength(0);

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 2,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 2,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerUp(canvas, { pointerId: 2 });
    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0]).toMatchObject({
      geometry_kind: "rotated_box",
      area_pixels: 30000,
    });
  });

  it("rejects secondary-pointer takeover, move and cancellation during draw", () => {
    const onCreate = vi.fn();
    const canvas = renderLayer([], onCreate);
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 10,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 11,
      clientX: 300,
      clientY: 225,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 11,
      clientX: 350,
      clientY: 250,
    });
    fireEvent.pointerUp(canvas, { pointerId: 11 });
    fireEvent.pointerCancel(canvas, { pointerId: 11 });
    expect(onCreate).not.toHaveBeenCalled();

    fireEvent.pointerMove(canvas, {
      pointerId: 10,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerUp(canvas, { pointerId: 10 });
    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0].points).toEqual([
      { x: 200, y: 150 },
      { x: 400, y: 150 },
      { x: 400, y: 300 },
      { x: 200, y: 300 },
    ]);
  });

  it("preserves saved source coordinates after a cancelled move, then accepts a real edit", () => {
    const original = rotatedBoxFromDrag(
      { x: 200, y: 150 },
      { x: 400, y: 300 },
      "class-1",
      "box-1",
    );
    const onUpdate = vi.fn();
    const canvas = renderLayer([original], vi.fn(), onUpdate);
    const polygon = canvas.querySelector("polygon");
    expect(polygon).not.toBeNull();
    const originalPoints = polygon?.getAttribute("points");

    fireEvent.pointerDown(polygon as SVGPolygonElement, {
      button: 0,
      pointerId: 20,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 20,
      clientX: 200,
      clientY: 125,
    });
    fireEvent.pointerCancel(canvas, { pointerId: 20 });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(canvas.querySelector("polygon")?.getAttribute("points")).toBe(
      originalPoints,
    );

    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 21,
        clientX: 150,
        clientY: 100,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 21,
      clientX: 200,
      clientY: 125,
    });
    fireEvent.pointerUp(canvas, { pointerId: 21 });
    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate.mock.calls[0][0].points).not.toEqual(original.points);
  });

  it("does not revise selected rotated boxes for clicks on move, rotation or resize handles", () => {
    const original = rotatedBoxFromDrag(
      { x: 200, y: 150 },
      { x: 400, y: 300 },
      "class-1",
      "box-1",
    );
    const onCreate = vi.fn();
    const onUpdate = vi.fn();
    const canvas = renderLayer([original], onCreate, onUpdate);
    const points = original.points;

    const polygon = canvas.querySelector("polygon") as SVGPolygonElement;
    fireEvent.pointerDown(polygon, {
      button: 0,
      pointerId: 41,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerUp(canvas, { pointerId: 41 });

    const rotation = canvas.querySelector("circle") as SVGCircleElement;
    fireEvent.pointerDown(rotation, {
      button: 0,
      pointerId: 42,
      clientX: 150,
      clientY: 62.5,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 42,
      clientX: 150,
      clientY: 62.5,
    });
    fireEvent.pointerUp(canvas, { pointerId: 42 });

    const corner = canvas.querySelector("rect") as SVGRectElement;
    fireEvent.pointerDown(corner, {
      button: 0,
      pointerId: 43,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerUp(canvas, { pointerId: 43 });

    expect(onCreate).not.toHaveBeenCalled();
    expect(onUpdate).not.toHaveBeenCalled();
    expect(original.points).toEqual(points);
    expect(canvas.querySelector("polygon")?.getAttribute("points")).toBe(
      points?.map((point) => `${point.x},${point.y}`).join(" "),
    );

    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 44,
        clientX: 150,
        clientY: 100,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 44,
      clientX: 175,
      clientY: 120,
    });
    fireEvent.pointerUp(canvas, { pointerId: 44 });
    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate.mock.calls[0][0].points).not.toEqual(original.points);
  });

  it("does not revise rotated boxes when image-edge clamping or return motion leaves geometry unchanged", () => {
    const original = rotatedBoxFromDrag(
      { x: 600, y: 200 },
      { x: 800, y: 350 },
      "class-1",
      "box-edge",
    );
    const onUpdate = vi.fn();
    const canvas = renderLayer([original], vi.fn(), onUpdate);

    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 51,
        clientX: 350,
        clientY: 135,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 51,
      clientX: 395,
      clientY: 135,
    });
    fireEvent.pointerUp(canvas, { pointerId: 51 });

    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 52,
        clientX: 350,
        clientY: 135,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 52,
      clientX: 325,
      clientY: 155,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 52,
      clientX: 350,
      clientY: 135,
    });
    fireEvent.pointerUp(canvas, { pointerId: 52 });

    expect(onUpdate).not.toHaveBeenCalled();
    expect(canvas.querySelector("polygon")?.getAttribute("points")).toBe(
      original.points?.map((point) => `${point.x},${point.y}`).join(" "),
    );
  });

  it("does not save a rotated-box edit when the browser revokes pointer capture", () => {
    const original = rotatedBoxFromDrag(
      { x: 200, y: 150 },
      { x: 400, y: 300 },
      "class-1",
      "box-1",
    );
    const onUpdate = vi.fn();
    const canvas = renderLayer([original], vi.fn(), onUpdate);
    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 30,
        clientX: 150,
        clientY: 100,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 30,
      clientX: 200,
      clientY: 125,
    });
    fireEvent.lostPointerCapture(canvas, { pointerId: 30 });
    fireEvent.pointerUp(canvas, { pointerId: 30 });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(canvas.querySelector("polygon")?.getAttribute("points")).toBe(
      original.points?.map((point) => `${point.x},${point.y}`).join(" "),
    );
  });

  it.each([
    {
      name: "NaN vertex",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[0].x = Number.NaN;
      },
    },
    {
      name: "infinite vertex",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[2].y = Number.POSITIVE_INFINITY;
      },
    },
    {
      name: "out-of-image vertex",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[1].x = 801;
      },
    },
    {
      name: "zero-area restored box",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[2] = { ...points[1] };
        points[3] = { ...points[0] };
      },
    },
    {
      name: "sheared quadrilateral",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[2].x += 40;
      },
    },
    {
      name: "nonorthogonal parallelogram",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[2].x += 40;
        points[3].x += 40;
      },
    },
    {
      name: "concave quadrilateral",
      damage: (points: Array<{ x: number; y: number }>) => {
        points[2] = { x: 230, y: 185 };
      },
    },
  ])("rejects corrupt $name and allows recovery", ({ damage }) => {
    const original = rotatedBoxFromDrag(
      { x: 200, y: 150 },
      { x: 400, y: 300 },
      "class-1",
      "imported-box",
    );
    const points = original.points!.map((point) => ({ ...point }));
    damage(points);
    const imported = { ...original, points };
    const onCreate = vi.fn();
    const onUpdate = vi.fn();
    const canvas = renderLayer([imported], onCreate, onUpdate);
    const polygon = canvas.querySelector("polygon") as SVGPolygonElement;
    const originalMarkup = polygon.getAttribute("points");

    fireEvent.pointerDown(polygon, {
      button: 0,
      pointerId: 81,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 81,
      clientX: 200,
      clientY: 125,
    });
    fireEvent.pointerUp(canvas, { pointerId: 81 });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
    expect(canvas.querySelector("polygon")?.getAttribute("points")).toBe(
      originalMarkup,
    );
    expect(imported.points).toEqual(points);
    expect(imported.area_pixels).toBeGreaterThan(4);

    // Only edits to the damaged record are blocked, not intentional new work.
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 82,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 82,
      clientX: 220,
      clientY: 160,
    });
    fireEvent.pointerUp(canvas, { pointerId: 82 });
    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("continues to edit valid angled rectangles without rewriting source geometry", () => {
    const original = rotatedBoxMaskFromPoints(
      rotatedBoxPoints({ x: 360, y: 280 }, 180, 100, Math.PI / 6),
      "class-1",
      "angled-box",
      true,
      2,
    );
    const onUpdate = vi.fn();
    const canvas = renderLayer([original], vi.fn(), onUpdate);
    fireEvent.pointerDown(
      canvas.querySelector("polygon") as SVGPolygonElement,
      {
        button: 0,
        pointerId: 90,
        clientX: 180,
        clientY: 140,
      },
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 90,
      clientX: 190,
      clientY: 150,
    });
    fireEvent.pointerUp(canvas, { pointerId: 90 });

    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate.mock.calls[0][0]).toMatchObject({
      id: "angled-box",
      geometry_kind: "rotated_box",
      persisted: true,
      revision: 2,
    });
    expect(onUpdate.mock.calls[0][0].points).not.toEqual(original.points);
    expect(original.points).toHaveLength(4);
  });
});
