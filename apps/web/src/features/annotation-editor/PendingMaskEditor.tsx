import { useEffect, useRef, useState, type PointerEvent } from "react";
import { imageContentUrl } from "../../api/client";

interface Props {
  imageId: string;
  maskUrl: string;
  width: number;
  height: number;
  onSave: (pngBase64: string) => Promise<void>;
  onCancel: () => void;
}

/** Edits only a pending raster. Canvas dimensions always match original pixels. */
export function PendingMaskEditor({
  imageId,
  maskUrl,
  width,
  height,
  onSave,
  onCancel,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const previous = useRef<{ x: number; y: number } | null>(null);
  const history = useRef<ImageData[]>([]);
  const redoHistory = useRef<ImageData[]>([]);
  const [mode, setMode] = useState("paint");
  const [radius, setRadius] = useState(8);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [undoCount, setUndoCount] = useState(0);
  const [redoCount, setRedoCount] = useState(0);
  useEffect(() => {
    let active = true;
    setReady(false);
    history.current = [];
    redoHistory.current = [];
    setUndoCount(0);
    setRedoCount(0);
    if (width * height > 32_000_000) {
      setError(
        "This image exceeds the 32 million pixel interactive editing limit.",
      );
      return;
    }
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (!active) return;
      const context = canvas.current?.getContext("2d", {
        willReadFrequently: true,
      });
      if (!context) {
        setError("Mask editing canvas is unavailable.");
        return;
      }
      try {
        context.drawImage(image, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height);
        for (let index = 0; index < pixels.data.length; index += 4) {
          const foreground =
            pixels.data[index] > 0 && pixels.data[index + 3] > 0;
          pixels.data[index] = 255;
          pixels.data[index + 1] = 60;
          pixels.data[index + 2] = 210;
          pixels.data[index + 3] = foreground ? 180 : 0;
        }
        context.putImageData(pixels, 0, 0);
        setReady(true);
      } catch (failure) {
        setError(String(failure));
      }
    };
    image.onerror = () => {
      if (active) setError("Could not load the pending mask. Close and retry.");
    };
    image.src = maskUrl;
    return () => {
      active = false;
    };
  }, [maskUrl, width, height]);
  function paint(event: PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current || !ready || saving) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const point = {
      x: ((event.clientX - bounds.left) * width) / bounds.width,
      y: ((event.clientY - bounds.top) * height) / bounds.height,
    };
    const context = event.currentTarget.getContext("2d");
    if (!context) return;
    context.globalCompositeOperation =
      mode === "erase" ? "destination-out" : "source-over";
    context.strokeStyle = "rgba(255,60,210,1)";
    context.fillStyle = "rgba(255,60,210,1)";
    context.lineWidth = radius * 2;
    context.lineCap = "round";
    context.beginPath();
    if (previous.current) {
      context.moveTo(previous.current.x, previous.current.y);
      context.lineTo(point.x, point.y);
      context.stroke();
    } else {
      context.arc(point.x, point.y, radius, 0, 2 * Math.PI);
      context.fill();
    }
    previous.current = point;
  }
  async function save() {
    const context = canvas.current?.getContext("2d");
    if (!context || !ready) return;
    setSaving(true);
    setError("");
    try {
      const binary = context.getImageData(0, 0, width, height);
      for (let index = 0; index < binary.data.length; index += 4) {
        const value = binary.data[index + 3] >= 128 ? 255 : 0;
        binary.data[index] = value;
        binary.data[index + 1] = value;
        binary.data[index + 2] = value;
        binary.data[index + 3] = 255;
      }
      const output = document.createElement("canvas");
      output.width = width;
      output.height = height;
      const outputContext = output.getContext("2d");
      if (!outputContext) throw new Error("Cannot encode the edited mask.");
      outputContext.putImageData(binary, 0, 0);
      await onSave(output.toDataURL("image/png").split(",")[1]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section aria-label="Edit pending mask" className="pending-mask-editor">
      <p>
        Paint or erase the proposed boundary. Saving edits keeps it pending for
        review.
      </p>
      <label>
        Brush action{" "}
        <select
          aria-label="Pending mask brush action"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          <option value="paint">Paint</option>
          <option value="erase">Erase</option>
        </select>
      </label>
      <label>
        Radius in source pixels{" "}
        <input
          type="number"
          min="1"
          max="100"
          value={radius}
          onChange={(event) =>
            setRadius(
              Math.max(1, Math.min(100, Number(event.target.value) || 1)),
            )
          }
        />
      </label>
      <div
        style={{
          position: "relative",
          width: "100%",
          maxWidth: 700,
          aspectRatio: `${width}/${height}`,
        }}
      >
        <img
          alt="Source image for pending mask editing"
          src={imageContentUrl(imageId)}
          style={{ position: "absolute", width: "100%", height: "100%" }}
        />
        <canvas
          ref={canvas}
          width={width}
          height={height}
          aria-label="Pending mask painting canvas"
          style={{
            position: "absolute",
            width: "100%",
            height: "100%",
            touchAction: "none",
          }}
          onPointerDown={(event) => {
            if (!ready || saving || event.button !== 0) return;
            const context = event.currentTarget.getContext("2d");
            if (!context) return;
            // Limit source-resolution history to roughly 128 MB, at most eight strokes.
            const limit = Math.max(
              1,
              Math.min(8, Math.floor(128_000_000 / (width * height * 4))),
            );
            history.current = [
              ...history.current.slice(-(limit - 1 || history.current.length)),
              context.getImageData(0, 0, width, height),
            ].slice(-limit);
            setUndoCount(history.current.length);
            redoHistory.current = [];
            setRedoCount(0);
            event.currentTarget.setPointerCapture(event.pointerId);
            drawing.current = true;
            previous.current = null;
            paint(event);
          }}
          onPointerMove={paint}
          onPointerUp={() => {
            drawing.current = false;
            previous.current = null;
          }}
          onPointerCancel={() => {
            drawing.current = false;
            previous.current = null;
          }}
        />
      </div>
      <button
        type="button"
        disabled={!undoCount || saving}
        onClick={() => {
          const pixels = history.current.pop();
          const context = canvas.current?.getContext("2d");
          if (pixels && context) {
            redoHistory.current.push(context.getImageData(0, 0, width, height));
            context.putImageData(pixels, 0, 0);
          }
          setUndoCount(history.current.length);
          setRedoCount(redoHistory.current.length);
        }}
      >
        Undo brush stroke
      </button>
      <button
        type="button"
        disabled={!redoCount || saving}
        onClick={() => {
          const pixels = redoHistory.current.pop();
          const context = canvas.current?.getContext("2d");
          if (pixels && context) {
            history.current.push(context.getImageData(0, 0, width, height));
            context.putImageData(pixels, 0, 0);
          }
          setUndoCount(history.current.length);
          setRedoCount(redoHistory.current.length);
        }}
      >
        Redo brush stroke
      </button>
      <button
        type="button"
        disabled={!ready || saving}
        onClick={() => void save()}
      >
        {saving ? "Saving pending mask…" : "Save pending edits"}
      </button>
      <button type="button" disabled={saving} onClick={onCancel}>
        Cancel mask edits
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
