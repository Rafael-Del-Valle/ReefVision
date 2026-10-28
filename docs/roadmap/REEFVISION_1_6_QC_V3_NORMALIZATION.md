# ReefVision 1.6 — saved QC v3 raw-signal normalization

Status: **implemented on draft PR #77; exact-head CI and release acceptance pending**.

## Scientific integrity contract

A saved `qc_review_queue` Workflow Builder run persists immutable raw QC signals, normalized signals, scoring weights, component explanations, dimensionless priority scores, input checksums and a review-required queue reference. Its scoring/evidence digests detect ordinary edits but are not substitutes for independently validating the deterministic scientific formula.

The v3 validator now verifies normalization from **persisted raw evidence**, without consulting live predictions or annotations or rewriting reviewer decisions:

- `pending_proposals` must be a nonnegative integral raw count; its normalized signal is `min(count / 10, 1)`.
- The other twelve frozen v3 inputs are bounded between zero and one; their normalized values must equal their raw values.
- Existing component/weight/score, rank, project scope, formula identity, provenance digest and review-state protections remain in force.
- Older v2 and unversioned snapshots retain their previous compatibility rules. No migration or automatic rewrite is introduced.

This prevents a re-signed queue from claiming five pending proposals while retaining a zero normalized count and unchanged priority score. The validator does **not** claim to authenticate who edited a local database or prove the raw observations were collected correctly.

## Regression coverage

- Standalone v3 tests: false confidence evidence, false pending counts, negative/fractional counts and out-of-range rates with recomputed item-evidence checksums; valid 0/5/10/15 pending counts including saturation.
- Executable saved-workflow test: persisted `qc_review_queue` artifact rejects a re-signed false pending count, preserves a researcher's completed state, then successfully reuses the restored queue with the same typed review-required output.
- No pretrained weights, network services, user-asset edits or cross-version branch integrations.

## Release blockers

Exact-head GitHub Actions must finish successfully. 1.1/1.6 Alembic 0038 collision, native Windows installed-GUI and MSI upgrade/rollback checks, and representative biological dataset acceptance remain unresolved. This change is **not** a release-ready notification.

## 2026-10-28 — human-readable explanation integrity

The v3 contract now freezes the **researcher-facing labels and deterministic descriptions** for all 13 scoring signals, and checks that each item's short reason summary is derived from its original top-four ranked component contributions. The queue generator and saved-workflow validator share one label mapping. A local actor cannot merely change a score explanation to claim "Verified coral polyp detection," recompute the item digest, and have the saved workflow silently replay that false biological claim. Numeric score validation and explicit researcher approval remain independent requirements.

Regression coverage includes three standalone re-signed negative cases (label, description, reason summary) and a persisted two-image `project_source → qc_review_queue` workflow that rejects a re-signed misleading label while retaining in-progress reviewer state, then replays the restored typed, dimensionless, review-required output. Existing v2/unversioned queues are not reinterpreted; no migration or live rescore is introduced.

**Verification boundary:** Source read-back and static line-length checks were performed. Exact-head CI (Ruff, mypy, pytest, frontend/E2E) must pass before these tests can be described as passing. Windows installed-GUI/MSI, real biological-image validation and the 1.1/1.6 migration conflict remain HOLD. No automated biological verification or release is authorized.
