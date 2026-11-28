# ReefVision 1.6 — isolated Alembic lineage integration handoff

**Status:** HOLD; read-only cross-track audit, not a migration reconciliation.
**Branch:** `develop/reefvision-1.6` / draft PR #77.
**Coordination:** issue #76. Do not merge or stamp either lineage automatically.

## Verified overlap with 1.1

Both isolated branches inherit revisions 0001–0037. Their subsequent
migration IDs refer to different schemas:

| Revision | 1.1 scientific-data branch | 1.6 QC branch |
| --- | --- | --- |
| 0038 | `0038_scientific_data.py`: `scientific_records`, `environmental_cache_entries` | `0038_review_queue_item_events.py`: append-only QC events |
| 0039 | `0039_computed_metrics.py`: metric definitions and results | `0039_review_queue_triage_event_types.py`: review-event CHECK expansion |
| 0040 | `0040_environmental_event_definitions.py`: immutable threshold definitions | `0040_review_queue_complete_event.py`: completion event |
| 0041 | `0041_computed_annotation_aggregates.py`: metric kinds/configuration | `0041_review_queue_bulk_request_registry.py`: global bulk request identity |
| 0042 | `0042_environmental_analysis_records.py`: composite analysis definitions/results | not present in isolated 1.6 |

An Alembic revision string does not prove which branch's DDL ran. A database
stamped 0038–0041 can therefore be mistaken for the other branch's
schema. A direct merge of these migration files cannot be accepted.
The 1.6 `migration_lineage_guard` deliberately rejects ambiguous
scientific/review schemas before desktop writes; it does **not** solve
cross-version compatibility.

## Safe reconciliation requirements (for coordinated integration)

1. Preserve both branches and existing installed databases. Inventory
   actual `alembic_version` rows, table columns, constraints, indexes,
   foreign keys, review events, and scientific records **read-only**.
2. Choose a reviewed unified Alembic DAG with globally unique revision
   identifiers and an explicit mapping for both historical 0038–0041
   lineages. Never rewrite applied migration files in an installed
   release or blindly use `alembic stamp`.
3. Implement and test data-preserving upgrades from fresh 0037,
   1.1 scientific 0038–0042, and 1.6 QC 0038–0041. Test ambiguous,
   partially applied, duplicate-head, orphaned and corrupted schemas
   fail closed without mutating research data.
4. Verify original scientific records, calibration/units, project/user
   class visibility, reviewer-event order, global idempotency keys,
   foreign-key RESTRICT policies and CHECK allowlists survive.
5. Exercise the resulting installed desktop API and **saved executable**
   `project_source -> qc_review_queue` Workflow Builder run, with typed
   `review_queue_reference`, dimensionless priority score, immutable
   provenance, researcher review gate and retry/replay behavior.
6. Require full backend/frontend/lint/type/E2E, Windows MSI clean
   install/upgrade/rollback, interactive GUI and representative
   biological-data acceptance before marking 1.6 release-ready.

## This branch's regression evidence

`test_desktop_real_migration_16.py` exercises real Alembic 0037 -> 0041
upgrades and persisted project/class visibility. The new
`test_real_0041_schema_enforces_reviewer_request_identity` inspects
actual Alembic-created UNIQUE, NOT NULL, CHECK, primary-key and RESTRICT
foreign-key contracts. Standalone and saved Workflow Builder QC tests
remain separate. These tests validate only the **isolated 1.6 lineage**;
they do not claim that the 1.1 collision has been reconciled.

The exact-head GitHub Actions results and physical Windows acceptance
must be checked independently. No scientific observations, local
checkpoints, user assets or deployed services are changed by this note.

## 2026-10-29 — interrupted scientific 0038 preflight (Track D)

A partially applied 1.1 scientific revision 0038 can leave SQLite tables
behind while Alembic still reports 0037 or has no version table. Previously
the isolated 1.6 desktop guard returned early in those cases, potentially
applying its incompatible review-event 0038 over preserved observations.

The guard now rejects known 1.1 scientific tables **before** returning for
unversioned/pre-review databases. The real desktop migration regression
covers both states, verifies that an original coral observation and the
entire schema survive two refused startup attempts, and requires that no
1.6 review table is created. Existing 0038–0041 lineage validation and
saved executable QC Workflow Builder tests remain unchanged. This does not
reconcile the independent 1.1/1.6 revision collision.

