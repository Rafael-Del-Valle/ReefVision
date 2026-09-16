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
  type Project,
} from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
  toAnnotationSavePayload,
  type ExtendedAnnotationSavePayload,
} from "./annotationEditorReducer";
import { CenterlineMeasurementLayer } from "./CenterlineMeasurementLayer";
import {
  addMaskAnnotation,
  changeMaskAnnotationClass,
  deleteMaskAnnotations,
  updateMaskAnnotation,
} from "./maskDocumentOperations";
import { MaskMeasurementPanel } from "./MaskMeasurementPanel";
import { PolygonMaskLayer, polygonMaskFromPoints } from "./PolygonMaskLayer";
import {
  generatePolygonFill,
  generateSmartClosePolygon,
} from "./rasterMaskApi";
import type {
  AnnotationDocument,
  EditorMaskAnnotation,
  EditorTool,
  Point,
} from "./types";

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
  const [smartCloseStrength, setSmartCloseStrength] = useState(0);
  const [fillPending, setFillPending] = useState(false);
  const [fillError, setFillError] = useState<string | null>(null);
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
    if (sessionQuery.data && loadedImageIdRef.current !== imageId) {
      dispatch({ type: "loadSession", session: sessionQuery.data });
      if (initialTool) {
        dispatch({ type: "setTool", tool: initialTool });
      }
      loadedImageIdRef.current = imageId;
    }
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
            target.closest(
              "input, textarea, select, [contenteditable='true']",
            ),
          ))
      ) {
        return;
      }

      const snapshot = stateRef.current;
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
  }, [deleteMasks]);

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
              </div>
            </div>
            <p className="annotation-helper">
              Polygon: add vertices and close the outline. Select an existing
              mask to move vertices, reassign its class, or delete it.
            </p>
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
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <span>Masks use original source-image coordinates.</span>
            <span>
              {isDirty(state) ? "Autosave pending" : "All changes synced"}
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
                flex: "0 0 auto",
              }}
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
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
