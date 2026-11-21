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

## Incomplete preview response guard (2026-11-20)

A second review of this existing UI found that a malformed or partially decoded
API preview could enable **Run reassign** or **Run Reassign and Delete** even
when its opaque operation ID or SHA-256 preview checksum was empty/missing.
The backend would reject such an execution, but the interface inaccurately
presented it as approved. An incomplete scientific reference report could also
throw during summary rendering before the researcher could recover.

Both operations now require a nonblank operation ID, a syntactically complete
64-hex-digit checksum and all required display/review arrays. Missing arrays
produce a visible non-executable incomplete-evidence message rather than
rendering an incomplete inventory or crashing. Eight parameterized React
regressions cover both actions under blank IDs, missing/malformed checksums,
and truncated scientific reference reports. This is a fail-closed client-side
contract; the **server's immutable preview checksum, current project scope,
reference inventory and concurrency controls remain the authority**.

No new schema, model, Workflow Builder node or science data change was needed:
existing typed executable standalone/saved QC nodes, units, provenance, retries
and explicit human-review gates are unaffected. This correction does not
qualify the MSI or remove the separate release acceptance hold.

## Release hold

The isolated 1.6 draft PR remains on HOLD until full exact-head lint/type,
backend/frontend/E2E, saved-workflow/scientific and migration acceptance pass,
the independent 1.1/1.6 Alembic-0038 collision is reconciled, real Windows
MSI/CAB clean install + upgrade/rollback and installed-GUI usability are
validated, and the researcher approves. 1.7 and revised 1.8 are untouched.

## Nested preview evidence and explicit warnings (2026-11-20)

The backend returns plan-level and audit-level warnings, but the class manager
previously hid them; it also accepted malformed entries inside otherwise valid
record lists. Approval now requires complete nested scientific groups with
nonnegative safe-integer counts and valid reference IDs, valid compatibility
impacts, and all required warning/blocker/failure arrays with readable text.
Both warning sources are rendered once per distinct warning. Incomplete or
malformed evidence fails closed; the backend checksum, scope checks and human
authorization remain authoritative. Added twelve parameterized React malformed
evidence regressions across both operations, plus a warning-display regression;
updated existing mock API responses to match the required backend schema.

This UI safety increment leaves scientific assets, migrations and typed,
executable standalone/saved QC Workflow Builder workflows, units, provenance,
retries and researcher gates untouched. Release remains on HOLD for the
1.1/1.6 Alembic-0038 collision and full Windows installer/GUI acceptance.
