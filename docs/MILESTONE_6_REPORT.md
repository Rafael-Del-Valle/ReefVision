# Milestone 6 Report

## Summary

This pass implements ReefVision Milestone 6 foundations for immutable dataset versions, leakage-aware split previews, version comparison, and queued YOLO detection exports from frozen snapshots.

## Implemented

- Added reversible Alembic migration `0006` plus SQLAlchemy models for `dataset_versions`, `dataset_version_items`, and `exports`.
- Added backend preview and creation APIs for immutable dataset versions with:
  - project-local sequential version numbers;
  - image-status eligibility filters;
  - seeded random and group-aware splitting;
  - manual split assignment support;
  - optional parent-version reuse for compatible split assignments;
  - stable manifest checksum generation.
- Added per-image frozen annotation snapshots so later working edits do not mutate prior dataset versions.
- Added dataset-version comparison APIs for added, removed, and changed images plus annotation deltas.
- Added queued YOLO detection exports backed by the existing jobs table and worker loop.
- Added a new React `Versions` tab for previewing, creating, comparing, and exporting immutable versions.

## Verification

Backend:

- `.\.venv\Scripts\python.exe -m ruff check apps/api/reefvision`
- `.\.venv\Scripts\python.exe -m ruff format --check apps/api`
- `.\.venv\Scripts\python.exe -m mypy apps/api/reefvision`
- `.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests -q`

Frontend:

- `npm --prefix apps/web run format:check`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test`
- `npm --prefix apps/web run build`

Milestone-specific backend acceptance coverage now includes:

- immutable snapshot preservation after working annotations change;
- deterministic split previews with group-aware behavior;
- YOLO export from an old dataset version after current-project edits.

## Known limitations

- Eligibility is currently based on the existing image-level `annotation_status` field because the repository still lacks per-annotation verification states.
- YOLO export output is written to a managed project-relative export directory and then zipped for download; arbitrary user-chosen filesystem destinations remain out of scope for this milestone.
- Playwright browser workflow tests could not complete in this environment because Chromium launch failed with `spawn EPERM`, so browser e2e verification remains environment-blocked rather than code-blocked.
- Milestones 7, 8, and 9 remain unimplemented in this pass.
