import type { WorkspacePresetId } from "./workspacePresets";

export type WorkspaceInspectorView =
  | "gallery"
  | "versions"
  | "interoperability"
  | "environmental_context"
  | "computed_metrics"
  | "models"
  | "training"
  | "classification"
  | "video"
  | "active_learning"
  | "classes"
  | "quality_control"
  | "review_queue"
  | "advanced_providers"
  | "workflows";

export type WorkspaceEvidenceBoundary =
  "mixed" | "provisional" | "review" | "record";

export interface WorkspaceInspectorAction {
  label: string;
  target: WorkspaceInspectorView;
  description: string;
}

export interface WorkspaceInspectorDefinition {
  title: string;
  summary: string;
  boundary: WorkspaceEvidenceBoundary;
  recordPolicy: string;
  actions: WorkspaceInspectorAction[];
}

export interface WorkspacePresetInspectorGuidance {
  title: string;
  description: string;
}

export const WORKSPACE_INSPECTOR_VIEWS: WorkspaceInspectorView[] = [
  "gallery",
  "versions",
  "interoperability",
  "environmental_context",
  "computed_metrics",
  "models",
  "training",
  "classification",
  "video",
  "active_learning",
  "classes",
  "quality_control",
  "review_queue",
  "advanced_providers",
  "workflows",
];

const WORKSPACE_INSPECTORS: Record<
  WorkspaceInspectorView,
  WorkspaceInspectorDefinition
