import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { AutomationApiHelp } from "./AutomationApiHelp";

export type OnboardingWorkspace =
  "classes" | "review_queue" | "workflows" | "system" | "updates";

const projectActions = [
  { workspace: "classes", label: "Open class manager" },
  { workspace: "review_queue", label: "Open QC review" },
  { workspace: "workflows", label: "Open Workflow Builder" },
] as const;

interface OnboardingModalProps {
  version: string;
  hasProject: boolean;
  automationApiBaseUrl?: string;
  automationProject?: { id: string; name: string };
  preferredWorkflowRevisionId?: string;
  onStartProject: (action: "create" | "choose") => void;
  onOpenWorkspace: (workspace: OnboardingWorkspace) => boolean;
  onClose: () => void;
  onDismissPermanently: () => void;
}

export function OnboardingModal({
  version,
  hasProject,
  automationApiBaseUrl,
  automationProject,
  preferredWorkflowRevisionId,
  onStartProject,
  onOpenWorkspace,
  onClose,
  onDismissPermanently,
}: OnboardingModalProps) {
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const automationButton = useRef<HTMLButtonElement>(null);
  const handingOff = useRef(false);
  const returningToHelp = useRef(false);
  const [automationOpen, setAutomationOpen] = useState(false);

  useEffect(() => {
    const previous = document.activeElement;
    closeButton.current?.focus();
    function keepFocusInDialog(event: FocusEvent) {
      if (
        !handingOff.current &&
        dialog.current &&
        event.target instanceof Node &&
        !dialog.current.contains(event.target)
      ) {
        closeButton.current?.focus();
      }
    }
    document.addEventListener("focusin", keepFocusInDialog);
    return () => {
      document.removeEventListener("focusin", keepFocusInDialog);
      if (
        !handingOff.current &&
        previous instanceof HTMLElement &&
        previous.isConnected
      ) {
        previous.focus();
      }
    };
  }, []);

  useEffect(() => {
    if (automationOpen) closeButton.current?.focus();
    if (!automationOpen && returningToHelp.current) {
      returningToHelp.current = false;
      automationButton.current?.focus();
    }
  }, [automationOpen]);

  function startProject(action: "create" | "choose") {
    handingOff.current = true;
    onStartProject(action);
    onClose();
  }

  function openWorkspace(workspace: OnboardingWorkspace) {
    handingOff.current = onOpenWorkspace(workspace);
    onClose();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = dialog.current?.querySelectorAll<HTMLElement>(
      "button:not([disabled]), select:not([disabled]), textarea:not([disabled])",
    );
    if (!controls?.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
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
        className="modal onboarding-modal"
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onKeyDown={handleKeyDown}
      >
        <div className="section-heading">
          <div>
            <h2 id="onboarding-title">
              {automationOpen
                ? "Automation API"
                : `Welcome to ReefVision ${version}`}
            </h2>
          </div>
          <button
            ref={closeButton}
            type="button"
            className="icon-button"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        {automationOpen && automationApiBaseUrl !== undefined ? (
          <>
            <AutomationApiHelp
              apiBaseUrl={automationApiBaseUrl}
              project={automationProject}
              preferredRevisionId={preferredWorkflowRevisionId}
            />
            <div className="modal-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  returningToHelp.current = true;
                  setAutomationOpen(false);
                }}
              >
                Back to Help
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="onboarding-grid">
              <article className="onboarding-card">
                <h3>Open a project and import media</h3>
                <p>
                  Create or open a project on Home. In Images &amp; annotation,
                  import files or a folder and open an image from the gallery.
                </p>
                {!hasProject && (
                  <div className="onboarding-card-actions">
                    <button
                      type="button"
                      onClick={() => startProject("create")}
                    >
                      Create a project
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => startProject("choose")}
                    >
                      Choose an existing project
                    </button>
                  </div>
                )}
              </article>
              <article className="onboarding-card">
                <h3>Annotate and review</h3>
                <p>
                  Use the image editor to draw boxes or masks. Register a local
                  checkpoint in Model Hub, choose it in the image inspector,
                  then review each prediction you want to accept.
                </p>
                {!hasProject && <p>Open a project to use these tools.</p>}
                <div className="onboarding-card-actions">
                  {projectActions.map(({ workspace, label }) => (
                    <button
                      key={workspace}
                      type="button"
                      className="secondary"
                      disabled={!hasProject}
                      onClick={() => openWorkspace(workspace)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </article>
              <article className="onboarding-card">
                <h3>Add environmental context</h3>
                <p>
                  Open Environmental Context in Data &amp; annotation. Add data,
                  select a saved record to inspect its source and quality, or
                  use Analyses to see what each method requires.
                </p>
              </article>
              <article className="onboarding-card">
                <h3>Save and return to work</h3>
                <p>
                  Use Dataset versions for reproducible exports,
                  Interoperability for project exchange, and System status for
                  backups, recovery, and compatibility diagnostics. Open Help to
                  return to this guide.
                </p>
                <div className="onboarding-card-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => openWorkspace("system")}
                  >
                    Open System status
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => openWorkspace("updates")}
                  >
                    Diagnostics / Updates
                  </button>
                  {automationApiBaseUrl !== undefined && (
                    <button
                      ref={automationButton}
                      type="button"
                      className="secondary"
                      onClick={() => setAutomationOpen(true)}
                    >
                      Automation API
                    </button>
                  )}
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
          </>
        )}
      </section>
    </div>
  );
}
