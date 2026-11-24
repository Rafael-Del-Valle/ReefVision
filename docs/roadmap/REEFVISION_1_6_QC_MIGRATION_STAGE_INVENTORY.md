# ReefVision 1.6 — staged QC migration inventory (read-only)

**Status: HOLD.** This diagnostic must never authorize an upgrade, issue an
Alembic stamp, change a research record, or imply installed-Windows acceptance.
Track D remains isolated on `develop/reefvision-1.6` and draft PR #77.

## Audited overlap and genuine gap

1.1 independently uses numeric revisions 0038–0042 for scientific, computed
metric, and environmental tables. 1.6 instead creates
`review_queue_item_events` in revision 0038, expands review-event type
constraints in 0039–0040, and creates `review_queue_bulk_requests` only
in revision 0041. The previous read-only inventory treated both QC tables as
a single all-or-none family. It therefore falsely labeled healthy 1.6
0038, 0039 and 0040 databases `incomplete_qc_schema_family`, even though
those revisions legitimately lack the 0041 registry.

## Correction and scientific safety

The inspector now diagnoses migration stages independently. A 1.6 QC 0039
or 0040 database with review events and no bulk registry has no false
incomplete-family warning. Revision 0038 **still** reports the real
cross-branch collision; it cannot be considered an authorized upgrade.
A bulk registry without its 0038 review-event predecessor, a 0041 bulk
table under an earlier QC revision stamp, a 0041 QC database missing
the bulk registry, and 0037-stamped review events are reported explicitly.
Other scientific-family and SQLite-integrity warnings remain unchanged.

Registered CLI regressions exercise four legitimate QC stage states and five
interrupted/contradictory states, retaining reviewer and biological sentinel
rows and comparing the complete SQLite bytes after two inspections each.
They assert typed JSON warning names, fail-closed strict exit, classification
and `upgrade_authorized: false` even for valid stage inventories.
No unmerged 1.1–1.5 branch is blended into this work. Existing
`project_source -> qc_review_queue` executable Workflow Builder, persisted
graphs/runs, typed dimensions, provenance, explicit researcher-review gates
and retries are preserved; this is inspector safety, **not** a workflow node.

## Full-CI regression and pre-0037 stamp hardening (2026-11-15)

Exact-head backend CI `43705800419` exposed two obsolete test expectations:
they still required `incomplete_qc_schema_family` for a valid 0038
review-event table without the later 0041 bulk registry. The test fixtures
now distinguish legitimate staged QC schemas from interrupted migrations,
including mixed scientific/QC inventories. The existing read-only inspector
contract is unchanged for legitimate 0038–0041 stages.

A separate real safety gap was identified: QC review events with a numeric
0036-or-earlier stamp escaped the prior `0037`-only pre-creation guard, and
bulk registries before 0037 also escaped the `0037`–`0040` guard.
The inspector now checks **all four-digit numeric predecessor revisions**
before 0038 (review events) or before 0041 (bulk requests). It does not infer
a stage from a malformed, mixed or nonnumeric stamp. Eight database-backed
cases cover legitimate QC stages, impossible pre-creation combinations,
repeatable read-only inspections and byte-identical researcher data.
A valid staged database is **never** automatically authorized for migration.

This is a diagnostic/preflight correctness change, not a new scientific
analysis or Workflow Builder node. Existing independently tested, executable
saved `project_source -> qc_review_queue` graphs, typed evidence and
researcher review gates are preserved. A successful lint/test CI result is
required before claiming the new cases passed.

## Outstanding release gate

Reconcile the 1.1/1.6 revision-number collision by an independently reviewed,
data-preserving unified DAG. Confirm full backend/frontend/lint/type/E2E and
representative saved-workflow/scientific data acceptance, actual native
Windows MSI/CAB install, upgrade/rollback, installed GUI and explicit
researcher approval. Do not merge, tag, release, deploy, download unapproved
models or delete research assets.


## 2026-11-24 — full backend structural fixture stage parity

Exact-head CI `45367114338` passed 2498 backend tests but exposed two
obsolete structural fixture expectations: the fixtures stamped 0038
incorrectly expected the expanded 0039 and 0040 event vocabularies to
match. They now require a mismatch. The full persisted structural
inspector additionally exercises all twelve combinations of the three
historical event vocabularies and four QC revision stamps, including
0041's unchanged 0040 event vocabulary. It checks the actual structural
report, repeated inspection, redaction, byte preservation, and refusal
to authorize any upgrade. The 0041 fixture tests the event table only,
not the separate bulk registry; full schema acceptance remains HOLD.
No production guard or applied migration is weakened or rewritten.

Independent disposable SQLite checks exercise the same twelve
combinations and verify the actual permitted event values. Full backend
CI on the new commit remains required. Existing standalone/saved QC
workflow execution and explicit researcher review remain unchanged.

