# ReefVision 1.6 — preserve QC coordination during asynchronous queue refresh

## Audited scope and actual gap

Track D's existing 1.6 implementation already includes class visibility, researcher QC comments and assignments, guarded close/discard controls, and an executable typed `qc_review_queue` Workflow Builder node with saved runs, provenance, idempotent retry and explicit researcher-review requirements. This is an interface-lifecycle correction, **not** a second QC workflow node or a migration.

The dashboard previously reset `coordinationItemId` whenever the derived active queue changed. A background queue-list refetch could temporarily omit the selected queue, causing the open coordination component to unmount and discard unsent biological notes or the original idempotency UUID for an uncertain audit event. The queue-history button for the **currently selected queue** also remained enabled while coordination was open and its click handler unmounted the panel.

## Fix

- Pin the original queue ID when the researcher opens coordination. Preserve the same coordination component and its original queue identity even when a refreshed list temporarily omits that queue. Host queue selection remains pinned while the panel is open.
- Disable **all** queue-history buttons during coordination, including the already-selected queue, with an event-handler guard as defense in depth.
- If a refresh omits the pinned queue, display an explicit warning and disable opening coordination on a different queue. A subsequent list refresh restores the normal queue display without clearing drafts.
- Only the existing guarded panel close (or an explicit project transition outside this component) clears the pinned queue. No automatic approval, event replay, model download, network transmission or research-asset mutation occurs.

## Regression and release gates

Dashboard regressions check that reselecting the same queue cannot discard a draft; that replacing the list with another queue preserves a coral observation, original host queue identity and the open panel; and that restoring the list leaves the draft unchanged. Existing standalone QC event tests and saved executable Workflow Builder regression suites remain mandatory; this UI-only change does not alter typed graph execution.

This is in-memory protection, **not** durable crash recovery. Native Windows installed-GUI/MSI upgrade and rollback, representative biological-data acceptance, complete exact-head CI, and independent 1.1/1.6 Alembic revision-0038 reconciliation remain required. Version 1.6 is **not release-ready**.
