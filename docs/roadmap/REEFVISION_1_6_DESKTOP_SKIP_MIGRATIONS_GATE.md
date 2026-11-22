# ReefVision 1.6 — safe skip-migrations desktop startup

## Audit and rationale

The 1.0–1.5 platform already includes a local sidecar, Alembic migrations,
the offline scientific database and an executable saved Workflow Builder.
The isolated 1.6 branch already implements class visibility, QC comments,
assignment/bulk triage, typed persisted QC graphs/runs, provenance, retries
and manual researcher approvals. These are not reimplemented.

The desktop's normal migration path performs the established 0038 lineage
preflight and checks the installed Alembic head after upgrade. However,
`--skip-migrations` previously skipped **both** migration and lineage
verification, then proceeded to initialize the API and local bundled-model
catalog. This could expose a missing, outdated or foreign-0038 database
to write-capable local endpoints or background jobs.

## Corrected startup contract

- `--skip-migrations` is **not** permission to serve an unknown schema.
  Before initializing the API or creating a research data directory, require
  an existing on-disk SQLite database. Reject empty/in-memory/missing files.
- Inspect the existing schema without stamp, upgrade, downgrade or repair.
  Use the same 1.1/1.6 Alembic-0038 compatibility gate as normal startup.
  Require the actual persisted revision to equal the packaged **1.6** head.
- Fail closed with a readable startup error when an older, foreign, corrupted
  or unversioned database is found. Preserve original biological records and
  require a reviewed backup/migration procedure instead of guessing lineage.
- Normal startup with migrations enabled retains the existing migration
  routine and checks. This change does not merge the incompatible version
  branches or imply that their data can safely share a revision history.

## Verification

`apps/api/reefvision/tests/test_desktop_skip_migrations_16.py` checks
missing-database refusal before API startup or directory creation, read-only
refusal of 0037 and a foreign scientific 0038 with preserved study notes,
and acceptance of a genuinely migrated 0041 database with the upgrade command
explicitly forbidden. These are disposable local SQLite fixtures; no user
database is opened or modified.

Run backend Ruff, mypy and full pytest, frontend lint/type/unit/E2E/build,
scientific saved-workflow regression, Alembic backwards compatibility and
native-Windows preservation checks on the exact SHA. Physical Windows MSI/CAB
clean-install and upgrade/rollback, installed-GUI startup with both valid and
stale database copies, and researcher review remain unverified until performed.

## Workflow Builder and release boundary

This is a sidecar startup safety check, not a biological workflow operation,
so the preexisting typed QC workflow ports, dimensionless priorities, saved
graphs and runs, source/provenance checks, retries and human-approval gates
are unchanged. It needs no duplicate workflow node or database migration.

**RELEASE HOLD:** independently reconcile the conflicting 1.1 and 1.6
Alembic revision-0038 schemas without destructive stamps, complete full
exact-head validation with representative biological records and replayed
scientific saved workflows, test the installed Windows MSI/CAB and GUI,
and obtain explicit researcher approval. Do not merge, tag, release, deploy,
download unapproved pretrained models or delete research assets.

## Follow-up: inspect physical SQLite health and preserved relationships (2026-11-22)

A matching Alembic 0041 revision and intact QC table constraints are necessary but
not sufficient evidence that a copied/restored biological database is usable.
Prior to the existing lineage and exact-head checks, `--skip-migrations` now
opens the already-present SQLite file through an explicit **read-only URI** and
requires:

- SQLite `PRAGMA integrity_check(1)` to return exactly `ok`. This verifies
  full B-tree, index and UNIQUE-constraint consistency beyond `quick_check`,
  which can return `ok` despite a damaged index's uniqueness contract.
  An unreadable/corrupt file is refused without creating a replacement database.
  The full check can increase startup time for very large local databases,
  but no approximate or sampled integrity pass can authorize scientific writes.
- Refuse non-SQLite backends **before** opening a connection: an external
  PostgreSQL/MySQL URL is not an offline desktop research database.
- `PRAGMA foreign_key_check` to report **no** orphaned references, including
  historical links whose parent rows could have been lost while foreign-key
  enforcement was disabled during an external restore.

