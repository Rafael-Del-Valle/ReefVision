import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";

import { rasterMaskContentUrl } from "./rasterMaskApi";
import type {
  EditorMaskAnnotation,
  EditorTool,
  Point,
} from "./types";

interface PolygonMaskLayerProps {
  width: number;
  height: number;
  masks: EditorMaskAnnotation[];
  classColors: Record<string, string>;
  hiddenClassIds?: string[];
  activeClassId: string | null;
  tool: EditorTool;
  selectedMaskIds: string[];
  onCreate: (mask: EditorMaskAnnotation) => void;
  onUpdate: (mask: EditorMaskAnnotation) => void;
  onSelectionChange: (maskIds: string[]) => void;
  onDeleteMaskIds?: (maskIds: string[]) => void;
}

interface VertexDrag {
  maskId: string;
  pointIndex: number;
  pointerId: number;
}

interface PolygonMetrics {
  areaPixels: number;
  xMin: number;
  yMin: number;
  xMax: number;
  yMax: number;
}

interface SegmentProjection {
  point: Point;
  distanceSquared: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function generatedMaskId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `mask-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function projectToSegment(
  point: Point,
  start: Point,
  end: Point,
): SegmentProjection {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  const lengthSquared = deltaX * deltaX + deltaY * deltaY;
  const fraction =
    lengthSquared === 0
      ? 0
      : clamp(
          ((point.x - start.x) * deltaX + (point.y - start.y) * deltaY) /
            lengthSquared,
          0,
          1,
        );
  const projected = {
    x: start.x + fraction * deltaX,
    y: start.y + fraction * deltaY,
  };
  return {
    point: projected,
    distanceSquared:
      (point.x - projected.x) ** 2 + (point.y - projected.y) ** 2,
  };
}

export function insertPolygonVertex(points: Point[], point: Point): Point[] {
  if (points.length < 2) {
    return points.map((existing) => ({ ...existing }));
  }

  let nearestEdgeIndex = 0;
  let nearestProjection = projectToSegment(point, points[0], points[1]);
  for (let index = 1; index < points.length; index += 1) {
    const projection = projectToSegment(
      point,
      points[index],
      points[(index + 1) % points.length],
    );
    if (projection.distanceSquared < nearestProjection.distanceSquared) {
      nearestEdgeIndex = index;
      nearestProjection = projection;
    }
  }

  const next = points.map((existing) => ({ ...existing }));
  next.splice(nearestEdgeIndex + 1, 0, nearestProjection.point);
  return next;
}

export function removePolygonVertex(
  points: Point[],
  pointIndex: number,
): Point[] {
  if (points.length <= 3 || pointIndex < 0 || pointIndex >= points.length) {
    return points.map((point) => ({ ...point }));
  }
  return points
    .filter((_, index) => index !== pointIndex)
    .map((point) => ({ ...point }));
}

export function polygonMetrics(points: Point[]): PolygonMetrics {
  if (points.length < 3) {
    throw new Error("A polygon mask requires at least three points");
  }
  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);
  const signedDoubleArea = points.reduce((total, point, index) => {
    const next = points[(index + 1) % points.length];
    return total + point.x * next.y - next.x * point.y;
  }, 0);
  return {
    areaPixels: Math.max(1, Math.round(Math.abs(signedDoubleArea) / 2)),
    xMin: Math.min(...xValues),
    yMin: Math.min(...yValues),
    xMax: Math.max(...xValues),
    yMax: Math.max(...yValues),
  };
}

export function polygonMaskFromPoints(
  points: Point[],
  labelClassId: string,
  id = generatedMaskId(),
  persisted = false,
): EditorMaskAnnotation {
  const metrics = polygonMetrics(points);
  return {
    id,
    label_class_id: labelClassId,
    geometry_kind: "polygon",
    points: points.map((point) => ({ ...point })),
    mask_path: null,
    x_min: metrics.xMin,
    y_min: metrics.yMin,
    x_max: metrics.xMax,
    y_max: metrics.yMax,
    area_pixels: metrics.areaPixels,
    source_type: "human",
    persisted,
  };
}

export function PolygonMaskLayer({
  width,
  height,
  masks,
  classColors,
  hiddenClassIds = [],
  activeClassId,
  tool,
  selectedMaskIds,
  onCreate,
  onUpdate,
  onSelectionChange,
  onDeleteMaskIds,
}: PolygonMaskLayerProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [draftPoints, setDraftPoints] = useState<Point[]>([]);
  const [pointerPosition, setPointerPosition] = useState<Point | null>(null);
  const [vertexDrag, setVertexDrag] = useState<VertexDrag | null>(null);
  const [dragPreview, setDragPreview] = useState<EditorMaskAnnotation | null>(
    null,
  );

  const hiddenClasses = useMemo(
    () => new Set(hiddenClassIds),
    [hiddenClassIds],
  );
  const selectedMasks = useMemo(
    () => new Set(selectedMaskIds),
    [selectedMaskIds],
  );

  useEffect(() => {
    if (tool !== "polygon") {
      setDraftPoints([]);
      setPointerPosition(null);
    }
  }, [tool]);

  function sourcePoint(
    svg: SVGSVGElement,
    clientX: number,
    clientY: number,
  ): Point {
    const bounds = svg.getBoundingClientRect();
    const normalizedX =
      bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0;
    const normalizedY =
      bounds.height > 0 ? (clientY - bounds.top) / bounds.height : 0;
    return {
      x: clamp(normalizedX * width, 0, width),
      y: clamp(normalizedY * height, 0, height),
    };
  }

  function imagePoint(event: PointerEvent<SVGSVGElement>): Point {
    return sourcePoint(event.currentTarget, event.clientX, event.clientY);
  }

  function finishDraft() {
    if (draftPoints.length < 3 || activeClassId === null) {
      return;
    }
    onCreate(polygonMaskFromPoints(draftPoints, activeClassId));
    setDraftPoints([]);
    setPointerPosition(null);
  }

  function updatedMask(
    sourceMask: EditorMaskAnnotation,
    points: Point[],
  ): EditorMaskAnnotation {
    const updated = polygonMaskFromPoints(
      points,
      sourceMask.label_class_id ?? activeClassId ?? "",
      sourceMask.id,
      sourceMask.persisted,
    );
    return { ...updated, revision: sourceMask.revision };
  }

  function selectMask(maskId: string, additive: boolean) {
    if (additive) {
      onSelectionChange(
        selectedMasks.has(maskId)
          ? selectedMaskIds.filter((id) => id !== maskId)
          : [...selectedMaskIds, maskId],
      );
      return;
    }
    onSelectionChange([maskId]);
  }

  function handleBackgroundPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.target !== event.currentTarget) {
      return;
    }
    svgRef.current?.focus();
    if (tool === "select") {
      onSelectionChange([]);
      return;
    }
    if (tool !== "polygon" || activeClassId === null) {
      return;
    }
    const point = imagePoint(event);
    setDraftPoints((current) => [...current, point]);
    setPointerPosition(point);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const point = imagePoint(event);
    if (vertexDrag !== null) {
      const sourceMask =
        dragPreview?.id === vertexDrag.maskId
          ? dragPreview
          : masks.find((mask) => mask.id === vertexDrag.maskId) ?? null;
      if (!sourceMask?.points) {
        return;
      }
      const nextPoints = sourceMask.points.map((existingPoint, index) =>
        index === vertexDrag.pointIndex ? point : existingPoint,
      );
      setDragPreview(updatedMask(sourceMask, nextPoints));
      return;
    }
    if (tool === "polygon" && draftPoints.length > 0) {
      setPointerPosition(point);
    }
  }

  function handlePointerUp(event: PointerEvent<SVGSVGElement>) {
    if (vertexDrag === null || event.pointerId !== vertexDrag.pointerId) {
      return;
    }
    if (dragPreview !== null) {
      onUpdate(dragPreview);
    }
    setVertexDrag(null);
    setDragPreview(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key === "Escape") {
      setDraftPoints([]);
      setPointerPosition(null);
      setVertexDrag(null);
      setDragPreview(null);
      return;
    }
    if (tool === "polygon" && event.key === "Enter") {
      event.preventDefault();
      finishDraft();
      return;
    }
    if (
      tool === "polygon" &&
      event.key === "Backspace" &&
      draftPoints.length > 0
    ) {
      event.preventDefault();
      setDraftPoints((current) => current.slice(0, -1));
      return;
    }
    if (
      tool === "select" &&
      (event.key === "Delete" || event.key === "Backspace") &&
      selectedMaskIds.length > 0 &&
      onDeleteMaskIds
    ) {
      event.preventDefault();
      onDeleteMaskIds(selectedMaskIds);
    }
  }

  function insertVertex(
    event: MouseEvent<SVGPolygonElement>,
    mask: EditorMaskAnnotation,
  ) {
    if (tool !== "select" || mask.points === null) {
      return;
    }
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) {
      return;
    }
    event.stopPropagation();
    const point = sourcePoint(svg, event.clientX, event.clientY);
    onUpdate(updatedMask(mask, insertPolygonVertex(mask.points, point)));
    onSelectionChange([mask.id]);
  }

  const draftPolyline =
    draftPoints.length > 0 && pointerPosition !== null
      ? [...draftPoints, pointerPosition]
      : draftPoints;

  return (
    <svg
      ref={svgRef}
      aria-label="Polygon mask layer"
      data-testid="polygon-mask-layer"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      tabIndex={0}
      onPointerDown={handleBackgroundPointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onKeyDown={handleKeyDown}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        overflow: "visible",
        touchAction: "none",
      }}
    >
      {masks.map((sourceMask) => {
        const mask = dragPreview?.id === sourceMask.id ? dragPreview : sourceMask;
        if (
          mask.label_class_id !== null &&
          hiddenClasses.has(mask.label_class_id)
        ) {
          return null;
        }
        const selected = selectedMasks.has(mask.id);
        const color =
          (mask.label_class_id && classColors[mask.label_class_id]) || "#2a9d8f";

        if (mask.geometry_kind === "raster_mask" && mask.mask_path !== null) {
          return (
            <image
              key={mask.id}
              data-mask-id={mask.id}
              href={rasterMaskContentUrl(mask)}
              x={0}
              y={0}
              width={width}
              height={height}
              opacity={selected ? 0.55 : 0.35}
              style={{ cursor: tool === "select" ? "pointer" : "default" }}
              onPointerDown={(event) => {
                event.stopPropagation();
                if (tool === "select") {
                  selectMask(mask.id, event.shiftKey);
                }
              }}
            />
          );
        }

        if (mask.points === null || mask.points.length < 3) {
          return null;
        }
        const pointText = mask.points
          .map((point) => `${point.x},${point.y}`)
          .join(" ");
        return (
          <g key={mask.id} data-mask-id={mask.id}>
            <polygon
              points={pointText}
              fill={color}
              fillOpacity={selected ? 0.35 : 0.22}
              stroke={color}
              strokeWidth={selected ? 3 : 2}
              vectorEffect="non-scaling-stroke"
              style={{ cursor: tool === "select" ? "pointer" : "default" }}
              onDoubleClick={(event) => insertVertex(event, mask)}
              onPointerDown={(event) => {
                event.stopPropagation();
                if (tool === "select") {
                  selectMask(mask.id, event.shiftKey);
                }
              }}
            />
            {selected &&
              tool === "select" &&
              mask.points.map((point, pointIndex) => (
                <circle
                  key={`${mask.id}-${pointIndex}`}
                  data-testid={`mask-vertex-${mask.id}-${pointIndex}`}
                  cx={point.x}
                  cy={point.y}
                  r={5}
                  fill="#ffffff"
                  stroke={color}
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                  style={{ cursor: "move" }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    if (event.altKey) {
                      const nextPoints = removePolygonVertex(
                        mask.points ?? [],
                        pointIndex,
                      );
                      if (nextPoints.length !== mask.points?.length) {
                        onUpdate(updatedMask(mask, nextPoints));
                      }
                      return;
                    }
                    event.currentTarget.ownerSVGElement?.setPointerCapture(
                      event.pointerId,
                    );
                    setVertexDrag({
                      maskId: mask.id,
                      pointIndex,
                      pointerId: event.pointerId,
                    });
                    setDragPreview(mask);
                  }}
                />
              ))}
          </g>
        );
      })}

      {draftPolyline.length > 0 && (
        <polyline
          data-testid="polygon-draft"
          points={draftPolyline
            .map((point) => `${point.x},${point.y}`)
            .join(" ")}
          fill="none"
          stroke={(activeClassId && classColors[activeClassId]) || "#2a9d8f"}
          strokeWidth={2}
          strokeDasharray="8 5"
          vectorEffect="non-scaling-stroke"
          pointerEvents="none"
        />
      )}
      {draftPoints.map((point, index) => (
        <circle
          key={`draft-${index}`}
          data-testid={`polygon-draft-point-${index}`}
          cx={point.x}
          cy={point.y}
          r={index === 0 && draftPoints.length >= 3 ? 7 : 4}
          fill="#ffffff"
          stroke={(activeClassId && classColors[activeClassId]) || "#2a9d8f"}
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
          style={{
            cursor:
              index === 0 && draftPoints.length >= 3 ? "pointer" : "default",
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            if (index === 0 && draftPoints.length >= 3) {
              finishDraft();
            }
          }}
        />
      ))}
    </svg>
  );
}
