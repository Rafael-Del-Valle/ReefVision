# ReefPose Phase 6 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and complete each tested increment.

**Goal:** Compare independent frozen video references to automatic ReefPose outputs with reproducible scientific reports.

**Architecture:** Store project-scoped reference revisions separately from annotation and training tables. Evaluate original Phase 4 predictions with the existing Phase 3–5 domain engines. Persist reports in the existing job system and expose the same operation through REST and Workflow Builder.

**Tech stack:** Python, SQLAlchemy/Alembic, FastAPI, React and existing Workflow Builder adapters.

**Spec:** Phase 6 user brief and the methodology in `docs/reefpose/phase6-validation.md`.

## Constraints and design choices

Work on `feature/reefpose-core` from `5aa98933`. Local commits only. Use installed dependencies and synthetic fixtures where independently labeled data are unavailable.

Reusing frozen training datasets would mix study references with model-assisted labels and cannot represent independent raters or observation windows. A dedicated import contract can preserve these records while using existing video and anatomy schema IDs. Blinding is supported by importing externally recorded, prediction-blind labels and preserving attestations. The local application has no account-based access isolation.

Use grouped development and test recordings. Require a completed development report and lock its selected configuration for test scoring. Bind the report to the model checkpoint, dataset hash and original machine prediction digest. Compare measurements by a stable identity mapping, definition, unit and timestamp/frame key. Compare events one-to-one within video, individual, label and completeness state. Unscored intervals and missing measurements cannot become negative examples.

## Review focus

- Reject source or group leakage even when two reference records have different IDs.
- Preserve rater disagreement and require explicit adjudication for confirmatory scoring.
- Avoid counting duplicate predictions, unscored intervals, or partial events as complete matches.
- Reject a modified or cross-model development lock on held-out evaluation.
- Treat nested frame measurements as clustered within the declared recording group.

## Increment 1 — Frozen references

- [ ] Add failing tests in `test_reefpose_validation.py` for freezing a two-rater reference, append-only revisions and shared groups across splits.
- [ ] Implement typed manifests in `schemas/reefpose_validation.py`, persistent rows in `db/models/reefpose_validation.py`, migration `0043`, and freeze/list/get in `services/reefpose_validation.py` and the new routes. Check registered videos and schema revisions.
- [ ] Run focused tests and migration round trips, then commit.

## Increment 2 — Scientific evaluation and reporting

- [ ] Add independently derived expected values for one-to-one event matching, ICC(A,1), signed measurement error, pose/identity misses, and development-only sensitivity.
- [ ] Implement `domain/reefpose_agreement.py` and `services/reefpose_validation_analysis.py`. Reuse Phase 3 localization, Phase 4 identity and Phase 5 measurement/detection functions. Preserve per-recording diagnostics and clustered uncertainty.
- [ ] Persist reproducible configuration selection, job input and report hashes. Add worker integration, progress/cancellation and JSON/CSV exports. Exercise real services against deterministic synthetic fixtures, then commit.

## Increment 3 — Application integration and acceptance

- [ ] Add executable source and validation nodes to Workflow Builder with dataset and prediction lineage checks. Test via persisted artifacts.
- [ ] Add a shared validation panel to Model Hub and Video Tracking Workspace. Use REST-backed dataset import, rater selection, submission, report history, charts and exports. Run the guarded Chromium acceptance test.
- [ ] Run backend/frontend suites, strict typing, Ruff, Prettier, production build, migration and installed CUDA checks. Document empirical data availability, fixture results and remaining limitations. Commit verified changes.
