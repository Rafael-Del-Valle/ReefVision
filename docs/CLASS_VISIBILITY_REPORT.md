# Class Visibility Report

## Completed In This Pass

- Preserved the existing session-local visibility workflow in the Annotation Editor.
- Added persisted `My Preference` visibility by stable local-user identity, project, and layer.
- Added persisted `Project Default` visibility by project and layer.
- Added supported layer keys for:
  - `annotations`
  - `predictions`
  - `qc_overlays`
  - `video_tracks`
  - `segmentation_overlays`
- Implemented precedence in the editor as:
  - session override
  - my preference
  - project default
  - visible by default
- Kept visibility changes local and immediate:
  - no annotation refetch
  - no editor reload
  - no annotation rewrites
- Split annotation visibility from prediction visibility so hiding a class for boxes no longer hides prediction proposals unless the prediction layer is configured separately.
- Added Alembic revision `0012` for visibility persistence tables.

## API Surface

- `GET /api/v1/projects/{project_id}/class-visibility`
- `PUT /api/v1/projects/{project_id}/class-visibility/preferences/{layer_type}`
- `DELETE /api/v1/projects/{project_id}/class-visibility/preferences/{layer_type}`
- `PUT /api/v1/projects/{project_id}/class-visibility/defaults/{layer_type}`
- `DELETE /api/v1/projects/{project_id}/class-visibility/defaults/{layer_type}`

## Editor Controls Added

- `Show all`
- `Hide all`
- `Invert`
- `Reset Session`
- `Save as My Preference`
- `Save as Project Default`
- `Reset My Preferences`
- `Reset to Project Defaults`
- `Copy Current Visibility to Project Defaults`
- `Apply Project Defaults to My Preferences`

## Validation

Passed:

- `python -m pytest apps/api/reefvision/tests/test_class_visibility.py -q`
- `python -m pytest apps/api/reefvision/tests/test_projects.py apps/api/reefvision/tests/test_class_visibility.py -q`
- `python -m ruff check apps/api/reefvision/services/class_visibility.py apps/api/reefvision/api/routes/class_visibility.py apps/api/reefvision/repositories/class_visibility.py apps/api/reefvision/schemas/class_visibility.py apps/api/reefvision/storage/identity.py apps/api/reefvision/tests/test_class_visibility.py`
- `python -m alembic -c apps/api/alembic.ini upgrade head`
- `python -m alembic -c apps/api/alembic.ini downgrade 0011`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test -- AnnotationEditor.test.tsx App.test.tsx`
- `npm --prefix apps/web run build`

Still not complete in this report:

- temporary QC reveal and restore behavior inside the QC editor flow
- saved visibility UI outside the Annotation Editor
- packaged-desktop validation of the new visibility controls
