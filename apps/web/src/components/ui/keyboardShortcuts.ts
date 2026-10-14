export type ShortcutScope = "gallery" | "annotation";

export interface KeyboardShortcut {
  id: string;
  group: "Gallery" | "View" | "Editing" | "Models and review";
  scope: ShortcutScope;
  label: string;
  keys: string[];
  protected?: boolean;
}

export interface ShortcutConflict {
  scope: ShortcutScope;
  key: string;
  commandIds: string[];
}

export const keyboardShortcuts: KeyboardShortcut[] = [
  {
    id: "gallery-previous",
    group: "Gallery",
    scope: "gallery",
    label: "Previous image",
    keys: ["ArrowLeft"],
  },
  {
    id: "gallery-next",
    group: "Gallery",
    scope: "gallery",
    label: "Next image",
    keys: ["ArrowRight"],
  },
  {
    id: "gallery-first",
    group: "Gallery",
    scope: "gallery",
    label: "First image",
    keys: ["Home"],
  },
  {
    id: "gallery-last",
    group: "Gallery",
    scope: "gallery",
    label: "Last image",
    keys: ["End"],
  },
  {
    id: "editor-previous",
    group: "Gallery",
    scope: "annotation",
    label: "Previous image in editor",
    keys: ["A"],
  },
  {
    id: "editor-next",
    group: "Gallery",
    scope: "annotation",
    label: "Next image in editor",
    keys: ["D"],
  },
  {
    id: "select-tool",
    group: "View",
    scope: "annotation",
    label: "Select tool",
    keys: ["V"],
  },
  {
    id: "pan-tool",
    group: "View",
    scope: "annotation",
    label: "Pan tool",
    keys: ["P"],
  },
  {
    id: "box-tool",
    group: "View",
    scope: "annotation",
    label: "Box tool",
    keys: ["B"],
  },
  {
    id: "fit-view",
    group: "View",
    scope: "annotation",
    label: "Fit image to view",
    keys: ["F"],
  },
  {
    id: "temporary-pan",
    group: "View",
    scope: "annotation",
    label: "Temporarily pan",
    keys: ["Alt+drag", "Middle-drag"],
  },
  {
    id: "zoom",
    group: "View",
    scope: "annotation",
    label: "Zoom around pointer",
    keys: ["Wheel"],
  },
  {
    id: "choose-class",
    group: "Editing",
    scope: "annotation",
    label: "Choose or assign class",
    keys: ["1–9"],
    protected: true,
  },
  {
    id: "copy",
    group: "Editing",
    scope: "annotation",
    label: "Copy selection",
    keys: ["Ctrl/Cmd+C"],
  },
  {
    id: "paste",
    group: "Editing",
    scope: "annotation",
    label: "Paste internal clipboard",
    keys: ["Ctrl/Cmd+V"],
  },
  {
    id: "duplicate",
    group: "Editing",
    scope: "annotation",
    label: "Duplicate selection",
    keys: ["Ctrl/Cmd+D"],
  },
  {
    id: "undo",
    group: "Editing",
    scope: "annotation",
    label: "Undo compatible edit",
    keys: ["Ctrl/Cmd+Z"],
  },
  {
    id: "redo",
    group: "Editing",
    scope: "annotation",
    label: "Redo compatible edit",
    keys: ["Ctrl/Cmd+Shift+Z", "Ctrl/Cmd+Y"],
  },
  {
    id: "delete",
    group: "Editing",
    scope: "annotation",
    label: "Delete selection",
    keys: ["Delete", "Backspace"],
  },
  {
    id: "cancel",
    group: "Editing",
    scope: "annotation",
    label: "Cancel transient operation",
    keys: ["Escape"],
  },
  {
    id: "toggle-annotations",
    group: "Editing",
    scope: "annotation",
    label: "Hide or show annotations",
    keys: ["H"],
  },
  {
    id: "sam-full-image",
    group: "Models and review",
    scope: "annotation",
    label: "Full-image SAM proposals",
    keys: ["Shift+1"],
    protected: true,
  },
  {
    id: "sam-refine-mask",
    group: "Models and review",
    scope: "annotation",
    label: "Selected-mask SAM refinement",
    keys: ["Shift+2"],
    protected: true,
  },
  {
    id: "proposal-next",
    group: "Models and review",
    scope: "annotation",
    label: "Next model proposal",
    keys: ["J"],
    protected: true,
  },
  {
    id: "proposal-previous",
    group: "Models and review",
    scope: "annotation",
    label: "Previous model proposal",
    keys: ["K"],
    protected: true,
  },
];

export function shortcutLabel(keys: string[]): string {
  return keys.join(" or ");
}

export function shouldIgnoreShortcutTarget(
  target: EventTarget | null,
): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(
    target.closest(
      'input, textarea, select, button, a, [contenteditable="true"], [role="dialog"], [role="menu"], [role="menuitem"]',
    ),
  );
}

export function findShortcutConflicts(
  shortcuts: KeyboardShortcut[],
): ShortcutConflict[] {
  const bindings = new Map<string, { key: string; commandIds: string[] }>();
  for (const shortcut of shortcuts) {
    for (const key of shortcut.keys) {
      const identity = `${shortcut.scope}:${key.toLowerCase()}`;
      const binding = bindings.get(identity) ?? { key, commandIds: [] };
      bindings.set(identity, {
        ...binding,
        commandIds: [...binding.commandIds, shortcut.id],
      });
    }
  }
  return Array.from(bindings.entries())
    .filter(([, binding]) => binding.commandIds.length > 1)
    .map(([identity, binding]) => {
      const separator = identity.indexOf(":");
      return {
        scope: identity.slice(0, separator) as ShortcutScope,
        key: binding.key,
        commandIds: binding.commandIds,
      };
    });
}
