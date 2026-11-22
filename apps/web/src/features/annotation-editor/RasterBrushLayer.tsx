import { useMemo, useRef, useState, type PointerEvent } from "react";

import type { RasterEditMode } from "./rasterMaskApi";
import type { Point } from "./types";

export interface RasterBrushSettings {
  mode: Exclude<RasterEditMode, "fill">;
  brushRadius: number;
}

interface RasterBrushLayerProps {
  width: number;
  height: number;
  mode: Exclude<RasterEditMode, "fill">;
  brushRadius: number;
  disabled?: boolean;
  onStroke: (points: Point[], settings: RasterBrushSettings) => void;
  onStrokeStart?: () => void;
  onStrokeCancel?: () => void;
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
  onStrokeStart,
  onStrokeCancel,
}: RasterBrushLayerProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const finishingPointerRef = useRef<number | null>(null);
  const [pointerId, setPointerId] = useState<number | null>(null);
  const [strokeSettings, setStrokeSettings] =
    useState<RasterBrushSettings | null>(null);
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
    if (disabled || event.button !== 0 || pointerId !== null) return;
    const point = sourcePoint(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    finishingPointerRef.current = null;
    setPointerId(event.pointerId);
    setStrokeSettings({ mode, brushRadius });
    onStrokeStart?.();
    setPoints([point]);
    setHoverPoint(point);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    if (pointerId !== null && pointerId !== event.pointerId) return;
    const point = sourcePoint(event);
    setHoverPoint(point);
    if (pointerId !== event.pointerId) return;
    setPoints((current) => {
      const last = current[current.length - 1];
      if (
        last &&
        distance(last, point) <
          Math.max(1, (strokeSettings?.brushRadius ?? brushRadius) * 0.2)
      ) {
        return current;
      }
      return [...current, point];
    });
  }

  function finishStroke(event: PointerEvent<SVGSVGElement>) {
    if (pointerId !== event.pointerId) return;
    const completed = points;
    // Releasing capture intentionally can synchronously emit lostpointercapture.
    // It must never cancel the already-approved stroke at this pointer-up.
    finishingPointerRef.current = event.pointerId;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setPointerId(null);
    setStrokeSettings(null);
    setPoints([]);
    if (completed.length > 0 && strokeSettings) {
      onStroke(completed, strokeSettings);
    }
  }

  function cancelStroke(event: PointerEvent<SVGSVGElement>) {
    if (
      pointerId !== event.pointerId ||
      finishingPointerRef.current === event.pointerId
    ) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    // Browser cancellation or capture loss must never paint an unapproved mask.
    setPointerId(null);
    setStrokeSettings(null);
    setPoints([]);
    onStrokeCancel?.();
  }

  const previewMode = strokeSettings?.mode ?? mode;
  const previewRadius = strokeSettings?.brushRadius ?? brushRadius;
  const previewFill =
    previewMode === "paint"
      ? "rgba(87, 204, 153, 0.35)"
      : "rgba(244, 96, 108, 0.35)";
  const previewStroke = previewMode === "paint" ? "#57cc99" : "#f4606c";

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
      onPointerCancel={cancelStroke}
      onLostPointerCapture={cancelStroke}
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
          r={previewRadius}
          fill={previewFill}
          pointerEvents="none"
        />
      )}
      {points.length > 1 && (
        <polyline
          points={strokeText}
          fill="none"
          stroke={previewStroke}
          strokeWidth={previewRadius * 2}
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
          stroke={previewStroke}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          pointerEvents="none"
        />
      )}
    </svg>
  );
}
