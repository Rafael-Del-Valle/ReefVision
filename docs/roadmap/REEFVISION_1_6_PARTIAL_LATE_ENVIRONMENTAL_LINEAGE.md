# ReefVision 1.6 — interrupted 1.1 environmental lineage safety

## Cross-version audit

The isolated ReefVision 1.1 branch has an independent Alembic lineage:
0038 creates `scientific_records` and `environmental_cache_entries`;
0039 creates `computed_metric_definitions` and `computed_metric_results`;
0040 creates `environmental_event_definitions`; 0041 adds reviewed-annotation
aggregate columns to the computed-metric tables; and 0042 creates
`environmental_analysis_definitions` and `environmental_analysis_results`.
The isolated 1.6 branch instead uses revisions 0038–0041 for human QC audit,
triage and bulk request history. Identical numeric stamps do **not** establish
identical schemas.

The existing 1.6 read-only desktop migration preflight already rejected
the four earliest 1.1 scientific tables. It did **not** recognize the later
0040/0042 tables when a partially restored SQLite database retained only
one of those tables and lost the base scientific tables. In that case a
plausible pre-review stamp, or missing stamp on an otherwise populated DB,
could cause unsafe Alembic replay. A successful QC Workflow Builder run
cannot establish migration safety for those environmental research records.

## Safe incremental repair

The 1.6 desktop guard now recognizes all three additional 1.1 environmental
science tables before any Alembic DDL or project write. It refuses
unversioned, pre-review, colliding-review, and foreign scientific revision
states where the preserved extension tables make the lineage incompatible.
It **does not** stamp, reconcile, drop, or transform researcher records.

The independent `scripts/inspect-alembic-lineage.py` read-only inventory
includes the late tables in its scientific lineage classification and
reports incomplete environmental analysis pairs or an extension surviving
without any base scientific table. It also detects analysis tables from 0042
without the preceding 0040 `environmental_event_definitions` table. Even a
complete 0042 analysis pair and a plausible 0042 stamp are not proof of
uninterrupted migration history when that predecessor is missing.
These are *optional* tables for legitimate earlier 1.1 revisions, so the
inventory does not require later tables in a healthy 0037–0039 database or
require analysis tables at 0040. A warning is a refusal signal, never authorization
to run an upgrade. Sensitive observation payloads are not included in the
JSON inventory.

## Acceptance and scientific boundaries

`test_migration_partial_environmental_16.py` covers all three tables,
seven missing/present/foreign revision states, unchanged schema and
biological observations after repeated read-only rejection, and desktop
startup refusal before Alembic begins. A separate standard-library
CLI regression checks partial-restore classification, strict refusal,
row counts without private values, and byte-for-byte SQLite retention.


The independent strict CLI regression also covers 0042 partial restores with
only analysis definitions, only results, and the complete analysis pair but no
0040 predecessor. It verifies exact database bytes, retained observation
payloads, and fail-closed status. Positive 0039, 0040, and 0042 stage fixtures
protect genuine incremental migrations from false warnings. The previously
failing exact-head CI formatter gate in the inspector was corrected in the same
iteration. These diagnostics **never authorize an upgrade**, even on a clean
database.

This is a **fail-closed safety fix**, not the still-required data-preserving
1.1/1.6 Alembic reconciliation. No 1.1 branch, stored workflow, scientific
analysis, QC decision, installed MSI, model weight, or user asset is
modified by this work. Windows installation, upgrade/rollback, interactive
installed GUI, representative biological and environmental datasets, the
executable saved QC Workflow Builder, and complete exact-head CI remain
release-approval gates. Do not signal completion on the basis of this
change alone.

## 2026-11-15 — staged scientific lineage inventory correctness

The 1.1 migration DAG creates two base scientific tables in **0038**, two
computed-metric tables in **0039**, environmental event definitions in **0040**,
and environmental-analysis definitions/results in **0042**. The diagnostic CLI
previously treated the entire four-table 0038/0039 sequence as a single
all-or-none family. Thus, a healthy scientific 0038 database was falsely
reported as an interrupted scientific schema.

