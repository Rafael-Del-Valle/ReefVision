import { describe, expect, it } from "vitest";

import {
  annotationEditorReducer,
  initialAnnotationEditorState,
} from "./annotationEditorReducer";

describe("annotation editor save messaging", () => {
  it("surfaces revision conflicts without discarding local edits", () => {
    const dirtyState = {
      ...initialAnnotationEditorState,
      documentVersion: 2,
      lastCommittedVersion: 1,
      saveState: "saving" as const,
    };

    const conflicted = annotationEditorReducer(dirtyState, {
      type: "saveFailed",
      message: "Annotation revision conflict. Reload before saving again.",
      conflict: true,
    });

    expect(conflicted.saveState).toBe("conflict");
    expect(conflicted.saveMessage).toContain("revision conflict");
    expect(conflicted.documentVersion).toBe(2);
    expect(conflicted.lastCommittedVersion).toBe(1);
  });

  it("surfaces ordinary autosave failures separately from conflicts", () => {
    const failed = annotationEditorReducer(initialAnnotationEditorState, {
      type: "saveFailed",
      message: "Mask save failed",
      conflict: false,
    });

    expect(failed.saveState).toBe("error");
    expect(failed.saveMessage).toBe("Mask save failed");
  });
});
