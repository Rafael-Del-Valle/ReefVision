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
