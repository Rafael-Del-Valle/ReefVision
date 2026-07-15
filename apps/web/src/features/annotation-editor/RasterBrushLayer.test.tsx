import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { RasterBrushLayer } from "./RasterBrushLayer";

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

function layer(): SVGSVGElement {
  return screen.getByTestId("raster-brush-layer") as unknown as SVGSVGElement;
}

function mockBounds(element: SVGSVGElement) {
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
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

describe("RasterBrushLayer", () => {
  it("commits sampled source-image coordinates after pointer release", () => {
    const onStroke = vi.fn();
    render(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="paint"
        brushRadius={10}
        onStroke={onStroke}
      />,
    );
    const canvas = layer();
    mockBounds(canvas);

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 3,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 3,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerUp(canvas, { pointerId: 3 });

    expect(onStroke).toHaveBeenCalledTimes(1);
    expect(onStroke.mock.calls[0][0]).toEqual([
      { x: 200, y: 150 },
      { x: 400, y: 300 },
    ]);
  });

  it("does not start strokes while disabled", () => {
    const onStroke = vi.fn();
    render(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="erase"
        brushRadius={10}
        disabled
        onStroke={onStroke}
      />,
    );
    const canvas = layer();
    mockBounds(canvas);
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 5,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerUp(canvas, { pointerId: 5 });
    expect(onStroke).not.toHaveBeenCalled();
  });
});