**HOLD:** exact-head Ruff/pytest/frontend/E2E, native Windows MSI
upgrade/rollback, installed GUI, and biological-data acceptance. No merge,
release, data deletion, or pretrained-weight download is authorized.

## 2026-10-29 — interrupted QC audit DDL preflight (Track D)

A partially applied 1.6 QC migration can leave `review_queue_item_events`
or `review_queue_bulk_requests` behind while the Alembic marker remains
0037 or is missing. The 1.6 guard previously checked only interrupted 1.1
scientific tables in those states, allowing desktop migration to begin against
ambiguous QC audit data. It now refuses these partial QC schemas before
Alembic can write, without deleting, stamping, or rewriting reviewer records.

Four real-database regression scenarios cover both QC table names with
unversioned and 0037 databases. Each inserts an audit sentinel, snapshots the
full SQLite schema, and requires two refused desktop startup attempts to
preserve the sentinel, schema and original Alembic state. The existing partial
science tests remain intact. The preceding CI's Ruff RUF043 failure is
corrected by making the scientific-schema test's regex explicitly raw.

This is a defensive 1.6-only migration gate, **not** reconciliation with
the independent 1.1 Alembic lineage. Exact-head integrated CI, Windows MSI
upgrade/rollback, installed-GUI and biological-data acceptance are required
before any release decision.

## 2026-10-29 — interrupted 0041 bulk-request registry preflight (Track D)

The Alembic 0041 migration creates a persistent, globally keyed bulk-review
request registry. SQLite DDL may survive an interrupted upgrade while the
version marker remains 0038, 0039, or 0040. Previously the guard validated
the earlier review-event schema but did not reject the unexpected bulk table,
so desktop startup could attempt to replay 0041 against existing reviewer
request identities.

The guard now **refuses** any 0038–0040 database containing
`review_queue_bulk_requests`, before Alembic upgrade and without altering
review events, bulk requests, research observations, or schema. A new
parameterized regression covers all three stamps with empty and populated
registries, plus two repeated desktop-start attempts that must never invoke
Alembic upgrade. The tests compare exact SQLite schema and scientific/audit
sentinels before and after each refusal.

This does not reconcile the independent 1.1/1.6 revision-ID collision.
Standalone and saved executable QC Workflow Builder regressions remain
required; this is a startup safety guard, not a new workflow operation.
Exact-head CI and native Windows installed-GUI/MSI upgrade/rollback and
biological-data acceptance remain outstanding. **Release HOLD.**

## 2026-10-29 — 0041 nullable reviewer-attribution preflight (Track D)

Audited the real 0038 audit-event DDL and existing 0041 guard. The guard already
checked idempotency-key and event-type nullability, but a forged 0041 schema
could still accept `NULL` for reviewer actor, queue/project scope, timestamp,
or the SQLite noninteger primary identity. Such an event cannot substantiate a
researcher's approval, even with an intact CHECK allowlist and request UNIQUE.

The isolated 1.6 guard now refuses revision-0041 tables with nullable `id`,
`review_queue_id`, `project_id`, `actor`, or `created_at`. It is read-only:
no migration stamping, record rewriting or deletion. New parameterized SQLite
regressions exercise a valid control plus all five forged nullable schemas,
including a successfully persisted NULL audit event, then require two refused
preflight attempts to preserve the exact schema, reviewer event, scientific
observation and revision marker. The real Alembic-0041 test also asserts the
five NOT NULL contracts. Windows MSI packaging preflight includes the test.

The preceding exact-head CI run `40959201065` failed Ruff formatting in the
two new audit-default regression files; the precise reported formatting
changes were applied before the new nullable-attribution implementation.
An independent SQLAlchemy/SQLite six-configuration reproduction passed, but
it is **not** an integrated repository test. Exact new-head CI and physical
Windows GUI/MSI upgrade/rollback remain unverified. The 1.1/1.6 revision-ID
collision is still unresolved. Existing standalone and saved executable
Workflow Builder QC review, provenance, typed units and human gates are
preserved, not replaced. **HOLD; no release, merge or approval automation.**

## 2026-11-02 — partial 1.1 computed-metric revision 0039 preflight (Track D)

The earlier collision audit covered 1.1 revision 0038 scientific-record/cache
DDL, but 1.1 revision 0039 independently creates
`computed_metric_definitions` and `computed_metric_results`. SQLite can
preserve either table after an interrupted migration, including when no 1.1
0038 table remains and the Alembic marker is absent or still 0037. The 1.6
preflight previously recognized neither metric table as a foreign scientific
lineage. It now rejects either table at unversioned, pre-review, and 0038–0040
review markers before desktop migration writes. No data, stamp, or applied
migration file is changed.

