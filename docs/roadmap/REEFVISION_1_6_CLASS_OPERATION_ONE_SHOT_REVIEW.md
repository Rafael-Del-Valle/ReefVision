# ReefVision 1.6 — one-shot class operation review approvals

## Existing scope and gap

The class manager already has separate server-checksummed reassignment and
reassign-and-delete previews, an explicit researcher confirmation, and typed
executable/saved Workflow Builder QC operations from 1.0–1.5/1.6. This patch
does not introduce a duplicate scientific node or change the data model.

Each operation previously cleared only its own preview on success. A second
preview could remain enabled after the first operation changed the scientific
reference inventory, although its original review was no longer current.
Worse, a delayed preview response could overwrite the latest completed-operation
feedback with a preview state.

## Corrective behavior

- Successful execution of **either** operation clears **both** preview approvals
  and increments their selection epoch, invalidating any earlier in-flight
  preview responses even if class metadata, target ID and notes are unchanged.
- Preview HTTP success no longer replaces the completed operation receipt.
- Two parameterized UI regressions exercise both execution directions with both
  approvals present. A third delays the opposite preview until after a completed
  execution and checks the reviewer sees the completed receipt while the late
  preview remains non-executable.

The API's immutable preview checksum and backend concurrency/safety gates remain
authoritative; this is an additional researcher-facing safeguard. The fix
changes no stored biological observations, annotations, models, provenance,
migration schemas or workflow serialization. Existing typed standalone/saved
QC workflows, retry semantics, human approval and offline behavior are preserved.

## Release hold

The isolated 1.6 draft PR remains on HOLD until full exact-head lint/type,
backend/frontend/E2E, saved-workflow/scientific and migration acceptance pass,
the independent 1.1/1.6 Alembic-0038 collision is reconciled, real Windows
MSI/CAB clean install + upgrade/rollback and installed-GUI usability are
validated, and the researcher approves. 1.7 and revised 1.8 are untouched.
