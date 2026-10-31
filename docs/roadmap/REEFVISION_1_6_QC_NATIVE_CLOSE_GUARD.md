# ReefVision 1.6 — native desktop QC window-close protection

## Gap and nonduplication audit

The review coordination panel already protects drafts, idempotent audit-event UUIDs, and the browser `beforeunload` lifecycle. The dashboard also keeps the panel mounted during item navigation. Native Tauri 2 window-close requests are a separate lifecycle and cannot be assumed to fire browser `beforeunload`. Existing standalone QC API and the saved, executable typed `qc_review_queue` Workflow Builder node already implement scientific provenance and researcher review; this UI lifecycle guard does not require a duplicate node or migration.

## Implementation

While any visited item has an unsent comment/assignee draft, a pending event mutation, or an uncertain request UUID, the panel registers a Tauri `onCloseRequested` listener. The listener calls `preventDefault` and displays a clear researcher-facing explanation. The researcher must finish or explicitly discard drafts and resolve uncertain events using the existing two-step confirmation controls before attempting desktop closure again. The listener is removed when the risk clears or the component unmounts. Asynchronous late registration is immediately removed, and registration failures produce a warning. In a browser, the native listener is never registered; the existing `beforeunload` safeguard remains active.

No network transmission, automatic retry, biological approval, local file persistence, or asset mutation is introduced. Review-event payloads and original UUIDs remain unchanged.

## Regression and release limits

Dedicated React/Vitest tests cover native close interception for unsent coral notes and an in-flight unassignment, listener cleanup, delayed registration cleanup, browser-only behavior, and a native registration failure. Exact-head CI and real installed Windows/Tauri GUI acceptance are mandatory before treating this as validated. Native listener registration is asynchronous and cannot guarantee interception during the registration interval. Abrupt process termination, OS crashes, power loss, or external React workspace unmounts are **not** durably recovered. Do not claim crash recovery or full Windows installer acceptance.

Remaining independent blockers: 1.1/1.6 Alembic revision-0038 reconciliation, installed Windows MSI upgrade/rollback, representative biological data acceptance, and complete scope/CI verification. No merge, release, tag, deployment, paid hosting, or pretrained weights.
