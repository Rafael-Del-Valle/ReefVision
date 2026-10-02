import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { SkeletonOverlayLayer } from "./SkeletonOverlayLayer";

const context = {
  clearRect: vi.fn(),
  fillRect: vi.fn(),
  fillStyle: "",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  );
});

it("maps pointer coordinates back to source-image skeleton pixels", () => {
  const onPixelClick = vi.fn();
  render(
    <div>
      <SkeletonOverlayLayer
        width={100}
        height={50}
        pixels={[{ x: 10, y: 10 }]}
        nodes={[]}
        addedPixels={[]}
        removedPixels={[]}
        editMode="add"
        onPixelClick={onPixelClick}
      />
    </div>,
  );

  const canvas = screen.getByTestId("skeleton-overlay");
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 10,
    top: 20,
    width: 200,
    height: 100,
    right: 210,
    bottom: 120,
    x: 10,
    y: 20,
    toJSON: () => ({}),
  } as DOMRect);

  fireEvent.pointerDown(canvas, {
    clientX: 110,
    clientY: 70,
  });

  expect(onPixelClick).toHaveBeenCalledWith({ x: 50, y: 25 });
});

it("is non-interactive in view mode while still drawing the skeleton", () => {
  const onPixelClick = vi.fn();
  render(
    <SkeletonOverlayLayer
      width={20}
      height={10}
      pixels={[
        { x: 2, y: 2 },
        { x: 3, y: 2 },
      ]}
      nodes={[
        {
          id: "endpoint-0001",
          kind: "endpoint",
          x: 2,
          y: 2,
          source_pixel_count: 1,
          external_connection_count: 1,
        },
      ]}
      addedPixels={[{ x: 4, y: 2 }]}
      removedPixels={[{ x: 2, y: 2 }]}
      editMode="view"
      onPixelClick={onPixelClick}
    />,
  );

  const canvas = screen.getByTestId("skeleton-overlay");
  expect(canvas).toHaveStyle({ pointerEvents: "none" });
  expect(context.fillRect).toHaveBeenCalled();
  fireEvent.pointerDown(canvas, { clientX: 5, clientY: 5 });
  expect(onPixelClick).not.toHaveBeenCalled();
});
