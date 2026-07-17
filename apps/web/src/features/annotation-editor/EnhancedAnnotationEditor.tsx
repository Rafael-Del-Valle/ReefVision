import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { AnnotationSession, Project } from "../../api/client";
import { AnnotationEditor } from "./AnnotationEditor";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";
import "./polygonWorkspace.css";
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

export function EnhancedAnnotationEditor({
  project,
  initialImageId,
  launchContext,
  onClose,
}: EnhancedAnnotationEditorProps) {
  const queryClient = useQueryClient();
  const [workspace, setWorkspace] = useState<EditorWorkspace>("boxes");
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
        onClose={onClose}
      />
    );
  }, [activeImageId, launchContext, onClose, project, workspace]);

  const annotationTypeSelector = (
    <label
      data-testid="annotation-type-toggle"
      style={{ minWidth: "10rem" }}
    >
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
        <option value="masks">Polygon</option>
        <option value="raster">Raster brush</option>
      </select>
    </label>
  );

  return (
    <>
      {workspaceContent}
      {createPortal(
        <div
          role="group"
          aria-label="Annotation type selector"
          style={toolbarTarget ? undefined : fallbackToolbarStyle}
        >
          {annotationTypeSelector}
        </div>,
        toolbarTarget ?? document.body,
      )}
    </>
  );
}