The read-only inspector now verifies completeness of each actual migration
pair separately, accepts the healthy 0038 table inventory without the
`incomplete_scientific_schema_family` diagnosis, and checks that 0039 metrics
have the 0038 base, and 0040/0042 records have metric predecessors.
Existing 0042-to-0040 predecessor checks remain. This detects partial
restores and avoids confusing a valid incremental stage with a corrupt one.
The legitimate **0038** database still reports
`revision_0038_requires_schema_lineage_reconciliation`: that collision
remains an independent blocker. No status from the inspector authorizes an
upgrade, and no migration stamp or scientific record is changed.

The registered CI preflight suite includes four valid scientific stages and
six missing-table/dependency scenarios, including byte-for-byte database
retention and original coral observation payloads. This is an audit accuracy
increment only, not a unified Alembic DAG, installed-GUI acceptance, or a
release claim. Existing executable QC Workflow Builder graphs and human
review requirements remain untouched.

## 2026-11-23 — required computed-metric stage inventory

The real 1.1 revision 0039 creates both immutable computed-metric tables.
A database with just the 0038 base pair and a later 0039 stamp could
previously pass strict inventory without either formula definitions or
results. The read-only inspector now requires the metric pair at known
scientific revisions 0039–0042, even if neither table survived. Legitimate
0038 and unrelated QC lineages retain their existing semantics. Twelve
new CLI regression combinations cover absent and partially retained metric
pairs, repeated refusal, private observation redaction and unchanged
SQLite bytes. The structural-contract fixture now retains the real 0039
metric inventory while isolating its original 0038 DDL checks.

The preceding push-triggered CI #45298701186 failed at the backend Ruff
formatter on one migration-stamp test line; the exact reported correction
is included. Full final-head CI and real installed Windows acceptance
remain required; this diagnostic is not Alembic reconciliation or upgrade
authorization. The existing executable saved QC Workflow Builder is not
changed.

## 2026-11-23 — required annotation aggregate column stage

The source-audited 1.1 revision 0041 adds `definition_kind` and
`configuration_json` to computed metric definitions, and `result_kind`
to results. A complete table inventory alone did not detect a partial
0041 column migration. The read-only inspector now checks these three
columns at scientific-only 0041–0042 stamps and reports premature
columns at earlier known scientific stamps. It never infers an upgrade
authorization or changes any data. This is column-presence evidence,
not a complete type/default/constraint equivalence check.

Thirty-two CLI regression configurations exhaust all eight subsets of
the three columns at revisions 0039–0042, including genuine earlier and
later stage controls, repeated strict inspection, redaction and unchanged
SQLite bytes. Existing synthetic positive-stage fixtures now include the
source-audited 0041 additions. The existing typed saved QC Workflow Builder
is unchanged; integrated lineage reconciliation and installed Windows
acceptance remain on HOLD.


## 2026-11-23 — reviewed-aggregate added-column contracts

The actual 1.1 revision 0041 adds two required VARCHAR(40) kind
discriminators with the server default `'scalar'`, and a nullable JSON
configuration column without a default. Identical stored metric rows and
complete column names do not establish those future-write semantics.
For known scientific-only 0041–0042 stamps, the read-only inventory
now compares these three source-audited column contracts using SQLite
table_xinfo: declared type, nullability, default, primary-key and
hidden-column flags. A noncanonical declaration fails closed; this is
not a complete verification of the entire metric table DDL or its data.

Eighteen CLI configurations cover both stages, correct declarations and
eight type, nullability or default mutations with identical historical
metric values. They require repeated strict refusal, private observation
redaction, and unchanged database bytes. Nine independent disposable
SQLite checks with canonical SQLAlchemy-compiled declarations confirmed
the expected contract comparisons. The earlier exact-head CI
#45313784341 passed frontend and native-Windows preservation but failed
Ruff formatting in the previous aggregate fixture before pytest; the
exact one-line correction is included. Integrated migration reconciliation,
full CI, saved biological workflow acceptance and installed Windows
verification remain on HOLD. Existing executable QC workflows are unchanged.

## 2026-11-23 — environmental definition and workflow result DDL

