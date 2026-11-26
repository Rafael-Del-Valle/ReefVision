# ReefVision 1.6 — QC regeneration completion gate

2026-11-26 · Track D · release HOLD

The existing 1.0–1.5 annotation/dataset/QC foundations and 1.6 typed saved-workflow queue, class visibility, reviewer controls, dense editor, onboarding and packaging plans are retained. Saved QC replay already requires a completed queue, but the manual regeneration entry point accepted failed or incomplete generation records if their other scientific checksums still matched. Only a completed snapshot may seed manual regeneration; refusal occurs before reading configuration or creating a replacement. This does not change the score formula, dimensionless priority unit, immutable dataset, or human-review semantics.

Four standalone API cases cover pending/running/failed/unknown persisted statuses, refusal without creating a queue, original scientific checksums and review state, and researcher-led restoration/recovery. A saved frozen workflow case covers failure and exact queue replay after rollback, and manual regeneration refusal for that same queue. Also corrected the frozen temporal test module's stale import of the provenance helper moved into the shared integrity module by the preceding iteration; otherwise that module cannot collect.

Eight isolated SQLite lifecycle probes passed for the exact completion predicate (including case/whitespace/empty malformed states). These are not repository pytest or an installed-GUI validation. Local GitHub DNS prevents checkout, Ruff is unavailable, and the connector exposes no PR-triggered workflows or combined status for the predecessor. Final exact-head CI and all new repository tests require verification.

Release HOLD: independent 1.1/1.6 Alembic-0038 reconciliation, complete CI, representative biological and saved-workflow acceptance, native Windows MSI/CAB clean install, upgrade/rollback and installed GUI, and explicit researcher approval. No new workflow node or migration, cross-version blending, main merge, tag, release, deployment, weights or user-asset deletion.
