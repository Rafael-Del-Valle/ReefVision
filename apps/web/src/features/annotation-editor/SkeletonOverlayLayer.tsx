import {
  useEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { SkeletonPixel } from "./skeletonAnalysisApi";

export type SkeletonEditMode = "view" | "add" | "remove";

export interface SkeletonOverlayModel {
  pixels: SkeletonPixel[];
  addedPixels: SkeletonPixel[];
  removedPixels: SkeletonPixel[];
  editMode: SkeletonEditMode;
  onPixelClick: (point: SkeletonPixel) => void;
}

interface SkeletonOverlayLayerProps extends SkeletonOverlayModel {
  width: number;
  height: number;
}

function pixelKey(point: SkeletonPixel): string {
  return `${point.x},${point.y}`;
}

export function SkeletonOverlayLayer({
  width,
  height,
  pixels,
  addedPixels,
  removedPixels,
  editMode,
  onPixelClick,
}: SkeletonOverlayLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, width, height);

    const removed = new Set(removedPixels.map(pixelKey));
    context.fillStyle = "rgba(45, 212, 191, 0.95)";
    for (const point of pixels) {
      if (removed.has(pixelKey(point))) continue;
      context.fillRect(point.x, point.y, 1, 1);
    }

    context.fillStyle = "rgba(74, 222, 128, 0.98)";
    for (const point of addedPixels) {
      context.fillRect(point.x, point.y, 1, 1);
    }

    context.fillStyle = "rgba(248, 113, 113, 0.98)";
    for (const point of removedPixels) {
      context.fillRect(point.x, point.y, 1, 1);
    }
  }, [addedPixels, height, pixels, removedPixels, width]);

  function handlePointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (editMode === "view") return;
    const rectangle = event.currentTarget.getBoundingClientRect();
    if (rectangle.width <= 0 || rectangle.height <= 0) return;
    const x = Math.max(
      0,
      Math.min(
        width - 1,
        Math.floor(((event.clientX - rectangle.left) / rectangle.width) * width),
      ),
    );
    const y = Math.max(
      0,
      Math.min(
        height - 1,
        Math.floor(
          ((event.clientY - rectangle.top) / rectangle.height) * height,
        ),
      ),
    );
    event.preventDefault();
    event.stopPropagation();
    onPixelClick({ x, y });
  }

  return (
    <canvas
      ref={canvasRef}
      data-testid="skeleton-overlay"
      aria-label="Skeleton analysis overlay"
      onPointerDown={handlePointerDown}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: editMode === "view" ? "none" : "auto",
        cursor:
          editMode === "add"
            ? "crosshair"
            : editMode === "remove"
              ? "not-allowed"
              : "default",
        imageRendering: "pixelated",
      }}
    />
  );
}
