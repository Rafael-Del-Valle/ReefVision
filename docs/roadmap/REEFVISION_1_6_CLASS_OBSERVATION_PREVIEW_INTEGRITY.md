# ReefVision 1.6 — class-operation approval bound to observation evidence

## Gap and version overlap

The existing standalone **Reassign** and **Reassign and Delete** Class Manager previews
bound researcher approval to class identity, reference IDs and QC/review memberships.
The earlier 1.0–1.5 service and the previous 1.6 implementation did **not** bind the
approval to annotation revisions/coordinates or the scientific content of pending
prediction proposals. A same-ID annotation edit or an in-place prediction change
could therefore be reassigned under an older preview, with no new researcher review.

## Fail-closed implementation

The existing preview SHA-256 now also covers an internally recomputed, ID-sorted
observation inventory for *all* source-class annotations (active and deleted) and
prediction proposals (pending and historical):

- Annotation record ID, image identity, revision and source-pixel bounding box.
- Proposal ID, image/model identities, model checksum, review status, predicted
  label/index, confidence, geometry kind, source-pixel bounding box, a canonical
  SHA-256 of polygon coordinates when present and the recorded mask-content SHA-256.

The API deliberately does not expose a new mutable approval field or create a new
database column. An execution that finds changed observation evidence returns
HTTP 409 with `preview_stale` **before** reassigning annotations, predictions, QC
issues or review queues; a fresh preview and explicit researcher approval are required.
Earlier pending previews are intentionally invalidated. Both successful operations
and historical scientific/model records retain their existing behavior.

## Regression and remaining boundaries

The database-backed HTTP regression covers both operation endpoints and seven
same-ID observation changes: annotation revision, annotation geometry, prediction
confidence, model checksum, box geometry, polygon coordinates and predicted label.
Each must reject stale approval and retain source class associations, review records
and operation provenance. Existing success tests still cover unchanged approval.

This guard records the observed database values at the recheck; it cannot alone
eliminate a concurrent write between that check and final commit or detect an
unmodified checksum when someone alters external mask bytes without updating the
stored mask SHA-256. It is not a cryptographic authentication mechanism.

These are explicit-researcher class metadata operations, **not** new analytical
Workflow Builder nodes. The existing local executable typed QC nodes, saved graphs,
saved-run provenance, retries and human review gates remain intact and must continue
to pass standalone and saved-workflow regressions. A new duplicated node would
not be appropriate for this increment.

**Release hold:** complete exact-head CI, migration/backwards-compatibility and
scientific data replay; independently reconcile the 1.1/1.6 Alembic revision-0038
collision; and validate Windows MSI/CAB installation/upgrade/rollback and the
installed GUI with real projects. Do not claim release readiness from this change.
