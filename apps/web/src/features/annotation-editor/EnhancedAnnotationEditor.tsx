import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { AnnotationSession, Project } from "../../api/client";
import { AnnotationEditor } from "./AnnotationEditor";
import "./annotationTypeVisibility.css";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";
import "./polygonWorkspace.css";
import { PromptPointAssistOverlay } from "./PromptPointAssistOverlay";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

interface AnnotationLaunchContext {
  returnLabel: string;
  contextTitle?: string;
  contextDescription?: string;
  highlightAnnotationIds?: string[];
  highlightPredictionIds?: string[];
}

interface EnhancedAnnotationEditorProps {
  project: Project;
  initialImageId: string;
  launchContext?: AnnotationLaunchContext;
  onClose: () => void;
}

type EditorWorkspace = "boxes" | "masks" | "raster";
type VertexEditMode = "move" | "insert" | "delete";

const fallbackToolbarStyle = {
  position: "fixed" as const,
  top: "1rem",
  right: "1rem",
  zIndex: 999999,
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  padding: "0.55rem",
  border: "1px solid rgba(182, 238, 228, 0.3)",
  borderRadius: "0.9rem",
  background: "rgba(3, 25, 30, 0.98)",
  boxShadow: "0 0.75rem 2rem rgba(0, 0, 0, 0.45)",
};

const visibilityGroupStyle = {
  display: "flex",
  alignItems: "center",
  gap: "0.45rem",
  flexWrap: "wrap" as const,
};

function stopEditorEvent(event: Event) {
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
}

