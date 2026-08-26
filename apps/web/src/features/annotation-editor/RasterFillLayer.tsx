import type { PointerEvent } from "react";

import type { Point } from "./types";

interface RasterFillLayerProps {
  width: number;
  height: number;
  disabled?: boolean;
  onFill: (point: Point) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export function RasterFillLayer({
  width,
  height,
  disabled = false,
  onFill,
}: RasterFillLayerProps) {
  function sourcePoint(event: PointerEvent<SVGSVGElement>): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: clamp(
        ((event.clientX - bounds.left) / Math.max(bounds.width, 1)) * width,
        0,
        width,
      ),
      y: clamp(
        ((event.clientY - bounds.top) / Math.max(bounds.height, 1)) * height,
        0,
        height,
      ),
    };
  }

  return (
    <svg
      aria-label="Flood fill layer"
      data-testid="raster-fill-layer"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      onPointerDown={(event) => {
        if (disabled || event.button !== 0) return;
        event.preventDefault();
        onFill(sourcePoint(event));
      }}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        touchAction: "none",
        cursor: disabled ? "not-allowed" : "cell",
      }}
    />
  );
}
