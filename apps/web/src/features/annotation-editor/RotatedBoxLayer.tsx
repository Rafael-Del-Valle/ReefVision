import { useMemo, useState, type PointerEvent } from "react";

import { polygonMetrics } from "./PolygonMaskLayer";
import type { EditorMaskAnnotation, Point } from "./types";

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
  creationClassId?: string;
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

function centerOf(points: Point[]): Point {
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
}

function dimensions(points: Point[]) {
  return {
    center: centerOf(points),
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
  // User-drawn boxes must have a stable winding regardless of drag direction.
  // Historically reverse-axis drags persisted counter-wound rectangles that
  // the rotation and resize tools could otherwise reinterpret.
  const left = Math.min(start.x, end.x);
  const right = Math.max(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const bottom = Math.max(start.y, end.y);
  return rotatedBoxMaskFromPoints(
    [
      { x: left, y: top },
      { x: right, y: top },
      { x: right, y: bottom },
      { x: left, y: bottom },
    ],
    labelClassId,
    id,
    false,
  );
}

// Original saved masks may predate canonical drawing order. Preserve their
// vertex winding when transforming a rectangle, rather than silently flipping
// its point identity and changing measurement provenance.
function boxWinding(points: Point[]): 1 | -1 {
  const edgeX = {
    x: points[1].x - points[0].x,
    y: points[1].y - points[0].y,
  };
  const edgeY = {
    x: points[3].x - points[0].x,
    y: points[3].y - points[0].y,
  };
  return edgeX.x * edgeY.y - edgeX.y * edgeY.x < 0 ? -1 : 1;
}

function orientedBoxPoints(
  center: Point,
  boxWidth: number,
  boxHeight: number,
  angle: number,
  winding: 1 | -1,
): Point[] {
  const points = rotatedBoxPoints(center, boxWidth, boxHeight, angle);
  return winding === 1 ? points : points.reverse();
}

function inside(points: Point[], width: number, height: number): boolean {
  return points.every(
    (point) =>
      point.x >= 0 && point.y >= 0 && point.x <= width && point.y <= height,
  );
}

// Restored biological observations may contain damaged four-point geometry
// even when cached area metadata claims a valid rotated box. Never turn that
// input into a new scientific revision through an editor gesture.
function editableRotatedBox(
  mask: EditorMaskAnnotation,
  width: number,
  height: number,
): boolean {
  const points = mask.points;
  if (
    !points ||
    points.length !== 4 ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    return false;
  }
  for (let index = 0; index < 4; index += 1) {
    const point = points[index];
    if (
      !point ||
      !Number.isFinite(point.x) ||
      !Number.isFinite(point.y) ||
      point.x < 0 ||
      point.x > width ||
      point.y < 0 ||
      point.y > height
    ) {
      return false;
    }
  }
  const topEdge = Math.hypot(
    points[1].x - points[0].x,
    points[1].y - points[0].y,
  );
  const sideEdge = Math.hypot(
    points[2].x - points[1].x,
    points[2].y - points[1].y,
  );
  if (!(topEdge > 0) || !(sideEdge > 0)) return false;

  // Four finite, positive-area points need not describe a rectangle:
  // corrupted imports can be sheared, concave or nonorthogonal. Rotation and
  // resize reconstruct a rectangle, which would silently change that evidence.
  const right = {
    x: points[1].x - points[0].x,
    y: points[1].y - points[0].y,
  };
  const down = {
    x: points[3].x - points[0].x,
    y: points[3].y - points[0].y,
  };
  const downEdge = Math.hypot(down.x, down.y);
  const symmetryError = Math.hypot(
    points[2].x - points[1].x - down.x,
    points[2].y - points[1].y - down.y,
  );
  if (
    !(downEdge > 0) ||
    symmetryError > 1e-8 * Math.max(topEdge, downEdge, 1) ||
    Math.abs(right.x * down.x + right.y * down.y) > 1e-8 * topEdge * downEdge
  ) {
    return false;
  }

  let signedDoubleArea = 0;
  for (let index = 0; index < 4; index += 1) {
    const next = points[(index + 1) % 4];
    signedDoubleArea += points[index].x * next.y - next.x * points[index].y;
  }
  return Number.isFinite(signedDoubleArea) && Math.abs(signedDoubleArea) > 1e-9;
}

function translate(
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

function rotate(
  mask: EditorMaskAnnotation,
  pointer: Point,
  width: number,
  height: number,
): EditorMaskAnnotation {
  if (!mask.points || mask.label_class_id === null) return mask;
  const d = dimensions(mask.points);
  const winding = boxWinding(mask.points);
  const angle =
    Math.atan2(pointer.y - d.center.y, pointer.x - d.center.x) +
    (winding * Math.PI) / 2;
  const points = orientedBoxPoints(d.center, d.width, d.height, angle, winding);
  if (!inside(points, width, height)) return mask;
  return rotatedBoxMaskFromPoints(
    points,
    mask.label_class_id,
    mask.id,
    mask.persisted,
    mask.revision,
  );
}

function resize(
  mask: EditorMaskAnnotation,
  pointer: Point,
  cornerIndex: number,
  width: number,
  height: number,
): EditorMaskAnnotation {
  if (!mask.points || mask.label_class_id === null) return mask;
  const d = dimensions(mask.points);
  const opposite = mask.points[(cornerIndex + 2) % 4];
  const signs = [
    { x: -1, y: -1 },
    { x: 1, y: -1 },
    { x: 1, y: 1 },
    { x: -1, y: 1 },
  ][cornerIndex];
  const winding = boxWinding(mask.points);
  const axisX = { x: Math.cos(d.angle), y: Math.sin(d.angle) };
  const axisY = {
    x: -winding * Math.sin(d.angle),
    y: winding * Math.cos(d.angle),
  };
  const delta = { x: pointer.x - opposite.x, y: pointer.y - opposite.y };
  const horizontal = delta.x * axisX.x + delta.y * axisX.y;
  const vertical = delta.x * axisY.x + delta.y * axisY.y;
  // Preserve which side of the fixed opposite vertex the grabbed corner
  // belongs to. Absolute projection lengths would reflect the box when a
  // pointer crosses that vertex, silently relocating biological geometry.
  // Keep the existing two-source-pixel minimum without flipping its axes.
  const boxWidth = Math.max(2, signs.x * horizontal);
  const boxHeight = Math.max(2, signs.y * vertical);
  const center = {
    x:
      opposite.x +
      0.5 * (signs.x * boxWidth * axisX.x + signs.y * boxHeight * axisY.x),
    y:
      opposite.y +
      0.5 * (signs.x * boxWidth * axisX.y + signs.y * boxHeight * axisY.y),
  };
  const points = orientedBoxPoints(
    center,
    boxWidth,
    boxHeight,
    d.angle,
    winding,
  );
  if (!inside(points, width, height)) return mask;
  return rotatedBoxMaskFromPoints(
    points,
    mask.label_class_id,
    mask.id,
    mask.persisted,
    mask.revision,
  );
}

function rotationHandle(points: Point[]): Point {
  const d = dimensions(points);
  const top = {
    x: (points[0].x + points[1].x) / 2,
    y: (points[0].y + points[1].y) / 2,
  };
  return {
    x: top.x + boxWinding(points) * Math.sin(d.angle) * 30,
    y: top.y - boxWinding(points) * Math.cos(d.angle) * 30,
  };
}

// Rotated scientific observations should be revised only when their source-pixel
// geometry changes; floating-point roundoff during rotation is not an edit.
function unchangedRotatedBoxGeometry(
  before: EditorMaskAnnotation,
  after: EditorMaskAnnotation,
): boolean {
  const original = before.points;
  const edited = after.points;
  return (
    before.label_class_id === after.label_class_id &&
    original !== null &&
    edited !== null &&
    original.length === edited.length &&
    original.every((point, index) => {
      const next = edited[index];
      return (
        next !== undefined &&
        Math.abs(point.x - next.x) <= 1e-9 &&
        Math.abs(point.y - next.y) <= 1e-9
      );
    })
  );
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
    if (
      drag !== null ||
      event.button !== 0 ||
      !state.mask ||
      !editableRotatedBox(state.mask, width, height)
    ) {
      return;
    }
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    svg.setPointerCapture(event.pointerId);
    setPreview(state.mask);
    setDrag({ ...state, pointerId: event.pointerId });
  }

  function handleBackgroundDown(event: PointerEvent<SVGSVGElement>): void {
    if (
      event.button !== 0 ||
      drag !== null ||
      event.target !== event.currentTarget ||
      activeClassId === null
    )
      return;
    const start = pointFor(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    // Freeze the biological class chosen when the gesture began, so toolbar
    // changes while dragging cannot silently relabel the observation.
    setDrag({
      kind: "create",
      pointerId: event.pointerId,
      start,
      creationClassId: activeClassId,
    });
    setPreview(rotatedBoxFromDrag(start, start, activeClassId));
  }

  function handleMove(event: PointerEvent<SVGSVGElement>): void {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const point = pointFor(event);
    if (drag.kind === "create") {
      if (drag.creationClassId)
        setPreview(rotatedBoxFromDrag(drag.start, point, drag.creationClassId));
    } else if (drag.mask && drag.kind === "move") {
      setPreview(
        translate(
          drag.mask,
          point.x - drag.start.x,
          point.y - drag.start.y,
          width,
          height,
        ),
      );
    } else if (drag.mask && drag.kind === "rotate") {
      setPreview(rotate(drag.mask, point, width, height));
    } else if (
      drag.mask &&
      drag.kind === "resize" &&
      drag.cornerIndex !== undefined
    ) {
      setPreview(resize(drag.mask, point, drag.cornerIndex, width, height));
    }
  }

  function finish(event: PointerEvent<SVGSVGElement>): void {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (preview?.points && (preview.area_pixels ?? 0) >= 4) {
      if (drag.kind === "create") {
        onCreate(preview);
        onSelectionChange([preview.id]);
      } else if (
        drag.mask &&
        !unchangedRotatedBoxGeometry(drag.mask, preview)
      ) {
        onUpdate(preview);
        onSelectionChange([preview.id]);
      }
    }
    setDrag(null);
    setPreview(null);
  }

  function cancel(event: PointerEvent<SVGSVGElement>): void {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    // A cancelled edit is a preview, never a committed scientific revision.
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
      onPointerCancel={cancel}
      onLostPointerCapture={cancel}
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
        const handle = editableRotatedBox(mask, width, height)
          ? rotationHandle(mask.points)
          : null;
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
                if (drag !== null || event.button !== 0) {
                  event.stopPropagation();
                  return;
                }
                const svg = event.currentTarget.ownerSVGElement;
                if (!svg) return;
                onSelectionChange([mask.id]);
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
            {isSelected && handle && (
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
                    if (drag !== null || event.button !== 0) {
                      event.stopPropagation();
                      return;
                    }
                    const svg = event.currentTarget.ownerSVGElement;
                    if (!svg) return;
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
                      if (drag !== null || event.button !== 0) {
                        event.stopPropagation();
                        return;
                      }
                      const svg = event.currentTarget.ownerSVGElement;
                      if (!svg) return;
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
