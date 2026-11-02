# ReefVision 1.6 — explicit QC confidence-selection provenance

The existing standalone review-queue service always records
`review_below_confidence` in a newly generated v3 queue's scoring
configuration. The value is `null` when no confidence filter was requested.
An omitted key is **not** an equivalent persisted research selection.

The executable saved `project_source -> dataset_version_source ->
qc_review_queue` graph reuses the original immutable queue on retries.
A previously re-signed v3 queue could omit the confidence-selection key:
`dict.get()` treated it as `null` during preliminary validation, and the
per-item replay check then indexed the absent key directly, causing a
`KeyError` rather than a controlled integrity rejection. Empty queues
could even pass without ever evaluating the absent field.

The v3 snapshot validator now requires explicit key presence before examining
saved items. It raises the existing `ValidationError` without rescoring live
annotations, replacing the queue, or changing researcher review decisions.
Historical v2 and unversioned queues retain their existing optional-key
compatibility contract; no migration is necessary.

Regression tests cover a re-signed v3 snapshot, historical v2 compatibility,
and a real persisted frozen-dataset Workflow Builder run with typed
`review_queue_reference` output, dimensionless priority units and explicit
`requires_researcher_review` status. The workflow test also rejects an
omitted QC ruleset, then rolls back and replays the original queue without
changing its item identity or evidence checksum.

This is a local scientific provenance and reliable-retry guard, **not**
biological ground-truth verification. Full exact-head CI, representative
biological-data review, independent 1.1/1.6 Alembic revision-0038 reconciliation,
Windows MSI/CAB upgrade/rollback and installed-GUI validation remain required
before any 1.6 release approval. No pretrained weights, paid services,
cross-version merges or research-asset mutations are involved.