`test_migration_partial_computed_metrics_16.py` exercises each independently
present metric table, all five marker states, repeatable read-only rejection,
full SQLite schema and biological-sentinel preservation, and desktop startup
refusal before Alembic upgrade for unversioned/0037 databases. These tests
validate a **defensive isolation guard**, not reconciliation of the 1.1/1.6
0038/0039 collision. Existing saved Workflow Builder QC execution, typed
priority output, researcher review gates and retries remain unchanged. A
reviewed data-preserving migration DAG, integrated CI, real biological-data
acceptance and native Windows installed-GUI/MSI validation remain required.

## 2026-11-02 — ambiguous pre-review Alembic marker refusal (Track D)

The 1.6 desktop preflight already rejects multiple Alembic heads containing a
review-lineage revision (0038–0041), but a damaged or partially restored
`alembic_version` table containing **only** pre-review markers could pass
through the early-return path. Duplicate 0037 rows, 0036/0037 mixed heads, or
an unrelated foreign head alongside 0037 are not an unambiguous migration
starting point. A single NULL, empty or whitespace-only marker is also invalid.

The read-only guard now rejects those states **before** Alembic upgrade,
without altering the stamp, scientific observations, reviewer records, or
SQLite schema. `test_migration_pre_review_revision_markers_16.py` checks
six malformed/multiple-stamp scenarios, repeated rejection with exact schema
and coral-observation preservation, three desktop startup paths that must
never invoke upgrade, and a valid single-0037 control. Existing review-lineage
multi-head behavior and unversioned fresh-database handling are unchanged.

This is **not** a reconciliation of the independent 1.1 and 1.6 revision
0038/0039 migrations. Preserve both lineages until a reviewed, data-preserving
unified DAG and real upgrade fixtures are available. Full CI, Windows MSI/CAB
upgrade/rollback, installed GUI and representative scientific acceptance remain
release blockers.


## 2026-11-02 — Empty Alembic revision table with retained observations

A populated SQLite database can lose every `alembic_version` row during a
partial restore or interrupted upgrade while retaining its biological/project
schema. Previously the 1.6 desktop preflight treated an existing but empty
revision table as an unversioned installation and allowed Alembic to attempt
replaying DDL over preserved data. It now **refuses read-only** when an empty
revision table coexists with any non-Alembic table, without guessing a version,
rewriting observations, or invoking the upgrade. An empty revision table in an
otherwise empty database remains a valid initialization state.

Parameterized regressions exercise direct preflight and two consecutive
desktop startup refusals on a disposable coral observation database with zero
revision rows; the entire SQLite table schema, observation values and revision
rows must remain unchanged. A fresh empty-database control verifies the
compatible path. This increment also resolves the preceding exact-head Ruff
import-order failure in the migration regression file. Existing typed,
researcher-gated, executable saved Workflow Builder QC workflows are unchanged;
no new node or migration is required.

**Release HOLD:** passing exact-head CI, independently reconciled 1.1/1.6
revision-0038 histories, representative scientific datasets, Windows MSI/CAB
upgrade and rollback, and installed-GUI acceptance are still required. Do not
stamp an affected database or automatically repair it.


## 2026-11-02 — missing Alembic table with retained research schema

The prior read-only guard refused an **empty** Alembic revision table with
retained data, but when the `alembic_version` table itself was absent it
only checked four known scientific and two QC audit tables. A restored
project, review queue, workflow run or older research table could therefore
survive without any migration provenance, and desktop startup would attempt
to replay initial Alembic DDL over that database.

The 1.6 preflight now refuses **any populated database without an
`alembic_version` table**, after retaining the existing specific diagnostic
paths for interrupted 1.1 science and 1.6 QC migrations. It never infers a
revision, stamps, deletes, or rewrites data. A genuinely empty database with
no tables remains supported. Existing single-revision databases and the
saved executable, typed, researcher-gated QC Workflow Builder are unchanged.

Parameterized regressions cover biological observations, project tables,
review queues, workflow runs and an unrecognized legacy table; each requires
two identical read-only refusals with exact SQLite schema/data preservation.
Desktop startup tests require that Alembic upgrade is never called for three
representative preserved schemas, and a fresh-database positive control
protects clean installation. This is a **fail-closed compatibility guard**,
not a unified 1.1/1.6 migration DAG or permission to upgrade old databases
without reviewed provenance.

