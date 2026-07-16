import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import type { AnnotationSession, Project } from "../../api/client";
import { AnnotationEditor } from "./AnnotationEditor";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";
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

const workspaceSwitcherStyle = {
  position: "fixed" as const,
  left: "50%",
  bottom: "1rem",
  transform: "translateX(-50%)",
  zIndex: 20000,
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  padding: "0.55rem",
  border: "1px solid rgba(182, 238, 228, 0.3)",
  borderRadius: "0.9rem",
  background: "rgba(3, 25, 30, 0.96)",
  boxShadow: "0 0.75rem 2rem rgba(0, 0, 0, 0.38)",
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

  let workspaceContent: ReactNode;
  if (workspace === "raster") {
    workspaceContent = (
      <RasterMaskWorkspace
        project={project}
        imageId={activeImageId}
        onReturnToMasks={() => setWorkspace("masks")}
        onReturnToBoxes={() => setWorkspace("boxes")}
        onClose={onClose}
      />
    );
  } else if (workspace === "masks") {
    workspaceContent = (
      <MaskAnnotationWorkspace
        project={project}
        imageId={activeImageId}
        onReturnToBoxes={() => setWorkspace("boxes")}
        onClose={onClose}
      />
    );
  } else {
    workspaceContent = (
      <AnnotationEditor
        project={project}
        initialImageId={activeImageId}
        launchContext={launchContext}
        onClose={onClose}
      />
    );
  }

  return (
    <>
      {workspaceContent}
      <div
        role="toolbar"
        aria-label="Annotation tools"
        style={workspaceSwitcherStyle}
      >
        <button
          type="button"
          className={workspace === "boxes" ? "active" : "secondary"}
          data-testid="open-box-workspace"
          title="Open the bounding-box annotation workspace"
          onClick={() => setWorkspace("boxes")}
        >
          Boxes
        </button>
        <button
          type="button"
          className={workspace === "masks" ? "active" : "secondary"}
          data-testid="open-mask-workspace"
          title="Open the polygon-mask workspace"
          onClick={() => setWorkspace("masks")}
        >
          Polygon masks
        </button>
        <button
          type="button"
          className={workspace === "raster" ? "active" : "secondary"}
          data-testid="open-raster-workspace"
          title="Open the raster paint and eraser workspace"
          onClick={() => setWorkspace("raster")}
        >
          Raster brush
        </button>
      </div>
    </>
  );
}
