# ReefVision 1.1 / 1.6 Alembic lineage collision — reconciliation contract

Status: **BLOCKED / design and acceptance checklist only**. This document is not a migration, an authorization to alter a research database, or proof of release readiness. Track D owns the 1.6 branch; integration must be coordinated with Tracks A/E under issue #76 before code is shared.

## Verified source-level collision (2026-11-11)

| Branch | Revision | Parent | Creates |
| --- | --- | --- | --- |
| `develop/reefvision-1.1` | `0038` (`0038_scientific_data.py`) | `0037` | `scientific_records`, `environmental_cache_entries` |
| `develop/reefvision-1.1` | `0039` (`0039_computed_metrics.py`) | `0038` | `computed_metric_definitions`, `computed_metric_results` |
| `develop/reefvision-1.6` | `0038` (`0038_review_queue_item_events.py`) | `0037` | `review_queue_item_events`, two history indexes |
| `develop/reefvision-1.6` | `0039` (`0039_review_queue_triage_event_types.py`) | `0038` | QC event-type changes |
| `develop/reefvision-1.6` | `0040` (`0040_review_queue_complete_event.py`) | `0039` | QC completion changes |
| `develop/reefvision-1.6` | `0041` (`0041_review_queue_bulk_request_registry.py`) | `0040` | `review_queue_bulk_requests` |

Both branches independently assign the same revision identifiers to different DDL. A version stamp alone cannot identify which schema was applied. **Do not** resolve by `alembic stamp`, renaming only the migration filename, auto-merging unmerged branches, or running a downgrade on populated research data.

## Safe integration design (requires review before implementation)

1. Retain both original migration files and recorded branch history as provenance. Choose unique *new* revision identifiers for a reviewed integrated migration graph; do not retroactively assert that a historical `0038` means the other branch's DDL ran.
2. On a **copy** of the database, classify actual schema and row evidence before any write: legacy `0037`; complete 1.1 scientific lineage; complete 1.6 QC lineage; already-combined compatible schema; partial/ambiguous/corrupt schema. Compare columns, FK delete policies, unique constraints, indexes, Alembic rows and representative content hashes, not just table presence.
3. Build explicit data-preserving forward paths for *each verified lineage*, with an atomic transaction or independently tested SQLite recovery strategy. Only create missing tables/constraints when classification proves they are absent and compatible. Preserve original row UUIDs, scientific payloads, review event order, QC client request IDs, Workflow Builder graph/run IDs, provenance hashes and foreign-key relationships.
4. Fail closed on ambiguous/mixed schemas, multiple Alembic heads, partial DDL, unexpected views or missing lineage metadata. Require an immutable backup, researcher approval and a documented recovery plan; no automatic stamp/drop/rebuild of user tables.
5. After integration, keep the 1.6 desktop `migration_lineage_guard.py` and `review_event_topology_16.py` protections until an independently reviewed compatibility replacement is tested. Do not relax them simply to allow a merge.

## Required executable acceptance matrix

- Fresh install from base and from `0037`, including no-data repeat startup.
- Populated 1.1 scientific-only at `0038` and `0039`: retain scientific records, cache entries, computed definitions/results and linked workflow runs.
- Populated 1.6 QC-only at each `0038`–`0041`: retain event IDs, client request idempotency, reviewer comments, assignments, completion, bulk-request registry, and saved executable `qc_review_queue` graphs/runs.
- Valid already-combined schema, if encountered: detect and preserve it without duplicate DDL.
- Negative cases: missing/duplicate/multiple stamps, mixed partial DDL, wrong foreign-key delete policies, altered indexes/unique constraints, orphaned links, interrupted migration and injected failure halfway through upgrade.
- For each positive case: compare pre/post exact rows, schema signatures, content hashes, FK integrity, no unexpected deletions, and **second-run idempotence**; validate a standalone QC action and a saved typed Workflow Builder execution with researcher review still required.
- On Windows: test MSI fresh install, upgrade and rollback against copied populated databases, followed by installed-GUI class visibility, review queue and saved-workflow acceptance. Never exercise migration experiments on the researcher's only database.

## Current evidence boundary

Source files and branch divergence were inspected through the GitHub connector on 2026-11-11. Local Git clone failed with `Could not resolve host: github.com`; this document has **not** been validated by repository pytest, Ruff, mypy, CI or native Windows acceptance. No cross-version migration or branch merge is authorized here.

## Coherent read-only evidence under concurrent local WAL activity (2026-11-15)

The lightweight `scripts/inspect-alembic-lineage.py` now opens one explicit read transaction **before** SQLite integrity, Alembic stamp, scientific/QC table inventory, and row-count checks. Python's `with sqlite3.connect(...)` alone does not pin a snapshot for successive read statements. A second local writer could otherwise commit an environmental schema migration between integrity checks and stamp/table reads, producing a report assembled from different committed versions. The inspector still opens `mode=ro`, sets `query_only`, checks WAL/SHM/journal sidecars, emits `upgrade_authorized: false`, and never performs a migration.

