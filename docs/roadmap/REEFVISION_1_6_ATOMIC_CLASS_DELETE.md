# ReefVision 1.6 — atomic unused-class deletion

## Audit and implementation

Class Manager already requires an explicit, consistent usage response before
offering **Delete unused**. The API independently checks all supported
scientific references, but previously read them before acquiring a SQLite
writer lock. Another local editor could add a biological observation between
the usage decision and deletion, despite the earlier UI confirmation.

The class DELETE service now performs a revision-preserving no-op UPDATE on
the source class **before** its authoritative reference check, retaining the
SQLite write lock through class deletion and commit. Existing 404 for missing
classes and HTTP 409 for referenced classes remain unchanged. It does not
rewrite original images, annotation history, immutable datasets, registered
model maps, visibility preferences or saved research workflows.

## Regression

The file-backed `test_unused_class_delete_locks_scientific_reference_recheck`
creates an image without biological annotations, attempts to insert a class
reference through an independent connection *during* the usage check, requires
a bounded writer-block outcome, verifies the source class and attempted
annotation are absent but the original image survives, and checks another
class write succeeds after commit. Existing referenced-class deletion and
Class Manager evidence-consistency tests retain their separate obligations.

This is a local class-management safety fix, not new scientific analysis.
Existing typed executable `project_source → qc_review_queue` saved graphs,
dimensionless QC scores, immutable evidence, researcher review gates and
node retries are preserved. A destructive-delete workflow node is deliberately
not introduced; deliberate researcher confirmation remains required.

## Limits / release hold

The atomicity relies on the local SQLite transaction model; do not interpret
it as cloud cross-service serialization. Verify the new test in exact-head
backend CI and recheck Ruff, mypy, frontend/E2E and migrations. Independent
1.1/1.6 Alembic-0038 reconciliation, representative biological acceptance,
Windows MSI/CAB clean install/upgrade/rollback, installed-GUI validation and
explicit scientist approval remain mandatory. This is not release approval.