The source-audited 1.1 revisions 0040 and 0042 now participate in the
existing opt-in structural inspection. It checks the three extension
tables' full declared columns, required values, defaults, key identities,
foreign-key actions, named full lookup indexes, and workflow-node result
uniqueness using the existing read-only schema validator. A missing
input snapshot or changed definition foreign key can otherwise conceal
broken scientific provenance even when current rows agree. No report
authorizes migration, and the existing inventory-only mode is unchanged.

Eight CLI regression configurations cover the canonical schema and
seven mutations, repeated inspection, confidential threshold redaction,
and byte-for-byte database preservation. The 0042 workflow-run foreign
keys are references to historical evidence, not new executable nodes.
Existing typed QC saved graphs remain untouched. This is not an
integrated Alembic DAG or installed Windows acceptance.

## 2026-11-23 — reserved SQLite schema identifier integrity

SQLite resolves ASCII identifier case variants as the same table, while
SQLAlchemy reflection and sqlite_master retain the original spelling. A
partially restored uppercase 1.1 science or 1.6 QC table could escape the
existing case-sensitive pre-review lineage checks. A view occupying one
of these reserved table names is also not a valid migration artifact.
Desktop preflight now refuses both before any Alembic writes. The independent
inventory identifies case-variant tables as present, reports mixed lineage
where applicable, and refuses noncanonical reserved objects in strict mode.
The checks do not rename objects, infer provenance, or alter researcher data.

Eighteen desktop and eighteen CLI configurations cover all seven scientific
and two QC names, case-variant tables and reserved views, repeated refusal,
original database bytes and private observation redaction. Existing executable
QC saved graphs and review gates are unchanged. This is not an integrated
migration DAG or installed Windows acceptance.

## 2026-11-24 — Alembic revision object identity

SQLite resolves case aliases and views through the name `alembic_version`;
SQLAlchemy's has_table also accepts views. A plausible revision returned
by a view of unrelated biological observations is not migration evidence.
The desktop guard now rejects noncanonical spelling and views occupying
the reserved revision name before reading any stamp or invoking Alembic.
The read-only CLI explicitly diagnoses the noncanonical revision object
without accepting its values as revision rows. Four desktop configurations
and five strict CLI configurations (including a canonical table control)
exercise repeated inspection, unchanged database bytes and private-data
redaction. Corrected the preceding exact CI SIM117 and inspector formatting
diagnostics. No schema mutation, integration of unmerged lineages, new
scientific workflow operation, or release approval is implied.

## 2026-11-24 — lineage-specific revision bounds

The independent 1.1 migration files end at 0042, while 1.6 QC ends at
0041. Strict inventory previously accepted a complete-looking QC family
with a 0042 stamp, or either family with arbitrary later or foreign
revision strings. The inspector now flags unsupported revision markers
for a recognized scientific/QC family, including the original shared
pre-review mask revision when paired with post-0037 tables. Earlier
numeric stamps retain the existing stage-specific diagnostics.
Sixteen persisted CLI configurations cover both families, valid 0039 and
scientific 0042 controls, unknown and out-of-range stamps, and retained
private observations. The preceding exact-head CI #45341910641 failed
before pytest on a test assertion exceeding Ruff's line limit; its exact
formatting correction is included. This remains read-only evidence,
not a unified migration DAG, workflow approval, or installed Windows
acceptance.

## 2026-11-24 — QC event vocabulary bound to stamped revision

The optional structural audit previously recognized each of the three
historical review-event CHECK vocabularies independently of the stamp.
An otherwise identical 0039 database retaining the 0038 constraint could
pass the structural check while rejecting legitimate triage events;
0040/0041 similarly require the completion event. The inspector now
binds the accepted vocabulary to known QC revisions 0038, 0039, 0040
and 0041, using the original migration declarations. It continues to
report the separate 0038 lineage collision and never authorizes an upgrade.
Twelve stage/vocabulary combinations extend the existing persisted CLI
regression, preserving research bytes, comments and review gates. The
previous exact-head CI #45349553769 failed solely at the inspector test
format check; its reported formatting correction is included. This is
read-only reconciliation evidence, not a unified migration or release.