A deterministic disposable-WAL regression injects a separate writer's 0039→0042 schema/stamp commit immediately after the first integrity probe. The in-progress read-only inspection must report only the original 0039 schema and stamp, while a subsequent inspection observes the complete 0042 schema. The biological sentinel is preserved. This proves consistency *within* one inspection, not immutability of a live WAL database; active-sidecar warnings continue to require a consistent external snapshot and researcher approval before any upgrade.


## Opt-in read-only 0038 structural evidence (2026-11-16)

The existing inspector at scripts/inspect-alembic-lineage.py can now check
two **source-audited** table contracts for the colliding revision-0038
branches without modifying an SQLite research database. Run against a
separately verified, quiescent copy, never the only working database:

    python scripts/inspect-alembic-lineage.py RESEARCH-COPY.sqlite --verify-structural-contracts --fail-on-warning

The optional flag checks scientific_records (1.1) and
review_queue_item_events (1.6) against their independently inspected
migration-source column sets, non-null fields, primary key, foreign-key
targets/delete policies and required index/UNIQUE column sets. The JSON
structural_contracts field reports only matches, mismatch, or absent for
these **fixed known table names**. A mismatch emits
lineage_table_contract_mismatch_<known-table> and fails strict mode.
No column contents, review notes, trigger SQL, raw index names or row IDs
are disclosed by this new structural check.

This is an **opt-in diagnostic**, not an integrated migration. Without the
flag, existing historical inspector behavior is preserved and
structural_contracts is empty. Positive shape matches alone cannot
distinguish independently applied revision IDs or prove that all recorded
rows, CHECK constraints, column type affinities, workflow references,
0039 computed metrics, 0040/0042 environmental extensions or 0041 QC
registry are compatible. These remain separate acceptance gates. The
inspector still sets upgrade_authorized: false, and 0038 still carries
the explicit reconciliation warning even when the table shape matches.

Ten disposable populated-database regressions cover positive controls,
missing/extra/generated columns, wrong FK delete policies, missing
indexes/UNIQUE and nullable reviewer attribution; a strict CLI regression
checks JSON redaction, exit code and unchanged database bytes. Full exact-head
backend CI and Windows installed-GUI acceptance must be checked separately.

## Unique-index semantics beyond column names (2026-11-16)

The optional 0038 structural audit now checks SQLite `PRAGMA index_xinfo`
for every UNIQUE key, including the primary key. In addition to matching
the expected columns and rejecting partial or extra UNIQUE indexes, it
requires the migration's ordinary ascending, BINARY-collated key semantics.
`PRAGMA index_info` alone hides collation and sort flags: a restored
review-event UNIQUE constraint on the expected columns but with
`client_request_id COLLATE NOCASE` would silently collapse distinct
case-sensitive reviewer idempotency tokens, while a DESC constraint would
not match the migration's declared key order. Both are flagged as
`lineage_table_contract_mismatch_review_queue_item_events` without
revealing request values, researcher identities, or SQL definitions.

Disposable regression scenarios retain valid uniqueness and unrelated
nonunique lookup indexes, and reject NOCASE, DESC, and combined changes
to the reviewer request-key UNIQUE. Repeated read-only strict inspection
must preserve review and biological sentinel rows and database bytes.
This check does **not** validate arbitrary CHECK clauses, SQLite type
affinities, row-level provenance, or compatibility with the 1.1 migration
branch; no upgrade is authorized.

## Source-declared type and environmental-cache audit (2026-11-18)

The opt-in read-only `--verify-structural-contracts` preflight now covers **both**
1.1 revision-0038 tables, not only `scientific_records`: it also checks
`environmental_cache_entries` against the source-audited `0038_scientific_data.py`
declaration. Its eight columns, required nullability, `projects.id ON DELETE CASCADE`
link and `UNIQUE(project_id, cache_key)` are verified. Unique-key inspection
rejects partial indexes, changed collation and descending keys, while unrelated
non-unique lookup indexes remain compatible. The independent scientific and QC
migration branches have **not** been merged or restamped.

For both scientific tables and the already-audited 1.6
`review_queue_item_events` table, the preflight also compares source-declared
SQLite column types including `VARCHAR(36)` identifiers, `JSON` payloads,
`DATETIME` timestamps and `VARCHAR` lengths. Equal historical values and
column names can conceal changed storage semantics. Type-token case and
whitespace are normalized. Drift returns fixed privacy-safe `mismatch`
diagnostics and a nonzero strict exit, never raw DDL or biological data.

Eleven populated disposable-SQLite variants cover the canonical pair, a
permitted additional lookup index, altered JSON/time/length contracts, lost
or case-insensitive cache uniqueness, changed FK delete policy, repeated
read-only runs and unchanged database bytes. This is **diagnostic evidence**
only. Matching shapes do not prove migration provenance or authorize upgrade.
An approved integrated migration, representative biology and saved-workflow
acceptance, and installed Windows MSI/GUI upgrade and rollback remain blocked.


