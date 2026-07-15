import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import {
  getAnnotationSession,
  imageContentUrl,
  saveAnnotations,
  type Project,
} from "../../api/client";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
  toAnnotationSavePayload,
} from "./annotationEditorReducer";
import {
  addMaskAnnotation,
  changeMaskAnnotationClass,
  deleteMaskAnnotations,
  updateMaskAnnotation,
} from "./maskDocumentOperations";
import { PolygonMaskLayer } from "./PolygonMaskLayer";
import type {
  AnnotationDocument,
  EditorMaskAnnotation,
} from "./types";

interface MaskAnnotationWorkspaceProps {
  project: Project;
  imageId: string;
  onReturnToBoxes: () => void;
  onClose: () => void;
}

export function MaskAnnotationWorkspace({
  project,
  imageId,
  onReturnToBoxes,
  onClose,
}: MaskAnnotationWorkspaceProps) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(
    annotationEditorReducer,
    initialAnnotationEditorState,
  );
  const stateRef = useRef(state);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const sessionQuery = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (sessionQuery.data) {
      dispatch({ type: "loadSession", session: sessionQuery.data });
    }
  }, [sessionQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const snapshot = stateRef.current;
      const sentVersion = snapshot.documentVersion;
      dispatch({ type: "saveStarted", sentVersion });
      const response = await saveAnnotations(
        imageId,
        toAnnotationSavePayload(snapshot),
      );
      dispatch({ type: "saveSucceeded", sentVersion, response });
      queryClient.setQueryData(["annotation-session", imageId], (current) => ({
        ...(current as object),
        ...response,
        label_classes: sessionQuery.data?.label_classes ?? [],
        previous_image_id: sessionQuery.data?.previous_image_id ?? null,
        next_image_id: sessionQuery.data?.next_image_id ?? null,
      }));
      await queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      });
      return true;
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Mask save failed";
      dispatch({
        type: "saveFailed",
        message,
        conflict: message.toLowerCase().includes("revision conflict"),
      });
    },
  });

  const saveNow = useCallback(async (): Promise<boolean> => {
    if (!isDirty(stateRef.current)) {
      return true;
    }
    if (savePromiseRef.current) {
      return savePromiseRef.current;
    }
    const request = saveMutation
      .mutateAsync()
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        savePromiseRef.current = null;
      });
    savePromiseRef.current = request;
    return request;
  }, [saveMutation]);

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
      dispatch({
        type: "commitDocument",
        document,
        maskSelection,
      });
    },
    [],
  );

  function createMask(mask: EditorMaskAnnotation) {
    commitDocument(addMaskAnnotation(stateRef.current.document, mask), [mask.id]);
  }

  function updateMask(mask: EditorMaskAnnotation) {
    commitDocument(updateMaskAnnotation(stateRef.current.document, mask), [mask.id]);
  }

  function deleteMasks(maskIds: string[]) {
    commitDocument(
      deleteMaskAnnotations(stateRef.current.document, maskIds),
      [],
    );
  }

  function applyClass(labelClassId: string) {
    if (state.selectedMaskIds.length === 0) {
      dispatch({ type: "setActiveClassId", classId: labelClassId });
      return;
    }
    commitDocument(
      changeMaskAnnotationClass(
        state.document,
        state.selectedMaskIds,
        labelClassId,
      ),
    );
    dispatch({ type: "setActiveClassId", classId: labelClassId });
  }

  async function leaveWorkspace(destination: "boxes" | "close") {
    const saved = await saveNow();
    if (!saved && !window.confirm("Discard unsaved mask edits?")) {
      return;
    }
    if (destination === "boxes") {
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
    state.document.maskAnnotations.forEach((mask) => {
      if (mask.label_class_id) {
        counts.set(mask.label_class_id, (counts.get(mask.label_class_id) ?? 0) + 1);
      }
    });
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
          <button type="button" onClick={() => void leaveWorkspace("close")}>
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

  return (
    <div className="annotation-editor-shell" data-testid="mask-workspace">
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
            onClick={() => dispatch({ type: "setTool", tool: "select" })}
          >
            Select vertices (V)
          </button>
          <button
            type="button"
            className={state.tool === "polygon" ? "active" : "secondary"}
            onClick={() => dispatch({ type: "setTool", tool: "polygon" })}
          >
            Polygon (P)
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!isDirty(state) || saveMutation.isPending}
            onClick={() => void saveNow()}
          >
            {saveMutation.isPending ? "Saving..." : "Save now"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void leaveWorkspace("boxes")}
          >
            Box editor
          </button>
          <button type="button" onClick={() => void leaveWorkspace("close")}>
            Close editor
          </button>
        </div>
      </header>

      <div className="annotation-editor-body">
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
              Click to add polygon vertices. Press Enter or click the first vertex
              to close. Drag selected vertices to refine the outline.
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
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <span>
              Polygon masks are saved in original source-image coordinates.
            </span>
            <span>{isDirty(state) ? "Autosave pending" : "All changes synced"}</span>
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
                src={imageContentUrl(image.id)}
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
              />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
