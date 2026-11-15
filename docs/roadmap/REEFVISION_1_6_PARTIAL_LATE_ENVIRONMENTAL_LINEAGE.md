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
without any base scientific table. These are *optional* tables for legitimate
earlier 1.1 revisions, so the inventory does not require them in a healthy
0037–0039 database. A warning is a refusal signal, never authorization
to run an upgrade. Sensitive observation payloads are not included in the
JSON inventory.

## Acceptance and scientific boundaries

`test_migration_partial_environmental_16.py` covers all three tables,
seven missing/present/foreign revision states, unchanged schema and
biological observations after repeated read-only rejection, and desktop
startup refusal before Alembic begins. A separate standard-library
CLI regression checks partial-restore classification, strict refusal,
row counts without private values, and byte-for-byte SQLite retention.

This is a **fail-closed safety fix**, not the still-required data-preserving
1.1/1.6 Alembic reconciliation. No 1.1 branch, stored workflow, scientific
analysis, QC decision, installed MSI, model weight, or user asset is
modified by this work. Windows installation, upgrade/rollback, interactive
installed GUI, representative biological and environmental datasets, the
executable saved QC Workflow Builder, and complete exact-head CI remain
release-approval gates. Do not signal completion on the basis of this
change alone.
