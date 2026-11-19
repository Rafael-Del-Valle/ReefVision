# ReefVision 1.6 — executable frozen-dataset QC workflows

The existing `qc_review_queue` Workflow Builder node now accepts an **optional typed
`dataset_version` input**, in addition to the required project reference.
Connect `project_source.project` to both `dataset_version_source.project`
and `qc_review_queue.project`, then connect `dataset_version_source.dataset`
to `qc_review_queue.dataset`. The source must have **no split filter**:
a split-filtered source cannot be represented as a whole-version queue.

Without the optional dataset edge, existing project-scoped saved graphs and
output payloads are unchanged. With it, the node calls the existing
`ReviewQueueService.create_queue_for_dataset_version` (also used by the
standalone dataset-version QC API). The immutable version's project, completion
status and manifest digest must match the checksummed source artifact. The
artifact must originate from a succeeded dataset-version source in the same
persisted run, on the correct typed port, and be bound to the QC consumer.
The output includes the dataset-version ID and manifest digest, retains a
**dimensionless** priority-score unit and always requires explicit researcher
review. It does not verify model detections or biological observations.

Existing workflow-run/node ownership, persisted artifact digests, retries,
immutable queue snapshots and manual review histories are reused. A re-signed
substitute manifest fails closed rather than generating a replacement queue.
A saved graph can be run again to create a new independent QC review queue
without overwriting an earlier researcher's decisions.

Regression coverage checks the standalone API against a saved executable
`project_source → dataset_version_source → qc_review_queue` graph, confirms
that later live annotation geometry changes do not affect frozen QC evidence,
and rejects a re-signed forged dataset manifest on replay.

**Limitations:** version-scoped queues currently omit live predictions and
temporal signals not preserved by the immutable dataset-version schema.
An optional version input is **not** a per-split queue; those need an explicit
separate scientific scope contract. Existing dataset-version manifests are
trusted as stored metadata, not freshly rehashed on-disk image bytes.
Native Windows MSI upgrade/rollback, installed-GUI validation, representative
biological-data acceptance and independent 1.1/1.6 Alembic revision-0038
reconciliation remain release blockers. No pretrained weights, network service,
automatic scientific approvals or research-data rewrites are introduced.

## Frozen study group and numeric class identity gate (1.6)

Dataset-version QC verifies the original producer's split contract before
creating a standalone queue or executing a saved typed Workflow Builder graph.
Allowed split labels are `train`, `validation`, `test`, and `unassigned`.
A non-null biological `group_key` denotes related images (for example,
tiles from one coral colony) that **must all belong to the same split**.
Ungrouped images remain independent. This prevents a re-signed local frozen
manifest from presenting study replicates across training and test sets after
the original group-aware split assignment. The frozen class dictionary also
requires unique, nonnegative integer indices so distinct taxa cannot silently
share a YOLO export index. Both tests inspect stored metadata; they do not
reauthenticate file bytes or infer a missing colony/group identity.

The original 0006 and mask-aware 0007 producers, existing saved typed
`dataset_version_source → qc_review_queue` graph, persisted artifact digests,
researcher approval gate, and read-only failure/rollback behavior are reused.
No migration, class renumbering, automatic model weight download, or new
workflow node is introduced. New synthetic and disposable database tests
cover valid ungrouped controls, recomputed-checksum group leakage and class
index collisions, standalone QC refusal and saved graph refusal/retry.


## Source-image fingerprint gate for empty biological observations (1.6)

A dataset can legitimately contain reviewed images with **zero detections and
zero masks**. Earlier checks of detection or mask geometry did not validate
those images' source dimensions and digest format. The shared read-only QC
validator now requires a lowercase 64-character hexadecimal source-image
SHA-256 and strictly positive integer source dimensions for **every** 0006 or
0007 frozen item, including observation-free images. Invalid source metadata
cannot be made QC-eligible by recomputing the nested item and manifest hashes.

Synthetic two-schema tests cover valid empty-image controls and seven fully
rehashed source-metadata corruptions; database-backed tests cover both the
standalone review-queue API and persisted executable typed Workflow Builder
with original provenance, rollback, replay, and researcher-approval gates.
This checks only recorded metadata; it **does not** read, repair, or rehash the
original image bytes, authenticate local SHA-256 claims, or approve research.