## 2026-11-24 — 0041 global bulk-request registry structural evidence

Predecessor exact-head CI `45376525159` passed all three jobs; the full
backend suite recorded 2512 passes and 32 skips. The optional structural
audit previously recognized the 0041 registry by table presence only.
The actual independent 0041 migration declares an eight-column registry
with a global primary key, required reviewer attribution and JSON item
identities, and RESTRICT parent foreign keys. The shared read-only audit
now verifies that DDL contract, including nullability, types, defaults,
primary-key identity, absence of extra unique or CHECK restrictions and
triggers, and immediate foreign-key behavior. This does not authenticate
stored request bodies or prove a migration was applied. A valid result
still cannot authorize any upgrade.

Ten persisted cases cover the valid schema and nine incompatible
mutations, with repeated inspection, redaction and byte preservation.
The existing 0041 event-vocabulary CLI fixture now uses the real bulk
registry shape rather than a placeholder table. Independent disposable
SQLAlchemy-compiled SQLite probes confirmed all ten structural cases;
full exact-head repository CI remains required. No migration or
scientific workflow node is changed; existing standalone/saved QC
workflow execution, provenance, retry and human approval remain intact.


## 2026-11-24 — Complete scalar/aggregate metric DDL inventory

The previous exact-head CI run `45385950760` passed backend, frontend
and native-Windows preservation. The read-only structural audit now
covers both scientific 0039 metric tables, using the actual independent
1.1 migrations 0039 and 0041. It checks formula/version/unit columns,
required provenance, foreign keys and delete actions, named lookup
indexes, workflow-node result uniqueness and unexpected triggers.
At revisions 0041–0042 it additionally requires the actual discriminator
and configuration columns, including their original defaults. Earlier
stages must retain the original scalar schema. This is structural
evidence only; no stored formula or result is authenticated by it.

Added 28 persisted stage/variant regression configurations, and replaced
two placeholder metric-pair fixtures with the original scalar shape.
Independent SQLAlchemy/SQLite checks passed for the same 28 combinations;
complete repository CI is still required. The report remains read-only
and never authorizes upgrades. Existing typed saved QC workflows,
provenance, retry and researcher review are unchanged.

## 2026-11-24 — QC request constraint identity and FK multiplicity

The independent QC 0038 migration names its request idempotency constraint;
0039 and 0040 recreate the event table in batch mode and preserve named
constraints. The structural inspector now requires that original named
constraint, not merely an equivalent SQLite autoindex. It also compares the
number of foreign-key rows to the original contracts for all audited tables:
duplicate links can otherwise disappear when converted to a set. Both checks
are diagnostic only and do not authenticate a stamp or authorize an upgrade.

Seven additional persisted CLI configurations cover renamed/unnamed QC
constraints, duplicated QC project links, and duplicated computed-metric
workflow links at each scientific stage 0039–0042. The existing tests check
redaction, repeatability and byte preservation. Independent disposable SQLite
probes verified the specific metadata ambiguity for the QC contract; full
repository CI remains required. Existing typed executable saved QC workflows
and review gates are unchanged; no migrations or research data are rewritten.

## 2026-11-24 — scientific named uniqueness and fixture parity

The original independent 1.1 migrations 0038, 0039 and 0042 name the
cache key, computed metric workflow-node result and environmental analysis
workflow-node result UNIQUE constraints. SQLite reports identical autoindex
metadata when these constraints are renamed or unnamed. The structural
inspector now requires their original names and columns in addition to
existing index semantics. Twelve new persisted CLI configurations exercise
renamed and unnamed constraints, including all four metric stages. The
canonical scientific fixtures now retain the real names. The older backend
QC structural fixture also restores the original named request constraint
required by the preceding guard. These are diagnostic checks, not proof of
migration provenance. Independent disposable SQLite probes confirmed that
the names are invisible in index metadata; full exact-head CI remains
required. Existing executable saved QC workflows and human approval are
unchanged, and no migration or research data is rewritten.

## 2026-11-24 — redundant UNIQUE declarations and candidate evidence boundary

SQLite can coalesce repeated UNIQUE declarations into the same autoindex,
including an extra UNIQUE on an existing primary key. The structural audit
now checks the number of declarations in the original table DDL as well as
canonical names and reflected index metadata. Ten additional CLI configurations
exercise repeated QC request/result uniqueness and redundant primary-key
uniqueness in QC and metric tables, with the existing repeatability, redaction
and byte-preservation checks. This does not authorize any migration.

