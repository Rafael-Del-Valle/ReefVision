# ReefVision 1.6 — frozen QC manifest and count reconciliation

## Scope and scientific rationale

The existing executable saved Workflow Builder graph `project_source → dataset_version_source → qc_review_queue` consumes a typed dataset-version artifact and a typed image collection. The artifact checksum is necessary but not sufficient: a database row and its producer artifact could both be edited and re-signed to agree on incorrect biological image or annotation totals. A frozen manifest body could also change without updating its original digest.

The 1.6 QC replay adapter now rejects saved runs when:

- The persisted dataset manifest JSON no longer hashes to the stored manifest SHA-256.
- The manifest summary disagrees with the version row's image or annotation count.
- The version row's image, annotation, or mask-annotation total disagrees with the independently persisted frozen per-image membership records.
- A frozen per-image annotation count disagrees with its saved annotation snapshot length (including mask annotations).

These checks operate on persisted frozen evidence, not later live annotations or model predictions. They do not edit existing reviewer decisions, assign biological truth, or download models. Existing typed ports, dimensionless QC priority scores, human review gate, workflow run provenance and deterministic retry behavior remain unchanged. No migration or new Workflow Builder node is introduced.

## Regression contract

`test_workflow_review_queue_dataset_lineage_16.py` exercises a real saved, executed graph and deliberately tampers with the manifest body, re-signs dataset producer counts to match corrupted version totals, or alters frozen per-image counts. Each case must fail closed with `ValidationError`, roll back, and replay the original immutable queue without changing pending researcher-review items. Existing standalone-versus-saved QC parity and dataset producer lineage tests remain applicable.

## Boundaries and acceptance

This verifies internal consistency, not the external authenticity of a deliberately re-signed entire dataset database or the scientific accuracy of an annotator. Independent validation on representative biological datasets is still required. Version 1.6 remains **release HOLD** until exact-head CI, 1.1/1.6 Alembic revision-0038 reconciliation, Windows MSI/CAB upgrade/rollback, installed-GUI testing, and full scientific acceptance are completed. No merges or releases are authorized.
