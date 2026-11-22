import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fitTransform } from "./geometry";
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

  it("refits on desktop resize when a registered WebView2 observer stops notifying", () => {
    let observations = 0;
    let disconnects = 0;
    class SilentResizeObserver {
      constructor(_callback: ResizeObserverCallback) {}
      observe() {
        observations += 1;
      }
      disconnect() {
        disconnects += 1;
      }
    }
    vi.stubGlobal("ResizeObserver", SilentResizeObserver);
    const removedListeners = vi.spyOn(window, "removeEventListener");
    try {
      const dimensions = { width: 960, height: 640 };
      const { unmount } = render(
        <ImageViewport
          width={1600}
          height={1200}
          label="Silent observer camera"
        >
          <svg data-testid="silent-observer-overlay" viewBox="0 0 1600 1200">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      const frame = screen.getByRole("region", {
        name: "Silent observer camera",
      });
      Object.defineProperty(frame, "clientWidth", {
        configurable: true,
        get: () => dimensions.width,
      });
      Object.defineProperty(frame, "clientHeight", {
        configurable: true,
        get: () => dimensions.height,
      });
      const transform = screen.getByTestId("image-viewport-transform");
      const polygon = screen
        .getByTestId("silent-observer-overlay")
        .querySelector("polygon");
      const originalPoints = polygon?.getAttribute("points");
      expect(observations).toBe(1);

      // ResizeObserver.observe succeeded but never delivered a callback.
      // Window resizing alone must measure and fit the initial camera image.
      fireEvent.resize(window);
      expect(transform.style.transform).toContain(
        `scale(${fitTransform({ width: 1600, height: 1200 }, dimensions).scale})`,
      );

      // A scientist's manual zoom must survive a second desktop resize.
      fireEvent.wheel(frame, { deltaY: -120, clientX: 480, clientY: 320 });
      const manuallyZoomedScale =
        transform.style.transform.match(/scale\(([^)]+)\)/)?.[1];
      expect(manuallyZoomedScale).toBeDefined();
      dimensions.width = 1100;
      dimensions.height = 720;
      fireEvent.resize(window);
      expect(transform.style.transform).toContain(
        `scale(${manuallyZoomedScale})`,
      );
      expect(polygon).toHaveAttribute("points", originalPoints);

      unmount();
      expect(disconnects).toBe(1);
      // The fallback must not accumulate listeners after switching images.
      expect(removedListeners).toHaveBeenCalledWith(
        "resize",
        expect.any(Function),
      );
    } finally {
      removedListeners.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("refits on visual viewport resize without changing annotated pixels", () => {
    // Embedded WebView2 may emit only visualViewport.resize after a desktop
    // scale change. A registered but silent ResizeObserver cannot help.
    class SilentResizeObserver {
      constructor(_callback: ResizeObserverCallback) {}
      observe() {}
      disconnect() {}
    }
    const visualViewport = new EventTarget();
    const removeListener = vi.spyOn(visualViewport, "removeEventListener");
    vi.stubGlobal("visualViewport", visualViewport);
    vi.stubGlobal("ResizeObserver", SilentResizeObserver);
    try {
      const dimensions = { width: 940, height: 620 };
      const { unmount } = render(
        <ImageViewport width={1600} height={1200} label="Visual viewport camera">
          <svg data-testid="visual-viewport-overlay" viewBox="0 0 1600 1200">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      const frame = screen.getByRole("region", {
        name: "Visual viewport camera",
      });
      Object.defineProperty(frame, "clientWidth", {
        configurable: true,
        get: () => dimensions.width,
      });
      Object.defineProperty(frame, "clientHeight", {
        configurable: true,
        get: () => dimensions.height,
      });
      const transform = screen.getByTestId("image-viewport-transform");
      const polygon = screen
        .getByTestId("visual-viewport-overlay")
        .querySelector("polygon");
      const sourcePoints = polygon?.getAttribute("points");

      // No window.resize event: VisualViewport alone must refit first-open.
      act(() => {
        visualViewport.dispatchEvent(new Event("resize"));
      });
      expect(transform.style.transform).toContain(
        `scale(${fitTransform({ width: 1600, height: 1200 }, dimensions).scale})`,
      );
      fireEvent.wheel(frame, { deltaY: -120, clientX: 470, clientY: 310 });
      const manualScale =
        transform.style.transform.match(/scale\(([^)]+)\)/)?.[1];
      expect(manualScale).toBeDefined();

      dimensions.width = 1120;
      dimensions.height = 740;
      act(() => {
        visualViewport.dispatchEvent(new Event("resize"));
      });
      expect(transform.style.transform).toContain(`scale(${manualScale})`);
      expect(polygon).toHaveAttribute("points", sourcePoints);

      unmount();
      expect(removeListener).toHaveBeenCalledWith(
        "resize",
        expect.any(Function),
      );
    } finally {
      removeListener.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("falls back to window resizing when WebView2 exposes no usable ResizeObserver", () => {
    // A property-existence check is insufficient: some desktop webviews
    // expose ResizeObserver as undefined while starting the first image.
    vi.stubGlobal("ResizeObserver", undefined);
    try {
      const dimensions = { width: 960, height: 640 };
      const { unmount } = render(
        <ImageViewport width={1600} height={1200} label="Fallback image">
          <svg data-testid="fallback-overlay" viewBox="0 0 1600 1200">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      const frame = screen.getByRole("region", { name: "Fallback image" });
      Object.defineProperty(frame, "clientWidth", {
        configurable: true,
        get: () => dimensions.width,
      });
      Object.defineProperty(frame, "clientHeight", {
        configurable: true,
        get: () => dimensions.height,
      });
      const transform = screen.getByTestId("image-viewport-transform");
      const polygon = screen
        .getByTestId("fallback-overlay")
        .querySelector("polygon");
      const originalPoints = polygon?.getAttribute("points");

      fireEvent.resize(window);
      const expectedFit = fitTransform(
        { width: 1600, height: 1200 },
        dimensions,
      );
      expect(transform.style.transform).toContain(
        `scale(${expectedFit.scale})`,
      );

      fireEvent.wheel(frame, { deltaY: -120, clientX: 480, clientY: 320 });
      const manualScale =
        transform.style.transform.match(/scale\(([^)]+)\)/)?.[1];
      expect(manualScale).toBeDefined();
      dimensions.width = 1100;
      dimensions.height = 720;
      fireEvent.resize(window);
      expect(transform.style.transform).toContain(`scale(${manualScale})`);
      expect(polygon).toHaveAttribute("points", originalPoints);
      unmount();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it.each(["constructor", "observe", "observe-and-disconnect"] as const)(
    "falls back to window resize when WebView2 ResizeObserver %s throws",
    (failure) => {
      let disconnects = 0;
      class BrokenResizeObserver {
        constructor(_callback: ResizeObserverCallback) {
          if (failure === "constructor") {
            throw new Error("ResizeObserver initialization unavailable");
          }
        }
        observe() {
          if (failure !== "constructor") {
            throw new Error("ResizeObserver.observe unavailable");
          }
        }
        disconnect() {
          disconnects += 1;
          if (failure === "observe-and-disconnect") {
            throw new Error("ResizeObserver.disconnect unavailable");
          }
        }
      }
      vi.stubGlobal("ResizeObserver", BrokenResizeObserver);
      try {
        const dimensions = { width: 920, height: 580 };
        const { unmount } = render(
          <ImageViewport width={1600} height={1200} label="Broken observer">
            <svg data-testid="broken-observer-overlay" viewBox="0 0 1600 1200">
              <polygon points="10,20 40,20 40,60" />
            </svg>
          </ImageViewport>,
        );
        const frame = screen.getByRole("region", { name: "Broken observer" });
        Object.defineProperty(frame, "clientWidth", {
          configurable: true,
          get: () => dimensions.width,
        });
        Object.defineProperty(frame, "clientHeight", {
          configurable: true,
          get: () => dimensions.height,
        });
        const transform = screen.getByTestId("image-viewport-transform");
        const polygon = screen
          .getByTestId("broken-observer-overlay")
          .querySelector("polygon");
        const originalPoints = polygon?.getAttribute("points");

        fireEvent.resize(window);
        const expected = fitTransform(
          { width: 1600, height: 1200 },
          dimensions,
        );
        expect(transform.style.transform).toContain(`scale(${expected.scale})`);
        expect(polygon).toHaveAttribute("points", originalPoints);
        unmount();
        expect(disconnects).toBe(failure === "constructor" ? 0 : 1);
      } finally {
        vi.unstubAllGlobals();
      }
    },
  );

  it("unmounts safely when a registered WebView2 observer refuses cleanup", () => {
    class BrokenCleanupObserver {
      constructor(_callback: ResizeObserverCallback) {}
      observe() {}
      disconnect() {
        throw new Error("ResizeObserver.disconnect unavailable");
      }
    }
    vi.stubGlobal("ResizeObserver", BrokenCleanupObserver);
    try {
      const { unmount } = render(
        <ImageViewport width={1600} height={1200} label="Cleanup failure">
          <svg data-testid="cleanup-overlay" viewBox="0 0 1600 1200">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      expect(screen.getByTestId("cleanup-overlay")).toBeInTheDocument();
      expect(unmount).not.toThrow();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("preserves user zoom and annotated pixel positions when a desktop pane resizes", () => {
    let notifyResize: (() => void) | undefined;
    class MockResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
    try {
      const size = { width: 900, height: 600 };
      const { rerender, unmount } = render(
        <ImageViewport width={1600} height={1200} label="Resizable image">
          <svg data-testid="resizing-overlay" viewBox="0 0 1600 1200">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      const frame = screen.getByRole("region", { name: "Resizable image" });
      Object.defineProperty(frame, "clientWidth", {
        configurable: true,
        get: () => size.width,
      });
      Object.defineProperty(frame, "clientHeight", {
        configurable: true,
        get: () => size.height,
      });
      const transform = screen.getByTestId("image-viewport-transform");
      const overlay = screen.getByTestId("resizing-overlay");
      const originalPoints = overlay
        .querySelector("polygon")
        ?.getAttribute("points");
      const currentView = () => {
        const match = transform.style.transform.match(
          /^translate\((-?[\d.]+)px, (-?[\d.]+)px\) scale\(([\d.]+)\)$/,
        );
        if (!match) throw new Error("Unexpected scientific viewport transform");
        return {
          offsetX: Number(match[1]),
          offsetY: Number(match[2]),
          scale: Number(match[3]),
        };
      };

      act(() => notifyResize?.());
      fireEvent.wheel(frame, { deltaY: -120, clientX: 450, clientY: 300 });
      const manual = currentView();
      expect(manual.scale).toBeGreaterThan(
        fitTransform({ width: 1600, height: 1200 }, size).scale,
      );

      // Hidden, collapsed, or unmeasurable WebView2 panels must not
      // substitute the 1200x780 fallback for a previously measured viewport.
      for (const [collapsedWidth, collapsedHeight] of [
        [0, 600],
        [900, 0],
        [0, 0],
        [Number.NaN, 600],
        [900, Number.POSITIVE_INFINITY],
        [Number.NEGATIVE_INFINITY, 600],
      ]) {
        act(() => {
          size.width = collapsedWidth;
          size.height = collapsedHeight;
          notifyResize?.();
        });
        expect(currentView()).toEqual(manual);
        expect(overlay.querySelector("polygon")).toHaveAttribute(
          "points",
          originalPoints,
        );
      }

      act(() => {
        size.width = 1100;
        size.height = 760;
        notifyResize?.();
      });
      const resized = currentView();
      expect(resized.scale).toBeCloseTo(manual.scale);
      expect(resized.offsetX).toBeCloseTo(manual.offsetX + 100);
      expect(resized.offsetY).toBeCloseTo(manual.offsetY + 80);
      expect(overlay.querySelector("polygon")).toHaveAttribute(
        "points",
        originalPoints,
      );

      // Explicit Fit re-enables automatic resizing; another camera image
      // with different source dimensions also starts with its own fit.
      fireEvent.click(screen.getByRole("button", { name: "Fit to View" }));
      act(() => {
        size.width = 1200;
        size.height = 820;
        notifyResize?.();
      });
      const expectedFit = fitTransform({ width: 1600, height: 1200 }, size);
      expect(currentView().scale).toBeCloseTo(expectedFit.scale);

      fireEvent.wheel(frame, { deltaY: -120, clientX: 450, clientY: 300 });
      rerender(
        <ImageViewport width={3200} height={800} label="Resizable image">
          <svg data-testid="resizing-overlay" viewBox="0 0 3200 800">
            <polygon points="10,20 40,20 40,60" />
          </svg>
        </ImageViewport>,
      );
      expect(currentView().scale).toBeCloseTo(
        fitTransform({ width: 3200, height: 800 }, size).scale,
      );
      unmount();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("blocks scrolling without zooming for horizontal-dominant, Shift, or zero-delta wheels", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Trackpad viewport">
        <div />
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Trackpad viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const initial = transform.style.transform;

    const wheel = (init: WheelEventInit) => {
      const event = new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        clientX: 300,
        clientY: 250,
        ...init,
      });
      // Testing Library wraps dispatch in React act(), flushing the viewport
      // state update before the transform assertion below.
      fireEvent(frame, event);
      return event.defaultPrevented;
    };

    expect(wheel({ deltaX: 120, deltaY: 0 })).toBe(true);
    expect(transform.style.transform).toBe(initial);
    // Precision trackpads report slight vertical jitter during a horizontal
    // scroll. Those gestures must not accidentally move annotated pixels.
    expect(wheel({ deltaX: 120, deltaY: -5 })).toBe(true);
    expect(transform.style.transform).toBe(initial);
    expect(wheel({ deltaX: 100, deltaY: 100 })).toBe(true);
    expect(transform.style.transform).toBe(initial);
    expect(wheel({ deltaY: -120, shiftKey: true })).toBe(true);
    expect(transform.style.transform).toBe(initial);
    expect(wheel({ deltaX: 0, deltaY: 0 })).toBe(false);
    expect(transform.style.transform).toBe(initial);
    expect(wheel({ deltaY: -100, ctrlKey: true })).toBe(false);
    expect(wheel({ deltaY: -100, metaKey: true })).toBe(false);
    expect(transform.style.transform).toBe(initial);

    expect(wheel({ deltaY: -100 })).toBe(true);
    expect(transform.style.transform).not.toBe(initial);
    const afterVerticalWheel = transform.style.transform;
    // Ordinary vertical-dominant diagonal gestures still zoom normally.
    expect(wheel({ deltaX: 5, deltaY: -100 })).toBe(true);
    expect(transform.style.transform).not.toBe(afterVerticalWheel);
  });

  it("contains malformed wheel pointer positions without changing scientific geometry", () => {
    render(
      <ImageViewport
        width={1600}
        height={1200}
        label="Invalid pointer viewport"
      >
        <svg data-testid="pointer-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 40,10 40,40" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Invalid pointer viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("pointer-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");
    const initial = transform.style.transform;

    const malformedWheel = (clientX: number, clientY: number) => {
      const event = new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        deltaY: -120,
        clientX: 200,
        clientY: 180,
      });
      // The native WebView2 event properties are read-only. Override them
      // to reproduce malformed input without depending on DOM coercion.
      Object.defineProperty(event, "clientX", { value: clientX });
      Object.defineProperty(event, "clientY", { value: clientY });
      fireEvent(frame, event);
      expect(event.defaultPrevented).toBe(true);
    };

    malformedWheel(Number.NaN, 180);
    malformedWheel(200, Number.POSITIVE_INFINITY);
    malformedWheel(Number.NEGATIVE_INFINITY, Number.NaN);
    expect(transform.style.transform).toBe(initial);
    expect(polygon).toHaveAttribute("points", originalPoints);

    // The first valid wheel event must still zoom the image and overlay.
    fireEvent.wheel(frame, { deltaY: -120, clientX: 200, clientY: 180 });
    expect(transform.style.transform).not.toBe(initial);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("contains malformed one-axis wheel values", () => {
    render(
      <ImageViewport
        width={1600}
        height={1200}
        label="Malformed wheel viewport"
      >
        <svg data-testid="wheel-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 40,10 40,40" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Malformed wheel viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("wheel-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");
    const initial = transform.style.transform;

    const wheel = (deltaX: number, deltaY: number) => {
      const event = new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        clientX: 200,
        clientY: 180,
      });
      // Override read-only axes to emulate bad WebView2 data without
      // relying on whether the native constructor accepts NaN/Infinity.
      Object.defineProperty(event, "deltaX", { value: deltaX });
      Object.defineProperty(event, "deltaY", { value: deltaY });
      fireEvent(frame, event);
      return event.defaultPrevented;
    };

    expect(wheel(Number.NaN, -120)).toBe(true);
    const zoomed = transform.style.transform;
    expect(zoomed).not.toBe(initial);

    expect(wheel(120, Number.POSITIVE_INFINITY)).toBe(true);
    expect(transform.style.transform).toBe(zoomed);

    // No finite axis must still be contained by the desktop viewer:
    // otherwise WebView2 may scroll the document behind the annotation.
    expect(wheel(Number.NaN, Number.NEGATIVE_INFINITY)).toBe(true);
    expect(wheel(Number.NaN, 0)).toBe(true);
    expect(wheel(0, Number.POSITIVE_INFINITY)).toBe(true);
    expect(transform.style.transform).toBe(zoomed);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("prevents document scrolling when the wheel targets an annotation overlay", () => {
    render(
      <ImageViewport width={6000} height={4000} label="Scientific image">
        <svg data-testid="pixel-aligned-overlay" viewBox="0 0 6000 4000">
          <polygon points="5,5 20,5 20,20" />
        </svg>
      </ImageViewport>,
    );

    const overlay = screen.getByTestId("pixel-aligned-overlay");
    const transform = screen.getByTestId("image-viewport-transform");
    const initialTransform = transform.style.transform;
    const originalPolygon = overlay.querySelector("polygon");
    const originalPoints = originalPolygon?.getAttribute("points");
    const wheel = new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaY: -120,
      clientX: 200,
      clientY: 180,
    });

    fireEvent(overlay, wheel);

    expect(wheel.defaultPrevented).toBe(true);
    expect(transform.style.transform).not.toBe(initialTransform);
    expect(overlay.querySelector("polygon")).toHaveAttribute(
      "points",
      originalPoints,
    );
  });

  it("ignores other pointers and only ends a pan for its originating pointer", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Multi-pointer viewport">
        <svg data-testid="fixed-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Multi-pointer viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("fixed-overlay")
      .querySelector("polygon");
    const originalGeometry = polygon?.getAttribute("points");
    const initial = transform.style.transform;

    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 11,
      clientX: 50,
      clientY: 60,
    });
    fireEvent.pointerMove(window, {
      pointerId: 12,
      clientX: 180,
      clientY: 200,
    });
    fireEvent.pointerUp(window, { pointerId: 12 });
    expect(transform.style.transform).toBe(initial);

    // A second pointerdown must not replace the original pan anchor.
    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 12,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(window, { pointerId: 11, clientX: 90, clientY: 110 });
    const afterOwnerMove = transform.style.transform;
    expect(afterOwnerMove).not.toBe(initial);
    expect(polygon).toHaveAttribute("points", originalGeometry);

    fireEvent.pointerCancel(window, { pointerId: 12 });
    fireEvent.pointerMove(window, { pointerId: 11, clientX: 95, clientY: 115 });
    expect(transform.style.transform).not.toBe(afterOwnerMove);

    fireEvent.pointerUp(window, { pointerId: 11 });
    const finished = transform.style.transform;
    fireEvent.pointerMove(window, {
      pointerId: 11,
      clientX: 150,
      clientY: 170,
    });
    expect(transform.style.transform).toBe(finished);
    expect(polygon).toHaveAttribute("points", originalGeometry);
  });

  it("ignores invalid pan coordinates and recovers without changing raster geometry", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Raster pan viewport">
        <svg data-testid="raster-geometry" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Raster pan viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("raster-geometry")
      .querySelector("polygon");
    const sourcePoints = polygon?.getAttribute("points");
    const original = transform.style.transform;

    const pointer = (
      target: Element | Window,
      type: string,
      clientX: number,
      clientY: number,
    ) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      // WebView2 properties are read-only; use explicit values rather than
      // DOM constructor coercion to reproduce nonfinite native coordinates.
      Object.defineProperties(event, {
        pointerId: { value: 19 },
        button: { value: 0 },
        altKey: { value: true },
        clientX: { value: clientX },
        clientY: { value: clientY },
      });
      fireEvent(target, event);
    };

    pointer(frame, "pointerdown", Number.NaN, 60);
    pointer(window, "pointermove", 100, 120);
    expect(transform.style.transform).toBe(original);

    // A bad pointerdown must not reserve the pan for later valid input.
    pointer(frame, "pointerdown", 50, 60);
    pointer(window, "pointermove", Number.POSITIVE_INFINITY, 110);
    pointer(window, "pointermove", 90, Number.NEGATIVE_INFINITY);
    expect(transform.style.transform).toBe(original);

    pointer(window, "pointermove", 90, 110);
    const panned = transform.style.transform;
    expect(panned).not.toBe(original);

    // Bad updates during a good drag are ignored without cancelling it.
    pointer(window, "pointermove", Number.NaN, 150);
    expect(transform.style.transform).toBe(panned);
    pointer(window, "pointermove", 120, 130);
    expect(transform.style.transform).not.toBe(panned);
    expect(transform.style.transform).not.toMatch(/NaN|Infinity/);
    expect(polygon).toHaveAttribute("points", sourcePoints);
  });

  it("rejects finite pan coordinates whose offset arithmetic overflows", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Overflow pan viewport">
        <svg data-testid="overflow-pan-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Overflow pan viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("overflow-pan-overlay")
      .querySelector("polygon");
    const sourcePoints = polygon?.getAttribute("points");
    const original = transform.style.transform;

    const pointer = (
      target: Element | Window,
      type: string,
      clientX: number,
      clientY: number,
    ) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        pointerId: { value: 57 },
        button: { value: 0 },
        altKey: { value: true },
        clientX: { value: clientX },
        clientY: { value: clientY },
      });
      fireEvent(target, event);
    };

    // The coordinates are individually finite, but subtraction of the
    // opposite extremes overflows. Neither axis may corrupt the viewport.
    pointer(frame, "pointerdown", -1e308, -1e308);
    pointer(window, "pointermove", 1e308, -1e308);
    expect(transform.style.transform).toBe(original);
    pointer(window, "pointermove", -1e308, 1e308);
    expect(transform.style.transform).toBe(original);
    expect(polygon).toHaveAttribute("points", sourcePoints);

    // A new ordinary drag must still pan the same unmodified source image.
    pointer(window, "pointerup", -1e308, -1e308);
    pointer(frame, "pointerdown", 50, 60);
    pointer(window, "pointermove", 90, 110);
    expect(transform.style.transform).not.toBe(original);
    expect(transform.style.transform).not.toMatch(/NaN|Infinity/);
    expect(polygon).toHaveAttribute("points", sourcePoints);
  });

  it("preserves wheel zoom when a prior pan pointer keeps moving", () => {
    render(
      <ImageViewport
        width={1600}
        height={1200}
        label="Concurrent pan and zoom viewport"
      >
        <svg data-testid="gesture-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,20 40,20 40,60" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", {
      name: "Concurrent pan and zoom viewport",
    });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("gesture-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");

    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 31,
      clientX: 100,
      clientY: 110,
    });
    fireEvent.pointerMove(window, {
      pointerId: 31,
      clientX: 140,
      clientY: 150,
    });
    const panned = transform.style.transform;

    fireEvent.wheel(frame, { deltaY: -120, clientX: 300, clientY: 250 });
    const zoomed = transform.style.transform;
    expect(zoomed).not.toBe(panned);

    // WebView2 can deliver another move from the still-held pan pointer
    // after the scientist has zoomed. Never restore the old pan anchor.
    fireEvent.pointerMove(window, {
      pointerId: 31,
      clientX: 220,
      clientY: 230,
    });
    expect(transform.style.transform).toBe(zoomed);
    expect(polygon).toHaveAttribute("points", originalPoints);

    // Ending the old gesture does not prevent a new deliberate pan.
    fireEvent.pointerUp(window, { pointerId: 31 });
    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 32,
      clientX: 100,
      clientY: 110,
    });
    fireEvent.pointerMove(window, {
      pointerId: 32,
      clientX: 125,
      clientY: 135,
    });
    expect(transform.style.transform).not.toBe(zoomed);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("cancels a pan on Escape without moving scientific overlays", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Escape viewport">
        <svg data-testid="escape-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Escape viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("escape-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");

    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 11,
      clientX: 50,
      clientY: 60,
    });
    fireEvent.pointerMove(window, { pointerId: 11, clientX: 90, clientY: 110 });
    const panned = transform.style.transform;

    // Cancelling the gesture must not leave a stale drag that moves the
    // image when the pointer continues moving after the keypress.
    fireEvent.keyDown(frame, { key: "Escape" });
    fireEvent.pointerMove(window, {
      pointerId: 11,
      clientX: 140,
      clientY: 160,
    });
    expect(transform.style.transform).toBe(panned);
    expect(polygon).toHaveAttribute("points", originalPoints);

    // A fresh pan must still work after cancellation.
    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 12,
      clientX: 50,
      clientY: 60,
    });
    fireEvent.pointerMove(window, { pointerId: 12, clientX: 80, clientY: 90 });
    expect(transform.style.transform).not.toBe(panned);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("preserves find shortcuts and editable labels without losing plain-F refit or polygon geometry", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Editable coral image">
        <svg data-testid="shortcut-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
        <div
          contentEditable
          suppressContentEditableWarning
          data-testid="annotation-label-editor"
        >
          Coral fragment
        </div>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Editable coral image" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("shortcut-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");
    const fitted = transform.style.transform;

    fireEvent.wheel(frame, { deltaY: -120, clientX: 300, clientY: 200 });
    const zoomed = transform.style.transform;
    expect(zoomed).not.toBe(fitted);
    expect(fireEvent.keyDown(frame, { key: "f", ctrlKey: true })).toBe(true);
    expect(fireEvent.keyDown(frame, { key: "f", metaKey: true })).toBe(true);
    expect(fireEvent.keyDown(frame, { key: "f", altKey: true })).toBe(true);
    expect(fireEvent.keyDown(frame, { key: "f", isComposing: true })).toBe(
      true,
    );
    expect(
      fireEvent.keyDown(screen.getByTestId("annotation-label-editor"), {
        key: "f",
      }),
    ).toBe(true);
    expect(transform.style.transform).toBe(zoomed);
    expect(polygon).toHaveAttribute("points", originalPoints);

    expect(fireEvent.keyDown(frame, { key: "f" })).toBe(false);
    expect(transform.style.transform).toBe(fitted);
    expect(polygon).toHaveAttribute("points", originalPoints);
  });

  it("refits when switching same-size camera images without carrying stale pan or zoom", () => {
    const renderSource = (sourceImageId: string) => (
      <ImageViewport
        width={1600}
        height={1200}
        label="Camera mask viewport"
        sourceImageId={sourceImageId}
      >
        <svg data-testid="source-geometry" viewBox="0 0 1600 1200">
          <polygon points="10,20 30,20 30,40" />
        </svg>
      </ImageViewport>
    );
    const { rerender } = render(renderSource("camera-a"));
    const frame = screen.getByRole("region", { name: "Camera mask viewport" });
    const transform = screen.getByTestId("image-viewport-transform");
    const originalGeometry = screen
      .getByTestId("source-geometry")
      .querySelector("polygon")
      ?.getAttribute("points");
    const fitted = transform.style.transform;

    fireEvent.wheel(frame, { deltaY: -120, clientX: 300, clientY: 200 });
    const zoomed = transform.style.transform;
    expect(zoomed).not.toBe(fitted);

    // A refetch of the *same* camera source must preserve the scientist's view.
    rerender(renderSource("camera-a"));
    expect(transform.style.transform).toBe(zoomed);

    fireEvent.pointerDown(frame, {
      button: 0,
      altKey: true,
      pointerId: 9,
      clientX: 50,
      clientY: 60,
    });
    fireEvent.pointerMove(window, {
      pointerId: 9,
      clientX: 100,
      clientY: 120,
    });
    expect(transform.style.transform).not.toBe(zoomed);

    // Dimensions are identical, so only the source identity can trigger
    // the reset. An old active pointer must not pan the newly opened image.
    rerender(renderSource("camera-b"));
    expect(transform.style.transform).toBe(fitted);
    fireEvent.pointerMove(window, {
      pointerId: 9,
      clientX: 140,
      clientY: 160,
    });
    expect(transform.style.transform).toBe(fitted);
    expect(
      screen.getByTestId("source-geometry").querySelector("polygon"),
    ).toHaveAttribute("points", originalGeometry);
  });

  it("contains malformed WebView2 viewport rectangles and overflowing zoom arithmetic", () => {
    render(
      <ImageViewport width={1600} height={1200} label="Camera zoom geometry">
        <svg data-testid="camera-zoom-overlay" viewBox="0 0 1600 1200">
          <polygon points="10,10 50,10 50,50" />
        </svg>
      </ImageViewport>,
    );
    const frame = screen.getByRole("region", { name: "Camera zoom geometry" });
    const transform = screen.getByTestId("image-viewport-transform");
    const polygon = screen
      .getByTestId("camera-zoom-overlay")
      .querySelector("polygon");
    const originalPoints = polygon?.getAttribute("points");
    const originalTransform = transform.style.transform;
    const originalRect = frame.getBoundingClientRect();
    const rectSpy = vi.spyOn(frame, "getBoundingClientRect");

    const wheelAt = (clientX: number, rectLeft: number) => {
      rectSpy.mockReturnValue({
        ...originalRect,
        left: rectLeft,
        top: originalRect.top,
      } as DOMRect);
      const wheel = new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        deltaY: -120,
        clientX: 200,
        clientY: 180,
      });
      Object.defineProperty(wheel, "clientX", { value: clientX });
      fireEvent(frame, wheel);
      // Invalid native input is contained so the surrounding page does not
      // scroll, but no scientifically meaningful pixel transform is made.
      expect(wheel.defaultPrevented).toBe(true);
      expect(transform.style.transform).toBe(originalTransform);
      expect(polygon).toHaveAttribute("points", originalPoints);
    };

    wheelAt(200, Number.NaN);
    wheelAt(1e308, -1e308); // finite operands overflow to Infinity
    wheelAt(Number.MAX_VALUE, 0); // zoomAtPoint overflows after subtraction
    rectSpy.mockRestore();

    // Invalid input must not disable a subsequent genuine camera zoom.
    fireEvent.wheel(frame, { deltaY: -120, clientX: 200, clientY: 180 });
    expect(transform.style.transform).not.toBe(originalTransform);
    expect(polygon).toHaveAttribute("points", originalPoints);
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
});
