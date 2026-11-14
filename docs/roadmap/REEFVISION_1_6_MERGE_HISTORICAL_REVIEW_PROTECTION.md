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
- Standalone `pending` or `in_progress` review-queue items retain the
  legacy class-reassignment behavior. **Workflow-owned QC queue items remain
  unchanged regardless of review state**, because their biological class IDs
  are immutable input evidence bound to an executable saved graph. Workflow
  ownership is the locally persisted `workflow:<run>:<node>` creator key,
  rather than the current review state. Completed or otherwise protected
  standalone review items also remain unchanged.
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

`test_saved_qc_workflow_class_evidence_survives_merge` executes an actual
persisted typed `project_source -> qc_review_queue` graph with both pending
and researcher-completed review states. It verifies dimensionless priority
scores, the required researcher-review gate, unchanged historical class IDs
and the saved run's original typed payload and SHA-256. The test replays the
real persisted QC node adapter after merge; this is stronger than inspecting
a fabricated graph JSON fixture.

This change is class-administration behavior, **not a new scientific analysis**;
adding a duplicate Workflow Builder node would be misleading. The executable
typed saved `project_source -> qc_review_queue` regression now also runs
for an **unreviewed/pending** item, and directly retries the actual persisted
QC node adapter after merge. Both pending and completed cases require the
same queue ID, source-class biological reference, dimensionless priority output,
unchanged saved artifact and a valid replay checksum. The review gate remains
`requires_researcher_review` until a researcher explicitly confirms it.

This protection does not relabel historical scientific evidence, infer that an
archived source taxon became a target taxon, or automatically approve research.
Standalone QC snapshots and the separately implemented Reassign operation
still need their own provenance-aware integrity acceptance; no migration or
cross-version branch integration is introduced.

## Release hold

This is a development increment, not biological acceptance. Complete exact-head
backend lint/type/pytest/migration and frontend unit/E2E/build verification,
representative biological and saved-workflow acceptance, independent 1.1/1.6
Alembic-0038 reconciliation, Windows MSI/CAB clean install/upgrade/rollback
and installed-GUI validation before any release. No model download, automatic
research approval, branch merge, deployment, or research-asset deletion.
