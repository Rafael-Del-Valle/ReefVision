# ReefVision 1.6 — private schema-drift diagnostics

Status: **release HOLD**. Isolated `develop/reefvision-1.6` / draft PR #77.

## Scoped gap and correction

The existing **read-only** offline research-copy preservation verifier protects
scientific observations, reviewer audit events, class visibility, Workflow
Builder graphs and other explicitly enumerated tables. Its missing-column
report previously included the **original column identifiers**. A researcher
can import a column whose name embeds a sample label, field-site ID, study
participant name or other private metadata. Printing such identifiers in
CI/acceptance JSON would disclose information even though no row values were
included.

Missing original columns still cause `HOLD`, but the per-table diagnostic
now emits `removed_column_count` instead of the identifier list. Fixed
protected table names and aggregate counts support release review without
exposing user-created column names. This changes a diagnostic JSON field,
not scientific database schema or content. Upgrade authorization remains
`false` even on a preservation-only pass; explicit researcher approval,
cross-version Alembic 0038 reconciliation and real Windows acceptance remain
required.

Four disposable populated-SQLite regressions cover scientific observations,
reviewer events, class visibility and saved Workflow Builder evidence. Every
case verifies HOLD, redacted JSON, unchanged original/candidate database bytes
and no automatic researcher approval. An existing additive-schema positive
control continues to permit harmless new candidate columns. No new workflow
node is appropriate for this independent offline migration preflight; existing
saved typed, provenance-bound QC graphs and review gates are unaffected.

**Verification boundary:** commit/readback and exact-head CI are required;
synthetic SQLite evidence is not a substitute for representative biological
observations or physical installed MSI/GUI clean-install/upgrade/rollback.
