import type {
  ClassVisibilityBundle,
  ClassVisibilityLayerType,
  ClassVisibilityScopeState,
} from "../../api/client";

export type VisibilitySource =
  "session" | "my_preference" | "project_default" | "visible_by_default";

export type VisibilityScopeKey = "user_preferences" | "project_defaults";

export interface ClassVisibilityLayerOption {
  id: ClassVisibilityLayerType;
  label: string;
  description: string;
  liveInEditor: boolean;
}

export interface ResolvedClassVisibilityState {
  hiddenClassIds: string[];
  source: VisibilitySource;
  userPreference: ClassVisibilityScopeState;
  projectDefault: ClassVisibilityScopeState;
}

export const visibilityLayerOptions: ClassVisibilityLayerOption[] = [
  {
    id: "annotations",
    label: "Annotations",
    description: "Bounding boxes and other saved annotation geometry.",
    liveInEditor: true,
  },
  {
    id: "predictions",
    label: "Predictions",
    description: "Pending proposal rows and prediction overlays.",
    liveInEditor: true,
  },
  {
    id: "qc_overlays",
    label: "QC Overlays",
    description: "Saved now and applied when QC overlays are shown.",
    liveInEditor: false,
  },
  {
    id: "video_tracks",
    label: "Video Tracks",
    description: "Saved now and applied in video-track workflows.",
    liveInEditor: false,
  },
  {
    id: "segmentation_overlays",
    label: "Segmentation Overlays",
    description: "Saved segmentation-mask overlays in the image editor.",
    liveInEditor: true,
  },
];

const EMPTY_SCOPE_STATE: ClassVisibilityScopeState = {
  saved: false,
  hidden_class_ids: [],
  updated_at: null,
  updated_by_identity: null,
};

export function visibilityLayerLabel(
  layerType: ClassVisibilityLayerType,
): string {
  return (
    visibilityLayerOptions.find((option) => option.id === layerType)?.label ??
    layerType
  );
}

export function visibilitySourceLabel(source: VisibilitySource): string {
  switch (source) {
    case "session":
      return "Session";
    case "my_preference":
      return "My Preference";
    case "project_default":
      return "Project Default";
    default:
      return "Visible by default";
  }
}

export function sanitizeHiddenClassIds(
  hiddenClassIds: readonly string[],
  validClassIds: readonly string[],
): string[] {
  const valid = new Set(validClassIds);
  const seen = new Set<string>();
  const sanitized: string[] = [];
  hiddenClassIds.forEach((classId) => {
    if (!valid.has(classId) || seen.has(classId)) {
      return;
    }
    seen.add(classId);
    sanitized.push(classId);
  });
  return sanitized;
}

function scopeState(
  bundle: ClassVisibilityBundle | undefined,
  scopeKey: VisibilityScopeKey,
  layerType: ClassVisibilityLayerType,
): ClassVisibilityScopeState {
  return bundle?.[scopeKey][layerType] ?? EMPTY_SCOPE_STATE;
}

export function resolveClassVisibilityState(
  layerType: ClassVisibilityLayerType,
  bundle: ClassVisibilityBundle | undefined,
  sessionOverrides: Partial<Record<ClassVisibilityLayerType, string[]>>,
  validClassIds: readonly string[],
): ResolvedClassVisibilityState {
  const userPreference = scopeState(bundle, "user_preferences", layerType);
  const projectDefault = scopeState(bundle, "project_defaults", layerType);
  const sessionOverride = sessionOverrides[layerType];

  if (sessionOverride !== undefined) {
    return {
      hiddenClassIds: sanitizeHiddenClassIds(sessionOverride, validClassIds),
      source: "session",
      userPreference,
      projectDefault,
    };
  }
  if (userPreference.saved) {
    return {
      hiddenClassIds: sanitizeHiddenClassIds(
        userPreference.hidden_class_ids,
        validClassIds,
      ),
      source: "my_preference",
      userPreference,
      projectDefault,
    };
  }
  if (projectDefault.saved) {
    return {
      hiddenClassIds: sanitizeHiddenClassIds(
        projectDefault.hidden_class_ids,
        validClassIds,
      ),
      source: "project_default",
      userPreference,
      projectDefault,
    };
  }
  return {
    hiddenClassIds: [],
    source: "visible_by_default",
    userPreference,
    projectDefault,
  };
}

export function updateClassVisibilityBundleScope(
  bundle: ClassVisibilityBundle,
  scopeKey: VisibilityScopeKey,
  layerType: ClassVisibilityLayerType,
  state: ClassVisibilityScopeState,
): ClassVisibilityBundle {
  if (scopeKey === "user_preferences") {
    return {
      ...bundle,
      user_preferences: {
        ...bundle.user_preferences,
        [layerType]: state,
      },
    };
  }
  return {
    ...bundle,
    project_defaults: {
      ...bundle.project_defaults,
      [layerType]: state,
    },
  };
}

/** Keep delayed visibility saves scoped to the project that issued them. */
export function updateClassVisibilityBundleForProject(
  bundle: ClassVisibilityBundle,
  projectId: string,
  originUserIdentity: string | null,
  scopeKey: VisibilityScopeKey,
  layerType: ClassVisibilityLayerType,
  state: ClassVisibilityScopeState,
): ClassVisibilityBundle {
  if (
    bundle.project_id !== projectId ||
    (scopeKey === "user_preferences" &&
      (originUserIdentity === null ||
        bundle.user_identity !== originUserIdentity))
  ) {
    return bundle;
  }
  return updateClassVisibilityBundleScope(bundle, scopeKey, layerType, state);
}
