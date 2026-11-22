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
    // WebView2 can construct a ResizeObserver successfully yet miss desktop
    // resize notifications. Always retain the window-resize fallback so the
    // initial camera image is fitted and manual scientific zoom is preserved.
    // updateSize ignores duplicate measurements from the two listeners.
    globalThis.addEventListener("resize", updateSize);
    // WebView2 can resize the visual viewport after desktop zoom or pane
    // adjustments without notifying ResizeObserver or window.resize.
    // Measure the actual canvas client dimensions, never the zoomed visual
    // viewport size, so polygon and mask coordinates remain image-relative.
    const visualViewport = globalThis.visualViewport;
    try {
      visualViewport?.addEventListener("resize", updateSize);
    } catch {
      // An incomplete embedded VisualViewport implementation must not break
      // initial image fitting; window.resize remains available.
    }
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver === "function") {
      try {
        observer = new ResizeObserver(updateSize);
        observer.observe(frame);
      } catch {
        // Broken WebView2 observers must not crash the first image, even
        // when disconnecting a partially registered observer also throws.
        try {
          observer?.disconnect();
        } catch {
          // The window-resize fallback remains active.
        }
        observer = null;
      }
    }
    return () => {
      try {
        observer?.disconnect();
      } catch {
        // Observer cleanup failures must not leak the window listener.
      }
      globalThis.removeEventListener("resize", updateSize);
      try {
        visualViewport?.removeEventListener("resize", updateSize);
      } catch {
        // Some embedded implementations fail to remove listeners on teardown.
      }
    };
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
      const offsetX = drag.view.offsetX + event.clientX - drag.x;
      const offsetY = drag.view.offsetY + event.clientY - drag.y;
      // Finite WebView2 coordinates can still overflow when subtracting a
      // very distant drag anchor. Never poison image/annotation transforms.
      if (!Number.isFinite(offsetX) || !Number.isFinite(offsetY)) return;
      updateView({ ...drag.view, offsetX, offsetY });
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
      const invalidAxis =
        !Number.isFinite(event.deltaX) || !Number.isFinite(event.deltaY);
      const deltaX = Number.isFinite(event.deltaX) ? event.deltaX : 0;
      const deltaY = Number.isFinite(event.deltaY) ? event.deltaY : 0;
      // A fully malformed precision-wheel gesture is still an input over
      // the scientific viewport. Contain it so WebView2 cannot scroll the
      // document behind the image, but do not change the pixel transform.
      if (deltaX === 0 && deltaY === 0 && !invalidAxis) return;

      event.preventDefault();
      event.stopPropagation();
      if (deltaX === 0 && deltaY === 0) return;
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
      const focus = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      // A transient WebView2 rectangle may be malformed even when the
      // wheel pointer itself is finite. Also reject finite operands whose
      // subtraction or zoom arithmetic overflows, instead of persisting
      // NaN/Infinity into the pixel-aligned scientific viewport.
      if (!Number.isFinite(focus.x) || !Number.isFinite(focus.y)) return;
      const nextView = zoomAtPoint(
        viewRef.current,
        focus,
        viewRef.current.scale * (deltaY > 0 ? 1 / 1.08 : 1.08),
      );
      if (
        !Number.isFinite(nextView.scale) ||
        !Number.isFinite(nextView.offsetX) ||
        !Number.isFinite(nextView.offsetY)
      ) {
        return;
      }
      // A pending pan still holds a pre-zoom transform. A later pointermove
      // must not overwrite the scientist's new zoom with that stale view.
      dragRef.current = null;
      manualViewRef.current = true;
      updateView(nextView);
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
    // Do not hijack Ctrl/Cmd+F browser search, menu shortcuts or text being
    // composed in editable scientific labels. Only plain F refits the image.
    if (
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }
    if (
      event.target instanceof HTMLElement &&
      (event.target.isContentEditable ||
        event.target.closest("[contenteditable]") ||
        event.target.closest("input, textarea, select, button"))
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
