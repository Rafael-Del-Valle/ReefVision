import {
  PointerEvent,
  useMemo,
  useRef,
  useState,
} from "react";

import type { Point } from "./types";
import type { RasterEditMode } from "./rasterMaskApi";

interface RasterBrushLayerProps {
  width: number;
  height: number;
  mode: RasterEditMode;
  brushRadius: number;
  disabled?: boolean;
  onStroke: (points: Point[]) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function distance(first: Point, second: Point): number {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

export function RasterBrushLayer({
  width,
  height,
  mode,
  brushRadius,
  disabled = false,
  onStroke,
}: RasterBrushLayerProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [pointerId, setPointerId] = useState<number | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [hoverPoint, setHoverPoint] = useState<Point | null>(null);

  const strokeText = useMemo(
    () => points.map((point) => `${point.x},${point.y}`).join(" "),
    [points],
  );

  function sourcePoint(event: PointerEvent<SVGSVGElement>): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    const normalizedX = bounds.width
      ? (event.clientX - bounds.left) / bounds.width
      : 0;
    const normalizedY = bounds.height
      ? (event.clientY - bounds.top) / bounds.height
      : 0;
    return {
      x: clamp(normalizedX * width, 0, width),
      y: clamp(normalizedY * height, 0, height),
    };
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    if (disabled || event.button !== 0) return;
    const point = sourcePoint(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    setPointerId(event.pointerId);
    setPoints([point]);
    setHoverPoint(point);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const point = sourcePoint(event);
    setHoverPoint(point);
    if (pointerId !== event.pointerId) return;
    setPoints((current) => {
      const last = current[current.length - 1];
      if (last && distance(last, point) < Math.max(1, brushRadius * 0.2)) {
        return current;
      }
      return [...current, point];
    });
  }

  function finishStroke(event: PointerEvent<SVGSVGElement>) {
    if (pointerId !== event.pointerId) return;
    const completed = points;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setPointerId(null);
    setPoints([]);
    if (completed.length > 0) onStroke(completed);
  }

  return (
    <svg
      ref={svgRef}
      aria-label="Raster brush layer"
      data-testid="raster-brush-layer"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishStroke}
      onPointerCancel={finishStroke}
      onPointerLeave={() => {
        if (pointerId === null) setHoverPoint(null);
      }}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        touchAction: "none",
        cursor: disabled ? "not-allowed" : "crosshair",
      }}
    >
      {points.length === 1 && (
        <circle
          cx={points[0].x}
          cy={points[0].y}
          r={brushRadius}
          fill={mode === "paint" ? "rgba(87, 204, 153, 0.35)" : "rgba(244, 96, 108, 0.35)"}
          pointerEvents="none"
        />
      )}
      {points.length > 1 && (
        <polyline
          points={strokeText}
          fill="none"
          stroke={mode === "paint" ? "#57cc99" : "#f4606c"}
          strokeWidth={brushRadius * 2}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={0.5}
          pointerEvents="none"
        />
      )}
      {hoverPoint && pointerId === null && (
        <circle
          cx={hoverPoint.x}
          cy={hoverPoint.y}
          r={brushRadius}
          fill="none"
          stroke={mode === "paint" ? "#57cc99" : "#f4606c"}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          pointerEvents="none"
        />
      )}
    </svg>
  );
}
