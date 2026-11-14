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
- The approved request carries all eight reference-category counts and a
  SHA-256 fingerprint of the sorted, category-scoped source record IDs. The
  backend recomputes the inventory before any merge and rejects count drift
  **or equal-count identity swaps** with HTTP 409 before class mutations.
  The usage API exposes the digest, not raw record identities.
- A failed/pending/refetching/hidden usage inspection cannot authorize the
  GUI Merge action. Preexisting local scripts without
  `expected_usage_counts` remain compatible.
- This protects **record-identity drift** even when the category counts are
  unchanged. It does not fingerprint edits to content under identical record
  IDs or lock the inventory against concurrent writes between check and commit.
  Legacy scripts may omit both optional approvals for compatibility; scripts
  requiring stronger safeguards should provide both reviewed values. Existing
  append-only event and researcher-review workflows remain authoritative.

The change is class-administration safety, not a new scientific analysis.
No duplicate Workflow Builder node, migration, model checkpoint, remote
service, or alteration to saved QC graph/runs is introduced. The executable
saved QC Workflow Builder regression suite must remain green.

## Verification and release limits

Backend regression: stale counts and equal-count record-ID replacement both
reject with 409 before writes; restoration of the reviewed inventory allows
normal merge and preserves annotation/QC historical behavior.
Legacy request contract remains covered. Frontend regressions: merging is
disabled without an inspected report, complete count breakdown and a valid
64-character identity digest; valid zero/nonzero source counts and digest both
travel with the reviewed merge request.

Full exact-head CI, representative biological-data and saved-workflow
acceptance, Alembic 0038 cross-version reconciliation, Windows MSI/CAB
upgrade/rollback, and installed-GUI confirmation remain release blockers.