**Release HOLD:** integrated exact-head CI, 1.1/1.6 revision collision
reconciliation, representative biological-data validation, native Windows
MSI/CAB upgrade/rollback and installed GUI acceptance remain mandatory.


### Preserved SQLite views without Alembic provenance (2026-11-02)

A SQLite backup can retain a view referring to a missing biological table while the `alembic_version` table is absent or empty. Table-only inspection incorrectly classifies this schema as a fresh database. The 1.6 desktop preflight now inspects views as well as tables and refuses migrations without revision provenance. Two parameterized read-only regressions check both absent and empty version tables, repeated desktop startup rejection, and byte-for-byte SQL schema snapshots. This is a safety hold, **not** a migration reconciliation or permission to stamp damaged databases. Existing saved Workflow Builder graphs and reviewer records must remain untouched. Full CI and native Windows validation are still required.


## 2026-11-05 — reproducible read-only lineage inventory (Track D)

The actual isolated migration sources were re-read at their branch refs:
1.1 `0038_scientific_data.py` creates `scientific_records` and
`environmental_cache_entries`; 1.6 `0038_review_queue_item_events.py`
creates `review_queue_item_events`. Both declare `revision = "0038"` and
`down_revision = "0037"`. Therefore the Alembic marker alone is
**insufficient evidence** of which schema was applied. This is a confirmed
identifier collision, not a failed or pending automated merge.

Before proposing any reconciliation, make a **separate, immutable copy** of
an installed database and inspect that copy in read-only mode. The following
Python standard-library diagnostic does not import application models, run
Alembic, execute migrations, or write a database. Pass the copy's path as its
single argument; do not run it against a live database being written by the
application:

```python
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
if not path.is_file():
    raise SystemExit(f"Not a database file: {path}")
with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
    db.execute("PRAGMA query_only=ON")
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    revisions = (
        [row[0] for row in db.execute("SELECT version_num FROM alembic_version")]
        if "alembic_version" in tables else []
    )
    names = (
        "scientific_records", "environmental_cache_entries",
        "computed_metric_definitions", "computed_metric_results",
        "review_queue_item_events", "review_queue_bulk_requests",
    )
    print("Alembic revision rows (including duplicates):", revisions)
    for name in names:
        if name in tables:
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({name})")]
            count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            print(name, "rows=", count, "columns=", columns)
        else:
            print(name, "ABSENT")
```

Treat a revision 0038/0039 with only scientific tables as the 1.1 lineage,
with only review-event tables as the 1.6 lineage, and with both families or
partial tables as **ambiguous** until a full constraint/index/foreign-key
inventory and migration history are reviewed. Never infer safe upgrade solely
from table names or row counts. Preserve identifiers and data; no stamping,
downgrades, renumbering of previously applied revisions, or destructive DDL
are authorized by this diagnostic. The next implementation step remains a
reviewed, tested unified migration graph covering all installed lineages.

**Evidence scope:** migration source inspection and read-only diagnostic
specification only. No installed database, Windows MSI, or executable test
was run as part of this documentation update. Release HOLD remains in force.

## 2026-11-16 — unsupported single Alembic revision preflight

The 1.6 desktop guard already rejected multiple heads, empty stamps, and
partially retained 1.1 scientific tables. It did **not** reject a *single*
unrecognized stamp when the known scientific tables were absent. For example,
a damaged 1.1 revision-0042 backup with missing 0038–0042 tables could appear
to be a safe pre-review 1.6 starting point. The desktop must not try Alembic
upgrade against an unrecognized lineage even if only the version table remains.

The read-only guard now accepts only packaged pre-review revision IDs
`0001`–`0037`, including the historical `53ba400993db` video/mask
migration between `0014` and `0015`. It still accepts a genuinely empty,
unversioned installation and the existing validated 1.6 review lineage
`0038`–`0041`; all other single-stamp candidates fail closed without
touching user records. Known scientific-table collisions retain their more
specific refusal reason.

`test_migration_unknown_single_stamp_16.py` adds read-only SQLite cases
for foreign/future, malformed and near-miss revision IDs, both with and
without a biological sentinel; it tests historical valid revisions and
ensures desktop startup never invokes Alembic upgrade on unsupported
single-stamp databases. This is a **migration safety preflight**, not a
research computation; it does not add a redundant Workflow Builder node.
Existing typed, saved, executable QC workflows, audit/retry provenance and
human-review gates are unchanged. This does not reconcile the 1.1/1.6
revision-0038 collision, authorize a migration, or validate a real Windows
installation. Exact-head CI, independent representative copied-database
validation and researcher approval are still required.

