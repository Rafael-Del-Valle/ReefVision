# ReefVision 1.6 — saved frozen QC dataset-source contract

## Scope audit and failure

The existing executable `dataset_version_source` node produces **two** typed
artifacts, in order: `dataset` (`dataset_version`) and `images`
(`image_collection`). The existing `qc_review_queue` adapter incorrectly
required the dataset producer to have exactly **one** output, so otherwise
valid saved `project_source → dataset_version_source → qc_review_queue`
graphs could fail before producing their researcher-review queue. This is a
compatibility defect in an existing Workflow Builder integration, not a new
modality or a reason to introduce another node.

CI run 41422583266 at 5c535f63 showed 11 backend failures (1609 passed,
32 skipped), including frozen QC saved-workflow execution. The frontend job
passed. One separate failure expected a later snapshot-integrity exception
when the replay's earlier saved-weight guard correctly failed first.

## Fixed execution and integrity contract

A saved frozen QC node now requires the dataset producer's **exact**
persisted two-output binding, validates the dataset and image artifact types,
ports, producer/run identity and JSON checksums, and compares the image
collection's IDs against the immutable `DatasetVersionItem` records. It
rejects missing, reordered, substituted, extra or re-signed contradictory
outputs; a dataset must be complete, same-project and unfiltered.

The node still consumes the typed dataset port and uses the existing
standalone `ReviewQueueService` for QC creation. Its persisted graph/run,
provenance, dimensionless priority scores, immutable scientific evidence,
idempotent retry and mandatory researcher-review gates remain unchanged.
No migration, new node, pretrained weights or external network service
is introduced. Historical queue records and researcher decisions are not
rewritten.

## Regression and limitations

`test_workflow_review_queue_frozen_dataset_16.py` exercises a real saved
workflow against standalone frozen dataset QC. The lineage test additionally
covers valid two-output binding, extra/missing/reordered outputs, re-signed
manifest and image-ID substitutions, plus rollback and reviewer-state
preservation. The prior scientific signal test now checks both the direct
snapshot-integrity rejection and the earlier replay-weight rejection.

This check compares stored artifact hashes and frozen database records;
it does **not** rehash original image files from disk or establish biological
ground truth. Windows installed-GUI/MSI upgrade/rollback, representative
biological acceptance, full CI and independent 1.1/1.6 Alembic 0038
reconciliation remain release gates. **Version 1.6 is not release-ready.**
