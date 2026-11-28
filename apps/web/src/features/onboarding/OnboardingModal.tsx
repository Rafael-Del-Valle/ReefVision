import { useEffect, useRef } from "react";

interface OnboardingModalProps {
  version: string;
  onClose: () => void;
  onDismissPermanently: () => void;
}

export function OnboardingModal({
  version,
  onClose,
  onDismissPermanently,
}: OnboardingModalProps) {
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement;
    closeButton.current?.focus();
    return () => {
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal onboarding-modal"
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          } else if (event.key === "Tab") {
            const buttons = dialog.current?.querySelectorAll("button");
            const first = buttons?.[0];
            const last = buttons?.[buttons.length - 1];
            if (event.shiftKey && event.target === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && event.target === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <div className="section-heading">
          <div>
            <h2 id="onboarding-title">Welcome to ReefVision {version}</h2>
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

        <div className="onboarding-grid">
          <article className="onboarding-card">
            <h3>Open a project and import media</h3>
            <p>
              Create or open a project on Home. In Images &amp; annotation,
              import files or a folder and open an image from the gallery.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Annotate and review</h3>
            <p>
              Use the image editor to draw boxes or masks. Register a local
              checkpoint in Model Hub, choose it in the image inspector, then
              review each prediction you want to accept.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Add environmental context</h3>
            <p>
              Open Environmental Context in Data &amp; annotation. Add data,
              select a saved record to inspect its source and quality, or use
              Analyses to see what each method requires.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Save and return to work</h3>
            <p>
              Use Dataset versions for reproducible exports, Interoperability
              for project exchange, and System status for backups and recovery.
              Open Help to return to this guide.
            </p>
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