## 2026-11-16 — scientific migration-stage ordering in independent inventory

The isolated, read-only `scripts/inspect-alembic-lineage.py` previously reported
no warnings for a database stamped 0037 but already containing both 1.1
scientific 0038 tables, or even the complete 0039 metric tables. Consequently
its informational report was misleading and `--fail-on-warning` could exit
successfully for a known interrupted-migration schema. The desktop's separate
guard already refused this state; the independent evidence inspector did not.

The inspector now reports `scientific_base_before_revision_0038` for any
scientific 0038 base table with a numeric pre-0038 stamp, and
`computed_metrics_before_revision_0039` for any 0039 metric table with
a numeric pre-0039 stamp, including older historical revisions. Both are
diagnostic warnings, **never upgrade permission**. Twelve CLI regression
variants cover strict/informational operation, valid scientific stages,
repeated read-only scans, unchanged biological and computed-metric sentinels,
and byte-identical SQLite snapshots. The existing 0038 lineage-collision
warning remains in place; no migration was executed or renumbered.

This closes an evidence-reporting discrepancy only. The independent 1.1/1.6
revision-0038 collision still requires a reviewed unified DAG, copied-database
science validation, Windows MSI/CAB upgrade and installed-GUI acceptance.
**1.6 remains on RELEASE HOLD.**


## 2026-11-25 — Atomic SQLite migration preflight and first DDL

The online Alembic environment previously relied on SQLAlchemy's outer
transaction. With sqlite3 legacy transaction control, SELECT and DDL do not
begin a physical SQLite transaction. An interrupted first migration step can
therefore persist a QC table without its revision stamp, and another local
writer can invalidate the lineage guard's snapshot before the first DML.

The SQLite online migration path now explicitly starts BEGIN IMMEDIATE before
running the lineage guard and any migration operation. This acquires the local
writer reservation and makes DDL and stamp DML part of the same outer
transaction. Failure rolls both back; retry requires the ordinary reviewed
startup path. Non-SQLite and offline SQL-generation paths are unchanged.

The real desktop regression injects an exception during the first QC index
creation after the actual 0037 -> 0038 table DDL, verifies a competing writer
is refused, checks that original schema, revision and observation values are
unchanged, then exercises 0037 -> 0041 recovery. It covers DELETE and WAL
journal modes using disposable files. Four independent minimal
SQLAlchemy/Alembic probes reproduced the old partial DDL and verified the
new lock, rollback and retry in both modes; these are not full repository
tests. Full exact-head migration/backend/frontend/E2E and Windows installed
acceptance remain required.

This protects the isolated 1.6 lineage, but does not reconcile 1.1/1.6's
conflicting revision identities, certify backups, or authorize upgrades
against original research assets. Existing standalone and saved executable
QC workflows, typed scientific units, provenance and reviewer approval are
preserved. No new scientific operation or workflow node is introduced.
Release HOLD pending integrated migration reconciliation, representative
biology, real MSI/CAB installation and upgrade/rollback, GUI acceptance and
explicit researcher approval.


## 2026-11-25 — Validate desktop migration postconditions before committing

The desktop previously checked the migrated revision and QC schema only after
Alembic committed its transaction. A defective final migration could therefore
persist an invalid registry or incorrect stamp even when startup correctly
refused to serve the API. The desktop now passes its independently resolved
packaged head into the online Alembic environment. Before the outer transaction
commits, the environment verifies the exact single revision and runs the
existing lineage guard against the resulting schema. SQLite rolls back failed
postconditions together with migration DDL and stamp writes. The separate
post-commit reopen check remains in place. Standalone CLI upgrade/downgrade
behavior is unchanged when the desktop expected-head attribute is absent.

Four new real desktop regression configurations inject either an extra bulk
registry index or an incorrect final revision during 0041, in DELETE and WAL
journal modes. They require the complete original schema, 0037 marker, and
coral observation to survive failure and the normal retry to reach valid 0041.
Four isolated SQLAlchemy/Alembic/SQLite probes confirmed rollback and retry
for both fault types and journal modes; these are not the full repository
tests. Existing typed standalone and saved-workflow QC provenance and human
review gates remain unchanged. This is a migration safety change, not a new
workflow node or cross-version DAG reconciliation. Release HOLD remains until
integrated lineage reconciliation, exact-head CI, representative biological
acceptance, installed Windows MSI/CAB and GUI upgrade/rollback, and explicit
researcher approval.

