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
