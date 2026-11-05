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
| 0040 | not audited as present on 1.1 at this inspection | `0040_review_queue_complete_event.py`: completion event |
| 0041 | not audited as present on 1.1 at this inspection | `0041_review_queue_bulk_request_registry.py`: global bulk request identity |

An Alembic revision string does not prove which branch's DDL ran. A database
stamped 0038 or 0039 can therefore be mistaken for the other branch's
schema. A direct merge of these migration files cannot be accepted.
The 1.6 `migration_lineage_guard` deliberately rejects ambiguous
scientific/review schemas before desktop writes; it does **not** solve
cross-version compatibility.

## Safe reconciliation requirements (for coordinated integration)

1. Preserve both branches and existing installed databases. Inventory
   actual `alembic_version` rows, table columns, constraints, indexes,
   foreign keys, review events, and scientific records **read-only**.
2. Choose a reviewed unified Alembic DAG with globally unique revision
   identifiers and an explicit mapping for both historical 0038/0039
   lineages. Never rewrite applied migration files in an installed
   release or blindly use `alembic stamp`.
3. Implement and test data-preserving upgrades from fresh 0037,
   1.1 scientific 0038/0039, and 1.6 QC 0038–0041. Test ambiguous,
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
