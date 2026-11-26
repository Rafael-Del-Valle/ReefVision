# ReefVision 1.6 — QC regeneration membership parity

2026-11-26 · Track D · release HOLD

The earlier standalone QC and dataset version producers already exist; 1.6 adds typed executable QC workflows and snapshot integrity. The saved workflow replay checks project-only split absence, frozen split membership and complete v3 frozen image coverage against a validated manifest. Manual regeneration previously checked internal snapshot digests but not these independent membership constraints. A re-signed incorrect split or omitted frozen image could therefore be accepted as regeneration lineage.

Both entry points now use one membership validator after snapshot integrity validation. Manual regeneration independently validates the frozen dataset manifest before comparing its split map. Historical v2 project and confidence-filtered subset behavior is retained. No source image, split, score, review or annotation is rewritten; intentional valid regeneration produces a new pending queue, while saved-node replay retains its original queue, typed output and dimensionless priority.

Regression: standalone project and frozen API regeneration reject re-signed false splits, preserve the original pending queue, and recover after restoration. Existing saved graph regressions cover incorrect splits, omitted frozen images, rollback and exact replay. Twelve isolated SQLite JSON membership probes passed, including historical v2 controls. Full repository tests/formatting and exact-head CI remain unverified; local checkout failed at GitHub DNS and Ruff is unavailable.

Release HOLD: independent 1.1/1.6 Alembic-0038 reconciliation, full CI, representative biological acceptance, genuine Windows MSI/CAB installation, upgrade/rollback and installed GUI, researcher approval. No cross-version branch blending, release, deployment, model download or asset deletion.