## Unexpected research-table triggers (2026-11-20, Track D)

Both independently audited revision-0038 sources create ordinary SQLite tables
and indexes, **not triggers**. The optional read-only structural preflight now
treats a trigger attached to any protected `scientific_records`,
`environmental_cache_entries`, or `review_queue_item_events` table as a
contract mismatch. A restored trigger could silently rewrite future biological
observations or reviewer histories even when stored rows and column/index/FK
contracts currently match. The query checks trigger presence only; it never
executes or reports trigger SQL, private field values, names or reviewer notes.

New disposable populated-DB variants for scientific and QC records, plus
strict CLI subprocess checks, require fail-closed mismatch diagnostics,
redaction of private trigger bodies and unchanged on-disk database bytes.
Without the opt-in flag, the existing historical inspector behavior remains
unchanged. This does not detect triggers on *other* tables with indirect
side effects; it is not complete schema provenance, an authorized migration,
or proof of 1.1/1.6 Alembic-0038 reconciliation. Original databases and saved
typed Workflow Builder QC graphs, provenance, retries and human-review gates
remain untouched. CI, representative saved-workflow execution and genuine
Windows MSI/installed-GUI acceptance are still required for release.

## Declared FK update action and lookup-index fidelity (2026-11-20, Track D)

The original independent 1.1 and 1.6 revision-0038 migrations use default
SQLite `ON UPDATE NO ACTION` foreign keys and full, ascending, BINARY-collated
indexes for scientific observation chronology and QC event chronology.
Previously the optional preflight matched foreign-key *delete* actions and
index names' column/UNIQUE signatures, but not foreign-key update policies
or the partial/collation/sort semantics of non-UNIQUE lookup indexes.

The read-only opt-in structural inspector now rejects `ON UPDATE CASCADE` or
other non-source update rules on protected table FKs; it also requires an
unfiltered, ascending BINARY lookup for each source-declared index. A partial
observation index, an alternate collation, or reversed event-time index can
have identical columns but different scientific retrieval and performance
semantics. Additional unrelated non-unique indexes remain permitted, while
unexpected UNIQUE constraints retain their existing fail-closed treatment.

Expanded disposable populated-DB regressions cover both scientific and QC
lineages, altered update actions, partial lookup indexes, NOCASE keys,
descending time keys, strict JSON-only CLI diagnostics, research-note
redaction and byte-identical originals after each read-only audit. These
regressions are **not** migration acceptance: the cross-branch 0038 collision
remains unresolved, `upgrade_authorized` stays false, no existing database
is altered, and representative biological saved-workflow, Windows MSI/CAB,
installed GUI and researcher approval remain release prerequisites. This
preflight is outside executable scientific Workflow Builder because it
inspects migration provenance without processing scientific observations.

## Independent strict schema comparison: revision-table trigger parity (2026-11-23)

The existing desktop migration guard and lightweight inspector already reject
triggers attached to Alembic's version table. The independent
`scripts/inspect_sqlite_lineage_16.py` comparison tool now rejects them too,
even if two copied databases have identical schema hashes and revision
strings. INSERT, UPDATE and DELETE triggers can change research records
when a migration changes its stamp; matching unsafe copies are not an
acceptable lineage baseline.

The inspector performs a read-only, case-insensitive catalog lookup inside
its existing pinned snapshot. It reports the fixed constraint diagnostic
`alembic_version_triggers_require_review` without emitting trigger bodies.
The existing strict stamp, integrity and collision flags return exit 2;
non-strict reports still require researcher review. Unrelated triggers
are not a stamp-contract failure. No triggers or records are altered.
Nine regression combinations check the three event types and three strict
flags against identical copies, plus an unrelated-trigger positive control.
The SQLite catalog query was separately exercised locally with disposable
databases for each event and the unrelated control.

This is diagnostic parity, not a migration or authorization to upgrade.
The integrated 1.1/1.6 migration graph, repository regression results,
populated biological and saved-workflow replay acceptance, and genuine
installed Windows MSI/CAB upgrade and rollback are still release gates.
The existing executable QC workflow, typed ports, provenance and review
gates are unchanged; this diagnostic is not a new scientific workflow node.

## Independent strict schema comparison: revision-table foreign keys (2026-11-23)

A canonical-looking version_num column and a clean foreign_key_check
do not prove that changing the revision is isolated from research records.
An incoming foreign key with ON UPDATE CASCADE or ON DELETE CASCADE
can change or remove linked observations when Alembic advances its stamp.
An outgoing foreign key can bind the revision to unrelated data.

