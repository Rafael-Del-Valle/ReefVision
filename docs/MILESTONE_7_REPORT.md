# Milestone 7 Report

## Summary

This pass implements ReefVision Milestone 7 foundations for:

- versioned historical annotation quality-control runs;
- persisted quality-control issues with measured values and thresholds;
- deterministic review-queue generation with explainable score breakdowns; and
- annotation-editor round-trip navigation from QC findings and ranked review items.

The backend and frontend implementation is in place and the core regression suite passes. Milestone 7 cannot be claimed fully complete in this environment because the browser workflow verification is blocked by local Playwright and Node-runtime permission failures, and the desktop production build is blocked by a missing MSVC linker prerequisite before NSIS packaging can begin.

## Completion status

| Area | Status | Notes |
|---|---|---|
| Backend QC and review-queue implementation | Complete | Models, migration, services, routes, and worker integration are present. |
| Frontend QC and review-queue dashboards | Complete | Tabs, filters, issue or queue actions, and annotation-editor context handoff are present. |
| Documentation | Complete for Milestone 7 scope | README, changelog, architecture, data model, product spec clarifications, new user guides, and this report were added or updated. |
| Browser workflow verification | Incomplete in this environment | Playwright Chromium launch fails with `spawn EPERM`; in-app browser fallback also hit a local permission error in the embedded Node runtime. |
| Desktop packaged verification | Incomplete in this environment | Desktop build stops early because `link.exe` is unavailable, so NSIS packaging, installer checksum, and upgrade-over-previous-version checks could not complete. |

## Files changed

### Backend

- `apps/api/migrations/versions/0007_quality_control_and_review_queues.py`
- `apps/api/reefvision/api/router.py`
- `apps/api/reefvision/api/routes/quality_control.py`
- `apps/api/reefvision/api/routes/review_queues.py`
- `apps/api/reefvision/db/models/__init__.py`
- `apps/api/reefvision/db/models/quality_control_issue.py`
- `apps/api/reefvision/db/models/quality_control_run.py`
- `apps/api/reefvision/db/models/review_queue.py`
- `apps/api/reefvision/db/models/review_queue_item.py`
- `apps/api/reefvision/domain/enums.py`
- `apps/api/reefvision/jobs/quality_control.py`
- `apps/api/reefvision/jobs/worker.py`
- `apps/api/reefvision/ml/providers.py`
- `apps/api/reefvision/repositories/quality_control.py`
- `apps/api/reefvision/repositories/review_queues.py`
- `apps/api/reefvision/schemas/quality_control.py`
- `apps/api/reefvision/schemas/review_queues.py`
- `apps/api/reefvision/services/jobs.py`
- `apps/api/reefvision/services/quality_control.py`
- `apps/api/reefvision/services/review_queues.py`

### Frontend

- `apps/web/src/App.tsx`
- `apps/web/src/App.test.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/features/annotation-editor/AnnotationEditor.tsx`
- `apps/web/src/features/quality-control/QualityControlDashboard.tsx`
- `apps/web/src/features/review-queues/ReviewQueueDashboard.tsx`
- `apps/web/src/styles/app.css`
- `apps/web/tests/e2e/milestone-7.spec.ts`

### Documentation

- `README.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/REEFVISION_PRODUCT_SPEC.md`
- `docs/DESKTOP_BUILD_AND_INSTALL.md`
- `docs/PRIORITIZATION_VS_CALIBRATED_UNCERTAINTY.md`
- `docs/QUALITY_CONTROL_GUIDE.md`
- `docs/QUALITY_CONTROL_RULE_REFERENCE.md`
- `docs/QUALITY_CONTROL_THRESHOLDS.md`
- `docs/REVIEW_PRIORITIZATION_FORMULA.md`
- `docs/REVIEW_QUEUE_GUIDE.md`
- `docs/MILESTONE_7_REPORT.md`

## Migration

