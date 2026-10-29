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
