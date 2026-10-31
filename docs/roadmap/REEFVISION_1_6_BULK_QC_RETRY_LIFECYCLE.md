# ReefVision 1.6 — Bulk QC retry lifecycle and navigation guard

## Scope and prior implementation audit

Version 1.6 already contains standalone bulk review, exact-item response validation,
researcher confirmation, scoped idempotent retries, and an executable saved
`qc_review_queue` Workflow Builder node with typed/provenance/review gates.
This change **does not** add a second review engine or a workflow node.

The existing dashboard keyed the bulk panel by page and filter values and only
mounted it while an item query had data. A filter change or transient refetch
could therefore destroy the component's unresolved bulk request UUID, even when
the server might already have committed the action. The parent also allowed
queue/workspace navigation while a bulk request was pending or uncertain.

## Implementation contract

- Keep the bulk panel instance keyed by queue identity, not page/filter values.
  Pass an empty visible-item list during loading; never clear an uncertain retry
  simply because the current page temporarily contains no rows.
- The bulk panel reports its protected queue to the dashboard while a request is
  pending or its outcome is uncertain. The dashboard blocks queue/scope/editor/
  workspace navigation until the request is resolved, and pins the original
  queue when an asynchronous queue-list refresh temporarily omits it.
- Preserve the **exact** original request payload and client UUID for retries.
  An identical retry may legitimately report zero changed items. The existing
  response-identity and researcher-review checks remain mandatory.
- Preserve manual scientific approval and audit history. Neither a QC queue
  completion nor a successful retry verifies predictions or biological labels.

## Regression evidence and remaining acceptance

Added component regression for a lost response, empty refreshed item list,
identical retry payload and protection release. Added dashboard regression for
filter changes, temporary queue-list omission, pinned host identity and blocked
navigation. Existing standalone bulk and saved-workflow tests remain required.

**Limitations:** This protects the mounted UI, not process crashes, power loss,
or forced termination. It does not persist raw biological notes or UUIDs to
browser storage, transmit research assets, or claim authenticated reviewer
identity. Full CI, Windows MSI upgrade/rollback and installed-GUI acceptance,
real-data scientific review, and the cross-version Alembic 0038 conflict must
still be verified before release.