Added reversible Alembic migration `0007_quality_control_and_review_queues.py`.

The migration creates:

- `quality_control_runs`
- `quality_control_issues`
- `review_queues`
- `review_queue_items`

The migration also adds indexes for common run, issue, queue, and queue-item filters so historical QC and review-queue data remains queryable without loading the full result set.

## Quality-control architecture

Milestone 7 introduces a versioned QC rule interface implemented in `apps/api/reefvision/services/quality_control.py`.

Key design points:

- rule logic is separate from API routes, persistence, worker execution, and frontend rendering;
- rules evaluate a deterministic `QualityControlContext` built from project or dataset-version scope;
- every issue stores rule ID, rule version, severity, measured values, thresholds, scope references, and a stable fingerprint;
- QC execution runs through background jobs of type `qc`;
- cancelled, failed, and historical runs are preserved rather than rewritten.

The current QC ruleset version is `1.0.0`.

## Implemented rules

Current ruleset categories:

- `annotation_geometry`
- `annotation_semantics`
- `image_integrity`
- `predictions`
- `statistics`
- `dataset_versions`

Implemented rule IDs:

- `invalid_bounding_box`
- `zero_area_box`
- `small_box`
- `out_of_bounds_box`
- `boundary_touching_box`
- `exact_duplicate_box`
- `near_duplicate_box`
- `same_class_overlap`
- `different_class_overlap`
- `missing_or_invalid_class`
- `annotation_unavailable_image`
- `reviewed_without_annotations`
- `annotation_count_outlier`
- `class_imbalance`
- `missing_group_key`
- `prediction_unmapped_class`
- `accepted_prediction_missing_provenance`
- `suspicious_bulk_acceptance`
- `dataset_manifest_inconsistency`
- `inconsistent_split_metadata`
- `missing_image_checksum`
- `broken_managed_file_reference`

All current rule versions are `1.0.0`.

## Threshold behavior

The current typed QC threshold configuration includes:

- `small_box_min_width_px`
- `small_box_min_height_px`
- `near_duplicate_iou_threshold`
- `same_class_overlap_iou_threshold`
- `different_class_overlap_iou_threshold`
- `boundary_touch_margin_px`
- `annotation_count_mad_multiplier`
- `class_imbalance_majority_ratio`
- `suspicious_bulk_acceptance_min_count`
- `suspicious_bulk_acceptance_window_minutes`
- `overlap_spatial_cell_px`

Thresholds are stored both on the QC run and on any issues that depend on them, so rerunning with different sensitivity preserves historical behavior instead of rewriting old findings.

## Statistical methods

`annotation_count_outlier` uses a deterministic median and median-absolute-deviation method:

- compute per-image annotation counts;
- compute the median count;
- compute MAD;
- fall back to scale `1.0` when MAD is zero;
- flag high or low outliers when the MAD score crosses the configured multiplier.

`class_imbalance` reports scope-level class skew and missing classes without changing any class map or annotation data.

## Run-history behavior

Each rerun creates a new `quality_control_runs` record.

Historical behavior implemented in this pass:

- old runs remain inspectable after corrections;
- new runs no longer include disappeared findings;
- old issues can be marked `resolved_in_later_run` when the same fingerprint is absent from a later successful run;
- acknowledgement and dismissal are separate from resolution and do not mutate annotation data.

## Prioritization formula

Current review formula metadata:

- Formula ID: `review_priority_v1`
- Formula version: `1.0.0`

Current scoring signals:

- `low_mean_confidence`
- `low_min_confidence`
- `pending_proposals`
- `rejection_rate`
- `count_disagreement`
- `unresolved_qc_severity`
- `rare_class_presence`
- `edited_acceptance_rate`
- `unreviewed_state`
- `missing_group_metadata`
- `incomplete_provenance`
- `recent_import`
- `stale_review_state`

The formula stores:

