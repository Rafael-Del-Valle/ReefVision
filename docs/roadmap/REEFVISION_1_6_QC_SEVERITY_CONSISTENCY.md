# ReefVision 1.6 — Saved QC severity consistency (development)

## Existing implementation and gap

This change extends the existing versioned `qc_review_queue` evidence validator and
executable Workflow Builder adapter. It does **not** introduce another review
queue, scoring algorithm, QC severity rule, workflow runtime, migration, or
automated biological verification. The 1.0–1.5 class management, project and
per-user visibility, review, workflow provenance and typed artifact contracts
remain in place on their own branches.

A generated v3 review item records the same unresolved QC issues in three
places: canonical `related_issue_ids_json`, `highest_qc_severity`, and the
dimensionless `unresolved_qc_severity` scoring signal. The generator uses
`info=0.3`, `warning=0.6`, and `error=1.0`. Previously, a persisted
snapshot could be modified and re-signed to contradict these fields while
retaining otherwise valid scoring digests.

## Implementation and scientific contract

For **v3** saved queues only, require an empty issue list, absent highest
severity and raw severity 0.0 together, or a nonempty issue list and a
recognized severity with its exact frozen score. This is an internal
consistency check on immutable saved evidence, not a lookup against mutable
live QC records. Keep the score unit dimensionless. Reject a mismatched,
re-signed snapshot before saved Workflow Builder replay; do not rewrite
reviewer comments, assignments, completion, source observations, or annotations.

Version 2 and unversioned historical queues retain their prior compatibility
contract. The test fixture checks that the frozen v3 map still equals the
existing QC generator map; future formula changes must use a new integrity
version rather than silently reinterpreting saved scientific evidence.

## Verification and release boundary

- Standalone validator: valid v3 snapshot and four re-signed contradictions,
  including missing issues, missing severity, mismatched severity and raw
  scoring inconsistency. Historical v2 regression remains.
- Saved graph: persisted `project_source -> qc_review_queue` rejects an
  invented QC issue with a re-signed item digest after researcher completion,
  preserves review state, and safely replays after evidence restoration.
- Automated tests and full CI are **required** on the exact new branch head.
  Native Windows MSI upgrade/rollback, installed GUI, representative
  biological data and independent 1.1/1.6 Alembic 0038 reconciliation remain
  separate release blockers.

No model downloads, automatic review approval, hosting, branch merging,
release publishing or deletion of research assets are authorized.
