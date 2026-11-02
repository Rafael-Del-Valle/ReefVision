# ReefVision 1.6 — frozen QC temporal ranking boundary

Dataset-version items preserve image/annotation evidence, experimental grouping,
and annotation review status, but **do not preserve per-image import/edit
timestamps**. Before this change, version-scoped review queues used the current
`ImageAsset.created_at` and `updated_at` for the `recent_import` and
`stale_review_state` ranking signals. A later edit to live metadata could
therefore change a frozen dataset's review priority and item evidence checksum,
even when its scientific snapshot was unchanged.

For **new** version-scoped queues, both temporal signals now contribute zero.
This means **unavailable**, not "scientifically established to be old" or
"researcher reviewed." The other version-scoped signals continue to use the
frozen QC context, and all project-scoped queues retain their existing
live-image timestamp ranking behavior. Existing persisted queues, reviewer
decisions, input checksums and Workflow Builder outputs are never rewritten.

A regression changes only a live image's import timestamp after creating a
reviewed octocoral dataset version. It asserts that a fresh version-scoped
queue has identical score, signals and evidence checksum; a fresh project
queue and executable saved `project_source → qc_review_queue` graph reflect
the changed live timestamp; and the historical workflow queue remains
checksum-valid, pending explicit researcher review.

**Limitations:** the schema currently lacks immutable per-image timestamps in
dataset-version items. Adding scientifically meaningful frozen temporal
signals requires a future backward-compatible versioned snapshot schema,
not substituting current mutable timestamps or silently inferring biological
sampling times from file import times. The saved Workflow Builder QC node
continues to accept a project reference; no dataset-version workflow input is
claimed. No Windows installed-GUI, representative biological study, or
cross-version migration acceptance is implied by this regression.
