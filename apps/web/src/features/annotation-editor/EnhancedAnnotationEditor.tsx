import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { AnnotationSession, Project } from "../../api/client";
import { AnnotationEditor } from "./AnnotationEditor";
import "./annotationTypeVisibility.css";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";
import "./polygonWorkspace.css";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

interface AnnotationLaunchContext {
  returnLabel: string;
  contextTitle?: string;
  contextDescription?: string;
  highlightAnnotationIds?: string[];
  highlightPredictionIds?: string[];
  initialWorkspace?: "boxes" | "masks" | "raster";
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
  top: "5rem",
  left: "1rem",
  zIndex: 999999,
  width: "4.6rem",
  boxSizing: "border-box" as const,
  overflowX: "hidden" as const,
  display: "flex",
  flexDirection: "column" as const,
  alignItems: "stretch",
  gap: "0.45rem",
  padding: "0.55rem",
  border: "1px solid rgba(182, 238, 228, 0.3)",
  borderRadius: "0.9rem",
  background: "rgba(3, 25, 30, 0.98)",
  boxShadow: "0 0.75rem 2rem rgba(0, 0, 0, 0.45)",
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
  const [workspace, setWorkspace] = useState<EditorWorkspace>(
    launchContext?.initialWorkspace ?? "boxes",
  );
  const [maskInitialTool, setMaskInitialTool] = useState<
    "polygon" | "fill" | "smart_close" | undefined
  >(undefined);
  const [activeMaskTool, setActiveMaskTool] = useState<
    "select" | "polygon" | "fill" | "smart_close" | "rotated_box"
  >("select");
  const [vertexEditMode, setVertexEditMode] = useState<VertexEditMode>("move");
  const [activeImageId, setActiveImageId] = useState(initialImageId);
  const [toolbarTarget, setToolbarTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setActiveImageId(initialImageId);
    setWorkspace(launchContext?.initialWorkspace ?? "boxes");
    setMaskInitialTool(undefined);
  }, [initialImageId, launchContext?.initialWorkspace]);

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
        ".annotation-tool-rail",
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
      if (
        !(event.target instanceof Element) ||
        !event.target.closest('[data-testid="polygon-mask-layer"]')
      ) {
        return;
      }

      if (event.key === "Enter") {
        stopEditorEvent(event);
      }
    };

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const layer = event.target.closest('[data-testid="polygon-mask-layer"]');
      if (!layer) {
        return;
      }
      if (
        !document
          .querySelector('[data-testid="activate-mask-select-tool"]')
          ?.classList.contains("active")
      ) {
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
  }, [vertexEditMode, workspace]);

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
          initialTool={maskInitialTool}
          onToolChange={(tool) => {
            if (
              tool === "select" ||
              tool === "polygon" ||
              tool === "fill" ||
              tool === "smart_close" ||
              tool === "rotated_box"
            ) {
              setActiveMaskTool(tool);
            }
          }}
          onReturnToBoxes={() => {
            setMaskInitialTool(undefined);
            setWorkspace("boxes");
          }}
          onOpenBrush={() => {
            setMaskInitialTool(undefined);
            setWorkspace("raster");
          }}
          onClose={onClose}
        />
      );
    }
    return (
      <AnnotationEditor
        project={project}
        initialImageId={activeImageId}
        launchContext={launchContext}
        onClose={onClose}
      />
    );
  }, [
    activeImageId,
    launchContext,
    maskInitialTool,
    onClose,
    project,
    workspace,
  ]);

  function returnToMainTools() {
    setMaskInitialTool(undefined);
    if (workspace === "masks") {
      document
        .querySelector<HTMLButtonElement>(
          '[data-mask-workspace-destination="boxes"]',
        )
        ?.click();
      return;
    }
    setWorkspace("boxes");
  }

  function activatePolygonTool() {
    if (workspace === "masks") {
      document
        .querySelector<HTMLButtonElement>(
          '[data-testid="activate-polygon-tool"]',
        )
        ?.click();
      return;
    }
    setMaskInitialTool("polygon");
    setActiveMaskTool("polygon");
    setWorkspace("masks");
  }

  function activateBrushTool() {
    setMaskInitialTool(undefined);
    if (workspace === "masks") {
      document
        .querySelector<HTMLButtonElement>(
          '[data-testid="activate-mask-brush-tool"]',
        )
        ?.click();
      return;
    }
    setWorkspace("raster");
  }

  function activateFillObjectTool() {
    if (workspace === "masks") {
      document
        .querySelector<HTMLButtonElement>(
          '[data-testid="activate-polygon-fill-tool"]',
        )
        ?.click();
      return;
    }
    setMaskInitialTool("fill");
    setActiveMaskTool("fill");
    setWorkspace("masks");
  }

  function activateSmartCloseTool() {
    if (workspace === "masks") {
      document
        .querySelector<HTMLButtonElement>(
          '[data-testid="activate-smart-close-tool"]',
        )
        ?.click();
      return;
    }
    setMaskInitialTool("smart_close");
    setActiveMaskTool("smart_close");
    setWorkspace("masks");
  }

  function activateVertexEditMode(mode: VertexEditMode) {
    setVertexEditMode(mode);
    setActiveMaskTool("select");
    document
      .querySelector<HTMLButtonElement>(
        '[data-testid="activate-mask-select-tool"]',
      )
      ?.click();
  }

  const annotationControls = (
    <div
      className={
        workspace === "boxes"
          ? "annotation-tool-extension"
          : "annotation-tool-submenu"
      }
    >
      {workspace !== "boxes" && (
        <button
          type="button"
          className="secondary annotation-tool-back"
          data-testid="return-main-tools"
          title="Return to the main annotation tools"
          onClick={returnToMainTools}
        >
          <span aria-hidden="true">←</span>
          <small>Main</small>
        </button>
      )}

      <div className="annotation-tool-group" data-testid="mask-tool-group">
        <span className="annotation-tool-group-label">
          {workspace === "boxes" ? "Masks" : "Mask tools"}
        </span>
        <button
          type="button"
          className={
            workspace === "masks" && activeMaskTool === "polygon"
              ? "active"
              : "secondary"
          }
          data-testid="open-polygon-tool"
          title="Draw editable polygon objects"
          onClick={activatePolygonTool}
        >
          <span aria-hidden="true">⬡</span>
          <small>Polygon</small>
        </button>
        <button
          type="button"
          className={
            workspace === "masks" && activeMaskTool === "fill"
              ? "active"
              : "secondary"
          }
          data-testid="open-fill-object-tool"
          title="Click enclosed regions such as holes to create countable mask objects"
          onClick={activateFillObjectTool}
        >
          <span aria-hidden="true">◉</span>
          <small>Fill</small>
        </button>
        <button
          type="button"
          className={
            workspace === "masks" && activeMaskTool === "smart_close"
              ? "active"
              : "secondary"
          }
          data-testid="open-smart-close-tool"
          title="Predict a closed polygon around a weak or broken opening boundary"
          onClick={activateSmartCloseTool}
        >
          <span aria-hidden="true">◎</span>
          <small>Smart close</small>
        </button>
        <button
          type="button"
          className={workspace === "raster" ? "active" : "secondary"}
          data-testid="open-brush-tool"
          title="Paint freehand mask objects"
          onClick={activateBrushTool}
        >
          <span aria-hidden="true">✎</span>
          <small>Brush</small>
        </button>
      </div>

      {workspace === "masks" && (
        <div
          className="annotation-tool-group annotation-tool-edit-group"
          data-testid="polygon-edit-tool-group"
        >
          <span className="annotation-tool-group-label">Polygon edit</span>
          <button
            type="button"
            className={vertexEditMode === "move" ? "active" : "secondary"}
            data-testid="move-polygon-nodes"
            title="Move polygon nodes"
            onClick={() => activateVertexEditMode("move")}
          >
            <span aria-hidden="true">↔</span>
            <small>Move</small>
          </button>
          <button
            type="button"
            className={vertexEditMode === "insert" ? "active" : "secondary"}
            data-testid="insert-polygon-node"
            title="Insert a polygon node"
            onClick={() => activateVertexEditMode("insert")}
          >
            <span aria-hidden="true">＋</span>
            <small>Add</small>
          </button>
          <button
            type="button"
            className={vertexEditMode === "delete" ? "active" : "secondary"}
            data-testid="delete-polygon-node"
            title="Delete a polygon node"
            onClick={() => activateVertexEditMode("delete")}
          >
            <span aria-hidden="true">−</span>
            <small>Delete</small>
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
        style={{ display: "contents" }}
      >
        {workspaceContent}
      </div>
      {createPortal(
        <div
          role="group"
          aria-label="Annotation mode and mask tools"
          style={toolbarTarget ? undefined : fallbackToolbarStyle}
        >
          {annotationControls}
        </div>,
        toolbarTarget ?? document.body,
      )}
    </>
  );
}
