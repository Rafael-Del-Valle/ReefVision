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
  it("discards a cancelled brush stroke and supports the next intentional stroke", () => {
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
      pointerId: 11,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 11,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerCancel(canvas, { pointerId: 11 });
    expect(onStroke).not.toHaveBeenCalled();
    expect(canvas.querySelector("polyline")).toBeNull();

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 12,
      clientX: 50,
      clientY: 50,
    });
    fireEvent.pointerUp(canvas, { pointerId: 12 });
    expect(onStroke).toHaveBeenCalledTimes(1);
    expect(onStroke.mock.calls[0][0]).toEqual([{ x: 100, y: 100 }]);
  });

  it("prevents competing pointers from replacing or finishing an active brush stroke", () => {
    const onStroke = vi.fn();
    render(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="erase"
        brushRadius={10}
        onStroke={onStroke}
      />,
    );
    const canvas = layer();
    mockBounds(canvas);
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 21,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 22,
      clientX: 350,
      clientY: 250,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 22,
      clientX: 300,
      clientY: 200,
    });
    fireEvent.pointerUp(canvas, { pointerId: 22 });
    fireEvent.pointerCancel(canvas, { pointerId: 22 });
    expect(onStroke).not.toHaveBeenCalled();

    fireEvent.pointerMove(canvas, {
      pointerId: 21,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerUp(canvas, { pointerId: 21 });
    expect(onStroke).toHaveBeenCalledTimes(1);
    expect(onStroke.mock.calls[0][0]).toEqual([
      { x: 200, y: 150 },
      { x: 300, y: 200 },
    ]);
  });

  it("drops a brush preview when the browser revokes pointer capture", () => {
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
      pointerId: 31,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.lostPointerCapture(canvas, { pointerId: 31 });
    fireEvent.pointerUp(canvas, { pointerId: 31 });
    expect(onStroke).not.toHaveBeenCalled();

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 32,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerUp(canvas, { pointerId: 32 });
    expect(onStroke).toHaveBeenCalledTimes(1);
  });

  it("retains the original paint mode and radius during a mid-stroke tool change", () => {
    const onStroke = vi.fn();
    const { rerender } = render(
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
      pointerId: 41,
      clientX: 100,
      clientY: 75,
    });

    rerender(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="erase"
        brushRadius={40}
        onStroke={onStroke}
      />,
    );
    expect(canvas.querySelector("circle")).toHaveAttribute("r", "10");
    expect(canvas.querySelector("circle")).toHaveAttribute(
      "fill",
      "rgba(87, 204, 153, 0.35)",
    );
    fireEvent.pointerMove(canvas, {
      pointerId: 41,
      clientX: 200,
      clientY: 150,
    });
    fireEvent.pointerUp(canvas, { pointerId: 41 });
    expect(onStroke).toHaveBeenCalledWith(
      [
        { x: 200, y: 150 },
        { x: 400, y: 300 },
      ],
      { mode: "paint", brushRadius: 10 },
    );
  });

  it("signals a cancelled stroke without recording it and permits later recovery", () => {
    const onStroke = vi.fn();
    const onStrokeStart = vi.fn();
    const onStrokeCancel = vi.fn();
    render(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="erase"
        brushRadius={15}
        onStroke={onStroke}
        onStrokeStart={onStrokeStart}
        onStrokeCancel={onStrokeCancel}
      />,
    );
    const canvas = layer();
    mockBounds(canvas);
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 42,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerCancel(canvas, { pointerId: 42 });
    expect(onStrokeStart).toHaveBeenCalledTimes(1);
    expect(onStrokeCancel).toHaveBeenCalledTimes(1);
    expect(onStroke).not.toHaveBeenCalled();

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 43,
      clientX: 150,
      clientY: 100,
    });
    fireEvent.pointerUp(canvas, { pointerId: 43 });
    expect(onStrokeStart).toHaveBeenCalledTimes(2);
    expect(onStroke).toHaveBeenCalledWith(
      [{ x: 300, y: 200 }],
      { mode: "erase", brushRadius: 15 },
    );
  });

  it("does not misclassify intentional capture release as stroke cancellation", () => {
    const onStroke = vi.fn();
    const onStrokeCancel = vi.fn();
    render(
      <RasterBrushLayer
        width={800}
        height={600}
        mode="paint"
        brushRadius={10}
        onStroke={onStroke}
        onStrokeCancel={onStrokeCancel}
      />,
    );
    const canvas = layer();
    mockBounds(canvas);
    Object.defineProperty(canvas, "releasePointerCapture", {
      configurable: true,
      value: vi.fn((pointerId: number) => {
        fireEvent.lostPointerCapture(canvas, { pointerId });
      }),
    });
    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 44,
      clientX: 100,
      clientY: 75,
    });
    fireEvent.pointerUp(canvas, { pointerId: 44 });
    expect(onStrokeCancel).not.toHaveBeenCalled();
    expect(onStroke).toHaveBeenCalledTimes(1);
    expect(onStroke).toHaveBeenCalledWith(
      [{ x: 200, y: 150 }],
      { mode: "paint", brushRadius: 10 },
    );
  });
});
