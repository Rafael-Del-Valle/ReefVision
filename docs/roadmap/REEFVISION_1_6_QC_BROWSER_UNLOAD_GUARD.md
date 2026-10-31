# ReefVision 1.6 — browser unload guard for QC coordination

## Existing capability and gap

The existing review coordination panel retains per-item drafts and original idempotency UUIDs during in-app A → B → A navigation. The dashboard now keeps that panel mounted during review-item changes and protects its own close button. Browser reload, window closure, and application shutdown bypass the panel close button; previously no `beforeunload` warning was registered. An interrupted event may already have reached SQLite, so losing its UUID can create a duplicate audit entry on resubmission.

## Bounded implementation

While **any** visited review item has an unsent comment/assignee draft, an event mutation is pending, or an uncertain event UUID remains unresolved, the mounted panel registers a browser `beforeunload` confirmation handler. It unregisters the handler when all such conditions clear or when the component unmounts. The handler never transmits biological data, retries a mutation, changes server records, or grants scientific approval. The existing explicit close/discard confirmation and original-UUID retry flow remain authoritative.

## Regression contract

React tests dispatch cancelable browser unload events and verify: (1) an unsent biological note activates the guard and clearing it removes the guard; (2) an in-flight reviewer unassignment with no unsent text still activates the guard and a confirmed response clears it; (3) a failed reviewer unassignment retains the warning until explicit two-step abandonment of its uncertain UUID. All tests use the existing standalone QC event API mock; no new Workflow Builder node is introduced because this is a browser-lifecycle safeguard, not a scientific processing operation. Existing executable, saved `qc_review_queue` Workflow Builder tests and provenance/review gates must continue to pass.

## Scientific and release limitations

Browser `beforeunload` is best-effort: some browsers suppress the confirmation, mobile and forced application termination can skip it, and it **does not** persist drafts or retry UUIDs across a crash. Native Tauri window-close behavior and external SPA/workspace navigation must be separately verified. No claim of durable crash recovery or Windows installed-GUI acceptance is made. The 1.1/1.6 Alembic revision-0038 conflict and physical Windows MSI/upgrade/rollback acceptance remain release blockers. No migration, model weights, research assets, or other version branch is modified.
