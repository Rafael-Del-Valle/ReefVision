import { describe, expect, it } from "vitest";

import type {
  ClassVisibilityBundle,
  ClassVisibilityScopeState,
} from "../../api/client";
import { updateClassVisibilityBundleForProject } from "./classVisibility";

const emptyState: ClassVisibilityScopeState = {
  saved: false,
  hidden_class_ids: [],
  updated_at: null,
  updated_by_identity: null,
};

function bundle(projectId: string): ClassVisibilityBundle {
  const scopes = {
    annotations: emptyState,
    predictions: emptyState,
    qc_overlays: emptyState,
    video_tracks: emptyState,
    segmentation_overlays: emptyState,
  };
  return {
    project_id: projectId,
    user_identity: "local-user:fixture",
    supported_layer_types: [
      "annotations",
      "predictions",
      "qc_overlays",
      "video_tracks",
      "segmentation_overlays",
    ],
    precedence: [],
    user_preferences: { ...scopes },
    project_defaults: { ...scopes },
  };
}

describe("class visibility mutation project isolation", () => {
  const saved: ClassVisibilityScopeState = {
    saved: true,
    hidden_class_ids: ["class-1"],
    updated_at: "2026-10-30T00:00:00Z",
    updated_by_identity: "local-user:fixture",
  };

  it("updates only the requested layer and scope for its original project", () => {
    const original = bundle("project-1");
    const updated = updateClassVisibilityBundleForProject(
      original,
      "project-1",
      "local-user:fixture",
      "user_preferences",
      "annotations",
      saved,
    );
    expect(updated.user_preferences.annotations).toEqual(saved);
    expect(updated.project_defaults.annotations).toBe(emptyState);
    expect(updated.user_preferences.predictions).toBe(emptyState);
    expect(original.user_preferences.annotations).toBe(emptyState);
  });

  it("cannot write a delayed result into another project's cached bundle", () => {
    const currentProject = bundle("project-2");
    const updated = updateClassVisibilityBundleForProject(
      currentProject,
      "project-1",
      "local-user:fixture",
      "project_defaults",
      "annotations",
      saved,
    );
    expect(updated).toBe(currentProject);
    expect(updated.project_defaults.annotations).toBe(emptyState);
  });

  it("rejects a late preference save from a different local user", () => {
    const currentUser = bundle("project-1");
    const updated = updateClassVisibilityBundleForProject(
      currentUser,
      "project-1",
      "local-user:previous",
      "user_preferences",
      "annotations",
      saved,
    );
    expect(updated).toBe(currentUser);
    expect(updated.user_preferences.annotations).toBe(emptyState);
  });

  it("rejects a late preference reset without a known originating identity", () => {
    const currentUser = bundle("project-1");
    const updated = updateClassVisibilityBundleForProject(
      currentUser,
      "project-1",
      null,
      "user_preferences",
      "annotations",
      emptyState,
    );
    expect(updated).toBe(currentUser);
  });

  it("allows project defaults to update regardless of the originating user", () => {
    const currentUser = bundle("project-1");
    const updated = updateClassVisibilityBundleForProject(
      currentUser,
      "project-1",
      "local-user:previous",
      "project_defaults",
      "annotations",
      saved,
    );
    expect(updated.project_defaults.annotations).toEqual(saved);
    expect(updated.user_preferences.annotations).toBe(emptyState);
  });
});
