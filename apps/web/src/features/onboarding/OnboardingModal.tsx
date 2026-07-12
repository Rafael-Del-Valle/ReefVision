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
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal onboarding-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">First run</p>
            <h2 id="onboarding-title">Welcome to ReefVision {version}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
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
            <h3>Research pipeline</h3>
            <p>
              Register local checkpoints, run inference, review predictions,
              create immutable dataset versions, run quality control, and build
              review queues from the current project state. YOLO export is
              available from dataset versions.
            </p>
          </article>
          <article className="onboarding-card">
            <h3>Recovery and support</h3>
            <p>
              Open System status for backups, restore into a new recovery
              location, log paths, and redacted diagnostics bundles. YOLO import
              remains planned in the product specification and is not yet
              exposed in this v1.6.0 interface.
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
