# ReefVision 1.6 — bulk QC window-close protection

## Prior implementation and overlap audit

The 1.6 bulk review panel already supports human-confirmed queue-only
transitions, server-backed idempotency keys, exact response item validation,
uncertain-response retry and explicit discard. Dashboard navigation/refetch
protection retains the in-memory request across filter and page changes.
The existing `qc_review_queue` Workflow Builder node is executable, typed,
persisted and reviewed; this UI safety fix does **not** create another node
or change its scientific outputs. Earlier versions' workflow and desktop
infrastructure remain isolated.

The coordination panel already guarded browser reload and native Tauri
window closure. Bulk triage did not. A researcher could close or reload the
desktop during a bulk request, losing the exact request UUID even if the
SQLite transaction committed and its HTTP response was lost.

## Implemented behavior

- While a bulk QC request is pending or its outcome uncertain, register
  browser `beforeunload` confirmation and a native Tauri close interceptor.
  Native close is refused and a visible warning explains the unresolved
  audit/idempotency risk.
- If native listener registration fails, whether through an asynchronous
  rejection or a synchronous throw from the Tauri window accessor/listener,
  show a retry control without changing the original bulk request, UUID,
  actor or item set. Browser-unload protection stays active during recovery.
- Remove both guards when the request succeeds or the researcher explicitly
  confirms the existing two-step discard process. A late asynchronous
  Tauri listener is immediately unregistered after its scope becomes safe.
- Browser-only operation never invokes the native window API.
- No automatic retry, silent scientific approval, cloud transfer, model
  download, research-record deletion or persistent storage of self-reported
  reviewer identities is introduced.

## Acceptance and limitations

`ReviewQueueBulkTriage.windowClose.test.tsx` covers idle closure,
native close during an in-flight request and uncertain outcome, exact UUID
replay, browser reload and explicit discard, failed native registration
with manual retry, synchronous native bridge failures and exact-UUID
recovery, and late listener cleanup. Existing standalone API and saved
Workflow Builder tests remain required.

Window-close protection is **best effort**. It cannot recover an original
UUID after an OS crash, power loss, forced termination or browser process
kill. Durable encrypted/local-only recovery requires separate design,
privacy review and regression coverage before claiming crash safety.

Release remains **HOLD** until exact-head CI, independent 1.1/1.6 Alembic
0038 lineage reconciliation, representative biological review acceptance,
Windows MSI/CAB upgrade/rollback and installed GUI validation.