## 2026-11-26 — Validate biological and reviewer foreign keys before commit

SQLite Alembic connections may leave foreign-key enforcement disabled for
batch table recreation. A valid final revision and QC table schema do not
prove that a migration retained parent records. The existing desktop
pre-commit verification now also runs SQLite `PRAGMA foreign_key_check`
within the same write transaction. Any violation, including a preexisting
orphan carried into the candidate schema, refuses the upgrade and rolls back
all migration DDL, stamps and data changes. The error does not expose
observation values or offending record identities. No rows are repaired,
deleted or automatically approved. This check applies to actual desktop
upgrades, not ordinary CLI migrations or an already-current startup.

The real desktop migration postcondition regression now injects a deleted
coral-colony parent while the final migration executes, for both DELETE and
WAL journal modes. It checks that the full schema, original revision,
observation and parent rows survive the refusal, and that a clean retry
reaches 0041 with no foreign-key violations. Four independent
SQLAlchemy/Alembic-context/SQLite fault-and-control probes passed across the
two journal modes; these are not the full repository tests.

No new scientific workflow node or migration revision is introduced.
Existing standalone and saved executable QC workflows, typed references,
provenance and explicit researcher review remain unchanged. This is not a
reconciliation of the independently published 1.1/1.6 migration histories.
Release HOLD pending integrated reconciliation, full exact-head CI,
representative biological/saved-workflow acceptance, genuine installed
Windows MSI/CAB GUI upgrade/rollback, and researcher approval.


## 2026-11-26 — Restore exact-head backend CI and strengthen refusal evidence

Exact-head CI #45769534178 passed frontend and native Windows preservation but
failed backend Ruff formatting before pytest on the long observation assertion
in `test_migration_stamp_triggers_16.py`. Apply the exact logged Ruff diff and
extend the existing unsafe version-table foreign-key and index tests to assert
byte-for-byte preservation after two actual desktop startup refusals, not only
after the direct read-only guard call. These are disposable SQLite fixtures;
no user database is touched. No production migration or workflow behavior is
changed. Fresh backend CI is required to verify these regressions and the
previous atomic migration and foreign-key postcondition tests. Full release
acceptance remains on HOLD.

## 2026-11-27 — exact-source reconciliation inventory and metadata mutation

The opening table now covers all four collisions, with the 1.1-only successor
0042. Reviewed nine actual migration sources at 1.1 head
`a3ea9c7827c748a671bce7103d2f11b0af3a6c9a` and 1.6 head
`56f565a8af7f773fb3f169a650dfac9579bb5a30`. The scientific branch creates
scientific/cache, metric, threshold and composite-analysis tables and adds
metric discriminator/configuration columns. The QC branch creates the event
and global request tables and expands the event CHECK twice. Their direct
upgrade table targets are disjoint; this is not proof that a combined runtime
or shared parent schema is compatible. The 1.4/1.5 changed-file inventories
also include integrated scientific, identity, ReefPose and spatial migration
families, which must be accounted for before approving a unified DAG.

The strict source graph auditor previously accepted a literal parent list that
was subsequently mutated in place, e.g. `down_revision.append("missing")`.
An actual Alembic 1.18.4 loader reproduced the missing-parent failure. Strict
metadata is now declarative: executable references to `down_revision`,
`depends_on` and `branch_labels` are rejected even if the name is not rebound.
Unmodified literal lists/tuples and the legacy diagnostic mode remain supported.
Eight negative CLI cases and one positive control preserve migration source bytes
and refuse automatic reconciliation. Thirteen isolated pytest probes of the
modified parser and loader passed; full repository tests and exact-head CI are
still required. This is a restricted static source contract, not a sandbox or
a proof of arbitrary Python execution behavior.

No migration files, data, or saved Workflow Builder behavior changed. HOLD for
reviewed cross-version migration integration, representative biology, exact-head
CI, installed Windows GUI/MSI upgrade and rollback, and researcher approval.

## 2026-11-27 — Strict verification of the actual packaged lineage

Exact-head CI #46083865728 passed frontend and native Windows preservation,
and 322 independent inspector tests passed. The collision audit step then
failed Ruff RUF001 on the deliberate fullwidth identifier fixture. Represent
the same four Unicode code points using escapes; the invalid identifier and
assertions remain identical at runtime. No test is disabled or weakened.