Both checks stop startup with a recovery-oriented error; they do not invent a
parent, delete a child, rewrite reviews, checkpoint an archive on purpose, or
approve any QC evidence. A missing database remains a hard error. The original
1.1/1.6 revision-0038 lineage collision remains unresolved and blocked.

Regression tests also reject external PostgreSQL/MySQL database URLs before
any connector opens a connection or the study data directory is created.
Disposable SQLite regression fixtures cover an unreadable source file, a
genuinely migrated 0041 schema containing an orphaned reference and original
biological note, and the existing intact migrated 0041 success case with no
upgrade invocation. An independent local SQLite-only probe confirmed
read-only URI access detects an orphan and rejects invalid database bytes while
preserving original file bytes. This probe is **not** a substitute for full
repository pytest, package CI or installed-Windows GUI verification.

The added check is **desktop startup assurance**, not a separate biological
computation, so it does not introduce a new Workflow Builder node. Existing
typed, executable saved QC graphs/runs, source units, provenance, reviewer
approval and retry contracts remain untouched. The final committed tests must
still pass exact-head CI; representative biological saved-workflow runs,
migration reconciliation, native Windows installer clean installation,
upgrade/rollback and interactive installed-GUI acceptance are release gates.

## Follow-up: full index and uniqueness verification (2026-11-22)

An independently reproduced SQLite example with two identical *Swiftia* records
and an externally altered UNIQUE index definition returns `ok` from
`PRAGMA quick_check(1)` while `PRAGMA integrity_check(1)` correctly reports
`non-unique entry in index`. The desktop read-only preflight now uses the latter
with a one-error reporting cap, before opening any write-capable application
engine. No attempt is made to rebuild the index, rewrite the observations or
change biological data, and no user database was inspected.

The new regression in `test_desktop_skip_migrations_16.py` creates a disposable,
fully migrated 0041 fixture, introduces an inconsistent index definition,
confirms quick-check's false negative, asserts fail-closed preflight, and
verifies the original database bytes and observations are preserved. It is a
**startup scientific-data protection**, not a duplicate Workflow Builder analysis
node: existing typed QC graphs, saved runs, provenance, reviewer gates and
retry semantics are unaffected. Repository pytest/CI, migration-lineage
reconciliation and actual installed-Windows acceptance remain mandatory.

## Follow-up: prevent cross-file integrity/lineage evidence (2026-11-22)

Two different SQLite research files can both be well-formed and carry the
packaged 0041 stamp. If an external restore, symlink replacement or local
process substitutes the target path after the read-only integrity/foreign-key
probe but before the Alembic/schema connection, the two verifications may
refer to **different biological observations**. A matching stamp does not
make that composite evidence scientifically valid.

For `--skip-migrations`, retain the initial on-disk file identity (device,
file ID/inode, byte length and nanosecond modification timestamp) and compare
it **before opening the writable SQLAlchemy engine and after the lineage
inspection**. A missing/replaced/modified file fails closed with instructions
to preserve the original and inspect a verified backup. The check never stamps,
repairs or rewrites the database; successful checks continue to enforce the
prior full-index integrity, foreign-key and Alembic-0038 lineage guards.

The regression creates two legitimate populated 0041 SQLite databases with
different *Swiftia* note text, substitutes one between independent preflights
and demands rejection **before** opening an application engine. Both original
and replacement observations are independently checked; the source remains
available in a test-only backup. This protection detects common file/path
replacement races but **does not guarantee a quiescent database indefinitely**:
a concurrent writer can commit through SQLite WAL without changing the main
file's stat signature, and changes after startup remain possible. A copied,
verified, quiescent research database and a single authorized desktop owner
remain important for release acceptance. A replacement with unchanged file
metadata is also outside this guard's detection promise.

This is an offline desktop startup invariant rather than a new biological
analysis transformation, so it does not duplicate a Workflow Builder node.
Existing typed saved QC graphs, provenance, dimensionless priorities, retry
behaviors and explicit researcher approval remain unchanged. Full exact-head
CI, representative persisted-workflow validation, 1.1/1.6 migration
reconciliation, and real Windows MSI/CAB clean-install/upgrade/rollback plus
installed-GUI acceptance remain **RELEASE HOLD** conditions.
