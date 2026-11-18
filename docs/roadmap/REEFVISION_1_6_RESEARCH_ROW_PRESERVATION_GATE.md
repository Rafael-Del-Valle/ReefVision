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

## Protected AUTOINCREMENT identity history

A baseline research table may use SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`. A migration can leave every current observation and reviewer record unchanged while resetting its `sqlite_sequence` counter, especially after deleting the highest-numbered historical row. Future inserts could then reuse an already-issued identifier even though the row-content SHA-256 comparison passes. The preservation-only gate now inspects internal allocation history for **the explicitly protected baseline tables only** and reports `changed_autoincrement_sequence` with HOLD if original and candidate counters differ, disappear, or acquire duplicate entries. It does not expose sequence numbers, private species names or record values. SQLite files without `sqlite_sequence` remain supported.

This is a narrow database-integrity control, not a full check of all allocated identity spaces: application UUIDs, IDs in unlisted tables, schema-level AUTOINCREMENT rules and physical file ancestry require separate verification. A pass still **never** authorizes migration. Three altered-history regressions plus one compatible additive-schema control preserve both SQLite files byte-for-byte.

## Offline research media and model preservation (optional, but required for asset evidence)

The database-only invocation deliberately reports `research_assets: {checked: false}`. It cannot establish preservation of images, video, audio, masks, local model checkpoints, or exports stored outside SQLite. For an independent read-only asset comparison, supply **both** offline, non-overlapping directory roots:

~~~powershell
python scripts/verify-research-row-preservation-16.py --before C:\\research\\before.sqlite --after C:\\research\\after.sqlite --before-assets C:\\research\\original-assets --after-assets C:\\research\\candidate-assets
~~~

The verifier recursively hashes each original regular file (SHA-256, streamed in 1 MiB chunks) and requires the same relative path with byte-identical content in the candidate directory. Each file is opened as a read-only file descriptor, with no-follow flags where supported and an identity/type check against the lstat-verified path; a swapped symlink or nonregular target cannot silently turn into trusted research evidence. It compares device/inode, byte length, modification and change timestamps and file type before/after hashing. After both inventories are collected it rewalks **both** directory trees to detect files added, removed, rewritten, or replaced between the original and candidate scans without rehashing large videos a second time. New candidate-only files are permitted; missing or changed originals cause HOLD. An empty original asset tree cannot establish preservation and causes HOLD. The scan rejects cross-root hardlinks when the filesystem reports stable nonzero device/inode identities, because changing a candidate must not silently modify its supposed source copy. **It also rejects any file with a link count other than one**: two independent scan roots can still contain links into a *third, unscanned directory*, where a later edit could change the supposedly preserved original or candidate. The link count is included in the before/after file metadata so a third-party link created during comparison invalidates the preservation claim. The conservative rule means intentionally hardlinked/deduplicated research files must first be copied into independently stored offline evidence roots; do not modify the originals to satisfy this gate. A symlink anywhere in either tree, missing root, overlapping roots, unreadable/nonregular file, or a file observed changing during inspection also fails closed. It returns **counts only** (checked, baseline/candidate, missing/changed/added), never private file names, model paths, or media contents. There is no networking, model download, directory modification, automatic migration or release authorization.

This is a research-directory comparison, not an exhaustive scan of every possible external path referenced from SQLite: verify the chosen asset roots actually include all study images, source videos, audio, exports and registered local checkpoints, and independently validate path references and external storage. These checks narrow accidental and adversarial time-of-check/time-of-use gaps, but do **not** provide an atomic directory snapshot: a writer could still change media after the final rewalk, filesystem timestamp/identity metadata can be unreliable on some mounted filesystems, and Windows does not expose the same no-follow flag as POSIX. The correct precondition remains quiescent offline copies with verified independent backups. For safe acceptance use verified **quiescent offline copies** with no live writers, and still perform the 1.1/1.6 schema reconciliation, scientific acceptance and physical Windows GUI upgrade/rollback gates.

Offline asset regressions additionally cover external hardlinks and links introduced after hashing.

## Regressions and release hold

Run pytest -q scripts/tests/test_verify_research_row_preservation_16.py to check typed scientific values, changed biological observations, removed reviewer events, changed class visibility and saved graphs, removed columns/tables, both VIRTUAL and STORED generated-column expression changes/removal, newly additive generated columns, added baseline rows, reordered baseline records, malformed inputs, no covered evidence, privacy/no source disclosure, bytes of both databases unchanged, active WAL sidecar refusal, byte-identical media/weight trees, missing or altered originals, symlink refusals and opening-time swaps, baseline/candidate mutations after the first inventory, late additions, and independent asset-root validation. These are synthetic disposable SQLite/filesystem checks, **not** representative scientist-reviewed datasets or native Windows MSI/CAB acceptance.

The existing executable saved project_source → qc_review_queue Workflow Builder integration, typed reference/data outputs, dimensional units, immutable provenance, idempotent retry and explicit researcher-review gates are preserved unchanged. This verifier audits *migration acceptance*, not an analysis/measurement feature requiring a new workflow node.

**Release 1.6 remains HOLD:** independently reconcile both 0038 branches with the owning 1.1 integration lane, then exercise the documented migration fixture matrix with actual migrations and representative records, end-to-end standalone/saved QC workflows, full exact-head CI, Windows MSI clean-install/upgrade/rollback, installed GUI and explicit researcher approval. Do not merge, re-stamp, deploy, download pretrained weights, publish or delete user research data based on this gate alone.


## Windows junction and directory-identity guard (2026-11-15)

On Windows, the same unchanged file can expose a different creation/change timestamp through path metadata (`lstat`) and the open file handle (`fstat`). The scanner now compares filesystem identity, size, modification time, type and hardlink count **across the path/handle boundary**, while still checking creation/change time separately **within the path before/after observations and the open-handle before/after observations**. This preserves mutation detection without rejecting a valid independently copied media tree merely because Windows reports creation times differently. Regression checks explicitly verify this narrow tolerance and rejection of changed inode, size, mtime, type and link count.

The offline asset verifier now refuses Windows directory junctions and other filesystem reparse points, even where `Path.is_symlink()` is false. Checking only symbolic links is insufficient for Windows research roots: a junction can redirect a seemingly isolated image or model folder to external data without changing the relative file names compared by the verifier. The check uses available Windows reparse-file attributes and `Path.is_junction()` when supported, and also works on Python versions without that method.

Both baseline and candidate scans now inventory directory identities and mutation-sensitive metadata, including empty subdirectories, and compare those identities during the second pass. A directory removed or substituted after initial hashing therefore produces a conservative HOLD even when no tracked file changed. Existing individual-file identity/hash checks, hardlink independence, typed SQLite preservation, and reviewer approval remain unchanged. The verifier does not follow or clean any rejected path, and diagnostics do not reveal private media filenames.

Regression coverage includes portable simulated reparse attributes, a deterministic empty-directory substitution between scanning passes, and four *real* Windows junction cases (original/candidate root and nested folder) in the existing Windows preflight suite. Passing these synthetic tests does not prove all Windows/network filesystem behaviors or establish an atomic snapshot. Representative copied research data and native installed desktop acceptance are still mandatory. The independent 1.1/1.6 revision-0038 migration collision remains unresolved; release HOLD.


## QC event append-order preservation (2026-11-15)

The 1.6 SQLite review history and assignee calculation use append rowid rather than
mutable workstation timestamps: a clock rollback must not resurrect an older reviewer
assignment. Existing reviewer events have UUID text primary keys, not a durable
integer sequence. A migration or import can rewrite identical events in a different
physical order; the existing row-value checksum would pass even though the current
assignee and paginated human audit history could change. This is a scientific
provenance/coordination risk, not an annotation-value change.

For the pre-existing review_queue_item_events table, the preservation-only gate now
also checks the UUID-to-SQLite-rowid mapping across independently copied databases.
A reordered mapping yields changed_review_event_append_order and **HOLD**, even
when every original event value and per-table row SHA-256 is identical. An explicitly
named rowid, _rowid_ or oid column shadows SQLite's implicit identity and
produces ambiguous_review_event_rowid with HOLD rather than false assurance.
The report includes only a status, counts and digests, not private event IDs,
actor names or biological data. The guard never updates the database, claims a
cross-platform durable event sequence or approves a migration. Immutable reviewer
actions and saved executable QC Workflow Builder artifacts remain unchanged.

Two isolated SQLite regression cases rebuild reviewer events in reverse insertion
order with identical record values and add a shadowing rowid alias. Both must HOLD,
while an unchanged independent copied database still passes preservation-only.
These are synthetic acceptance checks; the 1.1/1.6 Alembic-0038 collision,
representative research data, native Windows MSI/CAB installation and installed
GUI still require separate independent acceptance and researcher approval.


## Protect empty-table AUTOINCREMENT contracts (2026-11-18)

Preserving populated `sqlite_sequence` entries is not sufficient to protect
future scientific record identity allocation. SQLite does not insert a
`sqlite_sequence` row until an AUTOINCREMENT table receives its first row.
An offline rebuild can silently replace an empty protected
`id INTEGER PRIMARY KEY AUTOINCREMENT` table with ordinary
`id INTEGER PRIMARY KEY`, or vice versa. In both cases SQLite
`PRAGMA table_xinfo`, current rows and sequence entries can be identical
despite changed future row-ID reuse semantics.

The read-only preservation verifier now compares the original and candidate
`AUTOINCREMENT` keyword contract in each preexisting protected table's
stored `CREATE TABLE` DDL. Existing SQL tokenization ignores comments and
quoted literal/identifier occurrences, preventing false positives from a
research note or column named `autoincrement`. Either semantic change yields
`changed_autoincrement_contract` and **HOLD**, even with no saved records.
Unchanged empty and populated controls must still return
`PASS_PRESERVATION_ONLY`; no approval, database write, renumbering, or
scientific content disclosure occurs.

Eight disposable SQLite regressions cover both drift directions and both
preserved controls with empty and populated scientific tables. The independent
unit reproduction confirms that the pre-change SQLite metadata and row
comparisons cannot distinguish the empty-table drift. The added tests run
under the existing registered Linux backend and native-Windows research
preservation gates. Passing these tests is not lineage reconciliation or
installed-MSI acceptance. The conflicting 1.1/1.6 Alembic-0038 histories,
representative biology/saved-workflow tests, installed Windows GUI, and
researcher approval remain release blockers.
