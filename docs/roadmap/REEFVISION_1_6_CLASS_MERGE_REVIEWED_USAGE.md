# ReefVision 1.6 — reviewed class merge count guard

The legacy **Merge class** action can reassign active annotations, inference
proposals, and mutable QC records while archiving its source. It does not
rewrite preserved historical annotations, immutable dataset versions, or
registered model mappings. Researchers must inspect current source-class
usage before they approve a merge.

## Guard added

- The GUI requires an explicit **Usage** inspection, one verified project/class
  response, eight unique canonical reference categories, correct
  mutable/immutable flags, and internally consistent totals.
- The confirmation displays total and immutable reference counts.
- The approved request carries a snapshot of all eight reference-category
  counts. The backend recomputes counts before any class mutation and returns
  HTTP 409 if any count changed. No merge writes occur on that mismatch.
- A failed/pending/refetching/hidden usage inspection cannot authorize the
  GUI Merge action. Preexisting local scripts without
  `expected_usage_counts` remain compatible.
- This protects **count drift**, not changes to record identity with exactly
  the same category counts. The existing server validations, append-only
  annotation event creation, and researcher QC workflows remain authoritative.
  A future version should offer a revisioned, full-identity merge preview for
  legacy API callers.

The change is class-administration safety, not a new scientific analysis.
No duplicate Workflow Builder node, migration, model checkpoint, remote
service, or alteration to saved QC graph/runs is introduced. The executable
saved QC Workflow Builder regression suite must remain green.

## Verification and release limits

Backend regression: stale reviewed counts reject with 409 and preserve source
annotation/class/QC references; matching counts permit the existing merge.
Legacy request contract remains covered. Frontend regressions: merging is
disabled before an inspected usage response and for incomplete evidence; valid
zero/nonzero reviewed source counts travel into the merge request.

Full exact-head CI, representative biological-data and saved-workflow
acceptance, Alembic 0038 cross-version reconciliation, Windows MSI/CAB
upgrade/rollback, and installed-GUI confirmation remain release blockers.