Separate integrated candidate evidence exists in draft PRs #98, #102 and #103.
The corrective MSI was manufactured from `a580042e84c4d2fa0a646fbf8ec5a3dc90657fa8`,
not this isolated branch. Actions run `44779080692` completed the installer
build, fresh install, six predecessor roles and historical migration/rollback
jobs successfully. Offline run `44779273302` also passed. These results are
valuable to coordination, but cannot be attributed to this branch head or
substitute for independent biological reference acceptance. No candidate
branch is merged or restamped here. Existing executable saved QC workflows
and explicit researcher review remain unchanged; release HOLD.

## 2026-11-24 — revision stamp CHECK preflight

A restored Alembic table can contain a CHECK that pins its apparently valid
revision or prevents a later stamp. The check can be missed by SQLAlchemy
reflection when a SQL comment separates CHECK from its opening parenthesis.
On SQLite, both desktop preflight and the independent read-only CLI now
recognize actual CHECK tokens while ignoring comments and quoted identifiers
or literals. The CLI reports the noncanonical constraint without returning
its expression. Desktop refuses to start Alembic before any migration writes.
Eight configurations in each regression surface include normal stamps and
quoted/comment controls; the independent disposable SQLite probe also
verified the real Alembic-created table. No repair, restamp, change to
saved QC workflow behavior, or upgrade authorization is performed. The
previous inspector Ruff line-length/format issue was corrected.

## 2026-11-24 — revision stamp explicit-index preflight

SQLite expression and partial indexes may pass integrity checks at the current
revision yet raise an error when Alembic writes a future stamp. An independent
SQLite reproduction used conditional integer overflow on the next revision.
The original Alembic version table requires no explicit indexes; its automatic
primary-key index remains allowed. Both desktop startup and the read-only CLI
now reject explicit indexes on that table, including ordinary or redundant
indexes, pending researcher review. The CLI reports only their count and a
warning, not their names or expressions. Five configurations in each regression
surface cover the primary-key-only control and four explicit-index variants,
repeat inspection and assert unchanged database bytes. No automatic index
removal, migration, restamp or alteration of saved QC workflows is performed.

## 2026-11-24 — bulk-request registry startup foreign-key parity

The original 0041 registry declares precisely two foreign keys, each with
ON DELETE RESTRICT and the implicit ON UPDATE NO ACTION. Desktop preflight
previously reduced the SQLite relationships to a set of delete-only tuples:
a duplicate declaration or an update cascade could pass. A cascade can
rewrite the project scope of a committed QC request after a parent identity
change. The startup gate now checks relationship multiplicity, single-column
shape and the original update policy in addition to the existing delete
policy, without mutating data. The read-only structural inspector already
checks these contracts. Regression configurations cover duplicate links,
three altered update policies and the equivalent explicit NO ACTION control;
all fixtures retain a populated request, reviewer history and biological
sentinel. Six independent disposable SQLAlchemy/SQLite probes reproduced the
old acceptance and verified the new classification, including the actual
scope rewrite on a synthetic cascade. Full repository CI remains required;
no migration reconciliation, approval, workflow-node duplication or release
is performed.

## 2026-11-24 — event-parent update policy parity

The original 0038 review-event foreign keys use ON DELETE CASCADE and implicit
ON UPDATE NO ACTION. A restored table with ON UPDATE CASCADE previously
passed desktop topology inspection and could reattribute a committed event
when a queue, item or project identity changed. Startup now requires the
original update policy for all three parent links; the same check is applied
to reflected non-SQLite relationships. Existing deletion policy is unchanged.
The independent structural inspector already checks these update policies.
The regression matrix covers each SQLite parent with implicit and explicit
NO ACTION and four altered policies, repeated read-only inspection of populated
events, and four mocked non-SQLite variants. Eighteen independent SQLite and
SQLAlchemy policy probes passed, including three reproduced cascade changes.
The previous exact-head Ruff formatting diagnostic was corrected. Full CI and
representative saved-workflow acceptance remain required; this preflight is
not a new scientific node and does not modify a database or approve a review.

## 2026-11-24 — reflection-hidden QC history indexes

SQLite expression indexes are omitted by SQLAlchemy index reflection, including
unique and partial expression indexes. The original QC event migration has
exactly two explicit history indexes; its automatic primary-key and request
UNIQUE indexes are distinct. Desktop topology validation now checks the raw
SQLite explicit index inventory before reflection, rejecting extra or missing
explicit indexes while retaining the original automatic indexes. The guard
does not expose hidden index definitions, modify observations, or approve
review events. Six disposable database probes verified three previously
invisible expression-index variants, ordinary extra and missing indexes, and
the original positive control, with repeated read-only checks. The six
persisted regression configurations require exact schema and event-row
preservation. Full repository CI and independent biological acceptance remain
required. This is a startup safety guard, not a new scientific node or
migration reconciliation; existing typed saved QC workflows are unchanged.
