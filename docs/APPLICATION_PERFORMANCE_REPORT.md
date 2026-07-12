# ReefVision 1.6.0 Application Performance Report

## Scope

This report covers the `1.6.0` performance slice implemented in this pass:

- lightweight project dashboard loading via `/api/v1/project-summaries`;
- lightweight Training draft loading via `/api/v1/projects/{project_id}/training-draft-summaries`;
- per-draft detail loading via `/api/v1/training-drafts/{draft_id}`;
- debounced Training draft saves in the web client;
- SQL-backed QC issue paging and filtering.

The broader `1.6.0` request still includes additional work for Annotation Editor loading, class management, class visibility, QC actions, and packaged-desktop validation.

## Fixture

Measured with a local FastAPI `TestClient` benchmark harness using:

- 101 projects total;
- 6 classes per project;
- 250 training drafts on one project;
- 10,000 QC issues on one completed QC run.

## Measured Results

### Project creation

- `POST /api/v1/projects`: `80.45 ms`

### Project dashboard payload reduction

- `GET /api/v1/projects?include_archived=true`
  - `22.14 ms`
  - `224,763 bytes`
  - `101 projects`
- `GET /api/v1/project-summaries?include_archived=true`
  - `10.26 ms`
  - `35,470 bytes`
  - `101 projects`

Observed improvement for the dashboard list:

- response payload reduced by about `84%`;
- request time reduced by about `54%`.

### Training draft payload reduction

- `GET /api/v1/projects/{project_id}/training-drafts`
  - `26.12 ms`
  - `442,947 bytes`
  - `250 drafts`
- `GET /api/v1/projects/{project_id}/training-draft-summaries`
  - `24.70 ms`
  - `109,285 bytes`
  - `250 drafts`
- `GET /api/v1/training-drafts/{draft_id}`
  - `8.02 ms`
  - `1,772 bytes`

Observed improvement for Training loading:

- draft list payload reduced by about `75%`;
- full draft detail now loads only for the selected draft;
- draft editing no longer sends one PATCH per keystroke in the web client.

### QC issue paging

- `GET /api/v1/quality-control-runs/{run_id}/issues?page=1&page_size=50&class_id=class-1`
  - `118.79 ms`
  - `36,405 bytes`
  - `5,000 matching issues`
  - `50 items returned`

This endpoint now filters and pages in SQL instead of fetching the full run into Python first.

## Files Changed In This Slice

- `apps/api/reefvision/api/routes/projects.py`
- `apps/api/reefvision/api/routes/training.py`
- `apps/api/reefvision/repositories/projects.py`
- `apps/api/reefvision/repositories/quality_control.py`
- `apps/api/reefvision/repositories/training.py`
- `apps/api/reefvision/schemas/projects.py`
- `apps/api/reefvision/schemas/training.py`
- `apps/api/reefvision/services/projects.py`
- `apps/api/reefvision/services/training.py`
- `apps/api/reefvision/tests/test_projects.py`
- `apps/api/reefvision/tests/test_quality_control.py`
- `apps/api/reefvision/tests/test_training_workspace.py`
- `apps/web/src/App.test.tsx`
- `apps/web/src/App.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/features/training/TrainingWorkspace.tsx`

## Remaining Work

Still pending for the larger `1.6.0` milestone:

- measured Annotation Editor startup and image-switch improvements;
- remaining class-management work such as explicit reassign-and-delete flows and deeper compatibility tooling;
- visibility persistence beyond the current editor session;
- expanded QC actions and bulk operations;
- route-level code splitting for more heavy workspaces;
- packaged desktop benchmark and installer validation;
- consolidated before/after browser-side render and long-task instrumentation.
