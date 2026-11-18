# ReefVision 1.6 — preserve generated-column scientific formulas

Status: **offline migration-copy safeguard; release HOLD**. This addition is
not a database migration, an installed MSI test, an approval to upgrade or a
resolution of the independent 1.1/1.6 Alembic revision-0038 histories.

## Identified preservation gap

Existing protected-table verification compared every source column and all
currently calculated SQLite VIRTUAL/STORED generated values. It could still
report preservation if an original formula changed but the historical
observations happened to be 0 or NULL, yielding identical computed values.
Later nonzero biological measurements would then be reinterpreted silently.

## Behavior

For preexisting generated columns in the bounded protected-table inventory,
the read-only verifier compares their complete SQLite column-definition token
contracts. This includes the computation formula and declared storage mode
(also independently checked through table_xinfo). Harmless whitespace and
unquoted keyword case differences are normalized; unrelated newly added
ordinary or generated columns remain allowed. Rewritten but apparently
equivalent formulas conservatively require human inspection. If source DDL
cannot be parsed unambiguously, the verifier fails closed. No private SQL,
observation values or asset paths are printed in reports.

A modified original formula returns `changed_generated_column_contract` and
`HOLD`, even when baseline and candidate rows compare equal. The report
always retains `upgrade_authorized=false` and
`requires_researcher_approval=true`. The verifier never modifies either
SQLite copy or research assets.

## Verification and boundary

The existing CI-executed
`scripts/tests/test_verify_research_row_preservation_16.py` now exercises
both VIRTUAL and STORED generated measurements, same-value divergent formulas,
an altered conditional formula, equivalent SQL formatting, additive generated
columns, unchanged controls and quoted column identifiers. Assertions include
the original and candidate existing values being identical, the expected HOLD
or preservation-only result, unchanged database bytes and no auto-approval.
These are synthetic regression cases, not representative coral-workflow
acceptance or installed-Windows MSI validation.

Typed, persisted, executable `qc_review_queue` Workflow Builder graphs,
provenance, retries and explicit reviewer gates remain unchanged. This
out-of-band migration safety audit is not a scientific data-processing node,
and should not be added as a duplicate runtime Workflow Builder node.

Release remains **HOLD** pending full exact-head CI, independent 1.1/1.6
Alembic-0038 lineage reconciliation, real copied-data migration/recovery
matrix, representative biological and saved-workflow acceptance, actual
Windows MSI/CAB clean-install/upgrade/rollback with installed GUI and explicit
researcher approval. No version merge, tag, deployment, model weight download
or source-asset deletion is authorized.
