# ReefVision 1.6 — protected scientific-column and foreign-key preservation

**Status: release HOLD.** This adds a read-only migration-copy safety gate; it does not reconcile the 1.1/1.6 Alembic revision-`0038` collision or authorize any upgrade. Existing typed saved Workflow Builder QC runs, reviewer evidence and explicit human review remain unchanged.

## Verified gap

The prior `scripts/verify-research-row-preservation-16.py` compared the original protected scientific, annotation, class, QC and Workflow Builder row projections, generated values, review append chronology and AUTOINCREMENT state. Two database copies could have **identical existing biological rows** while a rebuilt table silently removed `NOT NULL`, changed a measurement's declared type/default, or replaced `ON DELETE RESTRICT` with `CASCADE`. A row-only preservation PASS did not establish that future observations remained safe.

## Increment

For every protected table already present in the baseline, verify that its preexisting column definitions retain declared type, nullability, default expression, primary-key position and generated/hidden flags. Allow additional columns but not silent changes to original columns. Preserve original **grouped** SQLite foreign-key contracts, including composite-key ordering, parent/child columns, update/delete actions and match rules; new foreign keys are allowed. Reject unsafe changes with `changed_column_contract` or `changed_foreign_key_contract`. Report only table and status, never scientific row contents, private defaults or observation IDs.

Disposable SQLite regressions cover unchanged controls, altered NOT NULL, numeric affinity and defaults, plus preserved RESTRICT versus CASCADE/SET NULL delete actions, while asserting database bytes are unchanged and `upgrade_authorized=false` even on a preservation-only PASS.

This gate complements the separate 0038 DDL and index inspectors, not replaces them. It does **not** prove CHECK/UNIQUE/index compatibility, validate every table, authorize migration or certify actual Windows MSI/GUI/rollback. Complete CI, independent 1.1/1.6 lineage reconciliation, representative biological + executable saved-workflow acceptance, genuine Windows MSI/CAB installation/upgrade/rollback and explicit researcher approval remain required. No 1.7/revised 1.8 branch changes, merge, release, hosting, pretrained weights or scientific-data mutation are authorized.