The strict read-only comparison inspector now checks for any incoming or
outgoing foreign key involving alembic_version within its pinned SQLite
snapshot, including case-insensitive target names. It reports
`alembic_version_foreign_keys_require_review` without adding linked row
values or foreign-key definitions to the diagnostic. The three existing
strict gates refuse even structurally identical database copies with zero
FK violations. Unrelated scientific foreign keys remain supported. The nine
parameterized negative cases and positive control check read-only behavior
and comparison results. Independent disposable SQLite probes verified
detection of update and delete cascades, outgoing and self references, and
unrelated and plain schemas; the actual cascade effects were also reproduced
on disposable data. Repository CI must validate the new regressions separately.

This strengthens the independent migration evidence gate only. It neither
rewrites the migration graph nor changes Workflow Builder or scientific
records. Integrated lineage, representative biological saved-workflow
acceptance, installed Windows validation and explicit approval remain HOLD.


## Desktop startup and primary inspector parity (2026-11-23)

The independent comparison gate is not sufficient if a desktop startup can
still advance a revision with incoming or outgoing foreign keys. Both the
desktop guard and primary read-only Alembic inventory now inspect the same
revision-table relationship topology before accepting a known revision.
The inventory reports only a boolean and a review warning; the desktop
refuses migration even when foreign_key_check is clean. Ordinary foreign
keys between scientific tables are unaffected.

Five parameterized regression configurations cover incoming UPDATE and
DELETE cascades, outgoing and self references, and an unrelated scientific
foreign-key control. Unsafe cases exercise two actual desktop preflight
calls with Alembic upgrade prohibited; the stamp and research rows must
remain unchanged. Six independent disposable SQLite/SQLAlchemy probes
passed for the relationship query, including the plain schema control.
Repository pytest and exact-head CI remain separate acceptance requirements.

No migration IDs, workflow operations, scientific units, review decisions
or existing research data are changed. The inherited typed executable QC
Workflow Builder is unchanged. Cross-version lineage reconciliation,
representative biology and genuine installed Windows MSI/GUI validation
remain release gates.


## Missing environmental migration stages (2026-11-23)

Source inspection of the independent 1.1 migrations confirms that revision
0040 creates environmental event definitions and 0042 creates both
environmental analysis definitions and results. A scientific-only database
stamped 0040 or 0041 with neither event table nor later analysis tables
previously passed strict inventory if its 0038/0039 families were intact.
The same issue affected a 0042 stamp with no analysis pair.

The read-only inventory now emits fixed missing-stage warnings for known
scientific-only 0040–0042 stamps lacking the event table, and for 0042
without the complete analysis pair. Earlier revisions and QC-only lineages
are not subjected to these scientific-stage requirements. The existing
dependency and premature-table warnings remain intact. Four added persisted
SQLite CLI regression configurations verify refusal, repeatability, private
record preservation and unchanged file bytes; prior complete-stage cases
remain compatibility controls. Ten independent disposable SQLite probes
of the new stage predicates passed; these are not repository pytest.

This is a diagnostic safeguard only. It does not reconcile revision IDs,
authorize upgrade, change any Workflow Builder capability, or establish
installed Windows acceptance. The integrated lineage, full CI, representative
saved biological workflows, real installer/GUI validation and researcher
approval remain HOLD.


## Alembic primary-key semantics in read-only lineage inventory (2026-11-25)

The lightweight read-only inspector now requires one ordinary ascending,
BINARY-collated primary-key index on the canonical version_num column.
An unchanged 0039 stamp, valid SQLite integrity check, and matching column
metadata could previously hide NOCASE/RTRIM key comparison or descending
key order. The inspector uses SQLite index_list/index_xinfo and reports
the existing noncanonical_alembic_stamp_constraints warning without
exposing key values or index names. Strict mode refuses that evidence.
Eight disposable QC database cases cover ordinary text and VARCHAR
controls, explicit BINARY, alternate collations, and descending keys,
including table-level primary-key declarations; the original file bytes
and review-note privacy are checked on repeat inspection and CLI execution.

This is diagnostic evidence only, not migration authorization, integration
of the independent 0038 branches, or a new scientific Workflow Builder node.
Original typed QC graphs, saved runs, provenance, retries, and researcher
review gates are unchanged. Real migration reconciliation, final CI,
representative biological saved-workflow acceptance, and installed Windows
MSI/GUI upgrade and rollback remain required.


## Independent copy-comparison stamp key parity (2026-11-25)

The separate `scripts/inspect_sqlite_lineage_16.py` comparison tool now
also checks the actual ascending BINARY primary-key index, not merely
column type, nullability and primary-key position. Two copies with
identical revision markers and identical malformed primary-key DDL
cannot pass strict lineage-collision, integrity or canonical-stamp gates.
Informational JSON remains available and both files remain read-only.

Nine parameterized cases in the already registered stamp-type regression
suite exercise valid and altered collation/order, with both copies,
strict and informational CLI modes, biological-data privacy and original
file-byte preservation. This is an offline evidence gate, not a new
scientific operation; existing typed saved QC Workflow Builder and
researcher approval remain unchanged. No reconciliation or upgrade is
authorized by this evidence alone.


