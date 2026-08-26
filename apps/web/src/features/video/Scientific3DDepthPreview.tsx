import { useEffect, useMemo, useState } from "react";

import {
  metricDepth3DPreviewUrl,
  type MetricVideoDepth3DResult,
} from "./videoScienceApi";

interface Scientific3DDepthPreviewProps {
  videoId: string;
  jobId: string;
  result: MetricVideoDepth3DResult;
}

export function Scientific3DDepthPreview({
  videoId,
  jobId,
  result,
}: Scientific3DDepthPreviewProps) {
  const frameCount = Math.max(
    1,
    result.depth_stack_shape[0] ?? result.decoded_frame_count ?? 1,
  );
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    setFrame(0);
  }, [jobId, videoId]);

  const previewUrl = useMemo(
    () => metricDepth3DPreviewUrl(videoId, jobId, frame),
    [frame, jobId, videoId],
  );

  const preview = result.depth_preview;
  const minimum = preview?.display_min_m;
  const maximum = preview?.display_max_m;

  return (
    <section className="panel-card" data-testid="scientific-3d-depth-preview">
      <p className="eyebrow">Metric depth preview</p>
      <h4>Raw Video Depth Anything output</h4>
      <p className="annotation-helper">
        ReefVision colorizes the persisted metric-depth array for display only.
        The underlying NPZ values are unchanged and remain model-estimated
        metric depth until independently validated underwater.
      </p>

      <div
        style={{
          background: "#121212",
          borderRadius: 8,
          overflow: "hidden",
          display: "grid",
          placeItems: "center",
          minHeight: 240,
        }}
      >
        <img
          src={previewUrl}
          alt={`Metric depth preview frame ${frame}`}
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            maxHeight: 560,
            objectFit: "contain",
            imageRendering: "auto",
          }}
        />
      </div>

      <label>
        Depth frame {frame + 1} / {frameCount}
        <input
          aria-label="Depth preview frame"
          type="range"
          min={0}
          max={Math.max(0, frameCount - 1)}
          step={1}
          value={frame}
          onChange={(event) =>
            setFrame(Number.parseInt(event.target.value, 10))
          }
        />
      </label>

      <div
        aria-label="Metric depth color scale"
        style={{
          height: 18,
          borderRadius: 5,
          background:
            "linear-gradient(90deg, rgb(25 45 170), rgb(0 175 235), " +
            "rgb(55 205 120), rgb(245 215 55), rgb(210 35 35))",
        }}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.8rem",
          marginTop: 4,
        }}
      >
        <span>
          Nearer
          {typeof minimum === "number" ? ` · ${minimum.toFixed(3)} m` : ""}
        </span>
        <span>
          Farther
          {typeof maximum === "number" ? ` · ${maximum.toFixed(3)} m` : ""}
        </span>
      </div>

      <div className="annotation-selection-list">
        <div className="annotation-selection-row">
          <strong>Display scaling</strong>
          <span>Whole-stack positive-depth 2nd–98th percentiles</span>
        </div>
        <div className="annotation-selection-row">
          <strong>Scientific tier</strong>
          <span>{result.depth_tier.replaceAll("_", " ")}</span>
        </div>
        <div className="annotation-selection-row">
          <strong>Colorization</strong>
          <span>Visualization only — stored metric values are unchanged</span>
        </div>
      </div>
    </section>
  );
}
