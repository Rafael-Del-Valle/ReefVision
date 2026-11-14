# ReefVision 1.6 — bind class-operation approval to QC/review membership

## Audited gap

Reassign and Reassign-and-Delete saved a preview checksum over reference record IDs,
group categories, source/target biological identity and warnings. A QC issue or a
review-queue item could retain its ID and category while gaining a different
`class_ids_json` / `label_class_ids_json` membership. A mutable state could also
change within the same preview group (QC open→acknowledged, queue pending→in_progress).
The unchanged record-ID inventory previously allowed execution under the old
researcher approval and silently rewrote a record whose scientific associations
had changed.

## Implemented contract

The existing 1.6 plan checksum now includes sorted source-referencing QC issue
IDs, their full ordered class-ID arrays and status, plus sorted review-queue item
IDs, their full ordered class-ID arrays and review states. This evidence covers
both mutable and historical source-referencing records. Before either operation
executes, it recomputes that evidence from the database and returns HTTP 409 for
a stale preview before reassigning annotations, model proposals, QC, or review
queue references. The operation is recorded as `preview_stale`; researchers
must inspect and approve a new preview.

The evidence is kept inside the approval checksum rather than exposed as
additional API output. No schema migration or model download is required.
An older saved preview that lacks this evidence will be invalidated and must be
created again. The change is local-first and does not alter standard review
decisions or immutable scientific dataset/model maps.

## Verification and limitations

Database-backed regressions separately change QC class membership, review
class membership, QC state within the mutable set and queue state within the
mutable set; each runs for both operation endpoints, verifying HTTP 409 and
preservation of source annotations and review links. Existing successful
operation regressions must continue to pass.

This safeguard binds approval to the referenced QC and review class membership
at the time of the execution recheck. It does not eliminate concurrent edits
between that check and the final transaction commit; it is not authentication
against filesystem access. Full Python backend tests and native Windows GUI/MSI
acceptance remain release gates.

These are researcher-approved metadata operations, not scientific analysis
nodes. Existing executable typed QC Workflow Builder nodes, saved graphs/runs,
scientific provenance and review gates remain unchanged; their standalone and
saved-workflow tests are mandatory regression gates.
