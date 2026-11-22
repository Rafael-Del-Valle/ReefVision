import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getAnnotationSession,
  getClassVisibilityBundle,
  imageDisplayUrl,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { RasterBrushLayer } from "./RasterBrushLayer";
import { shouldIgnoreShortcutTarget } from "../../components/ui/keyboardShortcuts";
import { RasterFillLayer } from "./RasterFillLayer";
import { SkeletonAnalysisPanel } from "./SkeletonAnalysisPanel";
import { ImageViewport } from "./ImageViewport";
import {
  SkeletonOverlayLayer,
  type SkeletonOverlayModel,
} from "./SkeletonOverlayLayer";
import {
  editRasterMask,
  duplicateRasterMask,
  rasterMaskContentUrl,
  reclassifyRasterMask,
  type RasterEditMode,
} from "./rasterMaskApi";
import {
  copyAnnotations,
  readInternalAnnotationClipboard,
  writeInternalAnnotationClipboard,
} from "./annotationClipboard";
import { resolveClassVisibilityState, visibilitySourceLabel } from "./classVisibility";
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

interface RasterEditCommand {
  imageId: string;
  baseRevision: number;
  maskAnnotationId: string | null;
  labelClassId: string;
  mode: RasterEditMode;
  brushRadius: number;
  fillTolerance: number;
  points: Point[];
}

interface RasterClassCommand {
  imageId: string;
  baseRevision: number;
  maskAnnotationId: string;
  labelClassId: string;
}

interface RasterDuplicateCommand {
  imageId: string;
  baseRevision: number;
  maskAnnotationId: string;
}

type RasterEditContext = Omit<RasterEditCommand, "points">;

