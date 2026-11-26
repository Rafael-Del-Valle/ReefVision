# ReefVision 1.6 — saved QC queue creator ownership

**Status:** development-only; not Windows installer or biological acceptance.

## Audited overlap and gap

The existing 1.0–1.5 Workflow Builder already persists typed graph runs,
artifact checksums, project-source provenance and human-review gates. Version
1.6 adds an executable `qc_review_queue` node using the same standalone
`ReviewQueueService`. This change does not create a new QC algorithm, schema
or workflow node.

The saved QC adapter uses `created_by=workflow:<run-id>:<node-run-id>` to
recover exactly one historical scientific queue on retry. Two public queue
creation routes previously accepted an arbitrary `created_by`, including
this internal namespace. Separately, the public regeneration endpoint copied
the original workflow queue's `created_by` into the new snapshot, producing
two queues with the same owner and making subsequent saved workflow retries
fail as ambiguous. This was a reproducible code-path defect, independent of
the unresolved cross-worker creation race.

## Bounded fix

- Both standalone project and dataset-version queue creation endpoints now
  reject a supplied creator whose trimmed, case-insensitive prefix is
  `workflow:` (HTTP 422), before any queue is created.
- The internal saved Workflow Builder adapter retains its exact owner identity.
  Ordinary standalone researcher labels remain permitted.
- Regenerating a workflow-owned queue now uses the local manual creator label
  `local_user` and preserves the source through
  `regenerated_from_queue_id`. Non-workflow regeneration retains its prior
  creator behavior.
- Saved workflow replay continues to select only its original queue, leaving
  scientific evidence, review comments, assignments, and researcher approval
  untouched. Regeneration is a distinct historical snapshot, not a retry.

## Regression and acceptance

`test_workflow_queue_creator_namespace_16.py` covers public owner spoofing
for both API routes, benign standalone creation, a real persisted
`project_source -> qc_review_queue` graph, manual reviewer comment,
regeneration lineage, exact-owner saved replay, typed dimensionless output,
and preservation of unverified annotations.

This does **not** authenticate local actor labels or retroactively repair
previously duplicated queue ownership. It does **not** establish database
atomicity for concurrent workflow workers. The independent 1.1/1.6 Alembic
revision-0038 conflict, exact-head CI, native Windows MSI upgrade/rollback,
installed GUI and representative biological-data validation remain release
blockers. No merge, tag, deployment or pretrained model download is authorized.

## Manual regeneration scientific configuration gate — 2026-11-26

Manual regeneration now refuses non-object configuration/checksum JSON and
translates invalid persisted scoring parameters into a domain validation
error rather than an uncontrolled server exception. Versioned source queues
must pass the same immutable scientific snapshot validation as saved workflow
replay before generating a new queue. A missing weight vector, omitted v3
threshold, or inconsistent QC source cannot silently become a default or
different scientific configuration. Legacy unversioned snapshots retain their
previous default behavior when the configuration is a valid object and its
parameters validate.

Five standalone corruption/refusal/recovery cases and an additional persisted
workflow regeneration refusal exercise preservation of the original queue,
review state, lineage, exact replay and reviewer comments. This is an existing
QC operation, not a new node or approval mechanism. The original scientific
evidence and dimensionless typed workflow output remain unchanged. Local
isolated Pydantic/configuration probes reproduced the unsafe paths; full
repository tests and exact-head CI are unverified. Integrated migration
reconciliation, representative biological acceptance and genuine installed
Windows MSI/GUI validation remain release blockers.

## Regeneration after integrity marker loss — 2026-11-26

A missing integrity version marker alone no longer opts a manual regeneration
out of saved scientific validation: the presence of either independent digest
also invokes the existing immutable snapshot validator. A workflow-owned queue
must pass that validator even if its checksum map is empty, matching the
saved-node replay gate. No source observations, priority formula, reviewer
history or typed workflow artifacts are changed. Valid unversioned standalone
queues with matching historical digests remain supported, as do older
standalone queues with neither optional digest. This is an accidental
corruption guard, not cryptographic authentication of arbitrary database
rewrites; the latter legacy case cannot establish a missing version's origin.

Three additional standalone refusal cases, two historical compatibility
controls and two additional persisted workflow regeneration scenarios cover
marker loss, digest corruption, missing workflow checksums, restored original
queue replay and retained pending human review. Nineteen isolated SQLite JSON
guard/digest probes passed; these are not full repository tests. GitHub
checkout remains blocked by DNS and exact-head CI is unverified. The
independent integrated migration, representative biological workflow and
native Windows installed-GUI/MSI acceptance gates remain HOLD.
