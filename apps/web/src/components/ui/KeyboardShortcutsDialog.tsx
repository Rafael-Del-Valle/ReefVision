import { useEffect } from "react";

import { keyboardShortcuts, shortcutLabel } from "./keyboardShortcuts";

interface KeyboardShortcutsDialogProps {
  onClose: () => void;
}

const groups = ["Gallery", "View", "Editing", "Models and review"] as const;

export function KeyboardShortcutsDialog({
  onClose,
}: KeyboardShortcutsDialogProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [onClose]);

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal rv-shortcut-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="keyboard-shortcuts-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Reference</p>
            <h2 id="keyboard-shortcuts-title">Keyboard shortcuts</h2>
          </div>
          <button type="button" autoFocus onClick={onClose}>
            Close
          </button>
        </div>

        <p>
          Shortcuts run only in the relevant gallery or annotation workspace.
          They are ignored while you type in form controls and while a dialog or
          menu owns focus.
        </p>
        <div className="rv-shortcut-groups">
          {groups.map((group) => (
            <section key={group} aria-labelledby={`shortcut-${group}`}>
              <h3 id={`shortcut-${group}`}>{group}</h3>
              <dl>
                {keyboardShortcuts
                  .filter((shortcut) => shortcut.group === group)
                  .map((shortcut) => (
                    <div key={shortcut.id}>
                      <dt>{shortcut.label}</dt>
                      <dd>
                        <kbd>{shortcutLabel(shortcut.keys)}</kbd>
                      </dd>
                    </div>
                  ))}
              </dl>
            </section>
          ))}
        </div>
        <p className="annotation-helper">
          Copy and paste use the ReefVision internal clipboard. They do not read
          or write the Windows, macOS, browser, or Linux system clipboard. Ctrl
          and Cmd are shown together because desktop and browser hosts use
          different command modifiers. Browser and operating-system shortcuts
          may take priority outside the focused ReefVision workspace.
        </p>
      </section>
    </div>
  );
}