The CI collision step previously ran the actual migration tree only in legacy
inventory mode. Add a regression to the already-invoked strict parent-graph
test module so CI must also verify the real isolated 1.6 tree, not just small
synthetic graphs. Independently inspected all 42 source metadata declarations:
0001 is the single root, 0041 the single head, and the historical
53ba400993db revision lies between 0014 and 0015. Require 42 unique revisions,
consistent graph, no unresolved parents/cycles/duplicates, unchanged source
bytes, and no automatic reconciliation permission. This locks the current
isolated 1.6 acceptance lineage; a deliberate future migration requires a
reviewed update to the test expectation.

This is source-only evidence, not a database upgrade or proof of arbitrary
Python execution, combined branch compatibility, or installed GUI behavior.
No existing scientific workflows, migrations, observations or reviewer
approvals change. Release HOLD pending replacement exact-head CI, reviewed
cross-version reconciliation, representative biological and persisted workflow
acceptance, installed Windows upgrade/rollback and explicit researcher approval.

## 2026-11-27 — Exact-head collision-audit CI recovery

CI #46089098488 on 7cd62c21 passed frontend and native Windows preservation
and all 322 inspector tests. Collision-audit Ruff lint passed, but its format
check stopped on four exact formatting hunks in the auditor and CLI tests.
Apply those logged formatting changes only; no production logic changes.
Extend the real packaged-lineage test to require that the strict CLI returns
zero, emits no stderr and reproduces the in-process report exactly while
preserving migration source bytes. The CLI must not authorize reconciliation.
The current main/1.6 comparison is diverged (2556 ahead, 358 behind at audit);
1.1 still contains distinct 0038–0042 scientific migrations. Do not merge or
renumber either branch automatically. New tests require exact-head CI; local
checkout is blocked by github.com DNS. Release HOLD remains unchanged.


## 2026-11-27 — Strict migration compilation boundary

Python's AST parser accepts some invalid modules, including module-level
return, break and continue, unbound nonlocal declarations and misplaced
future imports. Independent Alembic 1.18.4 loader probes reproduced all
five failures. Strict ancestry verification now compiles the exact source
snapshot without executing it before deriving revision or ancestry evidence.
Legacy inventory remains unchanged; strict CLI rejects invalid code before
emitting a report. Compilation alone cannot establish import success, DDL
equivalence or runtime migration safety. A valid module that would raise
if imported is intentionally still statically auditable. Five negative
CLI regressions and a non-execution control preserve source bytes.
No migration, database or scientific workflow is altered. Exact-head CI,
coordinated migration reconciliation and real Windows/scientific acceptance
remain required.


## 2026-11-27 — Complete source manifest and cross-track overlap

Exact-head CI #46099181696 on 4b94479f completed successfully (backend,
frontend/E2E/build and native Windows preservation). A fresh Git tree
inventory compared migration filenames and Git blob IDs at these fixed
heads. All nine trees contain the same 38 original migration source blobs,
including the historical 53ba400993db file. No original file is absent or
different in the inspected trees.

| Snapshot | Commit | Migration files |
| --- | --- | ---: |
| main | e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc | 38 |
| 1.0.3 | 2d588c297b02af488864c7cf1a9fe989d0681d9c | 38 |
| 1.1 | a3ea9c7827c748a671bce7103d2f11b0af3a6c9a | 43 |
| 1.2 | 28ab58b997bf79c48bb555f68938473700880d6d | 43 |
| 1.2 PR 85 | 14eb83eb20eb1013915835e199ac00d041b55181 | 57 |
| 1.3 PR 87 | f44053a90286ce57cc6f7356be922bcf8ba41e22 | 59 |
| 1.4 | c34728b1c886dafc9377e74b3f9dfd0f66eb0445 | 63 |
| 1.5 | bd8602a0ada6066fdaf3264452e50b61b1ce33a0 | 63 |
| 1.6 | 4b94479f8a639408cb0dca93561ac739c87d1628 | 42 |

1.4 and 1.5 contain identical migration filenames and blob IDs at these
heads. Their 25 additional files include the five 1.1 scientific files,
five identity files, seven ReefPose files, two 1.2 integration files,
two 1.3 scientific/temporal files, two spatial files and two 1.4 files.
The actual b12_integrated_0001 source joins 0042, b12_identity_0005 and
reefpose_0044. The actual b14_integration_0001 source joins
b13_temporal_0001 and spatial_0039; b14_spatial_0040 descends from that
join. These are migration source inventory observations, not a runtime
compatibility certification. The isolated 1.6 four QC files remain
distinct from the scientific 0038–0041 files.

