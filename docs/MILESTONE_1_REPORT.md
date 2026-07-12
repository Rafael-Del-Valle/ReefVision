# Milestone 1 Completion Report

## Status

Implemented and locally verified on July 8, 2026.

## Delivered

- `projects` and `label_classes` SQLAlchemy models.
- Reversible Alembic migration `0002_projects_and_label_classes.py`.
- Application-instance database engines and session factories so tests and alternate data directories remain isolated.
- Project repository, service, schemas, API routes, and structured domain errors.
- Safe managed project directories stored as portable paths beneath the configured ReefVision data root.
- Project create, list, retrieve, update, and archive operations.
- Label-class list, create, update, reorder, and deactivate operations.
- Stable project-local class indices and separate display ordering.
- Deterministic generated-slug disambiguation and explicit-slug conflict handling.
- Exact six-class octocoral project template from the product specification.
- React project dashboard, project-creation dialog, project detail view, and class-management interface.
- Backend integration tests and frontend component tests.
- Updated setup, architecture, data-model, and changelog documentation.

## API endpoints

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/archive`
- `GET /api/v1/projects/{project_id}/classes`
- `POST /api/v1/projects/{project_id}/classes`
- `PATCH /api/v1/classes/{class_id}`
- `POST /api/v1/classes/{class_id}/deactivate`

## Verification results

- Ruff lint: passed.
- Ruff formatting check: passed.
- mypy strict type check: passed.
- Backend pytest: **12 passed**.
- Frontend Prettier check: passed.
- Frontend TypeScript check: passed.
- Frontend Vitest: **3 passed**.
- Vite production build: passed.
- Python source and wheel builds: passed.
- Alembic blank-database upgrade through migration `0002`: passed.
- Alembic downgrade to `base`: passed.

One non-failing Starlette test-client deprecation warning is emitted by the current dependency combination. It does not affect application behavior or test results.

## Acceptance-test assessment

- Projects persist across application restarts.
- The octocoral template creates exactly six classes with indices 0 through 5.
- Generated duplicate slugs are deterministically suffixed.
- Explicit duplicate slugs are rejected.
- Project-local duplicate class names and indices are rejected.
- The same class name and index may be used in separate projects.
- Archiving hides a project from the default dashboard without deleting its managed directory.
- Project storage paths cannot escape the configured ReefVision data root.
- Class indices are not exposed through update operations; visible ordering uses `display_order` instead.
- Dashboard and class data are reloaded from the API and therefore survive browser refreshes.

## Known limitations

- Project deletion is intentionally not implemented; archiving is the safe Milestone 1 behavior.
- React Router is installed but the Milestone 1 interface uses a single dashboard screen. Dedicated URLs can be introduced when image galleries and editors require them.
- Playwright is not configured yet. Component and API integration tests cover this milestone; browser end-to-end setup should be introduced with the image-import workflow.
- Class reactivation is not yet exposed. Deactivation preserves the class for future annotation lineage.
- Image, annotation, model, prediction, and dataset-version entities remain outside this milestone.

## Next milestone

Milestone 2 should add image records, managed-copy importing, checksum-based duplicate detection, metadata extraction, background thumbnail jobs, group keys, paginated filtering, and the image gallery.
