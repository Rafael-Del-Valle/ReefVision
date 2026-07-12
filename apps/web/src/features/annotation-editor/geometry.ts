import type {
  EditorAnnotation,
  ImageSize,
  Point,
  ResizeHandle,
  ViewportTransform,
} from "./types";

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clampScale(scale: number): number {
  return clamp(scale, 0.1, 16);
}

export function boxWidth(annotation: EditorAnnotation): number {
  return annotation.x_max - annotation.x_min;
}

export function boxHeight(annotation: EditorAnnotation): number {
  return annotation.y_max - annotation.y_min;
}

export function boxArea(annotation: EditorAnnotation): number {
  return Math.max(0, boxWidth(annotation)) * Math.max(0, boxHeight(annotation));
}

export function createBoxFromPoints(
  start: Point,
  end: Point,
  imageSize: ImageSize,
): Omit<EditorAnnotation, "id" | "label_class_id"> {
  const x1 = clamp(start.x, 0, imageSize.width);
  const x2 = clamp(end.x, 0, imageSize.width);
  const y1 = clamp(start.y, 0, imageSize.height);
  const y2 = clamp(end.y, 0, imageSize.height);
  return {
    x_min: Math.min(x1, x2),
    y_min: Math.min(y1, y2),
    x_max: Math.max(x1, x2),
    y_max: Math.max(y1, y2),
  };
}

export function fitTransform(
  imageSize: ImageSize,
  containerSize: { width: number; height: number },
  padding = 32,
): ViewportTransform {
  const availableWidth = Math.max(1, containerSize.width - padding * 2);
  const availableHeight = Math.max(1, containerSize.height - padding * 2);
  const scale = clampScale(
    Math.min(
      availableWidth / imageSize.width,
      availableHeight / imageSize.height,
    ),
  );
  return {
    scale,
    offsetX: (containerSize.width - imageSize.width * scale) / 2,
    offsetY: (containerSize.height - imageSize.height * scale) / 2,
  };
}

export function screenToImage(
  point: Point,
  transform: ViewportTransform,
): Point {
  return {
    x: (point.x - transform.offsetX) / transform.scale,
    y: (point.y - transform.offsetY) / transform.scale,
  };
}

export function zoomAtPoint(
  transform: ViewportTransform,
  focusPoint: Point,
  nextScale: number,
): ViewportTransform {
  const scale = clampScale(nextScale);
  const imagePoint = screenToImage(focusPoint, transform);
  return {
    scale,
    offsetX: focusPoint.x - imagePoint.x * scale,
    offsetY: focusPoint.y - imagePoint.y * scale,
  };
}

export function translateAnnotations(
  annotations: EditorAnnotation[],
  delta: Point,
  imageSize: ImageSize,
): EditorAnnotation[] {
  const maxLeft = Math.max(...annotations.map((item) => -item.x_min));
  const maxUp = Math.max(...annotations.map((item) => -item.y_min));
  const maxRight = Math.min(
    ...annotations.map((item) => imageSize.width - item.x_max),
  );
  const maxDown = Math.min(
    ...annotations.map((item) => imageSize.height - item.y_max),
  );

  const dx = clamp(delta.x, maxLeft, maxRight);
  const dy = clamp(delta.y, maxUp, maxDown);

  return annotations.map((annotation) => ({
    ...annotation,
    x_min: annotation.x_min + dx,
    x_max: annotation.x_max + dx,
    y_min: annotation.y_min + dy,
    y_max: annotation.y_max + dy,
  }));
}

export function resizeAnnotation(
  annotation: EditorAnnotation,
  handle: ResizeHandle,
  point: Point,
  imageSize: ImageSize,
  minimumSize = 1,
): EditorAnnotation {
  let { x_min, y_min, x_max, y_max } = annotation;

  if (handle === "nw" || handle === "sw") {
    x_min = clamp(point.x, 0, x_max - minimumSize);
  }
  if (handle === "ne" || handle === "se") {
    x_max = clamp(point.x, x_min + minimumSize, imageSize.width);
  }
  if (handle === "nw" || handle === "ne") {
    y_min = clamp(point.y, 0, y_max - minimumSize);
  }
  if (handle === "sw" || handle === "se") {
    y_max = clamp(point.y, y_min + minimumSize, imageSize.height);
  }

  return {
    ...annotation,
    x_min,
    y_min,
    x_max,
    y_max,
  };
}