export function RasterMaskWorkspace({
  project,
  imageId,
  onReturnToMasks,
  onReturnToBoxes,
  onClose,
}: RasterMaskWorkspaceProps) {
  const queryClient = useQueryClient();
  const [selectedMaskId, setSelectedMaskId] = useState<string | null>(null);
  const strokeContextRef = useRef<RasterEditContext | null>(null);
  // Three revision-changing operations share a synchronous lock, including
  // keyboard shortcuts fired before React renders a pending button state.
  const mutationInFlightRef = useRef(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const acquireMutation = () => {
    if (mutationInFlightRef.current) return false;
    mutationInFlightRef.current = true;
    setMutationBusy(true);
    return true;
  };
  const releaseMutation = () => {
    mutationInFlightRef.current = false;
    setMutationBusy(false);
  };
  // Late saves from a previous image must not reselect its class or mask in
  // the newly opened image. Pending mutations can outlive navigation.
  const currentImageIdRef = useRef(imageId);
  const [createAnotherMaskRequested, setCreateAnotherMaskRequested] =
    useState(false);
  const [activeClassId, setActiveClassId] = useState<string | null>(null);
  const [mode, setMode] = useState<RasterEditMode>("paint");
  const [brushRadius, setBrushRadius] = useState(12);
  const [fillTolerance, setFillTolerance] = useState(24);
  const [skeletonOverlay, setSkeletonOverlay] =
    useState<SkeletonOverlayModel | null>(null);
  const [clipboardMessage, setClipboardMessage] = useState<string | null>(null);

  const sessionQuery = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    refetchOnWindowFocus: false,
  });
  const visibilityQuery = useQuery({
    queryKey: ["class-visibility", project.id],
    queryFn: ({ signal }) => getClassVisibilityBundle(project.id, signal),
    refetchOnWindowFocus: false,
    staleTime: 60_000,
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

  // An in-progress gesture belongs to the image, class and mask selected
  // when its initiating pointer went down, not whatever is selected at release.
  function captureEditContext(): RasterEditContext | null {
    if (
      mutationInFlightRef.current ||
      !session ||
      !activeClassId ||
      targetClassIsHidden
    ) {
      return null;
    }
    return {
      imageId,
      baseRevision: session.image.annotation_revision,
      maskAnnotationId: selectedMask?.id ?? null,
      labelClassId: activeClassId,
      mode,
      brushRadius,
      fillTolerance,
    };
  }
  const selectedSkeletonMask = useMemo(
    () => (selectedMask ? toEditorMaskAnnotation(selectedMask) : null),
    [selectedMask],
  );
  const selectedMaskClassId = selectedMask?.label_class_id ?? null;
  // The main box editor already respects saved segmentation visibility. The
  // separate brush workspace must use the same per-user/project precedence.
  // Never apply another project's cached visibility to this biological image.
  const visibilityBundle =
    visibilityQuery.data?.project_id === project.id
      ? visibilityQuery.data
      : undefined;
  const segmentationVisibility = resolveClassVisibilityState(
    "segmentation_overlays",
    visibilityBundle,
    {},
    session?.label_classes.map((item) => item.id) ?? [],
  );
  const targetClassIsHidden = segmentationVisibility.hiddenClassIds.some(
    (id) => id === selectedMaskClassId || id === activeClassId,
  );
  const selectedMaskClassIsHidden =
    selectedMaskClassId !== null &&
    segmentationVisibility.hiddenClassIds.includes(selectedMaskClassId);
  const selectedMaskColor =
    session?.label_classes.find((item) => item.id === selectedMaskClassId)
      ?.display_color ?? "#2a9d8f";

  useEffect(() => {
    currentImageIdRef.current = imageId;
    strokeContextRef.current = null;
    setSelectedMaskId(null);
    setActiveClassId(null);
    setCreateAnotherMaskRequested(false);
    setMode("paint");
  }, [imageId]);

  useEffect(() => {
    const firstClass = session?.label_classes.find((item) => item.is_active);
    if (
      session &&
      !session.label_classes.some(
        (item) => item.id === activeClassId && item.is_active,
      )
    ) {
      setActiveClassId(firstClass?.id ?? null);
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
    mutationFn: (command: RasterEditCommand) =>
      editRasterMask(command.imageId, {
        base_revision: command.baseRevision,
        mask_annotation_id: command.maskAnnotationId,
        label_class_id: command.labelClassId,
        mode: command.mode,
        brush_radius: command.brushRadius,
        fill_tolerance: command.fillTolerance,
        strokes: [{ points: command.points }],
      }),
    onSuccess: async (response) => {
      if (response.image.id !== currentImageIdRef.current) {
        // An old-image result can invalidate its own caches, but must never
        // select an old biological class/mask in the newly opened image.
        await queryClient.invalidateQueries({
          queryKey: ["annotation-session", response.image.id],
        });
        await queryClient.invalidateQueries({
          queryKey: ["project-images", response.image.project_id],
        });
        return;
      }
      setActiveClassId(response.mask_annotation.label_class_id);
      const deleted = response.mask_annotation.deleted_at !== null;
      if (deleted) {
        setSelectedMaskId(null);
      }
      await sessionQuery.refetch();
      if (response.image.id !== currentImageIdRef.current) return;
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
    onSettled: releaseMutation,
  });

  const classMutation = useMutation({
    mutationFn: (command: RasterClassCommand) =>
      reclassifyRasterMask(command.imageId, command.maskAnnotationId, {
        base_revision: command.baseRevision,
        label_class_id: command.labelClassId,
      }),
    onSuccess: async (response) => {
      if (response.image.id !== currentImageIdRef.current) {
        await queryClient.invalidateQueries({
          queryKey: ["annotation-session", response.image.id],
        });
        await queryClient.invalidateQueries({
          queryKey: ["project-images", response.image.project_id],
        });
        return;
      }
      setActiveClassId(response.mask_annotation.label_class_id);
      await sessionQuery.refetch();
      if (response.image.id !== currentImageIdRef.current) return;
      setSelectedMaskId(response.mask_annotation.id);
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
    },
    onSettled: releaseMutation,
  });

  const duplicateMutation = useMutation({
    mutationFn: (command: RasterDuplicateCommand) =>
      duplicateRasterMask(command.imageId, command.maskAnnotationId, {
        base_revision: command.baseRevision,
      }),
    onSuccess: async (response) => {
      if (response.image.id !== currentImageIdRef.current) {
        await queryClient.invalidateQueries({
          queryKey: ["annotation-session", response.image.id],
        });
        await queryClient.invalidateQueries({
          queryKey: ["project-images", response.image.project_id],
        });
        return;
      }
      await sessionQuery.refetch();
      if (response.image.id !== currentImageIdRef.current) return;
      setSelectedMaskId(response.mask_annotation.id);
      setCreateAnotherMaskRequested(false);
      setClipboardMessage(
        "Duplicated the raster pixels as a new unverified mask.",
      );
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
    },
    onSettled: releaseMutation,
  });

  const requestEdit = (command: RasterEditCommand) => {
    if (acquireMutation()) editMutation.mutate(command);
  };
  const requestClassChange = (labelClassId: string) => {
    if (!session || !selectedMask || !acquireMutation()) return;
    classMutation.mutate({
      imageId: session.image.id,
      baseRevision: session.image.annotation_revision,
      maskAnnotationId: selectedMask.id,
      labelClassId,
    });
  };
  const requestDuplicate = (maskId: string) => {
    if (
      !session ||
      !rasterMasks.some((mask) => mask.id === maskId) ||
      !acquireMutation()
    ) {
      return;
    }
    duplicateMutation.mutate({
      imageId: session.image.id,
      baseRevision: session.image.annotation_revision,
      maskAnnotationId: maskId,
    });
  };

  const copySelectedRaster = useCallback(() => {
    if (!session || !selectedMask) {
      setClipboardMessage("Select a raster mask before copying.");
      return;
    }
    const clipboard = copyAnnotations(
      {
        annotation_status: session.image.annotation_status,
        annotations: [],
        maskAnnotations: [toEditorMaskAnnotation(selectedMask)],
        deletedMaskAnnotationIds: [],
      },
      [],
      [selectedMask.id],
      {
        id: session.image.id,
        projectId: project.id,
        width: session.image.width_px,
        height: session.image.height_px,
      },
    );
    writeInternalAnnotationClipboard(clipboard);
    setClipboardMessage(
      "Copied 1 raster mask to ReefVision's internal clipboard.",
    );
  }, [selectedMask, session]);

  const pasteRaster = useCallback(() => {
    const clipboard = readInternalAnnotationClipboard();
    if (!session || !clipboard || clipboard.rasterMaskIds.length !== 1) {
      setClipboardMessage("Copy one raster mask before pasting.");
      return;
    }
    if (clipboard.sourceImage.id !== session.image.id) {
      setClipboardMessage(
        "Raster masks can only be pasted on their source image; ReefVision will not remap pixels.",
      );
      return;
    }
    requestDuplicate(clipboard.rasterMaskIds[0]);
  }, [requestDuplicate, session]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (shouldIgnoreShortcutTarget(event.target)) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      if (key === "c") {
        event.preventDefault();
        copySelectedRaster();
      } else if (key === "v") {
        event.preventDefault();
        pasteRaster();
      } else if (key === "d" && selectedMask) {
        event.preventDefault();
        requestDuplicate(selectedMask.id);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [copySelectedRaster, pasteRaster, requestDuplicate, selectedMask]);

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
  const canErase = selectedMask !== null && !targetClassIsHidden;

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
            disabled={mutationBusy}
            onClick={onReturnToMasks}
          >
            Polygon tool
          </button>
          <button
            type="button"
            className="visually-hidden"
            disabled={mutationBusy}
            onClick={onReturnToBoxes}
          >
            Box editor
          </button>
          <button type="button" disabled={mutationBusy} onClick={onClose}>
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
              <span>{mutationBusy ? "Saving..." : "Ready"}</span>
            </div>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className={mode === "paint" ? "active" : "secondary"}
                aria-pressed={mode === "paint"}
                disabled={mutationBusy}
                onClick={() => setMode("paint")}
              >
                Paint
              </button>
              <button
                type="button"
                className={mode === "erase" ? "active" : "secondary"}
                aria-pressed={mode === "erase"}
                disabled={!canErase || mutationBusy}
                onClick={() => setMode("erase")}
              >
                Erase
              </button>
              <button
                type="button"
                className={mode === "fill" ? "active" : "secondary"}
                aria-pressed={mode === "fill"}
                disabled={mutationBusy}
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
                  disabled={mutationBusy}
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
                  disabled={mutationBusy}
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
            {duplicateMutation.error && (
              <p className="form-error">{duplicateMutation.error.message}</p>
            )}
            {clipboardMessage && <p role="status">{clipboardMessage}</p>}
            <p
              className="annotation-helper"
              data-testid="raster-visibility-source"
            >
              Segmentation overlay visibility:{" "}
              {visibilityQuery.isPending
                ? "Loading saved settings"
                : visibilityQuery.isError
                  ? "Settings unavailable (showing all)"
                  : visibilitySourceLabel(segmentationVisibility.source)}
            </p>
            {targetClassIsHidden && (
              <p
                className="annotation-helper"
                data-testid="raster-hidden-class-notice"
                role="status"
              >
                This paint target is hidden by saved segmentation visibility.
                Its original pixels and revision remain unchanged. Show its
                class in the main annotation editor before painting or filling.
              </p>
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
                    disabled={mutationBusy}
                    onClick={() => {
                      if (
                        selectedMask &&
                        selectedMask.label_class_id !== labelClass.id
                      ) {
                        requestClassChange(labelClass.id);
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
                disabled={rasterMasks.length === 0 || mutationBusy}
                onClick={() => {
                  setCreateAnotherMaskRequested(true);
                  setSelectedMaskId(null);
                  setMode("paint");
                }}
              >
                Create another mask
              </button>
            </div>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className="secondary"
                title="Copy to ReefVision's internal clipboard (Ctrl/Cmd+C)"
                aria-keyshortcuts="Control+C Meta+C"
                disabled={!selectedMask || mutationBusy}
                onClick={copySelectedRaster}
              >
                Copy
              </button>
              <button
                type="button"
                className="secondary"
                title="Duplicate raster mask (Ctrl/Cmd+D)"
                aria-keyshortcuts="Control+D Meta+D"
                disabled={!selectedMask || mutationBusy}
                onClick={() =>
                  selectedMask && requestDuplicate(selectedMask.id)
                }
              >
                Duplicate
              </button>
              <button
                type="button"
                className="secondary"
                title="Paste compatible raster mask (Ctrl/Cmd+V)"
                aria-keyshortcuts="Control+V Meta+V"
                disabled={mutationBusy}
                onClick={pasteRaster}
              >
                Paste
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
                    disabled={mutationBusy}
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
              documentDirty={mutationBusy}
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
          <ImageViewport
            width={image.width_px}
            height={image.height_px}
            label="Raster mask viewport"
          >
            <img
              src={imageDisplayUrl(image.id)}
              alt={image.original_filename}
              draggable={false}
              style={{ display: "block", width: "100%", height: "100%" }}
            />
            {selectedMask && !selectedMaskClassIsHidden && (
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
                disabled={mutationBusy || activeClassId === null || targetClassIsHidden}
                onFill={(point) => {
                  const context = captureEditContext();
                  if (context) {
                    requestEdit({
                      ...context,
                      mode: "fill",
                      points: [point],
                    });
                  }
                }}
              />
            ) : (
              <RasterBrushLayer
                key={imageId}
                width={image.width_px}
                height={image.height_px}
                mode={mode}
                brushRadius={brushRadius}
                disabled={mutationBusy || activeClassId === null || targetClassIsHidden}
                onStrokeStart={() => {
                  strokeContextRef.current = captureEditContext();
                }}
                onStrokeCancel={() => {
                  strokeContextRef.current = null;
                }}
                onStroke={(points, settings) => {
                  const context = strokeContextRef.current;
                  strokeContextRef.current = null;
                  if (context) {
                    requestEdit({
                      ...context,
                      mode: settings.mode,
                      brushRadius: settings.brushRadius,
                      points,
                    });
                  }
                }}
              />
            )}
            {skeletonOverlay && (
              <SkeletonOverlayLayer
                width={image.width_px}
                height={image.height_px}
                {...skeletonOverlay}
              />
            )}
          </ImageViewport>
        </section>
      </div>
    </div>
  );
}
