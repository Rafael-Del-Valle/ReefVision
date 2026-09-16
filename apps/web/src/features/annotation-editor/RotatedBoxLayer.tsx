import { useMemo, useState, type PointerEvent } from "react";

import { polygonMetrics } from "./PolygonMaskLayer";
import type { EditorAnnotation, EditorMaskAnnotation, Point } from "./types";

interface RotatedBoxLayerProps {
  width: number;
  height: number;
  masks: EditorMaskAnnotation[];
  classColors: Record<string, string>;
  activeClassId: string | null;
  selectedMaskIds: string[];
  onCreate: (mask: EditorMaskAnnotation) => void;
  onUpdate: (mask: EditorMaskAnnotation) => void;
  onSelectionChange: (maskIds: string[]) => void;
}

type DragKind = "create" | "move" | "rotate" | "resize";
interface DragState {
  kind: DragKind;
  pointerId: number;
  start: Point;
  mask?: EditorMaskAnnotation;
  cornerIndex?: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function generatedMaskId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `rotated-box-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function sourcePoint(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number,
  width: number,
  height: number,
): Point {
  const bounds = svg.getBoundingClientRect();
  return {
    x: clamp(
      ((clientX - bounds.left) / Math.max(bounds.width, 1)) * width,
      0,
      width,
    ),
    y: clamp(
      ((clientY - bounds.top) / Math.max(bounds.height, 1)) * height,
      0,
      height,
    ),
  };
}

export function centerOfRotatedBox(points: Point[]): Point {
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
}

export function rotatedBoxDimensions(points: Point[]) {
  return {
    center: centerOfRotatedBox(points),
    width: Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y),
    height: Math.hypot(points[2].x - points[1].x, points[2].y - points[1].y),
    angle: Math.atan2(points[1].y - points[0].y, points[1].x - points[0].x),
  };
}

export function rotatedBoxPoints(
  center: Point,
  boxWidth: number,
  boxHeight: number,
  angle: number,
): Point[] {
  const halfWidth = boxWidth / 2;
  const halfHeight = boxHeight / 2;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [
    { x: -halfWidth, y: -halfHeight },
    { x: halfWidth, y: -halfHeight },
    { x: halfWidth, y: halfHeight },
    { x: -halfWidth, y: halfHeight },
  ].map((point) => ({
    x: center.x + point.x * cos - point.y * sin,
    y: center.y + point.x * sin + point.y * cos,
  }));
}

export function rotatedBoxMaskFromPoints(
  points: Point[],
  labelClassId: string,
  id: string,
  persisted: boolean,
  revision?: number,
): EditorMaskAnnotation {
  const metrics = polygonMetrics(points);
  return {
    id,
    label_class_id: labelClassId,
    geometry_kind: "rotated_box",
    points: points.map((point) => ({ ...point })),
    mask_path: null,
    x_min: metrics.xMin,
    y_min: metrics.yMin,
    x_max: metrics.xMax,
    y_max: metrics.yMax,
    area_pixels: metrics.areaPixels,
    source_type: "human",
    persisted,
    revision,
  };
}

export function rotatedBoxFromDrag(
  start: Point,
  end: Point,
  labelClassId: string,
  id = generatedMaskId(),
): EditorMaskAnnotation {
  return rotatedBoxMaskFromPoints(
    [
      { x: start.x, y: start.y },
      { x: end.x, y: start.y },
      { x: end.x, y: end.y },
      { x: start.x, y: end.y },
    ],
    labelClassId,
    id,
    false,
  );
}

export function rotationAngleForPoint(center: Point, pointer: Point): number {
  return Math.atan2(pointer.y - center.y, pointer.x - center.x) + Math.PI / 2;
}

export function rotatedBoxFromAnnotation(
  annotation: EditorAnnotation,
  angle: number,
  id = generatedMaskId(),
): EditorMaskAnnotation {
  const center = {
    x: (annotation.x_min + annotation.x_max) / 2,
    y: (annotation.y_min + annotation.y_max) / 2,
  };
  return rotatedBoxMaskFromPoints(
    rotatedBoxPoints(
      center,
      annotation.x_max - annotation.x_min,
      annotation.y_max - annotation.y_min,
      angle,
    ),
    annotation.label_class_id,
    id,
    false,
  );
}

export function rotatedBoxFitsImage(
  points: Point[],
  width: number,
  height: number,
): boolean {
  return points.every(
    (point) =>
      point.x >= 0 && point.y >= 0 && point.x <= width && point.y <= height,
  );
}

export function translateRotatedBox(
  mask: EditorMaskAnnotation,
  dx: number,
  dy: number,
  width: number,
  height: number,
): EditorMaskAnnotation {
  if (!mask.points || mask.label_class_id === null) return mask;
  const xs = mask.points.map((point) => point.x);
  const ys = mask.points.map((point) => point.y);
  const boundedX = clamp(dx, -Math.min(...xs), width - Math.max(...xs));
  const boundedY = clamp(dy, -Math.min(...ys), height - Math.max(...ys));
  return rotatedBoxMaskFromPoints(
    mask.points.map((point) => ({
      x: point.x + boundedX,
      y: point.y + boundedY,
    })),
    mask.label_class_id,
    mask.id,
    mask.persisted,
    mask.revision,
  );
}

export function rotateRotatedBox(
  mask: EditorMaskAnnotation,
  pointer: Point,
  width: number,
  height: number,
): EditorMaskAnnotation {
  if (!mask.points || mask.label_class_id === null) return mask;
  const d = rotatedBoxDimensions(mask.points);
  const angle =
    Math.atan2(pointer.y - d.center.y, pointer.x - d.center.x) + Math.PI / 2;
  const points = rotatedBoxPoints(d.center, d.width, d.height, angle);
  if (!rotatedBoxFitsImage(points, width, height)) return mask;
  return rotatedBoxMaskFromPoints(
    points,
    mask.label_class_id,
    mask.id,
    mask.persisted,
    mask.revision,
  );
}

export function resizeRotatedBox(
  mask: EditorMaskAnnotation,
  pointer: Point,
  cornerIndex: number,
  width: number,
  height: number,
): EditorMaskAnnotation {
  if (!mask.points || mask.label_class_id === null) return mask;
  const d = rotatedBoxDimensions(mask.points);
  const opposite = mask.points[(cornerIndex + 2) % 4];
  const signs = [
    { x: -1, y: -1 },
    { x: 1, y: -1 },
    { x: 1, y: 1 },
    { x: -1, y: 1 },
  ][cornerIndex];
  const axisX = { x: Math.cos(d.angle), y: Math.sin(d.angle) };
  const axisY = { x: -Math.sin(d.angle), y: Math.cos(d.angle) };
  const delta = { x: pointer.x - opposite.x, y: pointer.y - opposite.y };
  const boxWidth = Math.max(2, Math.abs(delta.x * axisX.x + delta.y * axisX.y));
  const boxHeight = Math.max(
    2,
    Math.abs(delta.x * axisY.x + delta.y * axisY.y),
  );
  const center = {
    x:
      opposite.x +
      0.5 * (signs.x * boxWidth * axisX.x + signs.y * boxHeight * axisY.x),
    y:
      opposite.y +
      0.5 * (signs.x * boxWidth * axisX.y + signs.y * boxHeight * axisY.y),
  };
  const points = rotatedBoxPoints(center, boxWidth, boxHeight, d.angle);
  if (!rotatedBoxFitsImage(points, width, height)) return mask;
  return rotatedBoxMaskFromPoints(
    points,
    mask.label_class_id,
    mask.id,
    mask.persisted,
    mask.revision,
  );
}

export function rotatedBoxRotationHandle(
  points: Point[],
  distance = 30,
): Point {
  const d = rotatedBoxDimensions(points);
  const top = {
    x: (points[0].x + points[1].x) / 2,
    y: (points[0].y + points[1].y) / 2,
  };
  return {
    x: top.x + Math.sin(d.angle) * distance,
    y: top.y - Math.cos(d.angle) * distance,
  };
}

export function RotatedBoxLayer({
  width,
  height,
  masks,
  classColors,
  activeClassId,
  selectedMaskIds,
  onCreate,
  onUpdate,
  onSelectionChange,
}: RotatedBoxLayerProps) {
  const rotatedMasks = useMemo(
    () =>
      masks.filter(
        (mask) =>
          mask.geometry_kind === "rotated_box" && mask.points?.length === 4,
      ),
    [masks],
  );
  const [drag, setDrag] = useState<DragState | null>(null);
  const [preview, setPreview] = useState<EditorMaskAnnotation | null>(null);
  const selected = new Set(selectedMaskIds);

  function pointFor(event: PointerEvent<SVGSVGElement>): Point {
    return sourcePoint(
      event.currentTarget,
      event.clientX,
      event.clientY,
      width,
      height,
    );
  }

  function beginFromElement(
    event: PointerEvent<SVGElement>,
    state: Omit<DragState, "pointerId">,
  ): void {
    event.stopPropagation();
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    svg.setPointerCapture(event.pointerId);
    setDrag({ ...state, pointerId: event.pointerId });
  }

  function handleBackgroundDown(event: PointerEvent<SVGSVGElement>): void {
    if (
      event.button !== 0 ||
      event.target !== event.currentTarget ||
      activeClassId === null
    )
      return;
    const start = pointFor(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ kind: "create", pointerId: event.pointerId, start });
    setPreview(rotatedBoxFromDrag(start, start, activeClassId));
  }

  function handleMove(event: PointerEvent<SVGSVGElement>): void {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const point = pointFor(event);
    if (drag.kind === "create") {
      if (activeClassId)
        setPreview(rotatedBoxFromDrag(drag.start, point, activeClassId));
    } else if (drag.mask && drag.kind === "move") {
      setPreview(
        translateRotatedBox(
          drag.mask,
          point.x - drag.start.x,
          point.y - drag.start.y,
          width,
          height,
        ),
      );
    } else if (drag.mask && drag.kind === "rotate") {
      setPreview(rotateRotatedBox(drag.mask, point, width, height));
    } else if (
      drag.mask &&
      drag.kind === "resize" &&
      drag.cornerIndex !== undefined
    ) {
      setPreview(resizeRotatedBox(drag.mask, point, drag.cornerIndex, width, height));
    }
  }

  function finish(event: PointerEvent<SVGSVGElement>): void {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (preview?.points && (preview.area_pixels ?? 0) >= 4) {
      if (drag.kind === "create") onCreate(preview);
      else onUpdate(preview);
      onSelectionChange([preview.id]);
    }
    setDrag(null);
    setPreview(null);
  }

  const rendered = rotatedMasks.map((mask) =>
    preview?.id === mask.id ? preview : mask,
  );
  if (preview && drag?.kind === "create") rendered.push(preview);

  return (
    <svg
      aria-label="Rotated bounding box layer"
      data-testid="rotated-box-layer"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      onPointerDown={handleBackgroundDown}
      onPointerMove={handleMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        touchAction: "none",
        cursor: "crosshair",
      }}
    >
      {rendered.map((mask) => {
        if (!mask.points || mask.label_class_id === null) return null;
        const color = classColors[mask.label_class_id] ?? "#2a9d8f";
        const isSelected = selected.has(mask.id) || preview?.id === mask.id;
        const handle = rotatedBoxRotationHandle(mask.points);
        const points = mask.points
          .map((point) => `${point.x},${point.y}`)
          .join(" ");
        return (
          <g key={mask.id} data-rotated-box-id={mask.id}>
            <polygon
              points={points}
              fill={color}
              fillOpacity={isSelected ? 0.24 : 0.14}
              stroke={color}
              strokeWidth={isSelected ? 3 : 2}
              vectorEffect="non-scaling-stroke"
              style={{ cursor: "move" }}
              onPointerDown={(event) => {
                const svg = event.currentTarget.ownerSVGElement;
                if (!svg) return;
                onSelectionChange([mask.id]);
                setPreview(mask);
                beginFromElement(event, {
                  kind: "move",
                  start: sourcePoint(
                    svg,
                    event.clientX,
                    event.clientY,
                    width,
                    height,
                  ),
                  mask,
                });
              }}
            />
            {isSelected && (
              <>
                <line
                  x1={(mask.points[0].x + mask.points[1].x) / 2}
                  y1={(mask.points[0].y + mask.points[1].y) / 2}
                  x2={handle.x}
                  y2={handle.y}
                  stroke={color}
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
                <circle
                  cx={handle.x}
                  cy={handle.y}
                  r={7}
                  fill="#fff"
                  stroke={color}
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                  style={{ cursor: "grab" }}
                  onPointerDown={(event) => {
                    const svg = event.currentTarget.ownerSVGElement;
                    if (!svg) return;
                    setPreview(mask);
                    beginFromElement(event, {
                      kind: "rotate",
                      start: sourcePoint(
                        svg,
                        event.clientX,
                        event.clientY,
                        width,
                        height,
                      ),
                      mask,
                    });
                  }}
                />
                {mask.points.map((point, cornerIndex) => (
                  <rect
                    key={`${mask.id}-${cornerIndex}`}
                    x={point.x - 5}
                    y={point.y - 5}
                    width={10}
                    height={10}
                    fill="#fff"
                    stroke={color}
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                    style={{ cursor: "nwse-resize" }}
                    onPointerDown={(event) => {
                      const svg = event.currentTarget.ownerSVGElement;
                      if (!svg) return;
                      setPreview(mask);
                      beginFromElement(event, {
                        kind: "resize",
                        start: sourcePoint(
                          svg,
                          event.clientX,
                          event.clientY,
                          width,
                          height,
                        ),
                        mask,
                        cornerIndex,
                      });
                    }}
                  />
                ))}
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}
