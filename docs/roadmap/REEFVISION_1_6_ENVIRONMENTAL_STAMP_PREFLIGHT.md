# ReefVision 1.6 — read-only scientific environmental stage-stamp preflight

**Status: RELEASE HOLD.** This is diagnostic work on the isolated `develop/reefvision-1.6` draft PR #77, not a 1.1 merge, Alembic repair, permission to upgrade, or an installed-Windows acceptance.

## Audited overlap and defect

The 1.1 science migrations create `environmental_event_definitions` in revision 0040 and `environmental_analysis_definitions` / `environmental_analysis_results` in revision 0042, following the 0038 scientific base and 0039 computed metrics. The 1.6 QC migrations independently reuse numerical revisions 0038–0041 for reviewer events and bulk controls. Existing preflight already detected missing 0040 event predecessors beneath analysis records, but could accept a **complete-looking 0042 analysis pair stamped as 0040 or 0041** or a 0040 event table stamped as 0039. SQLite integrity alone cannot establish the migration-history truth.

## Fail-closed diagnostic

The read-only Alembic inventory now adds two warnings to scientific-only lineage:

- `environmental_event_before_revision_0040` when event definitions are present under 0037–0039.
- `environmental_analysis_before_revision_0042` when either analysis table is present under 0037–0041.

A valid 0040 or 0041 event-only scientific stage and a valid 0042 analysis stage are not newly warned. QC-only lineage uses separate checks, and mixed lineage remains independently flagged. The genuine dual-use revision 0038 still requires **independent, data-preserving schema reconciliation**; this change does not migrate or rewrite a revision stamp.

Eight parameterized CLI regressions inspect each example twice in `--fail-on-warning` mode and verify status, warning ordering, scientific lineage, persistent researcher observations, and **byte-identical SQLite** before and after. Previous 1.6 QC stage coverage remains intact. Existing executable saved QC Workflow Builder graphs, typed dimensionless review signals, provenance, explicit approval gates and retry tests are preserved without adding a duplicate workflow node; the inspector itself performs no workflow analysis.

## Required independent acceptance

Require exact-head backend/CI and frontend/E2E completion, 1.1/1.6 Alembic 0038 reconciliation, representative biological and persisted Workflow Builder science checks, actual Windows MSI/CAB install and upgrade/rollback, installed-GUI acceptance and explicit researcher approval before release. Never equate read-only diagnostics or synthetic database fixtures with a safe migration or release.
