# ReefVision 1.6 — frozen QC dataset metadata lineage

## Scope and existing functionality

The existing offline `dataset_version_source` emits two typed, checksummed artifacts:
`dataset_version` metadata and an `image_collection`. The existing executable
`qc_review_queue` node consumes the dataset reference and preserves its
researcher-review gate, dimensionless ranking scores, persisted graph/run,
immutable queue evidence and idempotent retry behavior. This change does not
create a duplicate workflow node or change a database migration.

## Integrity contract

A saved-workflow replay now checks the dataset reference's version number,
resolved split method, per-split image counts, total image count, annotation
count and mask annotation count against the persisted complete
`DatasetVersion` and its `DatasetVersionItem` rows. The existing checks for
the exact two producer outputs, same-project ownership, manifest digest,
unfiltered dataset, producer parameters and frozen image IDs remain required.

A matching artifact SHA-256 alone is not sufficient: a modified metadata
payload could be re-signed while contradicting the actual frozen version.
Rejecting these contradictions prevents a saved review workflow from
presenting fabricated dataset statistics as provenance. No live annotations
or model predictions are consulted, and historical reviewer decisions are
not rewritten. Existing project-scoped QC remains unchanged.

## Regression and release limitations

`test_workflow_review_queue_dataset_lineage_16.py` executes a real saved
`project_source -> dataset_version_source -> qc_review_queue` workflow.
It verifies the valid producer contract, rejects re-signed mutations of
each scientific metadata field (including absent split counts and boolean
image counts), rolls back the attempted corruption, replays the original
immutable queue and checks that the human review state is preserved.

Run backend Ruff/format/mypy/pytest, frontend and workflow E2E, migrations
and Windows MSI/installed-GUI acceptance before claiming release readiness.
The independent 1.1/1.6 Alembic revision-0038 collision still requires
coordination; do not merge version branches or silently rewrite migrations.
Representative real biological datasets and Windows upgrade/rollback
acceptance are separate outstanding gates.

## Ordered image provenance and strict count types (2026-11-02)

A valid saved `dataset_version_source` image collection is ordered by
`DatasetVersionItem.id`. Re-signing the collection with the same image IDs
in a different order is not an exact replay of its persisted producer output.
The QC adapter now verifies this canonical order, not only set equality.
The per-split counts must also be genuine nonnegative Python integers:
`True` and `1.0` must not silently pass as the integer `1`.

The executable saved-workflow regression includes a two-image permutation
and re-signed boolean/float split-count substitutions, then checks rollback,
original immutable queue replay and unchanged pending researcher review.
This is metadata integrity validation, not an inference that any annotation
or prediction has been biologically verified. The earlier 1.1 migration
coordination and Windows installed-GUI acceptance gates remain open.


## Completed QC node output-binding integrity (2026-11-02)

A saved QC node marked `succeeded` with an existing workflow-owned
review queue must retain its persisted output artifact ID. Previously an
empty `output_artifact_ids_json` list bypassed the saved output
payload/checksum/binding checks, even though the node was complete.
The adapter now fails closed with `ValidationError` if that output
binding is missing. Nodes still running after an interrupted creation
may legitimately have no output yet and can use the existing deterministic
retry path; no historical queue or researcher decision is rewritten.

The regression executes a real frozen-dataset saved graph, removes only
the completed QC node's output binding in a transaction, verifies that
replay fails, rolls back, and verifies exact replay of the original
dimensionless, researcher-review-gated queue with all pending items
unchanged. The preceding multi-image parity test also received the exact
Ruff formatting corrections from CI run 41475202931. Full exact-head CI,
1.1/1.6 migration reconciliation, biological acceptance and native
Windows installer/installed-GUI checks remain release blockers.

## Completed QC orphaned-queue replay guard (2026-11-02)

The completed-node guard also rejects the case where **both** the saved
output binding and its workflow-owned review queue disappear. Previously the
missing queue prevented the binding-only guard from running, and the adapter
could create replacement QC evidence for an already-succeeded workflow node.
A completed node now fails closed before queue creation when either record is
missing. Only unfinished nodes retain their deterministic recovery path.

The saved frozen-dataset Workflow Builder regression runs both corruption
cases inside rollback-only transactions, then replays the original typed,
dimensionless, researcher-review-gated output and compares the original
pending review items. It does not modify historical researcher decisions or
live study assets. This is a provenance/retry safety check, not evidence of
biological correctness or installed Windows acceptance. CI and migration
lineage reconciliation remain required before release.