> = {
  gallery: {
    title: "Image annotation & inference",
    summary:
      "Inspect project imagery, organize selections, run registered models, and enter the canonical annotation editor.",
    boundary: "mixed",
    recordPolicy:
      "Predictions remain proposals until annotation changes are explicitly accepted or created through the annotation workflow.",
    actions: [
      {
        label: "Model Hub",
        target: "models",
        description: "Inspect registered and project-specific models.",
      },
      {
        label: "Review queue",
        target: "review_queue",
        description: "Open ranked items that require human review.",
      },
      {
        label: "Provider tools",
        target: "advanced_providers",
        description: "Open prompt, segmentation, depth, OCR, and VLM tools.",
      },
    ],
  },
  versions: {
    title: "Immutable dataset evidence",
    summary:
      "Freeze reviewed project state into reproducible dataset versions, splits, comparisons, and exports.",
    boundary: "record",
    recordPolicy:
      "Dataset versions are immutable records derived from eligible persisted project annotations and metadata.",
    actions: [
      {
        label: "Training",
        target: "training",
        description: "Use a versioned dataset in a reproducible training run.",
      },
      {
        label: "Interoperability",
        target: "interoperability",
        description: "Exchange versioned project and dataset information.",
      },
    ],
  },
  interoperability: {
    title: "Project exchange & provenance",
    summary:
      "Export, inspect, and import ReefVision exchange packages without bypassing project provenance.",
    boundary: "record",
    recordPolicy:
      "Imported material remains subject to the canonical project schema, validation, and provenance rules.",
    actions: [
      {
        label: "Dataset versions",
        target: "versions",
        description: "Inspect immutable dataset snapshots before exchange.",
      },
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Return to managed project imagery and annotations.",
      },
    ],
  },
  environmental_context: {
    title: "Environmental observations",
    summary:
      "Inspect project scientific records and import local sensor or NOAA station observations.",
    boundary: "record",
    recordPolicy:
      "Original and normalized quantities retain observation time, depth, quality flags, and source provenance. Unknown depth remains unknown; source kinds distinguish observations from modeled and derived data.",
    actions: [
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Return to the imagery associated with project records.",
      },
      {
        label: "Video & tracking",
        target: "video",
        description: "Inspect organism tracks and geographic observations.",
      },
    ],
  },
  computed_metrics: {
    title: "Computed scientific metrics",
    summary:
      "Define unit-aware expressions and calculate immutable results from explicit scientific records.",
    boundary: "record",
    recordPolicy:
      "Every result preserves the formula version, definition hash, input snapshots, units, uncertainty, subject identity, and workflow provenance. Verified annotations and unverified predictions remain separate evidence categories.",
    actions: [
      {
        label: "Environmental Context",
        target: "environmental_context",
        description: "Inspect the scientific records used as metric inputs.",
      },
      {
        label: "Workflow Builder",
        target: "workflows",
        description: "Run a saved metric definition in a reproducible graph.",
      },
    ],
  },
  models: {
    title: "Model registry",
    summary:
      "Inspect supported architectures and registered project checkpoints.",
    boundary: "provisional",
    recordPolicy:
      "Registering or selecting a model never converts its predictions into scientist-verified annotations.",
    actions: [
      {
        label: "Training",
        target: "training",
        description: "Launch or inspect reproducible training runs.",
      },
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Deploy registered models against project imagery.",
      },
    ],
  },
  training: {
    title: "Reproducible training",
    summary:
      "Configure, validate, launch, and inspect local model-training runs using versioned project evidence.",
    boundary: "provisional",
    recordPolicy:
      "A trained checkpoint is a model artifact. Its future predictions remain provisional until human review.",
    actions: [
      {
        label: "Dataset versions",
        target: "versions",
        description: "Inspect the immutable evidence used for training.",
      },
      {
        label: "Model Hub",
        target: "models",
        description: "Inspect registered checkpoints and compatibility.",
      },
    ],
  },
  classification: {
    title: "Image classification",
    summary:
      "Train and apply image-level classification workflows while preserving reviewable model outputs.",
    boundary: "provisional",
    recordPolicy:
      "Classification predictions remain machine output until the applicable scientist review workflow records a decision.",
    actions: [
      {
        label: "Training",
        target: "training",
        description: "Configure reproducible classification training.",
      },
      {
        label: "Review queue",
        target: "review_queue",
        description: "Direct uncertain outputs into human review.",
      },
    ],
  },
  active_learning: {
    title: "Active-learning acquisition",
    summary:
      "Prioritize informative samples using uncertainty and diversity signals without redefining scientific truth.",
    boundary: "provisional",
    recordPolicy:
      "Acquisition scores decide what should be reviewed next; they do not approve annotations or pose observations.",
    actions: [
      {
        label: "Review queue",
        target: "review_queue",
        description:
          "Review prioritized evidence with a scientist in the loop.",
      },
      {
        label: "Training",
        target: "training",
        description: "Use verified feedback in a later training cycle.",
      },
    ],
  },
  advanced_providers: {
    title: "Advanced provider proposals",
    summary:
      "Use prompted segmentation, depth, OCR, VLM, and other provider capabilities as scientific assistance.",
    boundary: "provisional",
    recordPolicy:
      "Provider outputs are proposals or derived evidence and must pass the canonical review path before becoming accepted project truth.",
    actions: [
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Return proposals to the image-centered review workflow.",
      },
      {
        label: "Model Hub",
        target: "models",
        description: "Inspect registered provider and model assets.",
      },
    ],
  },
  classes: {
    title: "Project class schema",
    summary:
      "Manage the stable label vocabulary used by annotation, training, review, and export workflows.",
    boundary: "record",
    recordPolicy:
      "Class changes are persisted project configuration and should remain explicit, reviewable schema decisions.",
    actions: [
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Use the current class schema during annotation.",
      },
      {
        label: "Review queue",
        target: "review_queue",
        description: "Inspect evidence that may require class correction.",
      },
    ],
  },
  quality_control: {
    title: "Quality-control evidence",
    summary:
      "Run explainable checks that identify annotation, metadata, or dataset issues requiring attention.",
    boundary: "review",
    recordPolicy:
      "A QC finding is evidence for review, not an automatic correction to scientist-verified project data.",
    actions: [
      {
        label: "Review queue",
        target: "review_queue",
        description: "Work through ranked scientist-review items.",
      },
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Inspect and correct the underlying image evidence.",
      },
    ],
  },
  review_queue: {
    title: "Scientist review queue",
    summary:
      "Work through ranked model proposals and project issues that require an explicit human decision.",
    boundary: "review",
    recordPolicy:
      "Machine scores prioritize review only. Acceptance, correction, or rejection remains an explicit scientist action.",
    actions: [
      {
        label: "Quality control",
        target: "quality_control",
        description: "Inspect explainable QC findings and review triggers.",
      },
      {
        label: "Images & annotation",
        target: "gallery",
        description: "Return to the underlying project imagery.",
      },
    ],
  },
  video: {
    title: "Video, tracking & pose",
    summary:
      "Analyze temporal imagery, organism tracks, repeated landmarks, pose identity, behavior, and movement evidence.",
    boundary: "mixed",
    recordPolicy:
      "Automated tracks, pose associations, and behavior outputs remain reviewable machine evidence until verified or corrected.",
    actions: [
      {
        label: "Active learning",
        target: "active_learning",
        description: "Prioritize difficult temporal or pose examples.",
      },
      {
        label: "Workflow builder",
        target: "workflows",
        description: "Compose repeatable video and pose analysis workflows.",
      },
    ],
  },
  workflows: {
    title: "Workflow graph",
    summary:
      "Compose typed analysis nodes around existing ReefVision operations, review gates, and reproducible outputs.",
    boundary: "mixed",
    recordPolicy:
      "The graph orchestrates canonical operations; it does not bypass their validation, provenance, or scientist-review requirements.",
    actions: [
      {
        label: "Active learning",
        target: "active_learning",
        description: "Connect acquisition and review loops to canonical tools.",
      },
      {
        label: "Video & tracking",
        target: "video",
        description: "Open temporal and pose tools used by workflow nodes.",
      },
    ],
  },
};

