# ReefVision 1.6 — QC scoring signal name parity

2026-11-26 | Release HOLD

The standalone request schema previously ignored unknown keys in `signal_weights`, whereas the existing executable Workflow Builder rejected them during planning. A typo could therefore silently rank biological images using the default weight instead of the researcher's requested weight. The shared `ReviewScoreWeights` model now forbids extra fields. Known partial weight maps still receive their existing defaults; zero and positive numerical weights retain their existing meaning. The scoring formula, dimensionless priority unit, original annotations, saved runs, provenance and human review gate are unchanged. No new node or database migration is required.

Acceptance: the existing invalid-weight graph planning regression now uses a real disposable imported image and exercises the standalone API as well. Unknown-only and mixed recognized/misspelled maps must refuse both paths and leave the queue list empty. Existing valid standalone/saved executable parity and retry tests remain required. Correct misspelled keys explicitly; do not silently substitute or rewrite saved research evidence.

Seven isolated Pydantic checks confirmed old silent default behavior, new unknown-key refusal and unchanged known/default values. These are not repository tests. Local Git checkout failed DNS resolution; exact-head backend/frontend/E2E/native-Windows CI and representative biological validation remain required. The independent 1.1/1.6 migration collision, actual installed Windows GUI and MSI upgrade/rollback, and explicit researcher approval remain release blockers.
