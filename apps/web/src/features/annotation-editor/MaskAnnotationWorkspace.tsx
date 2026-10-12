import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  getAnnotationSession,
  imageDisplayUrl,
  saveAnnotations,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
  toAnnotationSavePayload,
  type ExtendedAnnotationSavePayload,
} from "./annotationEditorReducer";
import {
  copyAnnotations,
  pasteAnnotations,
  readInternalAnnotationClipboard,
  writeInternalAnnotationClipboard,
} from "./annotationClipboard";
import { CenterlineMeasurementLayer } from "./CenterlineMeasurementLayer";
import {
  addMaskAnnotation,
  changeMaskAnnotationClass,
  deleteMaskAnnotations,
  updateMaskAnnotation,
} from "./maskDocumentOperations";
import { MaskMeasurementPanel } from "./MaskMeasurementPanel";
import { SkeletonAnalysisPanel } from "./SkeletonAnalysisPanel";
import { ImageViewport } from "./ImageViewport";
import {
  SkeletonOverlayLayer,
  type SkeletonOverlayModel,
} from "./SkeletonOverlayLayer";
import { PolygonMaskLayer, polygonMaskFromPoints } from "./PolygonMaskLayer";
import {
  generatePolygonFill,
  generateSmartClosePolygon,
} from "./rasterMaskApi";
import type {
  AnnotationDocument,
  EditorMaskAnnotation,
  EditorTool,
  MaskAnnotationRecord,
  Point,
} from "./types";

type MaskAwareAnnotationSession = AnnotationSession & {
  mask_annotations?: MaskAnnotationRecord[];
};

interface MaskAnnotationWorkspaceProps {
  project: Project;
  imageId: string;
  initialTool?: EditorTool;
  onToolChange?: (tool: EditorTool) => void;
  onReturnToBoxes: () => void;
  onOpenBrush?: () => void;
  onClose: () => void;
}