- raw signal values;
- normalized signal values;
- configured weights;
- final score;
- score breakdown;
- source QC run ID where applicable;
- item input checksum;
- generation metadata.

The current severity contribution mapping is:

- `error -> 1.0`
- `warning -> 0.6`
- `info -> 0.3`

This is a deterministic prioritization score, not calibrated uncertainty.

## Review-queue behavior

The review-queue subsystem supports:

- project or dataset-version scope;
- optional seeding from a selected completed QC run;
- historical queue preservation;
- filtering by class, split, QC severity, review state, and model ID;
- queue-item states of `pending`, `in_progress`, `completed`, and `skipped`;
- skip reasons;
- regeneration into a new queue record rather than rewriting old queues.

Queue generation does not modify annotations, predictions, dataset versions, or model state.

## API endpoints

### Quality control

- `GET /api/v1/projects/{project_id}/quality-control-runs`
- `POST /api/v1/projects/{project_id}/quality-control-runs`
- `GET /api/v1/dataset-versions/{version_id}/quality-control-runs`
- `POST /api/v1/dataset-versions/{version_id}/quality-control-runs`
- `GET /api/v1/quality-control-runs/{run_id}`
- `POST /api/v1/quality-control-runs/{run_id}/cancel`
- `GET /api/v1/quality-control-runs/{run_id}/issues`
- `GET /api/v1/quality-control-runs/{run_id}/compare`
- `POST /api/v1/quality-control-issues/{issue_id}/acknowledge`
- `POST /api/v1/quality-control-issues/{issue_id}/dismiss`

### Review queues

- `GET /api/v1/projects/{project_id}/review-queues`
- `POST /api/v1/projects/{project_id}/review-queues`
- `GET /api/v1/dataset-versions/{version_id}/review-queues`
- `POST /api/v1/dataset-versions/{version_id}/review-queues`
- `GET /api/v1/review-queues/{queue_id}`
- `GET /api/v1/review-queues/{queue_id}/items`
- `POST /api/v1/review-queue-items/{item_id}/start`
- `POST /api/v1/review-queue-items/{item_id}/complete`
- `POST /api/v1/review-queue-items/{item_id}/skip`
- `POST /api/v1/review-queue-items/{item_id}/return`
- `POST /api/v1/review-queues/{queue_id}/regenerate`

## Frontend workflows

Added project-level tabs:

- `Quality Control`
- `Review Queue`

Quality Control dashboard behavior:

- choose project or dataset-version scope;
- select rule categories;
- configure common thresholds;
- view historical runs and current run status;
- filter issues by severity, rule, class, image, and issue status;
- compare runs;
- acknowledge or dismiss issues;
- open the affected image in annotation mode.

Review Queue dashboard behavior:

- choose project or dataset-version scope;
- optionally choose a completed QC run;
- adjust prioritization weights;
- generate or regenerate queues;
- filter ranked items;
- start, complete, skip, or return queue items;
- open the ranked image in annotation mode.

Annotation editor integration now:

- preserves the originating workflow through `returnLabel`;
- shows a QC or queue context banner;
- highlights relevant annotations or predictions where IDs are available.

## Browser verification

### Implemented browser coverage

Added Playwright browser specs in `apps/web/tests/e2e/milestone-7.spec.ts` for:

- QC run generation and issue navigation into annotation mode;
- review-queue generation, item state transition, and return from annotation mode.

### Executed command and result

`& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run test:e2e -- tests/e2e/milestone-7.spec.ts`

Result:

- production Vite build passed as part of the script;
- both browser tests failed to launch because Playwright Chromium hit `browserType.launch: spawn EPERM`.

### Fallback attempt

An in-app browser fallback was attempted through the Codex browser skill, but the embedded Node runtime failed before browser control could begin with:

- `EPERM: operation not permitted, lstat 'C:\Users\rafae\AppData'`

Conclusion:

- browser workflow code is implemented and covered by new specs;
- browser verification remains environment-blocked rather than code-complete in this session.

