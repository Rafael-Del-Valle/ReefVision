# ReefVision 1.6 — frozen QC split membership on saved Workflow Builder replay

The existing executable `project_source → dataset_version_source → qc_review_queue` graph emits a typed, persisted, dimensionless review-priority artifact that requires researcher approval. The frozen dataset source already verifies its manifest, image membership, counts, and typed producer outputs.

## Gap and change

A completed queue's own evidence SHA-256 and summary can be recalculated after changing an item's `split`, making internally consistent but scientifically false training/validation/test provenance. During saved-node replay, each existing frozen QC item is now checked against the persisted `DatasetVersionItem` image-to-split map, after the source manifest and producer checks. Selected/filtered QC queues may contain a subset, but no foreign image or reassigned split. Project-scoped queues and historical queue data are not modified. No new workflow node or migration.

## Regression and limits

The saved executable graph regression first confirms idempotent replay, then changes an item's split, re-signs its evidence digest, split summary and output-artifact payload, and requires fail-closed rejection. A rollback must restore the original queue, output and pending human review. Standalone frozen QC scoring parity remains covered by existing tests.

This is a consistency check against locally persisted frozen version records, not an independent cryptographic signature or validation of taxonomic identity. Release remains blocked by exact-head CI, representative biological acceptance, the independent 1.1/1.6 Alembic 0038 conflict, and physical Windows MSI upgrade/rollback and installed-GUI checks.
