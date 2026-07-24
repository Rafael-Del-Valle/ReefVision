import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";

import {
  polygonsToRaster,
  rasterToPolygons,
  repairPolygons,
  type MaskRle,
  type PolygonGeometry,
} from "./maskConversionApi";

type ConversionMode = "polygon_to_raster" | "raster_to_polygon" | "repair";

const DEFAULT_POLYGONS = JSON.stringify(
  [
    {
      outer: [
        { x: 10, y: 10 },
        { x: 90, y: 10 },
        { x: 90, y: 70 },
        { x: 10, y: 70 },
      ],
      holes: [
        [
          { x: 35, y: 30 },
          { x: 65, y: 30 },
          { x: 65, y: 50 },
          { x: 35, y: 50 },
        ],
      ],
    },
  ] satisfies PolygonGeometry[],
  null,
  2,
);

function createRectangleRle(
  width: number,
  height: number,
  left: number,
  top: number,
  right: number,
  bottom: number,
): MaskRle {
  const counts: number[] = [];
  let currentValue = 0;
  let runLength = 0;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = x >= left && x < right && y >= top && y < bottom ? 1 : 0;
      if (value === currentValue) {
        runLength += 1;
      } else {
        counts.push(runLength);
        currentValue = value;
        runLength = 1;
      }
    }
  }
  counts.push(runLength);

  return { width, height, counts, order: "row_major" };
}

const DEFAULT_RLE = JSON.stringify(
  createRectangleRle(100, 80, 20, 10, 80, 70),
  null,
  2,
);

function parseJson<T>(value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`${label} is not valid JSON: ${message}`);
  }
}

export function MaskConversionPanel() {
  const [mode, setMode] = useState<ConversionMode>("polygon_to_raster");
  const [polygonsText, setPolygonsText] = useState(DEFAULT_POLYGONS);
  const [rasterText, setRasterText] = useState(DEFAULT_RLE);
  const [imageWidth, setImageWidth] = useState(100);
  const [imageHeight, setImageHeight] = useState(80);
  const [simplifyTolerance, setSimplifyTolerance] = useState(0);
  const [minimumComponentArea, setMinimumComponentArea] = useState(1);
  const [preserveHoles, setPreserveHoles] = useState(true);

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === "polygon_to_raster") {
        return polygonsToRaster({
          polygons: parseJson<PolygonGeometry[]>(
            polygonsText,
            "Polygon geometry",
          ),
          image_width: imageWidth,
          image_height: imageHeight,
          rle_order: "row_major",
        });
      }
      if (mode === "raster_to_polygon") {
        return rasterToPolygons({
          raster: parseJson<MaskRle>(rasterText, "Raster RLE"),
          simplify_tolerance: simplifyTolerance,
          minimum_component_area: minimumComponentArea,
          preserve_holes: preserveHoles,
        });
      }
      return repairPolygons({
        polygons: parseJson<PolygonGeometry[]>(
          polygonsText,
          "Polygon geometry",
        ),
        image_width: imageWidth,
        image_height: imageHeight,
        simplify_tolerance: simplifyTolerance,
        preserve_holes: preserveHoles,
      });
    },
  });

  const resultJson = useMemo(
    () => (mutation.data ? JSON.stringify(mutation.data, null, 2) : ""),
    [mutation.data],
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <section className="workspace-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Geometry utilities</p>
          <h3>Mask conversion and repair</h3>
        </div>
      </div>
      <p>
        Convert polygons to uncompressed RLE, recover polygons from raster
        masks, or repair polygon geometry through a rasterized round trip.
      </p>

      <form className="stacked-form" onSubmit={submit}>
        <label>
          Operation
          <select
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as ConversionMode);
              mutation.reset();
            }}
          >
            <option value="polygon_to_raster">Polygons to raster RLE</option>
            <option value="raster_to_polygon">Raster RLE to polygons</option>
            <option value="repair">Repair polygons</option>
          </select>
        </label>

        {mode === "raster_to_polygon" ? (
          <label>
            Uncompressed mask RLE
            <textarea
              rows={14}
              spellCheck={false}
              value={rasterText}
              onChange={(event) => setRasterText(event.target.value)}
            />
          </label>
        ) : (
          <label>
            Polygon geometry
            <textarea
              rows={14}
              spellCheck={false}
              value={polygonsText}
              onChange={(event) => setPolygonsText(event.target.value)}
            />
          </label>
        )}

        {mode !== "raster_to_polygon" && (
          <div className="form-grid">
            <label>
              Image width
              <input
                type="number"
                min={1}
                max={100000}
                value={imageWidth}
                onChange={(event) => setImageWidth(Number(event.target.value))}
              />
            </label>
            <label>
              Image height
              <input
                type="number"
                min={1}
                max={100000}
                value={imageHeight}
                onChange={(event) => setImageHeight(Number(event.target.value))}
              />
            </label>
          </div>
        )}

        {mode !== "polygon_to_raster" && (
          <div className="form-grid">
            <label>
              Simplify tolerance
              <input
                type="number"
                min={0}
                max={10000}
                step="0.1"
                value={simplifyTolerance}
                onChange={(event) =>
                  setSimplifyTolerance(Number(event.target.value))
                }
              />
            </label>
            {mode === "raster_to_polygon" && (
              <label>
                Minimum component area
                <input
                  type="number"
                  min={1}
                  max={1000000000}
                  value={minimumComponentArea}
                  onChange={(event) =>
                    setMinimumComponentArea(Number(event.target.value))
                  }
                />
              </label>
            )}
          </div>
        )}

        {mode !== "polygon_to_raster" && (
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={preserveHoles}
              onChange={(event) => setPreserveHoles(event.target.checked)}
            />
            Preserve interior holes
          </label>
        )}

        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Processing…" : "Run conversion"}
        </button>
      </form>

      {mutation.error && (
        <p className="form-error" role="alert">
          {mutation.error.message}
        </p>
      )}

      {mutation.data && (
        <div className="result-panel">
          <div className="form-grid">
            <div>
              <strong>Foreground pixels</strong>
              <p>{mutation.data.quality.foreground_pixels.toLocaleString()}</p>
            </div>
            <div>
              <strong>Components</strong>
              <p>{mutation.data.quality.component_count}</p>
            </div>
            <div>
              <strong>Holes</strong>
              <p>{mutation.data.quality.hole_count}</p>
            </div>
            {"round_trip_iou" in mutation.data && (
              <div>
                <strong>Round-trip IoU</strong>
                <p>{mutation.data.round_trip_iou.toFixed(4)}</p>
              </div>
            )}
          </div>

          <img
            className="mask-preview"
            src={`data:image/png;base64,${mutation.data.preview_png_base64}`}
            alt="Mask conversion preview"
          />

          {mutation.data.warnings.length > 0 && (
            <div className="warning-panel">
              <strong>Warnings</strong>
              <ul>
                {mutation.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <details>
            <summary>Response JSON</summary>
            <pre>{resultJson}</pre>
          </details>
        </div>
      )}
    </section>
  );
}
