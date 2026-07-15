import { useState } from "react";

import type { Project } from "../../api/client";
import { AnnotationEditor } from "./AnnotationEditor";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";

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

export function EnhancedAnnotationEditor({
  project,
  initialImageId,
  launchContext,
  onClose,
}: EnhancedAnnotationEditorProps) {
  const [workspace, setWorkspace] = useState<"boxes" | "masks">("boxes");

  if (workspace === "masks") {
    return (
      <MaskAnnotationWorkspace
        project={project}
        imageId={initialImageId}
        onReturnToBoxes={() => setWorkspace("boxes")}
        onClose={onClose}
      />
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
      <button
        type="button"
        className="secondary"
        data-testid="open-mask-workspace"
        title="Open the editable polygon and raster mask workspace"
        onClick={() => setWorkspace("masks")}
        style={{
          position: "fixed",
          right: "1rem",
          bottom: "1rem",
          zIndex: 10000,
          boxShadow: "0 0.5rem 1.5rem rgba(0, 0, 0, 0.24)",
        }}
      >
        Mask workspace
      </button>
    </>
  );
}
