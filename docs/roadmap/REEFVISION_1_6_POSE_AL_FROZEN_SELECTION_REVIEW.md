# Track D 1.6 — Frozen pose Active Learning cohort review (2026-11-23)

## Scope audit

Existing 1.0–1.5 pose inference, temporal association, editable Active Learning candidate reviews and typed, executable, saved Workflow Builder are preserved. The 1.6 human-approval path already checks project membership and current retraining readiness, but until this increment it did **not** compare the frozen workflow input's selection fingerprint, video identity, candidate IDs or counts against the authoritative saved round. A re-signed artifact could point at a different completed biological cohort while retaining an apparently valid researcher approval. This is a genuine scientific provenance gap; no new Workflow Builder node or migration is appropriate.

## Guard

The existing `pose_active_learning_review_gate` now compares its original typed `pose_active_learning_round` source evidence against the live local round manifest before granting approval:

- Exact original video ID and `selection_sha256` must match the authoritative round.
- Every candidate must still belong to the original selection, with no missing, duplicate, blank or foreign candidate IDs. Comparison is set-based because the workflow producer ranks by acquisition score while the export manifest sorts by track and frame.
- Both saved candidate and selected counts must be exact integers (not booleans) equal to the authoritative cohort size.
- The original round ID must be a nonempty string; unexpected unhashable project metadata is rejected as a domain validation error rather than a server crash.
- The round's **mutable** status may legitimately progress from open to complete as researchers verify candidates; approval still requires the current manifest to be complete and retraining-ready. No automatically approved truth is created.

Every refusal leaves the saved workflow run, waiting review node and parent job paused. Existing immutable payload SHA-256, local model policy, provenance, typed saved graph, retry behavior and scientist review remain intact. IDs, counts and hashes are dimensionless metadata; no biological measurement units change.

## Verification

New `test_workflow_pose_al_review_lineage_16.py` exercises standalone invalid video/selection/cohort/count/round/project evidence, a positive same-cohort different-sort-order control, and a real executable persisted Workflow Builder graph that produces pose inference → temporal association → local Active Learning → paused review. After a researcher verifies the candidate, four separately re-signed source mutations must refuse approval with unchanged paused state and no fabricated decision. The existing Phase-10 end-to-end positive test verifies the unmodified approval → dataset freeze → export path.

Separately, predecessor exact-head CI #45149196905 passed frontend and native-Windows research-preservation jobs and backend lint/mypy but **failed one backend test**: the persisted wrong-revision pose-lineage test received earlier input checksum refusal instead of the expected domain message (2423 passed, 32 skipped, one failed). This iteration changes its persisted corruption to the integer 0 while the standalone test continues to verify boolean rejection. Fresh exact-head CI is required; no full backend test, Windows installed GUI, MSI/CAB upgrade or release completion is claimed from these source-level changes.

## Release hold

Before 1.6 acceptance, resolve the incompatible 1.1/1.6 Alembic-0038 lineages independently, complete exact-head lint/type/backend/frontend/E2E/migrations, representative biological and twice-persisted saved scientific workflow validation, genuine Windows MSI/CAB clean install + upgrade/rollback and installed-GUI evidence, and obtain explicit researcher approval. Leave unmerged 1.7 and revised 1.8 untouched; do not auto-merge, tag, release, host, download unapproved weights or remove researcher assets.
