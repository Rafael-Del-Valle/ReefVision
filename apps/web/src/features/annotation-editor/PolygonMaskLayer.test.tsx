import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  PolygonMaskLayer,
  polygonMaskFromPoints,
  polygonMetrics,
} from "./PolygonMaskLayer";
import type { EditorMaskAnnotation } from "./types";

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

function mockLayerBounds(layer: SVGSVGElement) {
  vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
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
}

const polygonMask: EditorMaskAnnotation = polygonMaskFromPoints(
  [
    { x: 10, y: 10 },
    { x: 30, y: 10 },
    { x: 30, y: 25 },
    { x: 10, y: 25 },
  ],
  "class-1",
  "mask-1",
);

describe("polygon mask geometry", () => {
  it("calculates polygon bounds and pixel area", () => {
    expect(
      polygonMetrics([
        { x: 10, y: 10 },
        { x: 30, y: 10 },
        { x: 30, y: 25 },
        { x: 10, y: 25 },
      ]),
    ).toEqual({
      areaPixels: 300,
      xMin: 10,
      yMin: 10,
      xMax: 30,
      yMax: 25,
    });
  });

  it("rejects incomplete polygons", () => {
    expect(() =>
      polygonMetrics([
        { x: 0, y: 0 },
        { x: 10, y: 0 },
      ]),
    ).toThrow("at least three points");
  });
});

describe("PolygonMaskLayer", () => {
  it("creates a polygon from source-image pointer coordinates", () => {
    const onCreate = vi.fn();
    render(
      <PolygonMaskLayer
        width={400}
        height={300}
        masks={[]}
        classColors={{ "class-1": "#2a9d8f" }}
        activeClassId="class-1"
        tool="polygon"
        selectedMaskIds={[]}
        onCreate={onCreate}
        onUpdate={vi.fn()}
        onSelectionChange={vi.fn()}
      />,
    );

    const layer = screen.getByTestId("polygon-mask-layer");
    mockLayerBounds(layer);
    fireEvent.pointerDown(layer, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(layer, { clientX: 30, clientY: 10 });
    fireEvent.pointerDown(layer, { clientX: 30, clientY: 25 });
    fireEvent.pointerDown(layer, { clientX: 10, clientY: 25 });
    fireEvent.keyDown(layer, { key: "Enter" });

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0]).toMatchObject({
      label_class_id: "class-1",
      geometry_kind: "polygon",
      area_pixels: 300,
      x_min: 10,
      y_min: 10,
      x_max: 30,
      y_max: 25,
    });
  });

  it("selects polygon masks and requests explicit deletion", () => {
    const onSelectionChange = vi.fn();
    const onDeleteMaskIds = vi.fn();
    render(
      <PolygonMaskLayer
        width={400}
        height={300}
        masks={[polygonMask]}
        classColors={{ "class-1": "#2a9d8f" }}
        activeClassId="class-1"
        tool="select"
        selectedMaskIds={[polygonMask.id]}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onSelectionChange={onSelectionChange}
        onDeleteMaskIds={onDeleteMaskIds}
      />,
    );

    const layer = screen.getByTestId("polygon-mask-layer");
    const polygon = layer.querySelector("polygon");
    expect(polygon).not.toBeNull();
    fireEvent.pointerDown(polygon as SVGPolygonElement);
    expect(onSelectionChange).toHaveBeenCalledWith([polygonMask.id]);

    fireEvent.keyDown(layer, { key: "Delete" });
    expect(onDeleteMaskIds).toHaveBeenCalledWith([polygonMask.id]);
  });

  it("commits a dragged polygon vertex in image coordinates", () => {
    const onUpdate = vi.fn();
    render(
      <PolygonMaskLayer
        width={400}
        height={300}
        masks={[polygonMask]}
        classColors={{ "class-1": "#2a9d8f" }}
        activeClassId="class-1"
        tool="select"
        selectedMaskIds={[polygonMask.id]}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onSelectionChange={vi.fn()}
      />,
    );

    const layer = screen.getByTestId("polygon-mask-layer");
    mockLayerBounds(layer);
    const vertex = screen.getByTestId(`mask-vertex-${polygonMask.id}-0`);
    fireEvent.pointerDown(vertex, { pointerId: 4 });
    fireEvent.pointerMove(layer, {
      pointerId: 4,
      clientX: 20,
      clientY: 20,
    });
    fireEvent.pointerUp(layer, { pointerId: 4 });

    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate.mock.calls[0][0]).toMatchObject({
      id: polygonMask.id,
      points: [
        { x: 20, y: 20 },
        { x: 30, y: 10 },
        { x: 30, y: 25 },
        { x: 10, y: 25 },
      ],
    });
  });
});