const PRESET_GUIDANCE: Record<
  WorkspacePresetId,
  WorkspacePresetInspectorGuidance
> = {
  annotation: {
    title: "Annotation preset",
    description:
      "Keep image review central. Geometry edits, class decisions, and accepted annotations stay inside the canonical annotation editor.",
  },
  detection: {
    title: "Detection preset",
    description:
      "Detector selection and batch inference remain in the image/model workspaces. Detection output is a proposal until reviewed.",
  },
  segmentation: {
    title: "Segmentation preset",
    description:
      "Prompt and model masks remain provider proposals until the scientist accepts or edits them in the canonical mask workflow.",
  },
  pose: {
    title: "Pose Tracking preset",
    description:
      "Repeated landmarks, temporal identity, occlusion, identity breaks, and corrections remain canonical in the video and pose tools.",
  },
  morphometrics: {
    title: "Scale calibration & measurements",
    description:
      "Calibration, mask measurements, skeleton metrics, and physical-unit conversion stay tied to reviewed image evidence. Automatic scale-bar evidence must be confirmed before application.",
  },
  workflow: {
    title: "Workflow Builder preset",
    description:
      "Use the node graph to compose existing tools and future active-learning loops without creating a second analysis engine.",
  },
  review: {
    title: "Review / QA preset",
    description:
      "This layout emphasizes the boundary between provisional machine output and scientist-verified truth.",
  },
  custom: {
    title: "Custom Layout",
    description:
      "Custom layout changes presentation only. It does not alter scientific records, review state, or provenance.",
  },
};

export function workspaceInspectorDefinition(
  view: WorkspaceInspectorView,
): WorkspaceInspectorDefinition {
  return WORKSPACE_INSPECTORS[view] ?? WORKSPACE_INSPECTORS.gallery;
}

export function workspacePresetInspectorGuidance(
  preset: WorkspacePresetId,
): WorkspacePresetInspectorGuidance {
  return PRESET_GUIDANCE[preset] ?? PRESET_GUIDANCE.annotation;
}
