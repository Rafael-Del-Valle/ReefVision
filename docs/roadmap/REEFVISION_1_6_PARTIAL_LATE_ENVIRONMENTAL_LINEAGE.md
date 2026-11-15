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