## Desktop verification

### Observed runtime state

During investigation, a packaged sidecar process was already running from:

- `.desktop\smoke-install\reefvision-api.exe`

This is relevant to prior Windows file-lock investigations, but it did not determine the current build outcome.

### Executed command and result

`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1`

Result:

- build stopped before NSIS packaging;
- the script reported that Visual Studio Build Tools 2022 was present but `link.exe` was unavailable;
- it requested installation of:
  - `Desktop development with C++`
  - `MSVC v143 - VS 2022 C++ x64/x86 build tools`
  - `Windows 11 SDK` or `Windows 10 SDK`

Conclusion:

- complete desktop production build, installer path verification, installer version verification, and installer SHA-256 checksum generation remain blocked by the local toolchain prerequisite.

## Test commands and exact results

### Backend

`.\.venv\Scripts\python.exe -m ruff format --check apps/api`

- Result: `107 files already formatted`

`.\.venv\Scripts\python.exe -m ruff check apps/api`

- Result: `All checks passed!`

`.\.venv\Scripts\python.exe -m mypy apps/api/reefvision`

- Result: `Success: no issues found in 99 source files`

`.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests -q`

- Result: `50 passed, 1 warning in 13.96s`

`if(Test-Path '.runtime\tmp\milestone7_migration_check'){ Remove-Item -Recurse -Force '.runtime\tmp\milestone7_migration_check' }`
`New-Item -ItemType Directory -Path '.runtime\tmp\milestone7_migration_check' -Force | Out-Null`
`$env:REEFVISION_DATA_DIR=(Resolve-Path '.runtime\tmp\milestone7_migration_check').Path`
`.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini upgrade head`
`.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini downgrade base`

- Result: isolated upgrade through `0007` passed and isolated downgrade back to base passed

### Frontend

`& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run format:check`

- Result: `All matched files use Prettier code style!`

`& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run typecheck`

- Result: passed

`& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run test`

- Result: `7 passed`, `25 passed`

`& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run test:e2e -- tests/e2e/milestone-7.spec.ts`

- Result: production build passed, browser launch failed with `spawn EPERM`

### Packaging

`.\.venv\Scripts\python.exe -m build --no-isolation`

- Result: built `dist/reefvision-1.3.0.tar.gz` and `dist/reefvision-1.3.0-py3-none-any.whl`

### Desktop

`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1`

- Result: failed preflight because `link.exe` was unavailable

## Installer path and checksum

Not available from this pass.

Reason:

- the desktop production build stopped before NSIS bundling because the required MSVC linker toolchain was unavailable.

Expected installer output path once the toolchain is complete:

- `apps/web/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`

## Known limitations

- Playwright browser workflow verification is blocked by local Chromium launch permissions in this environment.
- In-app browser fallback verification is blocked by a separate embedded Node permission error.
- Desktop production packaging is blocked by the local Rust or MSVC linker prerequisite before NSIS can run.
- Installer checksum, installer path confirmation, and upgrade-over-previous-version verification therefore remain incomplete.
- The frontend QC dashboard currently exposes the most commonly tuned threshold fields directly in the UI, while the full typed threshold set is preserved and available at the API layer.

## Specification deviations

- No functional deviation was introduced in the core Milestone 7 architecture, but Milestone 7 cannot be declared fully complete because the required browser and desktop verification steps did not pass in this environment.
- The earlier product-spec wording that suggested images could be marked reviewed directly from the queue was clarified instead of implemented, because Milestone 7’s controlling brief explicitly forbids silent annotation changes during prioritization workflows.

## Explicit non-implementation confirmation

This Milestone 7 pass did not implement:

- model training;
- automatic annotation edits;
- automatic prediction acceptance;
- automatic prediction rejection;
- automatic model retraining;
- automatic active-learning dataset creation;
- model promotion.

Quality-control findings and review-queue scores remain recommendations and historical diagnostic records only.
