import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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

const floatingButtonStyle = {
  position: "fixed" as const,
  right: "1rem",
  bottom: "1rem",
  zIndex: 10000,
  boxShadow: "0 0.5rem 1.5rem rgba(0, 0, 0, 0.24)",
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
      <>
        <MaskAnnotationWorkspace
          project={project}
          imageId={activeImageId}
          onReturnToBoxes={() => setWorkspace("boxes")}
          onClose={onClose}
        />
        <button
          type="button"
          className="secondary"
          data-testid="open-raster-workspace"
          title="Open the raster paint and eraser workspace"
          onClick={() => setWorkspace("raster")}
          style={floatingButtonStyle}
        >
          Raster brush
        </button>
      </>
    );
  }

  return (
    <>
      <AnnotationEditor
        project={project}
        initialImageId={activeImageId}
        launchContext={launchContext}
        onClose={onClose}
      />
      <div
        style={{
          position: "fixed",
          right: "1rem",
          bottom: "1rem",
          zIndex: 10000,
          display: "flex",
          gap: "0.5rem",
        }}
      >
        <button
          type="button"
          className="secondary"
          data-testid="open-mask-workspace"
          title="Open the editable polygon and raster mask workspace"
          onClick={() => setWorkspace("masks")}
        >
          Polygon masks
        </button>
        <button
          type="button"
          className="secondary"
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
