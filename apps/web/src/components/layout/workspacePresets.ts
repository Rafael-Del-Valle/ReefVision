export type WorkspacePresetId =
  | "annotation"
  | "detection"
  | "segmentation"
  | "pose"
  | "morphometrics"
  | "workflow"
  | "review"
  | "custom";

export interface WorkspacePresetDefinition {
  id: WorkspacePresetId;
  label: string;
  shortLabel: string;
  description: string;
  defaultView:
    "gallery" | "advanced_providers" | "video" | "workflows" | "review_queue";
}

export const WORKSPACE_PRESETS: WorkspacePresetDefinition[] = [
  {
    id: "annotation",
    label: "Annotation",
    shortLabel: "Annotate",
    description:
      "Image-first layout for scientist annotation, metadata, and class review.",
    defaultView: "gallery",
  },
  {
    id: "detection",
    label: "Detection",
    shortLabel: "Detect",
    description:
      "Image workbench with registered detector selection and batch inference.",
    defaultView: "gallery",
  },
  {
    id: "segmentation",
    label: "Segmentation",
    shortLabel: "Segment",
    description:
      "Prompt-assisted and model-driven segmentation provider workspace.",
    defaultView: "advanced_providers",
  },
  {
    id: "pose",
    label: "Pose Tracking",
    shortLabel: "Pose",
    description:
      "Video, repeated-landmark pose tracking, temporal identity, and review.",
    defaultView: "video",
  },
  {
    id: "morphometrics",
    label: "Morphometrics",
    shortLabel: "Measure",
    description:
      "Image-centric measurement workflow with calibration and reviewed masks.",
    defaultView: "gallery",
  },
  {
    id: "workflow",
    label: "Workflow Builder",
    shortLabel: "Workflow",
    description:
      "Typed workflow graph editing, scientist review gates, and provenance.",
    defaultView: "workflows",
  },
  {
    id: "review",
    label: "Review / QA",
    shortLabel: "Review",
    description:
      "Scientist-in-the-loop validation, ranked review, and quality control.",
    defaultView: "review_queue",
  },
  {
    id: "custom",
    label: "Custom Layout",
    shortLabel: "Custom",
    description:
      "Keep the current tool while arranging navigation and inspector panels.",
    defaultView: "gallery",
  },
];

export function workspacePreset(
  presetId: WorkspacePresetId,
): WorkspacePresetDefinition {
  return (
    WORKSPACE_PRESETS.find((preset) => preset.id === presetId) ??
    WORKSPACE_PRESETS[0]
  );
}
