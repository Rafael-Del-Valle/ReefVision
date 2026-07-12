# Codex task: ReefVision Milestone 3

Read `AGENTS.md`, `docs/REEFVISION_PRODUCT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, and `docs/MILESTONE_2_REPORT.md` before editing.

Implement **Milestone 3 — Manual bounding-box annotation only**. Do not begin YOLO import/export, inference, dataset versions, active learning, segmentation, or video tracking.

Before editing, inspect the current repository and provide a concise file-level plan. Then implement the milestone with the following required scope:

1. Add `annotations`, `annotation_events`, and image-level revision persistence through a new reversible Alembic migration. Do not edit prior migrations.
2. Store canonical bounding boxes in original source-image pixels.
3. Add transactional batch operations for create, update, class change, delete, and restore.
4. Require expected revisions and return HTTP 409 for stale image or annotation edits.
5. Record append-only events for every committed annotation mutation.
6. Build a full-screen React/Konva annotation editor with fit, pan, cursor-centered zoom, draw, select, move, resize, class change, delete, multi-select, class visibility, and next/previous image navigation.
7. Add session undo/redo that remains consistent with autosave.
8. Add debounced autosave, explicit saving/saved/error states, and retained retryable operations after a failed save.
9. Add class keyboard shortcuts and ensure shortcuts do not trigger while typing in form controls.
10. Add per-image and per-class annotation counts and status controls.
11. Optimize rendering and selection for the 1,500-box fixture acceptance case.
12. Add backend unit/integration tests, frontend component tests, coordinate-transform tests, and a Playwright browser workflow.
13. Update documentation, changelog, and the milestone report.

Follow every requirement in `AGENTS.md`. Run formatting, linting, strict typing, backend tests, frontend tests, Playwright tests, production builds, and Alembic upgrade/downgrade verification. Report changed files, migration name, test results, manual verification, known limitations, and any specification deviations.

Do not claim completion unless every Milestone 3 acceptance test passes.
