import type { ViewportTransform } from "./types";

export interface ImageBounds {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

/**
 * Conservative image-space viewport. Unknown or invalid viewport geometry
 * disables culling, so imported scientific observations never disappear.
 */
export function viewportImageBounds(
  view: ViewportTransform | null,
  viewport: { width: number; height: number },
  paddingPixels = 32,
): ImageBounds | null {
  if (
    !view ||
    !Number.isFinite(view.scale) ||
    view.scale <= 0 ||
    !Number.isFinite(view.offsetX) ||
    !Number.isFinite(view.offsetY) ||
    !Number.isFinite(viewport.width) ||
    !Number.isFinite(viewport.height) ||
    viewport.width <= 0 ||
    viewport.height <= 0 ||
    !Number.isFinite(paddingPixels) ||
    paddingPixels < 0
  ) {
    return null;
  }
  return {
    x_min: (-paddingPixels - view.offsetX) / view.scale,
    y_min: (-paddingPixels - view.offsetY) / view.scale,
    x_max: (viewport.width + paddingPixels - view.offsetX) / view.scale,
    y_max: (viewport.height + paddingPixels - view.offsetY) / view.scale,
  };
}

/** Inclusive edge intersection; malformed or missing data is retained. */
export function intersectsViewport(
  bounds: ImageBounds,
  viewportBounds: ImageBounds | null,
): boolean {
  if (!viewportBounds) return true;
  if (
    !Number.isFinite(bounds.x_min) ||
    !Number.isFinite(bounds.y_min) ||
    !Number.isFinite(bounds.x_max) ||
    !Number.isFinite(bounds.y_max) ||
    bounds.x_min > bounds.x_max ||
    bounds.y_min > bounds.y_max
  ) {
    return true;
  }
  return (
    bounds.x_max >= viewportBounds.x_min &&
    bounds.x_min <= viewportBounds.x_max &&
    bounds.y_max >= viewportBounds.y_min &&
    bounds.y_min <= viewportBounds.y_max
  );
}

/** Filters only SVG nodes; callers retain their original full dataset. */
export function cullViewportItems<T extends ImageBounds>(
  items: T[],
  viewportBounds: ImageBounds | null,
): T[] {
  if (!viewportBounds) return items;
  return items.filter((item) => intersectsViewport(item, viewportBounds));
}
