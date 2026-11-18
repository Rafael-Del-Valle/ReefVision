# ReefVision 1.6 — protected CHECK and table-storage migration gate

**Status:** Read-only research-preservation diagnostic only. Not Alembic revision-0038 reconciliation, upgrade authorization, or release approval.

The existing 1.6 comparison protects scientific records, column contracts, foreign keys, UNIQUE constraints and reviewer chronology. SQLite column introspection does not expose CHECK predicates, STRICT typing or WITHOUT ROWID semantics. An imported table can retain identical existing coral measurements while silently dropping these protections for subsequent observations.

The verifier now lexes stored CREATE TABLE SQL without treating quoted literals and comments as constraints, then compares complete balanced expressions of existing CHECK clauses, including nested expressions. Additional CHECKs and additive unrelated columns remain permitted. It also compares SQLite pragma_table_list storage flags for protected tables. Removed, relaxed or reworded existing CHECK predicates, or changed STRICT/WITHOUT ROWID flags, result in HOLD with a non-sensitive diagnostic reason. Logically equivalent CHECK rewrites are intentionally not auto-certified, avoiding a false scientific compatibility claim. Original private DDL and data never appear in the JSON report.

Disposable SQLite regressions test five CHECK cases, one additive-column scenario and four storage-flag scenarios for identical present measurement rows. They verify fail-closed classification, non-disclosure, approval requirements and byte-for-byte unchanged database inputs. The existing backend CI executes the targeted research-preservation regression module.

This work is an offline migration inspection gate rather than a biological workflow operation. The existing executable saved QC Workflow Builder still provides typed, review-gated research outputs with provenance and explicit researcher authorization; no redundant Workflow Builder node or migration was introduced.

**Release HOLD:** independent reconciliation of competing 1.1/1.6 Alembic 0038 histories, complete exact-head CI, native Windows MSI/CAB clean install and upgrade/rollback, installed GUI and representative biological data plus saved-workflow scientific acceptance are still required. No cross-branch merge, automatic approval, downloads or research-asset mutation.
