import type {
  AnnotationDocument,
  EditorAnnotation,
  EditorMaskAnnotation,
  Point,
} from "./types";

interface ClipboardImage {
  id: string;
  projectId: string;
  width: number;
  height: number;
}

interface ClipboardBox {
  kind: "box";
  labelClassId: string;
  xMin: number;
  yMin: number;
  xMax: number;
  yMax: number;
}

interface ClipboardPolygon {
  kind: "polygon" | "rotated_box";
  labelClassId: string;
  points: Point[];
}

type ClipboardItem = ClipboardBox | ClipboardPolygon;

export interface AnnotationClipboard {
  sourceImage: ClipboardImage;
  items: ClipboardItem[];
  rasterMaskIds: string[];
  pasteCount: number;
  skippedRasterCount: number;
}

export interface ClipboardPaste {
  ok: true;
  annotations: EditorAnnotation[];
  maskAnnotations: EditorMaskAnnotation[];
  nextClipboard: AnnotationClipboard;
}

export type ClipboardPasteResult =
  ClipboardPaste | { ok: false; reason: string };

let internalClipboard: AnnotationClipboard | null = null;

export function readInternalAnnotationClipboard(): AnnotationClipboard | null {
  return internalClipboard;
}

export function writeInternalAnnotationClipboard(
  clipboard: AnnotationClipboard,
): void {
  internalClipboard = clipboard;
}

export function copyAnnotations(
  document: AnnotationDocument,
  selectedIds: string[],
  selectedMaskIds: string[],
  sourceImage: ClipboardImage,
): AnnotationClipboard {
  const boxIds = new Set(selectedIds);
  const maskIds = new Set(selectedMaskIds);
  const boxes: ClipboardBox[] = document.annotations
    .filter((annotation) => boxIds.has(annotation.id))
    .map((annotation) => ({
      kind: "box",
      labelClassId: annotation.label_class_id,
      xMin: annotation.x_min,
      yMin: annotation.y_min,
      xMax: annotation.x_max,
      yMax: annotation.y_max,
    }));
  const selectedMasks = document.maskAnnotations.filter((mask) =>
    maskIds.has(mask.id),
  );
  const polygons: ClipboardPolygon[] = selectedMasks.flatMap((mask) => {
    if (
      (mask.geometry_kind !== "polygon" &&
        mask.geometry_kind !== "rotated_box") ||
      !mask.label_class_id ||
      !mask.points
    ) {
      return [];
    }
    return [
      {
        kind: mask.geometry_kind,
        labelClassId: mask.label_class_id,
        points: mask.points.map((point) => ({ ...point })),
      },
    ];
  });
  return {
    sourceImage: { ...sourceImage },
    items: [...boxes, ...polygons],
    rasterMaskIds: selectedMasks
      .filter((mask) => mask.geometry_kind === "raster_mask")
      .map((mask) => mask.id),
    pasteCount: 0,
    skippedRasterCount: selectedMasks.filter(
      (mask) => mask.geometry_kind === "raster_mask",
    ).length,
  };
}

function itemPoints(item: ClipboardItem): Point[] {
  return item.kind === "box"
    ? [
        { x: item.xMin, y: item.yMin },
        { x: item.xMax, y: item.yMax },
      ]
    : item.points;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export function pasteAnnotations(
  clipboard: AnnotationClipboard,
  targetImage: ClipboardImage,
  createId: () => string,
): ClipboardPasteResult {
  if (clipboard.items.length === 0) {
    return {
      ok: false,
      reason: clipboard.rasterMaskIds.length
        ? "Open the brush workspace to paste copied raster masks."
        : "Copy an annotation before pasting.",
    };
  }
  if (clipboard.sourceImage.projectId !== targetImage.projectId) {
    return {
      ok: false,
      reason:
        "Clipboard annotations belong to a different project. ReefVision will not transfer class IDs or scientific provenance between projects.",
    };
  }
  if (
    clipboard.sourceImage.width !== targetImage.width ||
    clipboard.sourceImage.height !== targetImage.height
  ) {
    return {
      ok: false,
      reason: `Clipboard geometry uses ${clipboard.sourceImage.width}×${clipboard.sourceImage.height} source pixels; the current image is ${targetImage.width}×${targetImage.height}. ReefVision will not rescale scientific geometry.`,
    };
  }

  const points = clipboard.items.flatMap(itemPoints);
  if (
    points.length === 0 ||
    points.some(
      (point) =>
        !Number.isFinite(point.x) ||
        !Number.isFinite(point.y) ||
        point.x < 0 ||
        point.y < 0 ||
        point.x > clipboard.sourceImage.width ||
        point.y > clipboard.sourceImage.height,
    )
  ) {
    return {
      ok: false,
      reason: "Clipboard geometry is invalid or outside its source image.",
    };
  }

  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  const requestedOffset = 12 * (clipboard.pasteCount + 1);
  const dx = clamp(requestedOffset, -minX, targetImage.width - maxX);
  const dy = clamp(requestedOffset, -minY, targetImage.height - maxY);
  const translated = (point: Point): Point => ({
    x: point.x + dx,
    y: point.y + dy,
  });

  const annotations: EditorAnnotation[] = [];
  const maskAnnotations: EditorMaskAnnotation[] = [];
  for (const item of clipboard.items) {
    if (item.kind === "box") {
      annotations.push({
        id: createId(),
        label_class_id: item.labelClassId,
        x_min: item.xMin + dx,
        y_min: item.yMin + dy,
        x_max: item.xMax + dx,
        y_max: item.yMax + dy,
      });
      continue;
    }
    const translatedPoints = item.points.map(translated);
    const xs = translatedPoints.map((point) => point.x);
    const ys = translatedPoints.map((point) => point.y);
    maskAnnotations.push({
      id: createId(),
      label_class_id: item.labelClassId,
      geometry_kind: item.kind,
      points: translatedPoints,
      mask_path: null,
      x_min: Math.min(...xs),
      y_min: Math.min(...ys),
      x_max: Math.max(...xs),
      y_max: Math.max(...ys),
      area_pixels: null,
      source_type: "human",
      verification_status: "draft",
      persisted: false,
    });
  }

  return {
    ok: true,
    annotations,
    maskAnnotations,
    nextClipboard: {
      ...clipboard,
      pasteCount: clipboard.pasteCount + 1,
    },
  };
}