## Independent copy-comparison CHECK and index parity (2026-11-25)

The independent SQLite comparison inspector now refuses an Alembic stamp
table with an explicit CHECK or explicit index, matching the existing
lightweight lineage inventory. Identical databases with a current valid
stamp and clean integrity checks can otherwise conceal an expression or
partial index that fails on the next revision, or a CHECK that pins the
stamp to its current value. Quoted identifiers and comments containing
CHECK are not constraints. The check and index diagnostics expose fixed
reason codes rather than raw SQL or biological observations.

Nine disposable comparison regression configurations exercise identical
source/candidate databases, four strict modes and informational mode;
both files must remain byte-identical to their respective originals.
Nine isolated SQLite checks of the added predicate passed; repository
pytest and exact-head CI remain unverified locally. No scientific node,
migration, review state, or saved typed Workflow Builder contract changes.
Independent lineage reconciliation, real biological and installed Windows
acceptance and researcher approval remain mandatory.

## Independent comparison of implicit UNIQUE indexes (2026-11-25)

A table-level UNIQUE constraint with a non-BINARY collation can create an
extra automatic SQLite index with no stored SQL. The prior explicit-index
predicate missed it even when the canonical BINARY primary key was still
present. The comparison inspector now rejects distinct automatic UNIQUE
indexes as well as explicit indexes, matching the existing lightweight
lineage inventory's single-index requirement. SQLite may coalesce an
identical redundant UNIQUE with the primary key; that is not an extra index.

Five additional disposable-copy regression configurations cover NOCASE,
RTRIM, a private constraint label, and coalesced BINARY controls across
informational and four strict CLI modes. Eleven isolated SQLite probes
passed, including demonstrations of alternate uniqueness semantics.
Repository pytest and exact-head CI are not yet verified locally (GitHub
checkout DNS failure). Both input databases remain read-only, researcher
approval is still required, and no scientific workflow or migration is
changed. This does not reconcile the independent 1.1/1.6 lineage.


## Desktop startup parity for Alembic index semantics (2026-11-25)

The read-only inspectors already reject alternate primary-key collations,
descending keys and extra implicit UNIQUE indexes. The isolated 1.6 desktop
migration guard now rejects these before Alembic can execute a schema write
as well. SQLite automatic UNIQUE indexes have no catalog SQL, so the prior
explicit-index check alone could not see them. A declared primary key must
have a single ascending BINARY version_num key; an equivalent coalesced
BINARY UNIQUE remains compatible. Existing keyless pre-review fixtures and
historical compatibility behavior are deliberately retained; this is not
a blanket authorization of noncanonical stamps or a new integrated migration.

Thirteen disposable SQLite regression configurations exercise accepted and
refused declarations, private research-note preservation, repeated read-only
preflight, and two refused desktop startup attempts with Alembic upgrade
prohibited for each unsafe case. Thirteen independent SQLite/SQLAlchemy
predicate probes passed, each checked twice, with original schema, marker
and sentinel preservation. These isolated probes do not substitute for
repository pytest, lint/type/E2E or genuine installed Windows MSI acceptance.

The independent 1.1/1.6 migration graph is still unresolved. Existing typed
executable QC workflows, units, saved runs, provenance, retry and explicit
researcher review remain unchanged; this preflight is not a scientific
workflow operation. No database modification or release is authorized.

## Alembic stamp write and storage semantics (2026-11-27, Track D)

The diagnostic previously accepted a single, non-null, ascending BINARY
revision key with a default value, alternative SQLite `ON CONFLICT` policy,
or `WITHOUT ROWID` storage. These may preserve the current revision and pass
integrity checks while changing future stamp insertion, duplicate handling,
or storage semantics. The read-only inspector now also requires no column
default, no explicit conflict policy, and ordinary rowid storage. It uses the
existing comment-aware SQL tokenization rather than searching raw DDL text;
normal comments and explicit BINARY collation remain compatible. No raw stamp
default or DDL is added to the report.

The existing strict-CLI regression now covers 26 combinations, including
ordinary and WITHOUT ROWID versions of all 13 key declarations, repeated
read-only inspection, no authorization, redacted sentinel data and unchanged
database bytes. Independent SQLite checks validated the fixture DDL and
reproduced the earlier metadata-only false acceptance. Predecessor exact-head
CI #45975009660 passed backend (including lint, type, pytest and migration
checks), frontend (including Playwright and build), and native Windows
preservation. The new exact-head tests remain to be independently confirmed.
This strengthens the migration reconciliation evidence gate; it is not a
reconciliation or a new scientific workflow capability. Existing saved typed
QC workflows and researcher-review gates remain intact. Release HOLD pending
cross-track migration reconciliation, representative biological validation,
physical installed Windows MSI/CAB/GUI upgrade/rollback and approval.

