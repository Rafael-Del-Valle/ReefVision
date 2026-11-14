# ReefVision 1.6 — Preserve saved QC workflow evidence during class reassignment

## Existing capability and verified gap

The existing executable, typed `project_source -> qc_review_queue` Workflow Builder
stores a checksummed biological review snapshot that remains evidence while a
researcher decides whether to accept the underlying observations. Class Manager
**Merge** already protects workflow-owned queue items, including pending ones.
The separate **Reassign** and **Reassign-and-Delete** services previously
classified *all* pending/in-progress queue items as mutable. Reassignment
therefore silently changed class IDs inside an already-saved workflow result;
retrying the persisted QC node would fail evidence-integrity validation.

## Bounded change

- Read queue ownership from the persisted, same-project `ReviewQueue.created_by`
  value using the existing `workflow:<run>:<node>` convention.
- Exclude workflow-owned review items, regardless of review state, from the
  approved mutable list; include them among protected references and surface a
  researcher-facing warning.
- Include each referenced queue ID and creator in the preview evidence digest.
  An ownership change between preview and execution now fails HTTP 409 before
  any scientific writes. Under the SQLite claim's writer lock, mutation uses
  only record IDs from the freshly validated mutable plan.
- Reassign-and-Delete now **blocks physical deletion** when a workflow-owned
  review item retains the source class. Never erase its required biological
  class definition while the saved scientific artifact still references it.
- Standalone pending/in-progress review items retain previous reassignment
  behavior; completed standalone reviews, frozen datasets, registered model
  class maps and researcher decisions are not silently relabeled.
- No new migration, dataset rewrite, workflow node, cloud dependency,
  external pretrained weights, or automatic researcher approval.

## Regression contract

`test_class_reassignment_preserves_executable_saved_qc_evidence` executes and
persists a real typed Workflow Builder graph, checks dimensionless priority
scores and the explicit `requires_researcher_review` gate, then tests both
class operations. Reassign must transfer eligible standalone records without
altering the saved QC class IDs. Reassign-and-Delete must fail closed while
preserving the source class. Both paths retry the actual saved QC node adapter
and require matching original checksummed payloads.

`test_reassignment_preview_rejects_review_queue_ownership_drift` changes the
queue creator under the same record IDs after preview and asserts HTTP 409,
with no annotation or review-item mutations.

## Release limits

The change needs exact-head backend lint, type, database tests, migrations and
frontend build/E2E checks, representative biological datasets, independent
cross-branch Alembic-0038 reconciliation, and native Windows MSI/CAB and
installed-GUI acceptance. It does **not** establish release readiness.
