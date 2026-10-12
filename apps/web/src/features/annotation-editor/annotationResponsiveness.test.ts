import { describe, expect, it } from "vitest";

import { resolveGalleryNavigation } from "../gallery/galleryNavigation";
import { imageToScreen, screenToImage, zoomAtPoint } from "./geometry";
import {
  pasteAnnotations,
  type AnnotationClipboard,
} from "./annotationClipboard";
import { resolveRasterMaskSelection } from "./rasterMaskSelection";

function measure(operation: () => void): number {
  const started = performance.now();
  operation();
  return performance.now() - started;
}

describe("representative annotation responsiveness scenarios", () => {
  it("records reproducible interaction-kernel timings without changing geometry", () => {
    let destination: ReturnType<typeof resolveGalleryNavigation> = null;
    const imageSwitchMs = measure(() => {
      for (let index = 0; index < 100_000; index += 1) {
        destination = resolveGalleryNavigation({
          action: index % 2 ? "next" : "previous",
          index: index % 24,
          itemCount: 24,
          page: 50_000,
          pages: 100_000,
          wrap: false,
        });
      }
    });
    expect(destination).not.toBeNull();

    let transform = { scale: 1, offsetX: 0, offsetY: 0 };
    const sourcePoint = { x: 7_990, y: 5_990 };
    let roundTrip = sourcePoint;
    const zoomPanMs = measure(() => {
      for (let index = 0; index < 100_000; index += 1) {
        transform = zoomAtPoint(
          transform,
          { x: 960, y: 540 },
          index % 2 ? transform.scale * 1.001 : transform.scale / 1.001,
        );
        transform = {
          ...transform,
          offsetX: transform.offsetX + 0.01,
          offsetY: transform.offsetY - 0.01,
        };
        roundTrip = screenToImage(
          imageToScreen(sourcePoint, transform),
          transform,
        );
      }
    });
    expect(roundTrip.x).toBeCloseTo(sourcePoint.x, 8);
    expect(roundTrip.y).toBeCloseTo(sourcePoint.y, 8);

    const polygonItems: AnnotationClipboard["items"] = Array.from(
      { length: 500 },
      (_, index) => ({
        kind: "polygon" as const,
        labelClassId: "coral",
        points: [
          { x: index * 2, y: 10 },
          { x: index * 2 + 1, y: 10 },
          { x: index * 2 + 1, y: 12 },
        ],
      }),
    );
    let pastedCount = 0;
    const polygonInteractionMs = measure(() => {
      const result = pasteAnnotations(
        {
          sourceImage: { id: "large-image", width: 8_192, height: 6_144 },
          items: polygonItems,
          rasterMaskIds: [],
          pasteCount: 0,
          skippedRasterCount: 0,
        },
        { id: "large-image", width: 8_192, height: 6_144 },
        () => `copy-${pastedCount++}`,
      );
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.maskAnnotations).toHaveLength(500);
    });

    const masks = Array.from({ length: 10_000 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    let selected: string | null = null;
    const rasterSelectionMs = measure(() => {
      for (let index = 0; index < 100; index += 1) {
        selected = resolveRasterMaskSelection("mask-9999", masks, false);
      }
    });
    expect(selected).toBe("mask-9999");

    const measurements = {
      image_switch_100k_ms: imageSwitchMs,
      zoom_pan_100k_ms: zoomPanMs,
      polygon_duplicate_500_ms: polygonInteractionMs,
      raster_selection_10k_x100_ms: rasterSelectionMs,
    };
    console.info("REEFVISION_RESPONSIVENESS", JSON.stringify(measurements));
    Object.values(measurements).forEach((duration) => {
      expect(Number.isFinite(duration)).toBe(true);
      expect(duration).toBeLessThan(2_000);
    });
  });
});
