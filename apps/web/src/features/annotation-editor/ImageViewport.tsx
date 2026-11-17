import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
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
  sourceImageId,
  children,
}: {
  width: number;
  height: number;
  label: string;
  // Different camera sources can share dimensions but not viewport state.
  sourceImageId?: string;
  children: ReactNode;
}) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<ViewportTransform>(
    fitTransform({ width, height }, FALLBACK_SIZE),
  );
  const dragRef = useRef<{
    pointerId: number;
    x: number;
    y: number;
    view: ViewportTransform;
  } | null>(null);
  // Preserve a scientist-selected zoom/pan when the desktop pane resizes.
  const manualViewRef = useRef(false);
  const previousLayoutRef = useRef({
    width,
    height,
    sourceImageId,
    frameSize: FALLBACK_SIZE,
  });
  const [frameSize, setFrameSize] = useState(FALLBACK_SIZE);
  const [view, setView] = useState(viewRef.current);

  const updateView = useCallback((next: ViewportTransform) => {
    viewRef.current = next;
    setView(next);
  }, []);

  const fit = useCallback(() => {
    dragRef.current = null;
    manualViewRef.current = false;
    updateView(fitTransform({ width, height }, frameSize));
  }, [frameSize, height, updateView, width]);

  const actualSize = useCallback(() => {
    dragRef.current = null;
    manualViewRef.current = true;
    updateView(actualSizeTransform({ width, height }, frameSize));
  }, [frameSize, height, updateView, width]);

  useEffect(() => {
    const previous = previousLayoutRef.current;
    const imageChanged =
      width !== previous.width ||
      height !== previous.height ||
      sourceImageId !== previous.sourceImageId;
    const frameChanged =
      frameSize.width !== previous.frameSize.width ||
      frameSize.height !== previous.frameSize.height;
    if (imageChanged) {
      // New source identity (even at identical dimensions) means a distinct
      // scientific image. Discard the old zoom and in-flight pan anchor.
      manualViewRef.current = false;
      dragRef.current = null;
    }
    if (imageChanged || !manualViewRef.current) {
      updateView(fitTransform({ width, height }, frameSize));
    } else if (frameChanged) {
      // Keep the same original-image pixel under the viewport center.
      // A drag started before resizing must not reuse its old anchor.
      dragRef.current = null;
      updateView({
        ...viewRef.current,
        offsetX:
          viewRef.current.offsetX +
          (frameSize.width - previous.frameSize.width) / 2,
        offsetY:
          viewRef.current.offsetY +
          (frameSize.height - previous.frameSize.height) / 2,
      });
    }
    previousLayoutRef.current = { width, height, sourceImageId, frameSize };
  }, [frameSize, height, sourceImageId, updateView, width]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const updateSize = () => {
      // Collapsed WebView2/desktop panels can briefly report a zero-sized
      // frame. Keep the last valid measurement rather than replacing it
      // with the initial fallback and shifting a scientist's manual view.
      const measuredWidth = frame.clientWidth;
      const measuredHeight = frame.clientHeight;
      if (
        !Number.isFinite(measuredWidth) ||
        !Number.isFinite(measuredHeight) ||
        measuredWidth <= 0 ||
        measuredHeight <= 0
      ) {
        return;
      }
      const next = { width: measuredWidth, height: measuredHeight };
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
      // Ignore unrelated mouse, pen, or touch pointers during an active pan.
      if (!drag || event.pointerId !== drag.pointerId) return;
      // Malformed WebView2 pointer coordinates must not corrupt the stored
      // scientific image transform or its pixel-aligned mask overlays.
      if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) {
        return;
      }
      updateView({
        ...drag.view,
        offsetX: drag.view.offsetX + event.clientX - drag.x,
        offsetY: drag.view.offsetY + event.clientY - drag.y,
      });
    };
    const cancelPointer = (event: PointerEvent) => {
      if (dragRef.current?.pointerId === event.pointerId) {
        dragRef.current = null;
      }
    };
    const cancelAll = () => {
      dragRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cancelPointer);
    window.addEventListener("pointercancel", cancelPointer);
    window.addEventListener("blur", cancelAll);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cancelPointer);
      window.removeEventListener("pointercancel", cancelPointer);
      window.removeEventListener("blur", cancelAll);
    };
  }, [updateView]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;

    // React's delegated wheel listener may be passive in Chromium/WebView2.
    // Register directly so preventing document scroll actually works while
    // zooming the scientific image and its aligned annotation overlays.
    const handleNativeWheel = (event: globalThis.WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      // WebView2 trackpads can supply a malformed axis alongside a real
      // scroll value. Validate independently to avoid stray page movement.
      const deltaX = Number.isFinite(event.deltaX) ? event.deltaX : 0;
      const deltaY = Number.isFinite(event.deltaY) ? event.deltaY : 0;
      if (deltaX === 0 && deltaY === 0) return;

      event.preventDefault();
      event.stopPropagation();
      // Never zoom scientific overlays on horizontal or Shift scrolling.
      if (event.shiftKey || Math.abs(deltaX) >= Math.abs(deltaY)) {
        return;
      }

      // A malformed WebView2 pointer location must never poison the image
      // transform with NaN/Infinity or displace pixel-aligned annotations.
      // The wheel has already been contained, so retain the current view.
      if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) {
        return;
      }

      const rect = frame.getBoundingClientRect();
      // A pending pan still holds a pre-zoom transform. A later pointermove
      // must not overwrite the scientist's new zoom with that stale view.
      dragRef.current = null;
      manualViewRef.current = true;
      updateView(
        zoomAtPoint(
          viewRef.current,
          { x: event.clientX - rect.left, y: event.clientY - rect.top },
          viewRef.current.scale * (deltaY > 0 ? 1 / 1.08 : 1.08),
        ),
      );
    };
    frame.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => frame.removeEventListener("wheel", handleNativeWheel);
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
    // A second pointer must not steal a drag already in progress.
    if (dragRef.current) return;
    // Ignore bad input before taking ownership of a pan gesture. A later
    // valid pointerdown must still be able to initiate deliberate panning.
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    manualViewRef.current = true;
    dragRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      view: viewRef.current,
    };
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    // Escape cancels an in-progress pan without swallowing the editor's
    // own Escape shortcuts (for example, cancelling a polygon edit).
    if (event.key === "Escape") {
      dragRef.current = null;
      return;
    }
    if (event.key.toLowerCase() !== "f") return;
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
        <button type="button" className="secondary" onClick={fit}>
          Fit to View
        </button>
        <button type="button" className="secondary" onClick={actualSize}>
          Actual Size (100%)
        </button>
        <button type="button" className="secondary" onClick={fit}>
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
        onContextMenu={(event) => event.preventDefault()}
        onDoubleClick={(event) => {
          if (event.target === event.currentTarget) fit();
        }}
      >
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
      </div>
    </div>
  );
}
