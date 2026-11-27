# ReefVision 1.6 — typed frozen split metadata

The existing 0006 and 0007 dataset producers persist a nullable integer seed
and a list of textual split warnings. SQLite INTEGER affinity can retain a
fractional REAL or nonnumeric TEXT value, and JSON columns can retain an
object or nontext warning. Matching rehashed copies do not make these
values valid experimental provenance.

The shared frozen dataset integrity gate rejects noninteger seeds and
malformed or blank warning entries. Null, zero, negative integer seeds and
empty warning lists remain valid. No warnings are inferred or rewritten.
The existing standalone QC, regeneration and saved typed Workflow Builder
paths reuse this validator; saved runs retain dimensionless priority,
original artifacts and mandatory researcher review. The unkeyed digests
are consistency checks, not authentication.

Regression coverage: both original schema variants, valid controls,
malformed types, disposable database-backed standalone generation,
regeneration, saved replay refusal and rollback/recovery. Independent
SQLite metadata probes are not a substitute for full repository CI.

Release HOLD: independently reconcile 1.1/1.6 Alembic lineage, full
exact-head CI, representative biological studies and genuine installed
Windows MSI/CAB clean install, upgrade/rollback, GUI and owner approval.
No cross-version merge or migration is introduced.
