import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getAnnotationSession,
  imageContentUrl,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { RasterBrushLayer } from "./RasterBrushLayer";
import {
  editRasterMask,
  rasterMaskContentUrl,
  type RasterEditMode,
} from "./rasterMaskApi";
import type { MaskAnnotationRecord, Point } from "./types";

interface RasterMaskWorkspaceProps {
  project: Project;
  imageId: string;
  onReturnToMasks: () => void;
  onReturnToBoxes: () => void;
  onClose: () => void;
}

type MaskAwareAnnotationSession = AnnotationSession & {
  mask_annotations?: MaskAnnotationRecord[];
};

export function RasterMaskWorkspace({
  project,
  imageId,
  onReturnToMasks,
  onReturnToBoxes,
  onClose,
}: RasterMaskWorkspaceProps) {
  const queryClient = useQueryClient();
  const [selectedMaskId, setSelectedMaskId] = useState<string | null>(null);
  const [activeClassId, setActiveClassId] = useState<string | null>(null);
  const [mode, setMode] = useState<RasterEditMode>("paint");
  const [brushRadius, setBrushRadius] = useState(12);

  const sessionQuery = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    refetchOnWindowFocus: false,
  });
  const session = sessionQuery.data as MaskAwareAnnotationSession | undefined;
  const rasterMasks = useMemo(
    () =>
      (session?.mask_annotations ?? []).filter(
        (mask) => mask.geometry_kind === "raster_mask",
      ),
    [session?.mask_annotations],
  );
  const selectedMask =
    rasterMasks.find((mask) => mask.id === selectedMaskId) ?? null;

  useEffect(() => {
    const firstClass = session?.label_classes.find((item) => item.is_active);
    if (activeClassId === null && firstClass) {
      setActiveClassId(firstClass.id);
    }
  }, [activeClassId, session?.label_classes]);

  useEffect(() => {
    if (
      selectedMaskId &&
      !rasterMasks.some((mask) => mask.id === selectedMaskId)
    ) {
      setSelectedMaskId(null);
    }
  }, [rasterMasks, selectedMaskId]);

  const editMutation = useMutation({
    mutationFn: (points: Point[]) => {
      if (!session || !activeClassId) {
        throw new Error("Choose an active class before painting");
      }
      return editRasterMask(imageId, {
        base_revision: session.image.annotation_revision,
        mask_annotation_id: selectedMask?.id ?? null,
        label_class_id: activeClassId,
        mode,
        brush_radius: brushRadius,
        strokes: [{ points }],
      });
    },
    onSuccess: async (response) => {
      setSelectedMaskId(response.mask_annotation.id);
      setActiveClassId(response.mask_annotation.label_class_id);
      await sessionQuery.refetch();
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
    },
  });

  if (sessionQuery.isPending || !session) {
    return (
      <div className="annotation-editor-shell">
        <div className="annotation-editor-splash">
          <h2>Loading raster workspace</h2>
          <p>
            {sessionQuery.error instanceof Error
              ? sessionQuery.error.message
              : "Preparing image and raster masks..."}
          </p>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    );
  }

  const image = session.image;
  const canErase = selectedMask !== null;

  return (
    <div
      className="annotation-editor-shell"
      data-testid="raster-mask-workspace"
    >
      <header className="annotation-editor-topbar">
        <div>
          <p className="eyebrow">Revision-safe raster mask editor</p>
          <h2>{image.original_filename}</h2>
          <p className="annotation-editor-subtitle">
            {project.name} | revision {image.annotation_revision}
          </p>
        </div>
        <div className="annotation-editor-actions">
          <button
            type="button"
            className="secondary"
            disabled={editMutation.isPending}
            onClick={onReturnToMasks}
          >
            Polygon workspace
          </button>
          <button
            type="button"
            className="secondary"
            disabled={editMutation.isPending}
            onClick={onReturnToBoxes}
          >
            Box editor
          </button>
          <button
            type="button"
            disabled={editMutation.isPending}
            onClick={onClose}
          >
            Close editor
          </button>
        </div>
      </header>

      <div className="annotation-editor-body">
        <aside className="annotation-editor-sidebar">
          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Tool</p>
                <h3>Brush controls</h3>
              </div>
              <span>{editMutation.isPending ? "Saving..." : "Ready"}</span>
            </div>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className={mode === "paint" ? "active" : "secondary"}
                disabled={editMutation.isPending}
                onClick={() => setMode("paint")}
              >
                Paint
              </button>
              <button
                type="button"
                className={mode === "erase" ? "active" : "secondary"}
                disabled={!canErase || editMutation.isPending}
                onClick={() => setMode("erase")}
              >
                Erase
              </button>
            </div>
            <label>
              Brush radius: {brushRadius}px
              <input
                type="range"
                min="1"
                max="128"
                value={brushRadius}
                disabled={editMutation.isPending}
                onChange={(event) => setBrushRadius(Number(event.target.value))}
              />
            </label>
            <p className="annotation-helper">
              Each completed stroke is saved as a new immutable raster revision.
            </p>
            {editMutation.error && (
              <p className="form-error">{editMutation.error.message}</p>
            )}
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Classes</p>
                <h3>Paint class</h3>
              </div>
            </div>
            <ul className="annotation-class-list">
              {session.label_classes.map((labelClass) => (
                <li
                  key={labelClass.id}
                  className={`annotation-class-row ${activeClassId === labelClass.id ? "selected" : ""}`}
                >
                  <button
                    type="button"
                    className="annotation-class-button"
                    disabled={editMutation.isPending}
                    onClick={() => setActiveClassId(labelClass.id)}
                  >
                    <span
                      className="annotation-class-swatch"
                      style={{ backgroundColor: labelClass.display_color }}
                    />
                    <span className="annotation-class-text">
                      {labelClass.name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Raster instances</p>
                <h3>{rasterMasks.length} masks</h3>
              </div>
              <button
                type="button"
                className="secondary"
                disabled={editMutation.isPending}
                onClick={() => {
                  setSelectedMaskId(null);
                  setMode("paint");
                }}
              >
                New mask
              </button>
            </div>
            <div className="annotation-selection-list">
              {rasterMasks.length === 0 && <p>No raster masks yet.</p>}
              {rasterMasks.map((mask) => {
                const labelClass = session.label_classes.find(
                  (item) => item.id === mask.label_class_id,
                );
                return (
                  <button
                    type="button"
                    key={mask.id}
                    className={
                      selectedMaskId === mask.id ? "active" : "secondary"
                    }
                    disabled={editMutation.isPending}
                    onClick={() => {
                      setSelectedMaskId(mask.id);
                      setActiveClassId(mask.label_class_id);
                    }}
                  >
                    {labelClass?.name ?? "Unassigned"} | r{mask.revision} |{" "}
                    {mask.area_pixels ?? 0}px²
                  </button>
                );
              })}
            </div>
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <span>
              {selectedMask
                ? `Editing raster revision ${selectedMask.revision}`
                : "Painting a new raster mask"}
            </span>
            <span>{mode === "paint" ? "Paint mode" : "Eraser mode"}</span>
          </div>
          <div
            className="annotation-canvas-frame"
            style={{
              display: "grid",
              placeItems: "center",
              overflow: "auto",
              padding: "1rem",
            }}
          >
            <div
              style={{
                position: "relative",
                width: "min(100%, 1400px)",
                aspectRatio: `${image.width_px} / ${image.height_px}`,
              }}
            >
              <img
                src={imageContentUrl(image.id)}
                alt={image.original_filename}
                draggable={false}
                style={{ display: "block", width: "100%", height: "100%" }}
              />
              {selectedMask && (
                <img
                  src={rasterMaskContentUrl(selectedMask)}
                  alt="Selected raster mask"
                  draggable={false}
                  style={{
                    position: "absolute",
                    inset: 0,
                    width: "100%",
                    height: "100%",
                    opacity: 0.42,
                    pointerEvents: "none",
                  }}
                />
              )}
              <RasterBrushLayer
                width={image.width_px}
                height={image.height_px}
                mode={mode}
                brushRadius={brushRadius}
                disabled={editMutation.isPending || activeClassId === null}
                onStroke={(points) => editMutation.mutate(points)}
              />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
