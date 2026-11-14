# ReefVision 1.6 — immutable historical review semantics during class merge

## Audited gap

The preexisting **Merge class** API archived the source class but rewrote **all**
prediction proposals, quality-control issues, and review-queue items, regardless
of whether researchers had accepted, dismissed or completed them. This diverged
from the already implemented 1.6 **Reassign** contract, which migrates pending
predictions, open/acknowledged QC, and pending/in-progress review items only.
The difference could silently reclassify accepted model observations, closed QC
findings, and completed reviewer decisions after their original scientific review.

## Bounded implementation

- Merge still transfers active bounding-box annotations and creates append-only
  `class_merged` annotation events. It archives rather than hard-deletes its
  source class.
- Only `pending` prediction proposals are moved. Accepted/rejected/historical
  proposals retain their source class, status, and recorded model evidence.
- Only `open` or `acknowledged` QC issue class memberships are changed.
  Closed, dismissed, or other nonmutable QC issues remain unchanged.
- Only `pending` or `in_progress` review queue item class memberships
  are changed. Completed or otherwise protected review items remain unchanged.
- Response affected counts report **actual changes** instead of counting
  protected items. A warning names which classes of historical scientific
  records remain attached to the archived source class.
- Exact source usage counts, reference fingerprint and reviewed source/target
  biological identities continue to gate merges. Masks and image labels are
  still unsupported and block a merge. Historical frozen dataset versions,
  local registered model class maps and deleted annotations stay untouched.

## Tests and Workflow Builder implications

The database-backed `test_merge_preserves_accepted_predictions_and_completed_qc_history`
uses the established mixed mutable/historical fixture. It checks reviewed
merge approval, transferred counts, each protected and mutable modality,
frozen class maps and researcher-facing preservation warnings.

This change is class-administration behavior, **not a new scientific analysis**;
adding a duplicate Workflow Builder node would be misleading. The existing
executable typed saved `project_source -> qc_review_queue` regression,
its dimensionless priority output, persisted run provenance, review gates,
and retry/integrity tests remain required for release. This change does **not**
establish that every mutable QC item can safely be edited when referenced by
an immutable saved workflow; that relationship needs separate lineage-aware
regression and, if necessary, an additional fail-closed guard before approval.

## Release hold

This is a development increment, not biological acceptance. Complete exact-head
backend lint/type/pytest/migration and frontend unit/E2E/build verification,
representative biological and saved-workflow acceptance, independent 1.1/1.6
Alembic-0038 reconciliation, Windows MSI/CAB clean install/upgrade/rollback
and installed-GUI validation before any release. No model download, automatic
research approval, branch merge, deployment, or research-asset deletion.
