import { describe, expect, it } from "vitest";

import {
  findShortcutConflicts,
  keyboardShortcuts,
  shortcutLabel,
  shouldIgnoreShortcutTarget,
} from "./keyboardShortcuts";

describe("keyboard shortcut registry", () => {
  it("keeps protected SAM and class shortcuts discoverable without conflicts", () => {
    expect(findShortcutConflicts(keyboardShortcuts)).toEqual([]);
    expect(
      keyboardShortcuts.find((shortcut) => shortcut.id === "sam-full-image"),
    ).toMatchObject({ keys: ["Shift+1"], protected: true });
    expect(
      keyboardShortcuts.find((shortcut) => shortcut.id === "sam-refine-mask"),
    ).toMatchObject({ keys: ["Shift+2"], protected: true });
    expect(
      keyboardShortcuts.find((shortcut) => shortcut.id === "choose-class"),
    ).toMatchObject({ keys: ["1–9"], protected: true });
  });

  it("detects a conflicting binding in the same workspace", () => {
    const conflict = findShortcutConflicts([
      {
        id: "one",
        group: "Editing",
        scope: "annotation",
        label: "One",
        keys: ["Ctrl+C"],
      },
      {
        id: "two",
        group: "Editing",
        scope: "annotation",
        label: "Two",
        keys: ["Ctrl+C"],
      },
    ]);
    expect(conflict).toEqual([
      { scope: "annotation", key: "Ctrl+C", commandIds: ["one", "two"] },
    ]);
  });

  it("renders platform-neutral command labels", () => {
    expect(shortcutLabel(["Ctrl/Cmd+Shift+Z", "Ctrl/Cmd+Y"])).toBe(
      "Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y",
    );
  });

  it("ignores shortcuts owned by text controls, buttons, dialogs, and menus", () => {
    const dialog = document.createElement("section");
    dialog.setAttribute("role", "dialog");
    const plain = document.createElement("div");
    const input = document.createElement("input");
    const button = document.createElement("button");
    dialog.append(plain);

    expect(shouldIgnoreShortcutTarget(input)).toBe(true);
    expect(shouldIgnoreShortcutTarget(button)).toBe(true);
    expect(shouldIgnoreShortcutTarget(plain)).toBe(true);
    expect(shouldIgnoreShortcutTarget(document.body)).toBe(false);
  });
});