export function MaskAnnotationWorkspace({
  project,
  imageId,
  initialTool,
  onToolChange,
  onReturnToBoxes,
  onOpenBrush,
  onClose,
}: MaskAnnotationWorkspaceProps) {
  const queryClient = useQueryClient();
  const [centerlineEditing, setCenterlineEditing] = useState(false);
  const [skeletonOverlay, setSkeletonOverlay] =
    useState<SkeletonOverlayModel | null>(null);
  const [smartCloseStrength, setSmartCloseStrength] = useState(0);
  const [fillPending, setFillPending] = useState(false);
  const [fillError, setFillError] = useState<string | null>(null);
  const [clipboardMessage, setClipboardMessage] = useState<string | null>(null);
  const fillRequestRef = useRef<AbortController | null>(null);
  const [state, dispatch] = useReducer(
    annotationEditorReducer,
    initialAnnotationEditorState,
  );
  const stateRef = useRef(state);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);
  const loadedImageIdRef = useRef<string | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    onToolChange?.(state.tool);
  }, [onToolChange, state.tool]);

  useEffect(() => {
    setCenterlineEditing(false);
  }, [imageId]);

  useEffect(() => {
    setFillPending(false);
    setFillError(null);
    return () => {
      fillRequestRef.current?.abort();
      fillRequestRef.current = null;
    };
  }, [imageId, state.tool]);

  const sessionQuery = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    const session = sessionQuery.data;
    if (!session) {
      return;
    }
    const snapshot = stateRef.current;
    const imageChanged = loadedImageIdRef.current !== imageId;
    const newerSameImage =
      !imageChanged &&
      session.image.annotation_revision > snapshot.baseRevision;
    if (!imageChanged && !newerSameImage) {
      return;
    }
    if (
      !imageChanged &&
      (isDirty(snapshot) || snapshot.saveState === "saving")
    ) {
      return;
    }
    dispatch({ type: "loadSession", session });
    if (initialTool) {
      dispatch({ type: "setTool", tool: initialTool });
    }
    loadedImageIdRef.current = imageId;
  }, [imageId, initialTool, sessionQuery.data]);

  const { mutateAsync: persistDocument, isPending: savePending } = useMutation({
    mutationFn: (payload: ExtendedAnnotationSavePayload) =>
      saveAnnotations(imageId, payload),
  });

  const saveNow = useCallback(async (): Promise<boolean> => {
    const snapshot = state;
    if (!isDirty(snapshot)) {
      return true;
    }
    if (savePromiseRef.current) {
      return savePromiseRef.current;
    }

    const sentVersion = snapshot.documentVersion;
    dispatch({ type: "saveStarted", sentVersion });
    const request = persistDocument(toAnnotationSavePayload(snapshot))
      .then(async (response) => {
        const responseWithMasks = response as typeof response & {
          mask_annotations?: MaskAnnotationRecord[];
        };
        queryClient.setQueryData<MaskAwareAnnotationSession>(
          ["annotation-session", imageId],
          (current) =>
            current
              ? {
                  ...current,
                  image: response.image,
                  annotations: response.annotations,
                  counts_by_class: response.counts_by_class,
                  mask_annotations:
                    responseWithMasks.mask_annotations ??
                    current.mask_annotations ??
                    [],
                }
              : current,
        );
        dispatch({ type: "saveSucceeded", sentVersion, response });
        await queryClient.invalidateQueries({
          queryKey: ["project-images", project.id],
        });
        await queryClient.invalidateQueries({
          queryKey: ["mask-measurements"],
        });
        return true;
      })
      .catch((error: unknown) => {
        const message =
          error instanceof Error ? error.message : "Mask save failed";
        dispatch({
          type: "saveFailed",
          message,
          conflict: message.toLowerCase().includes("revision conflict"),
        });
        return false;
      })
      .finally(() => {
        savePromiseRef.current = null;
      });
    savePromiseRef.current = request;
    return request;
  }, [persistDocument, project.id, queryClient, state]);

  useEffect(() => {
    if (!isDirty(state) || state.saveState === "saving") {
      return;
    }
    const timeout = window.setTimeout(() => {
      void saveNow();
    }, 900);
    return () => window.clearTimeout(timeout);
  }, [saveNow, state]);

  const commitDocument = useCallback(
    (
      document: AnnotationDocument,
      maskSelection = stateRef.current.selectedMaskIds,
    ) => {
      dispatch({ type: "commitDocument", document, maskSelection });
    },
    [],
  );

  function createMask(mask: EditorMaskAnnotation) {
    commitDocument(addMaskAnnotation(stateRef.current.document, mask), [
      mask.id,
    ]);
  }

  async function fillPolygon(seed: Point) {
    const labelClassId = stateRef.current.activeClassId;
    const image = sessionQuery.data?.image;
    if (
      !labelClassId ||
      !image ||
      loadedImageIdRef.current !== imageId ||
      fillRequestRef.current
    )
      return;
    const controller = new AbortController();
    fillRequestRef.current = controller;
    setFillPending(true);
    setFillError(null);
    try {
      const result = await generatePolygonFill(
        imageId,
        { seed, tolerance: 24 },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const points = result.points;
      if (
        !Array.isArray(points) ||
        points.length < 3 ||
        points.some(
          (point) =>
            !point ||
            !Number.isFinite(point.x) ||
            !Number.isFinite(point.y) ||
            point.x < 0 ||
            point.y < 0 ||
            point.x > image.width_px ||
            point.y > image.height_px,
        ) ||
        Math.abs(
          points.reduce((sum, point, index) => {
            const next = points[(index + 1) % points.length];
            return sum + point.x * next.y - next.x * point.y;
          }, 0),
        ) === 0
      )
        throw new Error("Fill returned an invalid or empty polygon");
      createMask(polygonMaskFromPoints(points, labelClassId));
    } catch (error) {
      if (!controller.signal.aborted)
        setFillError(
          error instanceof Error ? error.message : "Polygon Fill failed",
        );
    } finally {
      if (fillRequestRef.current === controller) {
        fillRequestRef.current = null;
        setFillPending(false);
      }
    }
  }

  async function smartClosePolygon(seed: Point) {
    const labelClassId = stateRef.current.activeClassId;
    const image = sessionQuery.data?.image;
    if (
      !labelClassId ||
      !image ||
      loadedImageIdRef.current !== imageId ||
      fillRequestRef.current
    )
      return;
    const controller = new AbortController();
    fillRequestRef.current = controller;
    setFillPending(true);
    setFillError(null);
    try {
      const result = await generateSmartClosePolygon(
        imageId,
        { seed, closure_strength: smartCloseStrength },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const points = result.points;
      if (
        !Array.isArray(points) ||
        points.length < 3 ||
        points.some(
          (point) =>
            !point ||
            !Number.isFinite(point.x) ||
            !Number.isFinite(point.y) ||
            point.x < 0 ||
            point.y < 0 ||
            point.x > image.width_px ||
            point.y > image.height_px,
        ) ||
        Math.abs(
          points.reduce((sum, point, index) => {
            const next = points[(index + 1) % points.length];
            return sum + point.x * next.y - next.x * point.y;
          }, 0),
        ) === 0
      )
        throw new Error("Smart Close returned an invalid or empty polygon");
      createMask(polygonMaskFromPoints(points, labelClassId));
    } catch (error) {
      if (!controller.signal.aborted)
        setFillError(
          error instanceof Error ? error.message : "Smart Close failed",
        );
    } finally {
      if (fillRequestRef.current === controller) {
        fillRequestRef.current = null;
        setFillPending(false);
      }
    }
  }

  function updateMask(mask: EditorMaskAnnotation) {
    commitDocument(updateMaskAnnotation(stateRef.current.document, mask), [
      mask.id,
    ]);
  }

  const deleteMasks = useCallback(
    (maskIds: string[]) => {
      commitDocument(
        deleteMaskAnnotations(stateRef.current.document, maskIds),
        [],
      );
    },
    [commitDocument],
  );

  const copySelection = useCallback(() => {
    const snapshot = stateRef.current;
    const image = sessionQuery.data?.image;
    if (!image || snapshot.selectedMaskIds.length === 0) {
      setClipboardMessage("Select a polygon before copying.");
      return null;
    }
    const clipboard = copyAnnotations(
      snapshot.document,
      [],
      snapshot.selectedMaskIds,
      { id: image.id, width: image.width_px, height: image.height_px },
    );
    writeInternalAnnotationClipboard(clipboard);
    const count = clipboard.items.length;
    setClipboardMessage(
      clipboard.skippedRasterCount
        ? `Copied ${count} polygon${count === 1 ? "" : "s"}. Raster masks must be duplicated in the brush workspace.`
        : `Copied ${count} polygon${count === 1 ? "" : "s"} to ReefVision's internal clipboard.`,
    );
    return clipboard;
  }, [sessionQuery.data?.image]);

  const pasteClipboard = useCallback(
    (clipboard = readInternalAnnotationClipboard()) => {
      const image = sessionQuery.data?.image;
      if (!image || !clipboard) {
        setClipboardMessage("Copy an annotation before pasting.");
        return;
      }
      const result = pasteAnnotations(
        clipboard,
        { id: image.id, width: image.width_px, height: image.height_px },
        () => globalThis.crypto.randomUUID(),
      );
      if (!result.ok) {
        setClipboardMessage(result.reason);
        return;
      }
      if (result.annotations.length > 0) {
        setClipboardMessage(
          "Box annotations can only be pasted in the main Select workspace.",
        );
        return;
      }
      const snapshot = stateRef.current;
      commitDocument(
        {
          ...snapshot.document,
          maskAnnotations: [
            ...snapshot.document.maskAnnotations,
            ...result.maskAnnotations,
          ],
        },
        result.maskAnnotations.map((mask) => mask.id),
      );
      writeInternalAnnotationClipboard(result.nextClipboard);
      setClipboardMessage(
        `Pasted ${result.maskAnnotations.length} unverified polygon${result.maskAnnotations.length === 1 ? "" : "s"} in source-image coordinates.`,
      );
    },
    [commitDocument, sessionQuery.data?.image],
  );

  const duplicateSelection = useCallback(() => {
    const clipboard = copySelection();
    if (clipboard?.items.length) pasteClipboard(clipboard);
  }, [copySelection, pasteClipboard]);

  useEffect(() => {
    const handleDeleteShortcut = (event: globalThis.KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          Boolean(
            target.closest("input, textarea, select, [contenteditable='true']"),
          ))
      ) {
        return;
      }

      const snapshot = stateRef.current;
      const command = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (command && key === "z") {
        event.preventDefault();
        event.stopPropagation();
        dispatch({ type: event.shiftKey ? "redo" : "undo" });
        return;
      }
      if (command && key === "y") {
        event.preventDefault();
        event.stopPropagation();
        dispatch({ type: "redo" });
        return;
      }
      if (command && key === "c") {
        event.preventDefault();
        event.stopPropagation();
        copySelection();
        return;
      }
      if (command && key === "v") {
        event.preventDefault();
        event.stopPropagation();
        pasteClipboard();
        return;
      }
      if (command && key === "d") {
        event.preventDefault();
        event.stopPropagation();
        duplicateSelection();
        return;
      }
      if (event.key === "Escape" && fillRequestRef.current) {
        event.preventDefault();
        fillRequestRef.current.abort();
        fillRequestRef.current = null;
        setFillPending(false);
        setClipboardMessage("Canceled the in-progress mask operation.");
        return;
      }
      if (
        snapshot.tool !== "select" ||
        snapshot.selectedMaskIds.length === 0 ||
        (event.key !== "Backspace" && event.key !== "Delete")
      ) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      deleteMasks(snapshot.selectedMaskIds);
    };

    window.addEventListener("keydown", handleDeleteShortcut, true);
    return () =>
      window.removeEventListener("keydown", handleDeleteShortcut, true);
  }, [copySelection, deleteMasks, duplicateSelection, pasteClipboard]);

  function applyClass(labelClassId: string) {
    if (state.selectedMaskIds.length > 0) {
      commitDocument(
        changeMaskAnnotationClass(
          state.document,
          state.selectedMaskIds,
          labelClassId,
        ),
      );
    }
    dispatch({ type: "setActiveClassId", classId: labelClassId });
  }

  const refreshAfterMeasurementChange = useCallback(async (): Promise<void> => {
    const refreshed = await sessionQuery.refetch();
    if (refreshed.data) {
      dispatch({ type: "loadSession", session: refreshed.data });
      loadedImageIdRef.current = imageId;
    }
    await queryClient.invalidateQueries({
      queryKey: ["project-images", project.id],
    });
    await queryClient.invalidateQueries({ queryKey: ["mask-measurements"] });
  }, [imageId, project.id, queryClient, sessionQuery]);

  async function leaveWorkspace(destination: "boxes" | "close" | "brush") {
    fillRequestRef.current?.abort();
    fillRequestRef.current = null;
    setFillPending(false);
    const saved = await saveNow();
    if (!saved && !window.confirm("Discard unsaved mask edits?")) {
      return;
    }
    await queryClient.invalidateQueries({
      queryKey: ["annotation-session", imageId],
    });
    if (destination === "brush") {
      onOpenBrush?.();
    } else if (destination === "boxes") {
      onReturnToBoxes();
    } else {
      onClose();
    }
  }

  const classColors = useMemo(
    () =>
      Object.fromEntries(
        (sessionQuery.data?.label_classes ?? []).map((labelClass) => [
          labelClass.id,
          labelClass.display_color,
        ]),
      ),
    [sessionQuery.data?.label_classes],
  );
  const maskCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const mask of state.document.maskAnnotations) {
      if (mask.label_class_id) {
        counts.set(
          mask.label_class_id,
          (counts.get(mask.label_class_id) ?? 0) + 1,
        );
      }
    }
    return counts;
  }, [state.document.maskAnnotations]);

  if (sessionQuery.isPending || !sessionQuery.data) {
    return (
      <div className="annotation-editor-shell">
        <div className="annotation-editor-splash">
          <h2>Loading mask workspace</h2>
          <p>
            {sessionQuery.error instanceof Error
              ? sessionQuery.error.message
              : "Preparing masks and image data..."}
          </p>
          <button type="button" onClick={() => onClose()}>
            Close
          </button>
        </div>
      </div>
    );
  }

  const image = sessionQuery.data.image;
  const selectedMasks = state.document.maskAnnotations.filter((mask) =>
    state.selectedMaskIds.includes(mask.id),
  );
  const selectedMeasurementMask =
    selectedMasks.length === 1 ? selectedMasks[0] : null;
  const measurementEditingAvailable =
    selectedMeasurementMask?.persisted === true && !isDirty(state);

  return (
    <div
      className="annotation-editor-shell"
      data-testid="mask-workspace"
      data-active-tool={state.tool}
    >
      <header className="annotation-editor-topbar">
        <div>
          <p className="eyebrow">Editable segmentation workspace</p>
          <h2>{image.original_filename}</h2>
          <p className="annotation-editor-subtitle">
            {project.name} | {image.width_px} x {image.height_px} px
          </p>
        </div>
        <div className="annotation-editor-actions">
          <button
            type="button"
            className={state.tool === "select" ? "active" : "secondary"}
            data-testid="activate-mask-select-tool"
            title="Select masks and edit polygon vertices"
            onClick={() => {
              setCenterlineEditing(false);
              dispatch({ type: "setTool", tool: "select" });
            }}
          >
            Select vertices
          </button>
          <button
            type="button"
            className="visually-hidden"
            data-testid="activate-polygon-tool"
            title="Draw a polygon mask"
            onClick={() => {
              setCenterlineEditing(false);
              dispatch({ type: "setTool", tool: "polygon" });
            }}
          >
            Polygon
          </button>
          {onOpenBrush && (
            <button
              type="button"
              className="visually-hidden"
              data-testid="activate-mask-brush-tool"
              data-mask-workspace-destination="raster"
              onClick={() => void leaveWorkspace("brush")}
              title="Save polygon edits and open raster Brush workspace"
            >
              Brush
            </button>
          )}
          <button
            type="button"
            className="visually-hidden"
            data-testid="activate-polygon-fill-tool"
            title="Click an enclosed region to create one countable mask object"
            disabled={state.activeClassId === null}
            onClick={() => {
              setCenterlineEditing(false);
              dispatch({ type: "setTool", tool: "fill" });
            }}
          >
            Fill object
          </button>
          <button
            type="button"
            className="visually-hidden"
            data-testid="activate-smart-close-tool"
            title="Predict and close a weak or broken opening boundary"
            disabled={state.activeClassId === null}
            onClick={() => {
              setCenterlineEditing(false);
              dispatch({ type: "setTool", tool: "smart_close" });
            }}
          >
            Smart Close
          </button>
          <button
            type="button"
            className={centerlineEditing ? "active" : "secondary"}
            data-testid="activate-centerline-tool"
            title="Draw total-linear-extension centerline points"
            disabled={!measurementEditingAvailable}
            onClick={() => {
              dispatch({ type: "setTool", tool: "select" });
              setCenterlineEditing((current) => !current);
            }}
          >
            Centerline
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!isDirty(state) || savePending}
            onClick={() => void saveNow()}
          >
            {savePending ? "Saving..." : "Save now"}
          </button>
          <button
            type="button"
            className="visually-hidden"
            onClick={() => void leaveWorkspace("boxes")}
            data-mask-workspace-destination="boxes"
          >
            Box editor
          </button>
          <button type="button" onClick={() => void leaveWorkspace("close")}>
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
                <p className="eyebrow">Workflow</p>
                <h3>Mask state</h3>
              </div>
              <span className={`save-chip save-${state.saveState}`}>
                {state.saveState === "saving"
                  ? "Saving..."
                  : isDirty(state)
                    ? "Unsaved changes"
                    : "Saved"}
              </span>
            </div>
            <label>
              Annotation status
              <select
                value={state.document.annotation_status}
                onChange={(event) =>
                  commitDocument({
                    ...state.document,
                    annotation_status: event.target
                      .value as AnnotationDocument["annotation_status"],
                  })
                }
              >
                <option value="unannotated">Unannotated</option>
                <option value="in_progress">In progress</option>
                <option value="annotated">Annotated</option>
                <option value="reviewed">Reviewed</option>
                <option value="excluded">Excluded</option>
              </select>
            </label>
            {state.saveMessage && state.saveState !== "saved" && (
              <p className="form-error">{state.saveMessage}</p>
            )}
            {state.tool === "fill" && (
              <>
                <p className="annotation-helper">
                  Exact Fill follows the connected image region around your
                  click and creates one editable polygon. Use Smart Close when
                  the opening has weak, broken, or incomplete edges.
                </p>
                {fillPending && (
                  <p role="status">Finding connected region...</p>
                )}
                {fillError && (
                  <p role="alert" className="form-error">
                    {fillError}
                  </p>
                )}
              </>
            )}
            {state.tool === "smart_close" && (
              <>
                <label>
                  Auto-close tolerance
                  <input
                    type="range"
                    className="annotation-range-control"
                    min={0}
                    max={100}
                    step={1}
                    value={smartCloseStrength}
                    aria-label="Auto-close tolerance"
                    onChange={(event) =>
                      setSmartCloseStrength(Number(event.target.value))
                    }
                  />
                  <output>
                    {smartCloseStrength === 0
                      ? "Full opening"
                      : `${smartCloseStrength}%`}
                  </output>
                </label>
                <p className="annotation-helper">
                  Click near the center of the opening. Smart Close traces the
                  visible circular or oval rim and directly links across the
                  broken section. Full opening bridges only small breaks;
                  increase Auto-close tolerance when more of the rim is missing.
                </p>
                {fillPending && (
                  <p role="status">Predicting closed boundary...</p>
                )}
                {fillError && (
                  <p role="alert" className="form-error">
                    {fillError}
                  </p>
                )}
              </>
            )}
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Classes</p>
                <h3>Mask classes</h3>
              </div>
              <span>{state.document.maskAnnotations.length} masks</span>
            </div>
            <ul className="annotation-class-list">
              {sessionQuery.data.label_classes.map((labelClass) => (
                <li
                  key={labelClass.id}
                  className={`annotation-class-row ${state.activeClassId === labelClass.id ? "selected" : ""}`}
                >
                  <button
                    type="button"
                    className="annotation-class-button"
                    onClick={() => applyClass(labelClass.id)}
                  >
                    <span
                      className="annotation-class-swatch"
                      style={{ backgroundColor: labelClass.display_color }}
                    />
                    <span className="annotation-class-text">
                      {labelClass.name}
                    </span>
                    <span className="annotation-class-count">
                      {maskCounts.get(labelClass.id) ?? 0}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Selection</p>
                <h3>{selectedMasks.length} selected</h3>
              </div>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={state.history.length === 0}
                  onClick={() => dispatch({ type: "undo" })}
                >
                  Undo
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={state.future.length === 0}
                  onClick={() => dispatch({ type: "redo" })}
                >
                  Redo
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={selectedMasks.length === 0}
                  onClick={copySelection}
                >
                  Copy
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={selectedMasks.length === 0}
                  onClick={duplicateSelection}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!readInternalAnnotationClipboard()?.items.length}
                  onClick={() => pasteClipboard()}
                >
                  Paste
                </button>
              </div>
            </div>
            <p className="annotation-helper">
              Polygon: add vertices and close the outline. Select an existing
              mask to move vertices, reassign its class, or delete it.
            </p>
            {clipboardMessage && <p role="status">{clipboardMessage}</p>}
            <button
              type="button"
              className="danger-ghost"
              disabled={selectedMasks.length === 0}
              onClick={() => deleteMasks(state.selectedMaskIds)}
            >
              Delete selected masks
            </button>
            <div className="annotation-selection-list">
              {selectedMasks.map((mask) => (
                <div key={mask.id} className="annotation-selection-row">
                  <strong>
                    {sessionQuery.data.label_classes.find(
                      (labelClass) => labelClass.id === mask.label_class_id,
                    )?.name ?? "Unassigned"}
                  </strong>
                  <span>
                    {mask.geometry_kind} | {mask.area_pixels ?? 0} px²
                  </span>
                </div>
              ))}
            </div>
            <MaskMeasurementPanel
              projectId={project.id}
              imageId={image.id}
              labelClasses={sessionQuery.data.label_classes}
              selectedMasks={selectedMasks}
              documentDirty={isDirty(state)}
              onRevisionCommitted={refreshAfterMeasurementChange}
            />
            <SkeletonAnalysisPanel
              selectedMask={selectedMeasurementMask}
              documentDirty={isDirty(state)}
              onOverlayChange={setSkeletonOverlay}
            />
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <span>Masks use original source-image coordinates.</span>
            <span>
              {isDirty(state) ? "Autosave pending" : "All changes synced"}
            </span>
          </div>
          <ImageViewport
            width={image.width_px}
            height={image.height_px}
            label="Polygon mask viewport"
          >
            <img
              src={imageDisplayUrl(image.id)}
              alt={image.original_filename}
              draggable={false}
              style={{
                display: "block",
                width: "100%",
                height: "100%",
                userSelect: "none",
              }}
            />
            <PolygonMaskLayer
              key={image.id}
              width={image.width_px}
              height={image.height_px}
              masks={state.document.maskAnnotations}
              classColors={classColors}
              activeClassId={state.activeClassId}
              tool={state.tool}
              selectedMaskIds={state.selectedMaskIds}
              onCreate={createMask}
              onUpdate={updateMask}
              onSelectionChange={(selection) =>
                dispatch({ type: "setMaskSelection", selection })
              }
              onDeleteMaskIds={deleteMasks}
              onFill={(seed) =>
                void (state.tool === "smart_close"
                  ? smartClosePolygon(seed)
                  : fillPolygon(seed))
              }
            />
            <CenterlineMeasurementLayer
              width={image.width_px}
              height={image.height_px}
              selectedMask={selectedMeasurementMask}
              documentDirty={isDirty(state)}
              editing={centerlineEditing}
              onEditingChange={setCenterlineEditing}
              onRevisionCommitted={refreshAfterMeasurementChange}
            />
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