## Desktop startup parity for stamp write/storage options (2026-11-27)

The preceding diagnostic-only change passed all three jobs in exact-head
CI #45984652401, including backend, frontend/E2E and native Windows
preservation. The desktop startup guard nevertheless still allowed a
valid-looking revision key with a default value, an explicit conflict
policy, or WITHOUT ROWID storage to reach migration code. Match the
diagnostic's rejection of those options before any migration writes,
without removing the deliberately retained keyless legacy pre-review
compatibility. The check uses existing comment-aware SQL tokenization
and SQLite column metadata; it exposes no raw DDL or private defaults.

The new 12-case regression compares the startup guard and independent
inspector, checks repeat desktop refusal before Alembic upgrade, and
preserves exact database bytes and a biological sentinel. Independent
SQLAlchemy/SQLite probes passed all 12 configurations (8 refused,
4 ordinary or quoted/comment controls). Full repository test results
for this change are not yet verified. This is a startup safety gate,
not a new scientific workflow node or a resolution of the 0038 collision;
existing typed QC workflows, provenance, retries and human review remain
unchanged. Release HOLD pending cross-track reconciliation, representative
biological and saved-workflow acceptance, physical installed Windows
MSI/CAB/GUI upgrade/rollback, and researcher approval.


## Independent copy comparison parity (2026-11-27)

The separate `scripts/inspect_sqlite_lineage_16.py` comparison CLI still
accepted stamp defaults, explicit ON CONFLICT clauses, and WITHOUT ROWID
tables that the primary inspector and desktop startup already refuse.
Matching DDL hashes and valid current revision strings do not authenticate
these write/storage contracts. The comparison CLI now records stable,
redacted constraint diagnostics and refuses all four existing strict
stamp/integrity/collision/revision gates if either input is unsafe, while
retaining read-only diagnostic mode and ordinary quoted/comment controls.

Twelve independent SQLite probes passed: eight previously accepted
noncanonical configurations and four valid controls. Twelve new paired
source/copy CLI fixtures exercise the default diagnostic mode, four strict
gates, unchanged database bytes and sentinel redaction. Repository-level
regressions and exact-head CI are not yet verified; the local checkout
is blocked by GitHub DNS. Earlier CI #45984652401 completed backend,
frontend and native Windows preservation successfully, but that evidence
does not qualify this new head.

No migration or scientific workflow node was added. Existing typed QC
graphs, saved runs, provenance, retries and mandatory investigator review
are unchanged. Release HOLD remains for cross-version 0038 reconciliation,
representative biology and saved-workflow validation, real installed
Windows MSI/CAB/GUI clean installation, upgrade/rollback, and researcher
approval. No changes to 1.7 or revised 1.8.

## Bounded visible revision marker tokens (2026-11-27)

The independent copy comparison now refuses revision strings longer than
Alembic's declared 32-character capacity, non-ASCII lookalike digits,
invisible format controls and embedded whitespace. SQLite does not
enforce VARCHAR length; otherwise identical copies of an invalid stamp
could pass the strict revision and collision gates. Existing ordinary
ASCII identifiers, including foreign textual identifiers, remain
diagnostic evidence rather than proof of applied lineage.

Sixteen independent SQLite probes passed (five valid controls and eleven
invalid markers). Sixteen paired CLI regression cases exercise the four
strict gates, diagnostic mode, unchanged database bytes and sentinel
privacy. Repository regressions are pending exact-head CI; local checkout
is DNS-blocked. Existing typed saved QC workflow, retry and researcher
review remain unchanged. This is a read-only migration preflight, not
an executable scientific analysis node or migration authorization.

Release HOLD remains for cross-version reconciliation, representative
biology and saved-workflow acceptance, genuine Windows MSI/CAB and
installed-GUI upgrade/rollback, full exact-head CI and researcher approval.


## Malformed revision-marker diagnostic privacy (2026-11-27)

The independent read-only SQLite comparison now applies the same bounded
visible-token predicate to validation and diagnostic serialization. Previously,
a rejected TEXT revision could still be printed verbatim in the source or
reference JSON, potentially exposing misplaced study notes or control
characters. Invalid values now appear as JSON null while the list preserves
row cardinality. Valid historical and foreign revision tokens remain visible;
an invalid marker still fails all existing strict revision/integrity gates.
This does not authorize an upgrade or change any database.

Extended paired-copy regressions verify null redaction for malformed values,
valid marker preservation, and either-sided refusal despite identical DDL.
Independent disposable SQLite probes exercised 22 values, including valid
historical tokens, malformed text, BLOBs, NULL and numeric values, with
unchanged bytes. Full exact-head CI, reviewed cross-version reconciliation,
representative biological saved workflows and installed Windows acceptance
remain separate gates. No new scientific workflow node is needed for this
offline diagnostic; existing typed saved QC execution and review remain intact.


## Undecodable SQLite revision TEXT (2026-11-27)

