import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getAnnotationSession,
  imageDisplayUrl,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { RasterBrushLayer } from "./RasterBrushLayer";
import { RasterFillLayer } from "./RasterFillLayer";
import { SkeletonAnalysisPanel } from "./SkeletonAnalysisPanel";
import {
  SkeletonOverlayLayer,
  type SkeletonOverlayModel,
} from "./SkeletonOverlayLayer";
import {
  editRasterMask,
  rasterMaskContentUrl,
  reclassifyRasterMask,
  type RasterEditMode,
} from "./rasterMaskApi";
import { resolveRasterMaskSelection } from "./rasterMaskSelection";
import {
  toEditorMaskAnnotation,
  type MaskAnnotationRecord,
  type Point,
} from "./types";

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
  const [createAnotherMaskRequested, setCreateAnotherMaskRequested] =
    useState(false);
  const [activeClassId, setActiveClassId] = useState<string | null>(null);
  const [mode, setMode] = useState<RasterEditMode>("paint");
  const [brushRadius, setBrushRadius] = useState(12);
  const [fillTolerance, setFillTolerance] = useState(24);
  const [skeletonOverlay, setSkeletonOverlay] =
    useState<SkeletonOverlayModel | null>(null);

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
  const selectedSkeletonMask = useMemo(
    () => (selectedMask ? toEditorMaskAnnotation(selectedMask) : null),
    [selectedMask],
  );
  const selectedMaskClassId = selectedMask?.label_class_id ?? null;
  const selectedMaskColor =
    session?.label_classes.find((item) => item.id === selectedMaskClassId)
      ?.display_color ?? "#2a9d8f";

  useEffect(() => {
    setSelectedMaskId(null);
    setCreateAnotherMaskRequested(false);
    setMode("paint");
  }, [imageId]);

  useEffect(() => {
    const firstClass = session?.label_classes.find((item) => item.is_active);
    if (activeClassId === null && firstClass) {
      setActiveClassId(firstClass.id);
    }
  }, [activeClassId, session?.label_classes]);

  useEffect(() => {
    const nextSelection = resolveRasterMaskSelection(
      selectedMaskId,
      rasterMasks,
      createAnotherMaskRequested,
    );
    if (nextSelection !== selectedMaskId) {
      setSelectedMaskId(nextSelection);
    }
  }, [createAnotherMaskRequested, rasterMasks, selectedMaskId]);

  useEffect(() => {
    if (!createAnotherMaskRequested && selectedMaskClassId) {
      setActiveClassId(selectedMaskClassId);
    }
  }, [createAnotherMaskRequested, selectedMaskClassId]);

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
        fill_tolerance: fillTolerance,
        strokes: [{ points }],
      });
    },
    onSuccess: async (response) => {
      setActiveClassId(response.mask_annotation.label_class_id);
      const deleted = response.mask_annotation.deleted_at !== null;
      if (deleted) {
        setSelectedMaskId(null);
      }
      await sessionQuery.refetch();
      if (!deleted) {
        setSelectedMaskId(response.mask_annotation.id);
      }
      setCreateAnotherMaskRequested(false);
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["skeleton-analyses", response.mask_annotation.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["skeleton-readiness", response.mask_annotation.id],
      });
    },
  });

  const classMutation = useMutation({
    mutationFn: (labelClassId: string) => {
      if (!session || !selectedMask) {
        throw new Error("Select a painted mask before changing its class");
      }
      return reclassifyRasterMask(imageId, selectedMask.id, {
        base_revision: session.image.annotation_revision,
        label_class_id: labelClassId,
      });
    },
    onSuccess: async (response) => {
      setActiveClassId(response.mask_annotation.label_class_id);
      await sessionQuery.refetch();
      setSelectedMaskId(response.mask_annotation.id);
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
    },
  });

  if (sessionQuery.isPending || !session) {
    return (
      <div className="annotation-editor-shell">
        <div className="annotation-editor-splash">
          <h2>Loading brush workspace</h2>
          <p>
            {sessionQuery.error instanceof Error
              ? sessionQuery.error.message
              : "Preparing image and painted mask objects..."}
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
          <p className="eyebrow">Brush mask editor</p>
          <h2>{image.original_filename}</h2>
          <p className="annotation-editor-subtitle">
            {project.name} | revision {image.annotation_revision}
          </p>
        </div>
        <div className="annotation-editor-actions">
          <button
            type="button"
            className="visually-hidden"
            disabled={editMutation.isPending}
            onClick={onReturnToMasks}
          >
            Polygon tool
          </button>
          <button
            type="button"
            className="visually-hidden"
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
        <aside className="annotation-tool-rail" aria-label="Annotation tools" />
        <aside className="annotation-editor-sidebar">
          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Brush tool</p>
                <h3>Paint mask object</h3>
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
              <button
                type="button"
                className={mode === "fill" ? "active" : "secondary"}
                disabled={editMutation.isPending}
                onClick={() => setMode("fill")}
              >
                Fill
              </button>
            </div>
            {mode === "fill" ? (
              <label>
                Fill color tolerance: {fillTolerance}
                <input
                  type="range"
                  className="annotation-range-control"
                  min="0"
                  max="96"
                  value={fillTolerance}
                  disabled={editMutation.isPending}
                  onChange={(event) =>
                    setFillTolerance(Number(event.target.value))
                  }
                />
              </label>
            ) : (
              <label>
                Brush radius: {brushRadius}px
                <input
                  type="range"
                  className="annotation-range-control"
                  min="1"
                  max="128"
                  value={brushRadius}
                  disabled={editMutation.isPending}
                  onChange={(event) =>
                    setBrushRadius(Number(event.target.value))
                  }
                />
              </label>
            )}
            <p className="annotation-helper">
              Paint and erase edit the selected mask object. Erasing the final
              painted pixels deletes that object cleanly. Use Create another
              mask when you want to paint a separate countable object.
            </p>
            {editMutation.error && (
              <p className="form-error">{editMutation.error.message}</p>
            )}
            {classMutation.error && (
              <p className="form-error">{classMutation.error.message}</p>
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
                    disabled={editMutation.isPending || classMutation.isPending}
                    onClick={() => {
                      if (
                        selectedMask &&
                        selectedMask.label_class_id !== labelClass.id
                      ) {
                        classMutation.mutate(labelClass.id);
                        return;
                      }
                      setActiveClassId(labelClass.id);
                    }}
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
                <p className="eyebrow">Painted objects</p>
                <h3>{rasterMasks.length} masks</h3>
              </div>
              <button
                type="button"
                className="secondary"
                disabled={rasterMasks.length === 0 || editMutation.isPending}
                onClick={() => {
                  setCreateAnotherMaskRequested(true);
                  setSelectedMaskId(null);
                  setMode("paint");
                }}
              >
                Create another mask
              </button>
            </div>
            <div className="annotation-selection-list">
              {rasterMasks.length === 0 && (
                <p>
                  Your first stroke will create the first painted mask object.
                </p>
              )}
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
                      setCreateAnotherMaskRequested(false);
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

          <section className="annotation-sidebar-section">
            <SkeletonAnalysisPanel
              selectedMask={selectedSkeletonMask}
              documentDirty={
                editMutation.isPending || classMutation.isPending
              }
              onOverlayChange={setSkeletonOverlay}
            />
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <span>
              {selectedMask
                ? `Editing painted object revision ${selectedMask.revision}`
                : createAnotherMaskRequested
                  ? "Painting a separate mask object"
                  : "Painting the first mask object"}
            </span>
            <span>
              {mode === "paint"
                ? "Paint mode"
                : mode === "erase"
                  ? "Eraser mode"
                  : "Fill mode"}
            </span>
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
                src={imageDisplayUrl(image.id)}
                alt={image.original_filename}
                draggable={false}
                style={{ display: "block", width: "100%", height: "100%" }}
              />
              {selectedMask && (
                <div
                  data-testid="selected-raster-mask-overlay"
                  aria-label="Selected raster mask"
                  style={{
                    position: "absolute",
                    inset: 0,
                    width: "100%",
                    height: "100%",
                    opacity: 0.42,
                    pointerEvents: "none",
                    backgroundColor: selectedMaskColor,
                    WebkitMaskImage: `url(${rasterMaskContentUrl(selectedMask)})`,
                    maskImage: `url(${rasterMaskContentUrl(selectedMask)})`,
                    WebkitMaskRepeat: "no-repeat",
                    maskRepeat: "no-repeat",
                    WebkitMaskPosition: "center",
                    maskPosition: "center",
                    WebkitMaskSize: "100% 100%",
                    maskSize: "100% 100%",
                  }}
                />
              )}
              {mode === "fill" ? (
                <RasterFillLayer
                  width={image.width_px}
                  height={image.height_px}
                  disabled={editMutation.isPending || activeClassId === null}
                  onFill={(point) => editMutation.mutate([point])}
                />
              ) : (
                <RasterBrushLayer
                  width={image.width_px}
                  height={image.height_px}
                  mode={mode}
                  brushRadius={brushRadius}
                  disabled={editMutation.isPending || activeClassId === null}
                  onStroke={(points) => editMutation.mutate(points)}
                />
              )}
              {skeletonOverlay && (
                <SkeletonOverlayLayer
                  width={image.width_px}
                  height={image.height_px}
                  {...skeletonOverlay}
                />
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
