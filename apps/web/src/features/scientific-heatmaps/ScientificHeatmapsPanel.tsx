import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getImages, imageDisplayUrl, type Project } from "../../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import {
  getScientificHeatmap,
  type HeatmapKind,
  type ScientificHeatmap,
} from "./scientificHeatmapsApi";

const LAYERS: {
  kind: HeatmapKind;
  label: string;
  color: string;
}[] = [
  {
    kind: "reviewed_boxes",
    label: "Reviewed boxes",
    color: "#e5ad43",
  },
  {
    kind: "verified_masks",
    label: "Verified segmentation masks",
    color: "#21c7bd",
  },
  {
    kind: "pending_predictions",
    label: "Pending model predictions",
    color: "#ad83f2",
  },
];

type ScaleMode = "per_layer" | "shared";

function exportJson(data: ScientificHeatmap): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `reefvision-heatmap-${data.image_id}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ScientificHeatmapsPanel({ project }: { project: Project }) {
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState("");
  const [classId, setClassId] = useState("");
  const [columns, setColumns] = useState(16);
  const [rows, setRows] = useState(16);
  const [opacity, setOpacity] = useState(0.65);
  const [scaleMode, setScaleMode] = useState<ScaleMode>("per_layer");

  const [visible, setVisible] = useState<Record<HeatmapKind, boolean>>({
    reviewed_boxes: true,
    verified_masks: true,
    pending_predictions: false,
  });

  const imagesQuery = useQuery({
    queryKey: ["heatmap-images", project.id, page],
    queryFn: ({ signal }) =>
      getImages(project.id, { page, pageSize: 24, sortBy: "newest" }, signal),
  });

  const images = imagesQuery.data?.items ?? [];
  const selectedImage =
    images.find((image) => image.id === selectedId) ?? images[0];

  const heatmapQuery = useQuery({
    queryKey: [
      "scientific-heatmap",
      project.id,
      selectedImage?.id,
      columns,
      rows,
      classId,
    ],
    enabled: Boolean(selectedImage),
    queryFn: ({ signal }) => {
      if (!selectedImage) {
        throw new Error("Choose an image first.");
      }
      return getScientificHeatmap(
        project.id,
        selectedImage.id,
        columns,
        rows,
        classId,
        signal,
      );
    },
  });

  const heatmap = heatmapQuery.data;

  const sharedMaximum = Math.max(
    1,
    ...(heatmap?.layers.map((layer) => layer.max_cell_count) ?? []),
  );

  function changePage(nextPage: number) {
    setPage(nextPage);
    setSelectedId("");
  }

  function toggleLayer(kind: HeatmapKind) {
    setVisible((previous) => ({
      ...previous,
      [kind]: !previous[kind],
    }));
  }

  return (
    <section
      className="feature-workspace"
      aria-label="Scientific Heatmaps workspace"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">ReefVision 1.1 — Scientific analysis</p>
          <h2>Scientific Heatmaps</h2>
          <p>
            Visualize spatial object counts from verified annotations and
            pending predictions without merging their evidence.
          </p>
        </div>
      </div>

      <div className="training-card-grid">
        <section className="panel-card training-content">
          <h3>Data selection</h3>

          <label>
            Source image
            <select
              value={selectedImage?.id ?? ""}
              disabled={images.length === 0}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {images.map((image) => (
                <option key={image.id} value={image.id}>
                  {image.original_filename}
                </option>
              ))}
            </select>
          </label>

          <div>
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => changePage(page - 1)}
            >
              Previous images
            </button>{" "}
            <button
              type="button"
              disabled={!imagesQuery.data || page >= imagesQuery.data.pages}
              onClick={() => changePage(page + 1)}
            >
              Next images
            </button>
            <p className="form-help">
              Image page {page}
              {imagesQuery.data ? ` of ${imagesQuery.data.pages}` : ""}
            </p>
          </div>

          <label>
            Annotation class
            <select
              value={classId}
              onChange={(event) => setClassId(event.target.value)}
            >
              <option value="">All classes</option>
              {project.label_classes.map((label) => (
                <option key={label.id} value={label.id}>
                  {label.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Grid columns: {columns}
            <input
              type="range"
              min={2}
              max={32}
              value={columns}
              onChange={(event) => setColumns(Number(event.target.value))}
            />
          </label>

          <label>
            Grid rows: {rows}
            <input
              type="range"
              min={2}
              max={32}
              value={rows}
              onChange={(event) => setRows(Number(event.target.value))}
            />
          </label>
        </section>

        <section className="panel-card training-content">
          <h3>Overlay controls</h3>

          {LAYERS.map((layer) => (
            <label key={layer.kind}>
              <input
                type="checkbox"
                checked={visible[layer.kind]}
                onChange={() => toggleLayer(layer.kind)}
              />{" "}
              <span style={{ color: layer.color }}>{layer.label}</span>
            </label>
          ))}

          <label>
            Overlay opacity: {Math.round(opacity * 100)}%
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(event) => setOpacity(Number(event.target.value))}
            />
          </label>

          <label>
            Intensity scale
            <select
              value={scaleMode}
              onChange={(event) =>
                setScaleMode(event.target.value as ScaleMode)
              }
            >
              <option value="per_layer">Relative to each layer</option>
              <option value="shared">Shared across layers</option>
            </select>
          </label>

          <p className="form-help">
            Each object contributes to one cell based on its bounding-rectangle
            center. Overlapping masks are not converted to union coverage or
            physical area.
          </p>
        </section>
      </div>

      {imagesQuery.isPending ? (
        <LoadingState title="Loading project images" />
      ) : imagesQuery.error ? (
        <ErrorState
          title="Image list unavailable"
          message={imagesQuery.error.message}
          onRetry={() => imagesQuery.refetch()}
        />
      ) : !selectedImage ? (
        <EmptyState
          title="No imported images"
          description="Import project images to create heatmaps."
        />
      ) : heatmapQuery.isPending ? (
        <LoadingState title="Calculating scientific heatmap" />
      ) : heatmapQuery.error ? (
        <ErrorState
          title="Heatmap calculation unavailable"
          message={heatmapQuery.error.message}
          onRetry={() => heatmapQuery.refetch()}
        />
      ) : heatmap ? (
        <section
          className="panel-card training-content"
          aria-label="Heatmap visualization"
        >
          <div className="section-heading">
            <div>
              <h3>{selectedImage.original_filename}</h3>
              <p>
                {heatmap.width_px} × {heatmap.height_px} pixels
                {" · "}Annotation revision {heatmap.annotation_revision}
                {" · "}Status {heatmap.annotation_status}
              </p>
            </div>
            <button type="button" onClick={() => exportJson(heatmap)}>
              Export heatmap JSON
            </button>
          </div>

          <div
            style={{
              position: "relative",
              width: "100%",
              aspectRatio: `${heatmap.width_px} / ${heatmap.height_px}`,
              background: "#091724",
              overflow: "hidden",
            }}
          >
            <img
              src={imageDisplayUrl(selectedImage.id)}
              alt={`Source image ${selectedImage.original_filename}`}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "fill",
              }}
            />

            <svg
              role="img"
              aria-label="Source-pixel heatmap overlay"
              viewBox={`0 0 ${heatmap.width_px} ${heatmap.height_px}`}
              preserveAspectRatio="none"
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                pointerEvents: "none",
              }}
            >
              {heatmap.layers
                .filter((layer) => visible[layer.kind])
                .map((layer) => {
                  const color =
                    LAYERS.find((entry) => entry.kind === layer.kind)?.color ??
                    "#ffffff";

                  const cellWidth = heatmap.width_px / heatmap.columns;
                  const cellHeight = heatmap.height_px / heatmap.rows;

                  return (
                    <g
                      key={layer.kind}
                      data-testid={`heatmap-layer-${layer.kind}`}
                    >
                      {layer.counts.flatMap((line, row) =>
                        line.map((count, column) => {
                          if (count <= 0) return null;

                          const intensity =
                            scaleMode === "per_layer"
                              ? layer.normalized[row][column]
                              : count / sharedMaximum;

                          return (
                            <rect
                              key={`${row}-${column}`}
                              x={column * cellWidth}
                              y={row * cellHeight}
                              width={cellWidth}
                              height={cellHeight}
                              fill={color}
                              fillOpacity={
                                opacity * Math.max(0, Math.min(1, intensity))
                              }
                            />
                          );
                        }),
                      )}
                    </g>
                  );
                })}
            </svg>
          </div>

          <div className="training-card-grid">
            {heatmap.layers.map((layer) => (
              <article
                className="panel-card"
                key={layer.kind}
                aria-label={`${layer.kind} summary`}
              >
                <h4>
                  {LAYERS.find((item) => item.kind === layer.kind)?.label}
                </h4>
                <p>Objects: {layer.object_count}</p>
                <p>Maximum objects per cell: {layer.max_cell_count}</p>
                <p>Overlay: {visible[layer.kind] ? "Visible" : "Hidden"}</p>
              </article>
            ))}
          </div>

          <details>
            <summary>Scientific provenance and limitations</summary>
            <p>
              Source image SHA-256: <code>{heatmap.image_sha256}</code>
            </p>
            <p>
              Source snapshot SHA-256: <code>{heatmap.source_sha256}</code>
            </p>
            <p>
              Result SHA-256: <code>{heatmap.content_sha256}</code>
            </p>
            <p>
              Algorithm: <code>{heatmap.algorithm}</code>
            </p>
            <ul>
              {heatmap.methodological_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </section>
      ) : null}
    </section>
  );
}
