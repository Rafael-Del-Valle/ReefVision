# ReefVision 1.6 — QC source-finding scope and severity gate

## Audit and nonduplicate scope

Quality-control runs, independently verified image annotations, review queues,
and typed executable Workflow Builder QC nodes already exist in earlier
ReefVision releases and on the isolated 1.6 branch. This increment does
not introduce a new QC engine, annotation data type, workflow node, or schema.

A locally restored or externally modified active QC finding can retain its
original completed run ID while carrying another project's ID, a different
dataset-version scope, an out-of-scope image ID, or a severity absent from
the QC scoring contract. The former review-queue generator silently
interpreted unknown severity as zero using the lookup fallback, or
attributed mismatched findings to the wrong biological study.

## Implementation and scientific semantics

Before inserting **new** queue records, 1.6 compares **all** source findings
against the QC run's persisted issue count and selected rule IDs. This
detects removed or reattributed findings even if they were dismissed or
project-wide. It then validates source findings against the selected project,
dataset version, image inventory and severity scores (info, warning, error). A
mismatch raises a user-visible, generic validation error without exposing
confidential finding text. Dismissed or otherwise non-active findings and
run-wide findings with no image ID are not ranked as image-specific evidence.

Standalone review queues and saved executable `project_source ->
qc_review_queue` graphs call the same service. Saved graphs retain typed,
checksummed, dimensionless priority outputs, failure diagnostics and
explicit `requires_researcher_review` status. Failed runs must leave no
forged review-queue output. Correcting the source and explicitly starting
another run can produce a fresh, pending review queue.

No historical snapshots, investigator decisions, annotations, original
images, model weights or prior migrations are changed. This is a
scientific **consistency check**, not automated biological verification.

## Regression and remaining acceptance

`test_review_queue_qc_source_finding_scope_16.py` checks invalid
severity, mismatched study identity, unselected rule attribution and altered
run-level issue counts against both the standalone API
and persisted, executable saved graphs, ensures writes are atomic,
and tests an explicit correction/recovery while historical review
evidence remains intact.

Release remains on hold for independent Alembic 0038 reconciliation
across 1.1/1.6, exact-head backend/frontend/E2E CI, real biological
acceptance, Windows MSI/CAB installation and upgrade/rollback, installed
GUI validation and explicit researcher approval.
