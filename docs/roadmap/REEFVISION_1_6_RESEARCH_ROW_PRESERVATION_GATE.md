# ReefVision 1.6 — research row-preservation gate for migration copies

**Status: development validation, not release approval.** Track D, draft PR #77 and master issue #76. This is a content-level companion to the existing structural read-only checks in scripts/inspect_sqlite_lineage_16.py and scripts/inspect-alembic-lineage.py, not another migrator, class/QC service, or Workflow Builder node.

## Reason for the gate

A schema fingerprint, a valid Alembic stamp, passing SQLite integrity checks and a green workflow CI do **not** prove that a 1.1 → 1.6 migration preserved original biological observations, reviewed annotations, user visibility, append-only reviewer events, or persisted executable Workflow Builder graphs and artifacts. A migration could delete, insert, or silently overwrite rows while leaving its DDL unchanged.

The independent, standard-library CLI scripts/verify-research-row-preservation-16.py accepts **two different, offline, disposable SQLite copies**: the original before migration and the same dataset after a candidate migration. It opens both read-only (mode=ro, query_only=ON), pins SQLite read transactions, checks database and FK integrity, and rejects observed WAL/SHM/rollback-journal sidecars. It compares the original ordinary and generated-column projection in each protected baseline table, in deterministic primary-key order (or all-column order without a declared PK). Each value has a type-specific encoding so NULL, INTEGER, REAL, TEXT and BLOB cannot be silently confused. Checksums and counts are returned; no biological values, reviewer comments or raw JSON payloads are printed.

Protected evidence includes project/class identity; individual and project-default visibility; manual box/mask annotation and edit events; dataset versions; QC runs, queues, reviewer events and bulk request identities; saved Workflow Builder graphs, executions, node-run state and typed artifacts; scientific observations, NOAA/environmental cache and computed metrics; and the later environmental event/analysis tables. The exact enumerated coverage is in source. Tables absent from the *before* database can legitimately be created in the *after* database; new columns in existing tables are permitted only if every original projected value is retained. Any change in existing row content/count, missing original column/table, or changed primary key fails closed.

## Run on independent offline copies

~~~powershell
python scripts/inspect-alembic-lineage.py --fail-on-warning C:\research\before.sqlite
python scripts/inspect_sqlite_lineage_16.py --compare-to C:\research\after.sqlite --fail-on-integrity-error C:\research\before.sqlite
python scripts/verify-research-row-preservation-16.py --before C:\research\before.sqlite --after C:\research\after.sqlite
~~~

The last command exits **0** with PASS_PRESERVATION_ONLY only for a content-preserving projection and exits **2** with HOLD otherwise. A passing result **always** contains upgrade_authorized: false and requires_researcher_approval: true. In particular, the known independent 1.1/1.6 **Alembic revision 0038 collision** is **not resolved** by two equivalent content digests, because this tool intentionally permits different after-migration Alembic markers and new schema objects.

**Scope limits:** Only explicitly enumerated tables are checked; this does not verify external image/video/audio files, model weights, all database tables, migrations' DDL and constraints, image geometry validity, scientific units, or any real installed desktop. Rows inserted into previously existing tables are treated conservatively as changes rather than presumed acceptable backfills. Original SQLite **VIRTUAL and STORED generated columns** are now included in the baseline projection through `PRAGMA table_xinfo`, not silently omitted by `table_info`. Changes to existing generated values or removal of those columns fail closed; adding a newly generated column is allowed while all existing values remain unchanged. Hidden virtual-table implementation columns are unsupported and cause HOLD. Equal values on one dataset do **not** establish equivalence of two generated expressions on other data: independent schema/topology and domain validation remain required. A live database can change even when sidecars are not observed. Protect originals and make verified offline backups before attempting candidate upgrade/rollback testing.

## Offline research media and model preservation (optional, but required for asset evidence)

The database-only invocation deliberately reports `research_assets: {checked: false}`. It cannot establish preservation of images, video, audio, masks, local model checkpoints, or exports stored outside SQLite. For an independent read-only asset comparison, supply **both** offline, non-overlapping directory roots:

~~~powershell
python scripts/verify-research-row-preservation-16.py --before C:\\research\\before.sqlite --after C:\\research\\after.sqlite --before-assets C:\\research\\original-assets --after-assets C:\\research\\candidate-assets
~~~

The verifier recursively hashes each original regular file (SHA-256, streamed in 1 MiB chunks) and requires the same relative path with byte-identical content in the candidate directory. New candidate-only files are permitted; missing or changed originals cause HOLD. An empty original asset tree cannot establish preservation and causes HOLD. A symlink anywhere in either tree, missing root, overlapping roots, unreadable/nonregular file, or a file observed changing during inspection also fails closed. It returns **counts only** (checked, baseline/candidate, missing/changed/added), never private file names, model paths, or media contents. There is no networking, model download, directory modification, automatic migration or release authorization.

This is a research-directory comparison, not an exhaustive scan of every possible external path referenced from SQLite: verify the chosen asset roots actually include all study images, source videos, audio, exports and registered local checkpoints, and independently validate path references and external storage. It does not claim a consistent snapshot of files being modified concurrently. For safe acceptance use verified **quiescent offline copies** with no live writers, and still perform the 1.1/1.6 schema reconciliation, scientific acceptance and physical Windows GUI upgrade/rollback gates.

## Regressions and release hold

Run pytest -q scripts/tests/test_verify_research_row_preservation_16.py to check typed scientific values, changed biological observations, removed reviewer events, changed class visibility and saved graphs, removed columns/tables, both VIRTUAL and STORED generated-column expression changes/removal, newly additive generated columns, added baseline rows, reordered baseline records, malformed inputs, no covered evidence, privacy/no source disclosure, bytes of both databases unchanged, active WAL sidecar refusal, byte-identical media/weight trees, missing or altered originals, symlink refusals, and independent asset-root validation. These are synthetic disposable SQLite/filesystem checks, **not** representative scientist-reviewed datasets or native Windows MSI/CAB acceptance.

The existing executable saved project_source → qc_review_queue Workflow Builder integration, typed reference/data outputs, dimensional units, immutable provenance, idempotent retry and explicit researcher-review gates are preserved unchanged. This verifier audits *migration acceptance*, not an analysis/measurement feature requiring a new workflow node.

**Release 1.6 remains HOLD:** independently reconcile both 0038 branches with the owning 1.1 integration lane, then exercise the documented migration fixture matrix with actual migrations and representative records, end-to-end standalone/saved QC workflows, full exact-head CI, Windows MSI clean-install/upgrade/rollback, installed GUI and explicit researcher approval. Do not merge, re-stamp, deploy, download pretrained weights, publish or delete user research data based on this gate alone.