SQLite can store invalid UTF-8 as TEXT with clean quick and integrity checks.
The default Python driver decoder raises an exception containing the offending
value, bypassing revision-marker redaction and losing the row count.
The revision query now scopes a replacement-character decoder to that query
alone, restores the original connection decoder in a finally block, and
applies the existing visible ASCII token validator. Invalid TEXT is null in
the report, not a leaked exception or accepted revision. Non-TEXT values
remain rejected. Legitimate UTF-8 and UTF-16 database markers still work.

Added ten paired-copy malformed-byte cases and three supported-encoding
controls, checking strict refusal, byte preservation and researcher review.
Twenty-three independent SQLite probes passed; the full repository suite
and exact-head CI remain unverified. This is read-only migration preflight,
not a scientific node or migration authorization. Existing typed saved QC
graphs and review gates are unchanged. Cross-version reconciliation,
representative biology, installed Windows qualification and explicit owner
approval remain release gates.

## Concurrent WAL regression recovery (2026-11-27)

Exact-head CI 46026973389 passed 123 of 124 lineage tests; the sole failure
was the older interleaved connection test double, which did not implement
SQLite's text_factory property. Frontend and native Windows preservation
passed. The test now uses a real sqlite3.Connection subclass via the factory
argument. It exercises valid and malformed revision TEXT with a concurrent
committed WAL writer, verifies one pinned schema/stamp snapshot, redaction,
restoration of the original decoder on close, and confirms the writer's
changes actually exist. Two independent local SQLite/pytest probes passed;
production code is unchanged. The full repository suite and new exact-head
CI are not yet confirmed. Existing scientific Workflow Builder and approval
gates remain unchanged; 1.1/1.6 reconciliation and installed GUI remain HOLD.


## Pinned successor collision inventory and source triage (2026-11-27)

Rechecked main at `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`,
Track A 1.1 at `a3ea9c7827c748a671bce7103d2f11b0af3a6c9a`,
and Track D 1.6 at `840274e2718f11da34155931702832d842233039`.
Compared migration-file changes from main and read the nine individual
migration sources at those pinned heads. These are Git blob IDs, not database
content checksums. All listed revisions have the immediately preceding
numeric revision as their parent; there are **four** divergent revision IDs,
not just the initial 0038 collision.

| Revision | 1.1 source and Git blob | 1.6 source and Git blob |
| --- | --- | --- |
| 0038 | scientific_data — f066c4c3babaeeb6a1ae25e47c13ad4b54df4232 | review_queue_item_events — bbf1800c6615172c17d305834bfd7d8aaf4ae892 |
| 0039 | computed_metrics — c13a16679e5918b118cb578cb844976d0531f04f | review_queue_triage_event_types — 95df4e595022d07e5363e676ae33d1406bb2ec04 |
| 0040 | environmental_event_definitions — 78f25db9064cd510ec316c724dca1c70afc209d1 | review_queue_complete_event — 64b8a212dc8e8d72ac22c1b7aa231433c68c1a1a |
| 0041 | computed_annotation_aggregates — ffa78e862f177c3eac26468e020005708db1454b | review_queue_bulk_request_registry — ffdd803cb3467f2dd4d924e92baaa57bd4887169 |
| 0042 | environmental_analysis_records — cc39e27d1a1f676059c5d651868f76ae5b83db45 | absent from isolated 1.6 |

The two families touch distinct post-0037 table names in the audited
sources, but that does not prove combined runtime compatibility. 1.1
0041 adds two scalar-default discriminator columns and nullable aggregate
configuration; 0042 adds immutable environmental analysis definitions and
results with saved workflow references, source snapshots and uncertainty.
1.6 0039/0040 recreate the QC event CHECK while guarding scope/orphans;
0041 adds the global bulk request registry with restrictive parent FKs.
Its populated downgrade is explicitly refused. Do not downgrade either
family to reconcile it: 1.1 downgrades drop scientific tables/columns,
and 1.6 downgrades can refuse valid audit history.

Expand the required populated 1.1 fixture matrix to **every** stage
0038–0042, including environmental event definitions, scalar and aggregate
results, environmental analysis source and uncertainty evidence, saved
workflow references, and each existing content hash. Test 1.6 at each
0038–0041 stage with append-only event history and bulk idempotency. No
fixture may reinterpret a numeric stamp without independent schema and
row evidence. No migration files from the other branch have been copied.

The existing read-only collision CLI now emits
`collision_source_relationship` for every repeated revision ID, using
the same per-file SHA-256 snapshot already used for its fingerprints:
`byte_identical` or `source_differs`. This distinguishes common unchanged
history from a source difference without conflating a comment-only edit
with incompatible DDL. Both categories still count as collisions and
retain exit 2 and `safe_to_reconcile_automatically=false`. A byte-identical
duplicate inside one lineage is also refused. The new CLI regressions
exercise three isolated roots, reverse input order, all four successor
collisions, a one-sided successor, and an identical within-root duplicate.
Four independent local classification probes passed; the full CLI suite
and exact new-head CI are not yet verified (local checkout DNS failure).