Previously the strict source report emitted source and ancestry digests
only for collided IDs. A unique integration head or QC-only successor
could therefore be omitted from review evidence. The strict
revision_manifests map now lists every source per input root with its
revision ID, path, parent IDs, exact source SHA-256 and verified ancestry
SHA-256 (null for any source in an inconsistent graph). Duplicate
identifiers retain separate rows rather than being collapsed into one.
Legacy report mode is unchanged; the report never authorizes automatic
reconciliation. Two CLI regressions cover a unique multi-parent join,
duplicate source retention, no ancestry assertion on an invalid graph,
and source preservation. Three independent helper-level tests passed;
new full-repository tests and exact-head CI still need verification.

Use this evidence to prepare a reviewed multi-lineage migration design
before any upgrade or remapping. No migration, database, existing
standalone or typed saved QC Workflow Builder, review gate or user asset
is altered. Release HOLD remains for coordinated migration reconciliation,
representative biology, installed Windows MSI/CAB and GUI upgrade/rollback,
full new-head CI and explicit researcher approval.

## 2026-11-27 — Pairwise verified common-ancestry frontier

Predecessor exact-head Actions run [46103842099](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/46103842099)
on f06278ed passed all three jobs (backend, frontend including E2E/build,
and native Windows preservation). This is not installed-GUI acceptance.

Rechecked the complete migration Git trees: main e94dad6a, 1.1 a3ea9c78,
1.2 28ab58b9, 1.4 38c00303, 1.5 bd8602a0 and 1.6 f06278ed still
retain the same 38 original blobs. The isolated 1.6 has four QC-only
files; the scientific 1.1 has five separate science files, four of
which reuse the QC revision IDs. The 1.4/1.5 inventories have 63 files
each, including the earlier integration lineages. Do not merge branches.

Strict mode now emits deterministic `root_comparisons` for each pair
of input directories: left/right-only revision IDs, shared revision IDs,
verified identical and divergent history IDs and the maximal common
ancestry frontier (which can contain multiple parents). The frontier
is a source-level review aid, not a database stamp or instruction to
run migrations. A byte-identical successor after a divergent ancestor
remains divergent; invalid graphs retain inventory but return null for
all three ancestry classifications. An empty verified frontier means
no common source history, not missing evidence. Single-directory mode
returns an empty pair list and legacy mode remains unchanged.

Two CLI regressions cover divergent ancestry of identical successors,
multi-parent common frontier, unique IDs, three-way comparison with
a duplicate-ID invalid graph, order independence, empty versus unknown
frontier and source preservation. Four independent helper-level tests
passed locally; new repository CI still requires verification. Local
GitHub checkout is DNS-blocked. No new scientific operation or Workflow
Builder node is introduced; existing saved typed QC workflows, review
gates, provenance and units are preserved.

Release HOLD: reviewed migration reconciliation (including all earlier
integration branches), representative biological acceptance, actual
Windows MSI/CAB installed-GUI clean/upgrade/rollback and investigator
approval. Never infer an automatic remapping from this report.

## 2026-11-27 — Migration source filesystem boundary

Previous exact-head Actions run 46108824658 completed all three jobs
successfully (backend, frontend, native Windows preservation). The source
auditor previously checked symbolic links using pathlib alone; NTFS
junctions are not symbolic links, and recursive glob discovery can omit
redirected directories or walk a substituted tree. It could also block
reading a POSIX FIFO named as a Python migration.

The read-only auditor now checks absolute-root ancestors with lstat and
rejects Windows reparse points and symbolic links before resolving the root.
Explicit directory inventory checks entries before descending and only
accepts regular Python migration files. Both legacy and strict reports
retain ordinary source discovery and refuse redirected or nonregular
sources. This is a static path-safety check, not a guarantee against
concurrent malicious filesystem mutation or an authorization to upgrade.

Eight independent helper probes passed on Linux, including real symlinks,
a FIFO, normal recursive discovery and simulated Windows reparse metadata.
Added real NTFS junction regressions (root, ancestor and nested) to the
existing Windows parent-graph CI suite and bounded POSIX FIFO CLI
regressions in both modes. Native NTFS execution and full exact-head CI
remain to be verified. No migration revision, data, executable saved QC
workflow or review gate is changed. Release HOLD remains for reviewed
cross-version migration reconciliation, representative biology, genuine
installed Windows MSI/CAB GUI upgrade/rollback and researcher approval.
