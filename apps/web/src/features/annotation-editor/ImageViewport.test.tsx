import { fireEvent, render, screen } from "@testing-library/react";
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
