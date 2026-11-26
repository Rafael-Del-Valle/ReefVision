# ReefVision 1.6 — frozen annotation regeneration parity

2026-11-26 · Track D · release HOLD

Prior annotation and immutable dataset producers and the 1.6 executable QC node already exist. Saved v3 replay checked frozen class census, rarity, count disagreement, review status, biological group presence and assisted-annotation provenance against the validated manifest. Manual regeneration checked the snapshot and membership but omitted these independent annotation checks. A re-signed false or missing taxon could seed a new queue.

Both entry points now use the same annotation-evidence contract after snapshot and membership validation, without reading mutable live observations or changing the v3 formula or units. Historical v2 and project scopes retain their previous behavior. Valid manual regeneration creates a new pending queue; saved replay retains the original queue and human-review requirement.

Two standalone API and two saved-workflow regression configurations cover substituted and omitted taxa, refusal, restoration and recovery. Twelve isolated SQLite/manifest probes passed for the shared validator; repository pytest, Ruff and exact-head CI are not confirmed (GitHub DNS prevents checkout; Ruff unavailable).

Release HOLD: independent 1.1/1.6 Alembic-0038 reconciliation, complete CI, representative biological workflows, genuine Windows MSI/CAB installation, upgrade/rollback and installed GUI, explicit researcher approval. No cross-version merge, release, deployment, weights or asset deletion.
