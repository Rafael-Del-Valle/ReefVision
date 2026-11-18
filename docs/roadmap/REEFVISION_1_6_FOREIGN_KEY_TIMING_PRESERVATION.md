# ReefVision 1.6 — offline foreign-key timing preservation

Status: **read-only migration preflight, not an upgrade authorization**. The original 1.1/1.6 Alembic revision-0038 lineage collision and installed-Windows acceptance remain unresolved.

## Audited overlap and scientific risk

The 1.0–1.5 scientific and Workflow Builder facilities already persist research rows and graph provenance; the 1.6 branch already implements class visibility, QC coordination, typed executable saved `project_source → qc_review_queue`, review gates and a non-destructive migration-copy verifier. This change adds **no duplicate workflow node, schema revision or research-side write**.

SQLite `PRAGMA foreign_key_list` reports parent mappings and update/delete actions but **omits whether a foreign key is DEFERRABLE and initially DEFERRED or IMMEDIATE**. An offline migration may therefore preserve every existing scientific value, primary key, FK metadata, reviewer event and saved-workflow record while silently changing whether a multi-step write can temporarily contain a missing parent. That can break atomic annotation and reviewer workflows on future writes.

The existing `scripts/verify-research-row-preservation-16.py` now compares original and candidate FK timing from stored SQLite `CREATE TABLE` DDL, matching each reference by local column names, remote table and referenced column names. It handles inline and table-level foreign keys, explicit `NOT DEFERRABLE`, `DEFERRABLE INITIALLY DEFERRED`, `DEFERRABLE INITIALLY IMMEDIATE` and their implicit SQLite defaults. Added unrelated references are permitted; changed timing on an original reference returns `changed_foreign_key_timing_contract` and **HOLD**. Unsupported/ambiguous declaration shapes fail closed with a fixed non-private error; none of the source DDL, private identifiers or biological values is emitted.

## Verification and boundaries

The synthetic standalone subprocess regressions cover changed, unchanged, implicit-default and additive cases for both inline and table-level declarations, plus two-reference swaps that must not evade a simple table-wide policy-set comparison. Each case asserts preserved database bytes, privacy-safe diagnostic output, explicit researcher approval and `upgrade_authorized=false`. The Linux backend and native-Windows preservation CI commands explicitly include the new test file, subject to exact-head CI confirmation.

This checks only SQLite declarative timing on the protected tables and does **not** prove cross-version Alembic compatibility, successful future transactions on real biological databases, saved workflow acceptance, Windows MSI/CAB clean install/upgrade/rollback or installed-GUI behavior. An unrecognized complex FK declaration requires human inspection rather than a guessed PASS. Keep all original scientific files and approvals untouched. No merge, auto-release, pretrained downloads or remote service are authorized.
