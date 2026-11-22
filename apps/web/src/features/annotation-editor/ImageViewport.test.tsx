import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ImageViewport } from "./ImageViewport";

describe("ImageViewport", () => {
  it("updates the viewport transform without rerendering unchanged scientific layers", () => {
    const renders = vi.fn();
    function HeavyScientificLayer() {
      renders();
      return <svg data-testid="heavy-scientific-layer" />;
    }
    render(
      <ImageViewport width={8192} height={6144} label="Large image viewport">
        <HeavyScientificLayer />
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Large image viewport" });

    fireEvent.wheel(frame, { deltaY: -100, clientX: 300, clientY: 250 });
    fireEvent.wheel(frame, { deltaY: -100, clientX: 310, clientY: 260 });

    expect(screen.getByTestId("heavy-scientific-layer")).toBeInTheDocument();
    expect(renders).toHaveBeenCalledTimes(1);
  });

  it("temporarily pans overlays without changing their source geometry", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Mask viewport">
        <svg data-testid="scientific-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Mask viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("scientific-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");
    const initial = transform.style.transform;

    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      clientX: 50,
      clientY: 60,
    });
    fireEvent.pointerMove(window, { clientX: 90, clientY: 110 });

    expect(transform.style.transform).not.toBe(initial);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("zooms around the pointer and exposes fit, actual size, and reset", async () => {
    render(
      <ImageViewport width={1600} height={1200} label="Raster viewport">
        <div />
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Raster viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const initial = transform.style.transform;

    fireEvent.wheel(frame, { deltaY: -100, clientX: 300, clientY: 250 });
    expect(transform.style.transform).not.toBe(initial);
    await userEvent.click(
      screen.getByRole("button", { name: "Actual Size (100%)" }),
    );
    expect(transform.style.transform).toContain("scale(1)");
    await userEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(transform.style.transform).not.toContain("scale(1)");
    await userEvent.click(screen.getByRole("button", { name: "Fit to View" }));
    expect(transform.style.transform).not.toContain("scale(1)");
  });

  it("isolates active panning from a second pointer and its release", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Multi-pointer viewport">
        <svg aria-label="Retained biological annotation">
          <rect x="10" y="20" width="30" height="40" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Multi-pointer viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const original = transform.style.transform;

    fireEvent.pointerDown(frame, {
      pointerId: 7,
      button: 0,
      altKey: true,
      clientX: 10,
      clientY: 20,
    });
    fireEvent.pointerDown(frame, {
      pointerId: 8,
      button: 0,
      altKey: true,
      clientX: 300,
      clientY: 400,
    });
    fireEvent.pointerMove(window, {
      pointerId: 8,
      clientX: 800,
      clientY: 900,
    });
    fireEvent.pointerUp(window, { pointerId: 8 });
    expect(transform.style.transform).toBe(original);

    fireEvent.pointerMove(window, {
      pointerId: 7,
      clientX: 50,
      clientY: 60,
    });
    const afterPrimaryMove = transform.style.transform;
    expect(afterPrimaryMove).not.toBe(original);
    fireEvent.pointerMove(window, {
      pointerId: 8,
      clientX: 900,
      clientY: 900,
    });
    expect(transform.style.transform).toBe(afterPrimaryMove);

    fireEvent.pointerUp(window, { pointerId: 7 });
    fireEvent.pointerMove(window, {
      pointerId: 7,
      clientX: 120,
      clientY: 150,
    });
    expect(transform.style.transform).toBe(afterPrimaryMove);
    expect(
      screen
        .getByLabelText("Retained biological annotation")
        .querySelector("rect"),
    ).toHaveAttribute("x", "10");
  });

  it("ignores foreign pointer cancellation but cancels on active pointer or window blur", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Pointer cancel viewport">
        <svg />
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Pointer cancel viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");

    fireEvent.pointerDown(frame, {
      pointerId: 1,
      button: 1,
      clientX: 20,
      clientY: 20,
    });
    fireEvent.pointerCancel(window, { pointerId: 2 });
    const beforeMove = transform.style.transform;
    fireEvent.pointerMove(window, {
      pointerId: 1,
      clientX: 40,
      clientY: 40,
    });
    expect(transform.style.transform).not.toBe(beforeMove);
    const afterMove = transform.style.transform;

    fireEvent.pointerCancel(window, { pointerId: 1 });
    fireEvent.pointerMove(window, {
      pointerId: 1,
      clientX: 90,
      clientY: 90,
    });
    expect(transform.style.transform).toBe(afterMove);

    fireEvent.pointerDown(frame, {
      pointerId: 3,
      button: 1,
      clientX: 10,
      clientY: 10,
    });
    fireEvent.blur(window);
    fireEvent.pointerMove(window, {
      pointerId: 3,
      clientX: 200,
      clientY: 200,
    });
    expect(transform.style.transform).toBe(afterMove);
  });

  it("keeps wheel zoom while dragging and pans from the latest pointer position", () => {
    render(
      <ImageViewport
        width={1600}
        height={1200}
        label="Zoom during pan viewport"
      >
        <svg aria-label="Preserved image annotations">
          <rect x="10" y="20" width="30" height="40" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Zoom during pan viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const readTransform = () => {
      const match = transform.style.transform.match(
        /^translate\(([-+\d.e]+)px, ([-+\d.e]+)px\) scale\(([-+\d.e]+)\)$/,
      );
      if (!match) throw new Error("Invalid viewport transform");
      return match.slice(1).map(Number);
    };

    fireEvent.pointerDown(frame, {
      pointerId: 12,
      button: 1,
      clientX: 20,
      clientY: 30,
    });
    fireEvent.pointerMove(window, {
      pointerId: 12,
      clientX: 40,
      clientY: 50,
    });
    const beforeZoom = readTransform();
    fireEvent.wheel(frame, {
      deltaY: -100,
      clientX: 200,
      clientY: 180,
    });
    const zoomed = readTransform();
    expect(zoomed[2]).toBeGreaterThan(beforeZoom[2]);

    fireEvent.pointerMove(window, {
      pointerId: 12,
      clientX: 55,
      clientY: 75,
    });
    const moved = readTransform();
    expect(moved[0]).toBeCloseTo(zoomed[0] + 15, 8);
    expect(moved[1]).toBeCloseTo(zoomed[1] + 25, 8);
    expect(moved[2]).toBe(zoomed[2]);

    fireEvent.click(screen.getByRole("button", { name: "Fit to View" }));
    const fitted = transform.style.transform;
    fireEvent.pointerMove(window, {
      pointerId: 12,
      clientX: 100,
      clientY: 110,
    });
    expect(transform.style.transform).toBe(fitted);
    expect(
      screen
        .getByLabelText("Preserved image annotations")
        .querySelector("rect"),
    ).toHaveAttribute("x", "10");
  });

  it("preserves Alt-modified polygon vertex gestures", () => {
    const onPointerDown = vi.fn();
    render(
      <ImageViewport width={1600} height={1200} label="Polygon viewport">
        <svg viewBox="0 0 1600 1200">
          <circle
            data-testid="polygon-vertex"
            cx="10"
            cy="10"
            r="5"
            onPointerDown={onPointerDown}
          />
        </svg>
      </ImageViewport>,
    );

    fireEvent.pointerDown(screen.getByTestId("polygon-vertex"), {
      button: 0,
      altKey: true,
    });

    expect(onPointerDown).toHaveBeenCalledTimes(1);
  });

  it("ignores horizontal-only and invalid wheel input without shifting scientific overlays", () => {
    render(
      <ImageViewport
        width={1600}
        height={1200}
        label="Wheel integrity viewport"
      >
        <svg aria-label="Original scientific polygon">
          <polygon points="10,10 30,10 20,30" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Wheel integrity viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const original = transform.style.transform;
    const polygon = screen
      .getByLabelText("Original scientific polygon")
      .querySelector("polygon");

    fireEvent.wheel(frame, {
      deltaX: 150,
      deltaY: 0,
      clientX: 100,
      clientY: 100,
    });
    // Override an already-created DOM event: WebIDL constructors can reject
    // nonfinite numeric initialization before the React handler sees it.
    const invalidDelta = createEvent.wheel(frame, {
      deltaY: -100,
      clientX: 100,
      clientY: 100,
    });
    Object.defineProperty(invalidDelta, "deltaY", { value: Infinity });
    fireEvent(frame, invalidDelta);
    const invalidFocus = createEvent.wheel(frame, {
      deltaY: -100,
      clientX: 100,
      clientY: 100,
    });
    Object.defineProperty(invalidFocus, "clientX", { value: Infinity });
    fireEvent(frame, invalidFocus);
    expect(transform.style.transform).toBe(original);
    expect(polygon).toHaveAttribute("points", "10,10 30,10 20,30");

    fireEvent.wheel(frame, {
      deltaY: -100,
      clientX: 100,
      clientY: 100,
    });
    expect(transform.style.transform).not.toBe(original);
    expect(polygon).toHaveAttribute("points", "10,10 30,10 20,30");
  });

  it("rejects invalid pointer origins and movements but recovers on valid input", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Pan integrity viewport">
        <svg aria-label="Original coral coordinates">
          <rect x="4" y="7" width="9" height="12" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Pan integrity viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const initial = transform.style.transform;

    const invalidStart = createEvent.pointerDown(frame, {
      pointerId: 1,
      button: 1,
      clientX: 10,
      clientY: 10,
    });
    Object.defineProperty(invalidStart, "clientX", { value: Infinity });
    fireEvent(frame, invalidStart);
    fireEvent.pointerMove(window, {
      pointerId: 1,
      clientX: 40,
      clientY: 40,
    });
    expect(transform.style.transform).toBe(initial);

    fireEvent.pointerDown(frame, {
      pointerId: 2,
      button: 1,
      clientX: 10,
      clientY: 20,
    });
    const invalidMove = createEvent.pointerMove(window, {
      pointerId: 2,
      clientX: 30,
      clientY: 40,
    });
    Object.defineProperty(invalidMove, "clientX", { value: NaN });
    fireEvent(window, invalidMove);
    expect(transform.style.transform).toBe(initial);
    fireEvent.pointerMove(window, {
      pointerId: 2,
      clientX: 40,
      clientY: 50,
    });
    expect(transform.style.transform).not.toBe(initial);
    expect(
      screen.getByLabelText("Original coral coordinates").querySelector("rect"),
    ).toHaveAttribute("x", "4");
  });

  it.each([
    [0, 1200],
    [1600, 0],
    [-1, 1200],
    [1.5, 1200],
    [Number.NaN, 1200],
    [1600, Number.POSITIVE_INFINITY],
  ])(
    "does not expose editable biological overlays for invalid image size %s x %s",
    (width, height) => {
      render(
        <ImageViewport
          width={width}
          height={height}
          label="Invalid metadata viewport"
        >
          <svg data-testid="source-pixel-annotations">
            <rect x="4" y="7" width="9" height="12" />
          </svg>
        </ImageViewport>,
      );
      const frame = screen.getByRole("region", {
        name: "Invalid metadata viewport",
      });
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Annotation editing is paused",
      );
      expect(screen.queryByTestId("source-pixel-annotations")).toBeNull();
      expect(screen.queryByTestId("image-viewport-transform")).toBeNull();
      expect(
        screen.getByRole("button", { name: "Fit to View" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Actual Size (100%)" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Reset View" }),
      ).toBeDisabled();
      fireEvent.wheel(frame, {
        deltaY: -100,
        clientX: 100,
        clientY: 100,
      });
      fireEvent.pointerDown(frame, {
        pointerId: 23,
        button: 1,
        clientX: 10,
        clientY: 10,
      });
      fireEvent.pointerMove(window, {
        pointerId: 23,
        clientX: 100,
        clientY: 100,
      });
      expect(screen.queryByTestId("image-viewport-transform")).toBeNull();
    },
  );

  it("recovers only after valid image metadata and discards stale pan state", () => {
    const source = (
      <svg aria-label="Unchanged source coordinates">
        <polygon points="10,10 30,10 20,30" />
      </svg>
    );
    const { rerender } = render(
      <ImageViewport width={1600} height={1200} label="Metadata recovery">
        {source}
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Metadata recovery" });
    fireEvent.pointerDown(frame, {
      pointerId: 45,
      button: 1,
      clientX: 20,
      clientY: 20,
    });
    rerender(
      <ImageViewport width={0} height={1200} label="Metadata recovery">
        {source}
      </ImageViewport>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByLabelText("Unchanged source coordinates")).toBeNull();
    fireEvent.pointerMove(window, {
      pointerId: 45,
      clientX: 100,
      clientY: 200,
    });

    rerender(
      <ImageViewport width={1600} height={1200} label="Metadata recovery">
        {source}
      </ImageViewport>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    const transform = screen.getByTestId("image-viewport-transform");
    const restored = transform.style.transform;
    expect(restored).not.toMatch(/NaN|Infinity/);
    expect(
      screen
        .getByLabelText("Unchanged source coordinates")
        .querySelector("polygon"),
    ).toHaveAttribute("points", "10,10 30,10 20,30");
    fireEvent.pointerMove(window, {
      pointerId: 45,
      clientX: 200,
      clientY: 400,
    });
    expect(transform.style.transform).toBe(restored);
    fireEvent.wheel(frame, {
      deltaY: -100,
      clientX: 100,
      clientY: 100,
    });
    expect(transform.style.transform).not.toBe(restored);
    expect(
      screen
        .getByLabelText("Unchanged source coordinates")
        .querySelector("polygon"),
    ).toHaveAttribute("points", "10,10 30,10 20,30");
  });

});
