import { useState } from "react";

import type { Project } from "../../api/client";
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
  const [workspace, setWorkspace] = useState<EditorWorkspace>("boxes");

  if (workspace === "raster") {
    return (
      <RasterMaskWorkspace
        project={project}
        imageId={initialImageId}
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
          imageId={initialImageId}
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
        initialImageId={initialImageId}
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
