# Codex task: ReefVision Milestone 2

Read `AGENTS.md`, `docs/REEFVISION_PRODUCT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, and `docs/MILESTONE_1_REPORT.md` before editing.

Implement **Milestone 2 — Image import and gallery only**. Do not begin manual annotation, YOLO import/export, inference, or dataset versioning.

Before editing, inspect the current repository and provide a concise file-level plan. Then implement the milestone with the following required scope:

1. Add `images` and `jobs` SQLAlchemy models and a new reversible Alembic migration. Do not edit prior migrations.
2. Support managed-copy import for JPEG, PNG, TIFF, and WebP.
3. Validate images, calculate SHA-256, record dimensions, media type, file size, available metadata, and original source path.
4. Detect exact duplicates within a project before copying.
5. Use safe atomic copy behavior and clean incomplete files after failures.
6. Generate thumbnails through persisted background jobs with retryable failure states.
7. Produce an import report separating successful, duplicate, unsupported, and failed files.
8. Add stable paginated image-list endpoints with filename, annotation-status, and group-key filters.
9. Allow `group_key` and image status updates.
10. Build a responsive project gallery with thumbnails, filename, dimensions, status, group key, and empty/missing-thumbnail states.
11. Add backend unit/integration tests, frontend component tests, and Playwright setup for the first complete browser workflow.
12. Update documentation, changelog, and the milestone report.

Follow every requirement in `AGENTS.md`. Run formatting, linting, strict typing, backend tests, frontend tests, Playwright tests, production builds, and Alembic upgrade/downgrade verification. Report changed files, migration name, test results, manual verification, known limitations, and any specification deviations.

Do not claim completion unless every Milestone 2 acceptance test passes.