export function EnhancedAnnotationEditor({
  project,
  initialImageId,
  launchContext,
  onClose,
}: EnhancedAnnotationEditorProps) {
  const queryClient = useQueryClient();
  const [workspace, setWorkspace] = useState<EditorWorkspace>("boxes");
  const [vertexEditMode, setVertexEditMode] = useState<VertexEditMode>("move");
  const [pointAssistEnabled, setPointAssistEnabled] = useState(false);
  const [activeImageId, setActiveImageId] = useState(initialImageId);
  const [toolbarTarget, setToolbarTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setActiveImageId(initialImageId);
  }, [initialImageId]);

  useEffect(() => {
    return queryClient.getQueryCache().subscribe((event) => {
      const query = event.query;
      if (query.queryKey[0] !== "annotation-session") {
        return;
      }
      const data = query.state.data as AnnotationSession | undefined;
      if (
        query.state.status === "success" &&
        data?.image.project_id === project.id
      ) {
        setActiveImageId(data.image.id);
      }
    });
  }, [project.id, queryClient]);

  useEffect(() => {
    const findToolbarTarget = () => {
      const target = document.querySelector<HTMLElement>(
        ".annotation-editor-topbar .annotation-editor-actions",
      );
      setToolbarTarget((current) => (current === target ? current : target));
    };

    findToolbarTarget();
    const observer = new MutationObserver(findToolbarTarget);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [workspace, activeImageId]);

  useEffect(() => {
    if (workspace !== "masks") {
      return;
    }

    const updateInstructions = () => {
      const helpers = document.querySelectorAll<HTMLElement>(
        '[data-testid="mask-workspace"] .annotation-helper',
      );
      for (const helper of helpers) {
        if (helper.textContent?.includes("press Enter")) {
          helper.textContent =
            "Add at least three vertices, then click the first node to close. Select a polygon and use Move nodes, Insert node, or Delete node to refine it.";
        }
      }
    };

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (pointAssistEnabled) {
        return;
      }
      if (
        !(event.target instanceof Element) ||
        !event.target.closest('[data-testid="polygon-mask-layer"]')
      ) {
        return;
      }

      if (event.key === "Enter") {
        stopEditorEvent(event);
        return;
      }

      const selectToolActive = document
        .querySelector('[data-testid="activate-mask-select-tool"]')
        ?.classList.contains("active");
      if (
        selectToolActive &&
        (event.key === "Delete" || event.key === "Backspace")
      ) {
        stopEditorEvent(event);
      }
    };

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (pointAssistEnabled) {
        return;
      }
      if (!(event.target instanceof Element)) {
        return;
      }
      const layer = event.target.closest('[data-testid="polygon-mask-layer"]');
      if (!layer) {
        return;
      }

      if (
        vertexEditMode === "insert" &&
        event.target.tagName.toLowerCase() === "polygon"
      ) {
        const polygon = event.target;
        stopEditorEvent(event);
        polygon.dispatchEvent(
          new MouseEvent("dblclick", {
            bubbles: true,
            cancelable: true,
            clientX: event.clientX,
            clientY: event.clientY,
          }),
        );
        return;
      }

      if (
        vertexEditMode === "delete" &&
        event.target.tagName.toLowerCase() === "circle" &&
        event.target.getAttribute("data-testid")?.startsWith("mask-vertex-") &&
        !event.altKey
      ) {
        const vertex = event.target;
        stopEditorEvent(event);
        vertex.dispatchEvent(
          new MouseEvent("pointerdown", {
            bubbles: true,
            cancelable: true,
            clientX: event.clientX,
            clientY: event.clientY,
            altKey: true,
          }),
        );
      }
    };

    updateInstructions();
    const observer = new MutationObserver(updateInstructions);
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [pointAssistEnabled, vertexEditMode, workspace]);

  const workspaceContent = useMemo(() => {
    if (workspace === "raster") {
      return (
        <RasterMaskWorkspace
          project={project}
          imageId={activeImageId}
          onReturnToMasks={() => setWorkspace("masks")}
          onReturnToBoxes={() => setWorkspace("boxes")}
          onClose={onClose}
        />
      );
    }
    if (workspace === "masks") {
      return (
        <MaskAnnotationWorkspace
          project={project}
          imageId={activeImageId}
          onReturnToBoxes={() => setWorkspace("boxes")}
          onClose={onClose}
        />
      );
    }
    return (
      <AnnotationEditor
        project={project}
        initialImageId={activeImageId}
        launchContext={launchContext}
        onMaskPredictionAccepted={(kind) =>
          setWorkspace(kind === "raster_mask" ? "raster" : "masks")
        }
        onClose={onClose}
      />
    );
  }, [activeImageId, launchContext, onClose, project, workspace]);

  function activateVertexEditMode(mode: VertexEditMode) {
    setVertexEditMode(mode);
    document
      .querySelector<HTMLButtonElement>(
        '[data-testid="activate-mask-select-tool"]',
      )
      ?.click();
  }

  const annotationControls = (
    <div style={visibilityGroupStyle}>
      <label data-testid="annotation-type-toggle" style={{ minWidth: "10rem" }}>
        Annotation type
        <select
          aria-label="Annotation type"
          data-testid="annotation-type-select"
          value={workspace}
          onChange={(event) =>
            setWorkspace(event.target.value as EditorWorkspace)
          }
        >
          <option value="boxes">Bounding boxes</option>
          <option value="masks">Polygons</option>
          <option value="raster">Raster masks</option>
        </select>
      </label>
      {
        <button
          type="button"
          className={pointAssistEnabled ? "active" : "secondary"}
          data-testid="toggle-point-assist"
          aria-pressed={pointAssistEnabled}
          onClick={() => setPointAssistEnabled((current) => !current)}
        >
          {pointAssistEnabled ? "Close Point Assist" : "Point Assist"}
        </button>
      }
      {workspace === "masks" && (
        <div
          role="group"
          aria-label="Polygon node editing"
          style={visibilityGroupStyle}
        >
          <button
            type="button"
            className={vertexEditMode === "move" ? "active" : "secondary"}
            data-testid="move-polygon-nodes"
            disabled={pointAssistEnabled}
            onClick={() => activateVertexEditMode("move")}
          >
            Move nodes
          </button>
          <button
            type="button"
            className={vertexEditMode === "insert" ? "active" : "secondary"}
            data-testid="insert-polygon-node"
            disabled={pointAssistEnabled}
            onClick={() => activateVertexEditMode("insert")}
          >
            Insert node
          </button>
          <button
            type="button"
            className={vertexEditMode === "delete" ? "active" : "secondary"}
            data-testid="delete-polygon-node"
            disabled={pointAssistEnabled}
            onClick={() => activateVertexEditMode("delete")}
          >
            Delete node
          </button>
        </div>
      )}
    </div>
  );

  return (
    <>
      <div
        data-testid="enhanced-annotation-editor"
        data-active-annotation-type={workspace}
        data-boxes-visible={workspace === "boxes"}
        data-polygons-visible={workspace === "masks"}
        data-raster-visible={workspace === "raster"}
        data-vertex-edit-mode={vertexEditMode}
        data-point-assist-enabled={pointAssistEnabled}
        style={{ display: "contents" }}
      >
        {workspaceContent}
      </div>
      {createPortal(
        <div
          role="group"
          aria-label="Annotation controls"
          style={toolbarTarget ? undefined : fallbackToolbarStyle}
        >
          {annotationControls}
        </div>,
        toolbarTarget ?? document.body,
      )}
      {pointAssistEnabled && (
        <PromptPointAssistOverlay
          key={activeImageId}
          project={project}
          imageId={activeImageId}
          activeWorkspace={workspace}
          onAccepted={(kind) => {
            setPointAssistEnabled(false);
            setWorkspace(kind === "polygon" ? "masks" : "raster");
          }}
          onClose={() => setPointAssistEnabled(false)}
        />
      )}
    </>
  );
}
