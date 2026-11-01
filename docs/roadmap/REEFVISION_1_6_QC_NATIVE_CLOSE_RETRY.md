# ReefVision 1.6 — native QC close guard recovery and hidden-draft acceptance

## Scope and prior-work audit

Track D retains the existing 1.6 project/class visibility, QC event API, per-item draft state, review queues, bulk triage, and the executable saved `qc_review_queue` Workflow Builder node. This change is a local desktop usability and audit-protection safeguard, not a new scientific analysis node. It does not alter 1.0–1.5 workflows, schema, verified observations, or user assets.

## Failure mode

Tauri's native `onCloseRequested` listener can fail to register. Previously the coordination panel warned the researcher but offered no way to restore protection without clearing all unsent drafts and reopening the unsafe state. A researcher could have unsent biological observations or an uncertain event UUID while native close interception remained unavailable.

## Behavior

- On failed native registration, display a warning and an explicit **Retry desktop close protection** control.
- A retry removes the warning temporarily, invalidates the previous subscription attempt and registers the native listener again. No draft, reviewer identity, audit event, request UUID, or server record is changed.
- Successful registration clears the warning. A native close request while unsafe calls `preventDefault`.
- The guard remains active for drafts on *any* visited review item, including hidden drafts after A → B navigation.
- The browser `beforeunload` safeguard is unchanged; Tauri native close protection is not equivalent to durable crash recovery.

## Automated acceptance

`ReviewQueueCoordinationPanel.windowClose.test.tsx` covers failed registration followed by explicit successful retry, retention of the original biological draft, blocked native closure, absence of unintended audit writes, and A → B → A preservation of a hidden draft while the native guard remains active. Existing native-close, uncertain-UUID, browser-unload, cross-item close, and saved QC Workflow Builder regressions remain in place.

## Outstanding release requirements

This implementation is **not** a guarantee against process crashes, forced operating-system termination, failed Tauri event registration, or external workspace navigation. Full 1.6 release acceptance still requires exact-head frontend/backend CI, independent 1.1/1.6 Alembic 0038 lineage reconciliation, installed Windows GUI and MSI/CAB upgrade/rollback testing, real biological-data acceptance, and researcher approval. Do not merge, tag, release, deploy, download model weights, or delete assets on the basis of this increment.

## Coordination synchronous-registration recovery (2026-10-31)

The coordination panel's native close guard previously handled asynchronous
`onCloseRequested()` rejection but not synchronous exceptions thrown by
`getCurrentWindow()` or `onCloseRequested()` before a Promise was returned.
An exception during the effect could interrupt UI rendering while unsent
biological notes or an uncertain event idempotency UUID remained in memory.
The bulk-review panel already had this protection; this is the remaining
coordination-specific gap, not a new QC feature or Workflow Builder node.

The coordination guard now catches both synchronous exceptions and rejected
registration Promises. It exposes the existing explicit retry control, retains
the original unsent notes and exact event request UUID, and continues browser
`beforeunload` protection. Listener cleanup after a successful retry remains
scoped to the active panel. Three additional component regression cases cover
both synchronous exception sites and a lost server response followed by
identical-UUID replay. No automatic review completion or biological approval
is introduced.

**Validation boundary:** Remote commit and file readback can verify the
implementation, but do not substitute for exact-head frontend type/lint/Vitest,
Playwright, backend/migration CI, native installed Windows WebView2, MSI
upgrade/rollback, or representative biological-data acceptance. This is
best-effort window-close protection; abrupt crashes/power loss still require
durable recovery. The existing typed, executable and saved `qc_review_queue`
Workflow Builder integration is unchanged. Release remains HOLD.
