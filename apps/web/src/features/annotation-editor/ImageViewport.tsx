import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { actualSizeTransform, fitTransform, zoomAtPoint } from "./geometry";
import type { ViewportTransform } from "./types";

const FALLBACK_SIZE = { width: 1200, height: 780 };

export function ImageViewport({
  width,
  height,
  label,
  children,
}: {
  width: number;
  height: number;
  label: string;
  children: ReactNode;
}) {
  // An imported image with missing, fractional or nonfinite pixel dimensions
  // cannot safely map annotations to the displayed source-image coordinate frame.
  // Keep its overlays unmounted until valid metadata is supplied; never infer
  // biological coordinates from the fallback viewport size.
  const hasValidImageSize =
    Number.isSafeInteger(width) &&
    Number.isSafeInteger(height) &&
    width > 0 &&
    height > 0;
  const frameRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<ViewportTransform>(
    fitTransform(
      hasValidImageSize ? { width, height } : FALLBACK_SIZE,
      FALLBACK_SIZE,
    ),
  );
  const dragRef = useRef<{
    pointerId: number;
    x: number;
    y: number;
  } | null>(null);
  const [frameSize, setFrameSize] = useState(FALLBACK_SIZE);
  const [view, setView] = useState(viewRef.current);

  const updateView = useCallback((next: ViewportTransform) => {
    // Unreliable pointer/media metadata must never poison the displayed
    // transform: a nonfinite offset would make every scientific overlay vanish.
    if (
      !Number.isFinite(next.scale) ||
      next.scale <= 0 ||
      !Number.isFinite(next.offsetX) ||
      !Number.isFinite(next.offsetY)
    ) {
      return;
    }
    viewRef.current = next;
    setView(next);
  }, []);

  const fit = useCallback(() => {
    dragRef.current = null;
    if (!hasValidImageSize) return;
    updateView(fitTransform({ width, height }, frameSize));
  }, [frameSize, hasValidImageSize, height, updateView, width]);

  const actualSize = useCallback(() => {
    dragRef.current = null;
    if (!hasValidImageSize) return;
    updateView(actualSizeTransform({ width, height }, frameSize));
  }, [frameSize, hasValidImageSize, height, updateView, width]);

  useEffect(() => {
    fit();
  }, [fit, height, width]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const updateSize = () => {
      const next = {
        width: frame.clientWidth || FALLBACK_SIZE.width,
        height: frame.clientHeight || FALLBACK_SIZE.height,
      };
      setFrameSize((current) =>
        current.width === next.width && current.height === next.height
          ? current
          : next,
      );
    };
    updateSize();
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(updateSize);
      observer.observe(frame);
      return () => observer.disconnect();
    }
    globalThis.addEventListener("resize", updateSize);
    return () => globalThis.removeEventListener("resize", updateSize);
  }, []);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const drag = dragRef.current;
      // A secondary touch/pen pointer must not move the active drag.
      if (!drag || event.pointerId !== drag.pointerId) return;
      // Apply movement to the latest view: a wheel zoom during a pan must
      // not be rolled back by the next pointermove.
      if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) {
        return;
      }
      const deltaX = event.clientX - drag.x;
      const deltaY = event.clientY - drag.y;
      const offsetX = viewRef.current.offsetX + deltaX;
      const offsetY = viewRef.current.offsetY + deltaY;
      // Keep the last valid pointer origin so a later valid event can recover.
      if (!Number.isFinite(offsetX) || !Number.isFinite(offsetY)) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (deltaX === 0 && deltaY === 0) return;
      updateView({ ...viewRef.current, offsetX, offsetY });
    };
    const cancel = (event: PointerEvent) => {
      // Finishing a different pointer must not abandon this drag.
      if (dragRef.current?.pointerId === event.pointerId) {
        dragRef.current = null;
      }
    };
    const cancelAll = () => {
      dragRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cancel);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancelAll);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cancel);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("blur", cancelAll);
    };
  }, [updateView]);

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const preservesPolygonGesture =
      event.button === 0 &&
      event.altKey &&
      event.target instanceof Element &&
      Boolean(event.target.closest("circle, polygon"));
    if (
      preservesPolygonGesture ||
      (event.button !== 1 &&
        event.button !== 2 &&
        !(event.button === 0 && event.altKey))
    ) {
      return;
    }
    if (
      !hasValidImageSize ||
      dragRef.current ||
      !Number.isFinite(event.clientX) ||
      !Number.isFinite(event.clientY)
    ) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
    };
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    // Horizontal-only/zero-delta wheel events are not zoom commands.
    if (
      !hasValidImageSize ||
      !Number.isFinite(event.deltaY) ||
      event.deltaY === 0 ||
      !Number.isFinite(event.clientX) ||
      !Number.isFinite(event.clientY)
    ) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const focusX = event.clientX - rect.left;
    const focusY = event.clientY - rect.top;
    if (!Number.isFinite(focusX) || !Number.isFinite(focusY)) return;
    event.preventDefault();
    updateView(
      zoomAtPoint(
        viewRef.current,
        { x: focusX, y: focusY },
        viewRef.current.scale * (event.deltaY > 0 ? 1 / 1.08 : 1.08),
      ),
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!hasValidImageSize || event.key.toLowerCase() !== "f") return;
    if (
      event.target instanceof HTMLElement &&
      event.target.closest("input, textarea, select, button")
    ) {
      return;
    }
    event.preventDefault();
    fit();
  }

  return (
    <div className="annotation-image-viewport">
      <div className="annotation-viewport-controls">
        <button
          type="button"
          className="secondary"
          onClick={fit}
          disabled={!hasValidImageSize}
        >
          Fit to View
        </button>
        <button
          type="button"
          className="secondary"
          onClick={actualSize}
          disabled={!hasValidImageSize}
        >
          Actual Size (100%)
        </button>
        <button
          type="button"
          className="secondary"
          onClick={fit}
          disabled={!hasValidImageSize}
        >
          Reset View
        </button>
        <span>Alt+drag or middle-drag to pan · Wheel to zoom</span>
      </div>
      <div
        ref={frameRef}
        className="annotation-canvas-frame annotation-transform-viewport"
        role="region"
        aria-label={label}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onPointerDownCapture={handlePointerDown}
        onWheel={handleWheel}
        onContextMenu={(event) => event.preventDefault()}
        onDoubleClick={(event) => {
          if (hasValidImageSize && event.target === event.currentTarget) fit();
        }}
      >
        {hasValidImageSize ? (
          <div
            data-testid="image-viewport-transform"
            className="annotation-transform-content"
            style={{
              width,
              height,
              transform: `translate(${view.offsetX}px, ${view.offsetY}px) scale(${view.scale})`,
            }}
          >
            {children}
          </div>
        ) : (
          <p role="alert">
            Image pixel dimensions are invalid. Annotation editing is paused
            until the original image metadata is corrected.
          </p>
        )}
      </div>
    </div>
  );
}
