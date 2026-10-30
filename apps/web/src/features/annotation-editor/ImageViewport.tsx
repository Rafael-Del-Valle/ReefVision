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
  children,
}: {
  width: number;
  height: number;
  label: string;
  children: ReactNode;
}) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<ViewportTransform>(
    fitTransform({ width, height }, FALLBACK_SIZE),
  );
  const dragRef = useRef<{
    x: number;
    y: number;
    view: ViewportTransform;
  } | null>(null);
  const [frameSize, setFrameSize] = useState(FALLBACK_SIZE);
  const [view, setView] = useState(viewRef.current);

  const updateView = useCallback((next: ViewportTransform) => {
    viewRef.current = next;
    setView(next);
  }, []);

  const fit = useCallback(() => {
    dragRef.current = null;
    updateView(fitTransform({ width, height }, frameSize));
  }, [frameSize, height, updateView, width]);

  const actualSize = useCallback(() => {
    dragRef.current = null;
    updateView(actualSizeTransform({ width, height }, frameSize));
  }, [frameSize, height, updateView, width]);

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
      if (!drag) return;
      updateView({
        ...drag.view,
        offsetX: drag.view.offsetX + event.clientX - drag.x,
        offsetY: drag.view.offsetY + event.clientY - drag.y,
      });
    };
    const cancel = () => {
      dragRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cancel);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cancel);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("blur", cancel);
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
      if (!Number.isFinite(event.deltaX) || !Number.isFinite(event.deltaY)) return;
      if (event.deltaX === 0 && event.deltaY === 0) return;

      event.preventDefault();
      event.stopPropagation();
      // Horizontal trackpad movement must not unexpectedly zoom the image.
      if (event.deltaY === 0) return;

      const rect = frame.getBoundingClientRect();
      updateView(
        zoomAtPoint(
          viewRef.current,
          { x: event.clientX - rect.left, y: event.clientY - rect.top },
          viewRef.current.scale * (event.deltaY > 0 ? 1 / 1.08 : 1.08),
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
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      view: viewRef.current,
    };
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
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