Predecessor CI #46035183120 passed backend, frontend/E2E/build and native
Windows preservation. This is a source-level reconciliation input, not
an integrated migration or installed Windows acceptance. Existing typed
saved QC Workflow Builder execution, units, provenance, retry and mandatory
researcher review are unchanged. Release remains HOLD for reviewed
cross-version reconciliation, populated biological/workflow validation,
real MSI/CAB installed-GUI clean/upgrade/rollback and explicit approval.


## Transitive source ancestry evidence (2026-11-27)

Byte-identical successor files can inherit incompatible earlier revisions.
With `--verify-parent-graph`, the collision audit now fingerprints each
revision's source hash and the complete validated parent ancestry, using
deterministic sorted parent links. The report adds
`collision_ancestry_sha256` and `collision_ancestry_relationship`:
`identical_history`, `divergent_history`, or `unverified_graph` when any
participating directory has an inconsistent parent graph. No fingerprint
is supplied for an invalid graph. These are source ancestry fingerprints,
not proof of applied database history or equivalent migration behavior.

Run on separately checked-out, complete migration directories only. The
default invocation retains its prior report and collision exit behavior.
Both identical and divergent collisions still fail strict CLI execution;
no automatic reconciliation or migration is authorized.

Two CLI regressions cover identical descendants of divergent parents,
reverse input order, invalid-graph evidence withholding, default-mode
compatibility and original source preservation. Ten isolated Python
fingerprint/classification assertions passed, including multi-parent DAG
propagation; the repository CLI tests and exact-head CI remain unverified
locally because github.com DNS prevents checkout. This is offline
migration evidence, not a new scientific Workflow Builder operation.
Existing saved QC runs, units, provenance, retry and human review are
unchanged. Cross-version reconciliation, populated biological acceptance,
installed Windows MSI/GUI and researcher approval remain release gates.

## Dependency-free ancestry boundary (2026-11-27)

Alembic's independent `depends_on` edges also constrain applied revision
order. Previously the opt-in parent graph audit ignored them and could
report a valid source graph even when Alembic could not resolve a missing
dependency. The supported 1.1/1.6 linear-family comparison is now explicitly
limited to sources with no dependency declaration or one literal None.
Nonempty dependency links, dynamic declarations and ambiguous bindings
fail strict inspection before any ancestry evidence is emitted. The
default collision-only mode remains unchanged. This is a conservative
limitation, not support for arbitrary dependency DAGs or branch labels.

All nine pinned divergent/successor migration sources listed above declare
`depends_on = None` (typed in 1.6). The existing static parent-link parser
is reused for dependency validation, retaining literal multi-parent links.
Two CLI regressions cover 12 refused dependency forms and three compatible
controls, source preservation and default-mode compatibility. Local Python
probes of the extracted parser passed 12 refusals and five valid parent
controls; a real Alembic 1.18.4 revision loader independently reproduced
the missing-dependency failure. The full repository CLI suite and exact-head
CI remain unverified because local GitHub checkout is DNS-blocked.

No migrations or databases are modified. Existing typed saved QC workflows,
provenance, retries and investigator review remain intact. Release HOLD
still requires reviewed cross-version reconciliation, populated scientific
and saved-workflow validation, installed Windows MSI/CAB/GUI acceptance
and explicit researcher approval.

## Unlabeled ancestry boundary (2026-11-27)

Alembic branch labels share a namespace with revision identifiers and with
other branch labels. A graph with valid literal parent edges can therefore
still fail Alembic's revision loader when two labels collide or a label
matches an existing revision ID. The opt-in parent-graph audit now refuses
nonempty, dynamic or ambiguous branch_labels declarations instead of
reporting unverifiable ancestry. Missing or one literal None remains
supported. Default collision-only reporting is unchanged. This deliberately
limits strict evidence to the existing unlabeled, dependency-free families;
it does not claim support for arbitrary labeled migration graphs.

Rechecked the four 1.6 and five 1.1 divergent/successor migrations at the
pinned heads: every file declares branch_labels = None (typed in 1.6).
Twenty-two independent local Python/pytest probes passed: ten parser
refusals, nine valid parent/label controls, and three actual Alembic 1.18.4
revision-map namespace-collision reproductions. Two new CLI regressions
cover ten refused declarations, three compatible controls, source bytes
and default-mode compatibility. Full repository CLI tests and exact-head
CI remain unverified (local GitHub checkout DNS failure).

No migration or database is executed or modified. This remains a source
preflight, not a new scientific node or migration authorization. Existing
typed saved QC workflows, provenance, retries and researcher review are
unchanged. Release HOLD remains for cross-version reconciliation,
representative biological and workflow checks, installed Windows MSI/CAB
GUI qualification, full CI and explicit researcher approval.
