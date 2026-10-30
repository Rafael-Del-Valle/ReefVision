import { useEffect, useRef, type KeyboardEvent } from "react";

export type OnboardingDestination =
  | "classes"
  | "review_queue"
  | "workflows"
  | "system"
  | "create_project"
  | "projects";

interface OnboardingModalProps {
  version: string;
  hasProject: boolean;
  onNavigate: (destination: OnboardingDestination) => void;
  onClose: () => void;
  onDismissPermanently: () => void;
}

export function OnboardingModal({
  version,
  hasProject,
  onNavigate,
  onClose,
  onDismissPermanently,
}: OnboardingModalProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const handoffFocusRef = useRef(false);

  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    closeButtonRef.current?.focus();

    // A dialog-level Tab handler cannot catch focus moved outside the dialog
    // by browser chrome, extensions, scripts, or a dynamically mounted control.
    // Keep the first-run help modal truly modal without changing background data.
    function keepFocusInDialog(event: FocusEvent) {
      const dialog = dialogRef.current;
      if (
        dialog &&
        event.target instanceof Node &&
        !dialog.contains(event.target)
      ) {
        closeButtonRef.current?.focus();
      }
    }
    document.addEventListener("focusin", keepFocusInDialog);
    return () => {
      document.removeEventListener("focusin", keepFocusInDialog);
      // Opening the project-creation dialog is a modal-to-modal handoff.
      // Do not steal focus from its auto-focused project-name input.
      if (!handoffFocusRef.current && previouslyFocused?.isConnected) {
        previouslyFocused.focus();
      }
    };
  }, []);

  function navigateTo(destination: OnboardingDestination) {
    // Both project destinations hand keyboard focus to the next workspace.
    // Restoring the old trigger would leave focus behind the launcher.
    if (destination === "create_project" || destination === "projects") {
      handoffFocusRef.current = true;
    }
    onNavigate(destination);
    onClose();
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>(
      "button:not([disabled])",
    );
    if (!buttons?.length) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="modal onboarding-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onKeyDown={handleDialogKeyDown}
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">First run</p>
            <h2 id="onboarding-title">Welcome to ReefVision {version}</h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="icon-button"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="onboarding-grid">
          <article className="onboarding-card">
            <h3>Getting started</h3>
            <p>
              ReefVision stores managed data in its application data directory,
              not inside the install folder. Create a project first, then use
              the Images tab to import source images as protected managed
              copies.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Annotation workflow</h3>
            <p>
              Open an image from the gallery, draw or edit bounding boxes, and
              use Smart Mask when a local assist checkpoint is registered. Model
              inference stays local and predictions must still be reviewed by a
              human before they count as verified annotations.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Research review and workflows</h3>
            <p>
              Manage classes and saved per-user or project visibility settings,
              then use quality-control review queues to prioritize images.
              Assign reviewers, add comments, or manually triage multiple items.
              Workflow Builder can save and rerun a QC queue with typed results
              and provenance; queue rankings never approve model predictions or
              replace researcher verification.
            </p>
            {!hasProject && (
              <>
                <p>
                  Select or create a project to open class, QC, or workflow
                  tools.
                </p>
                <div className="onboarding-card-actions">
                  <button
                    type="button"
                    onClick={() => navigateTo("create_project")}
                  >
                    Create a project
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => navigateTo("projects")}
                  >
                    Choose an existing project
                  </button>
                </div>
              </>
            )}
            <div className="onboarding-card-actions">
              <button
                type="button"
                className="secondary"
                disabled={!hasProject}
                onClick={() => navigateTo("classes")}
              >
                Open class manager
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!hasProject}
                onClick={() => navigateTo("review_queue")}
              >
                Open QC review
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!hasProject}
                onClick={() => navigateTo("workflows")}
              >
                Open Workflow Builder
              </button>
            </div>
          </article>
          <article className="onboarding-card">
            <h3>Recovery and support</h3>
            <p>
              Open System status for backups, restore into a new recovery
              location, log paths, and redacted diagnostics bundles. Keep a
              verified backup before moving research data to another computer.
            </p>
            <div className="onboarding-card-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => navigateTo("system")}
              >
                Open System status
              </button>
            </div>
          </article>
        </div>

        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Skip for now
          </button>
          <button type="button" onClick={onDismissPermanently}>
            Don&apos;t show on startup
          </button>
        </div>
      </section>
    </div>
  );
}
