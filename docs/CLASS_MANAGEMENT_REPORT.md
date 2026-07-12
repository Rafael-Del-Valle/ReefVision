# ReefVision 1.6.0 Class Management Report

## Prior State

Before this pass, ReefVision supported only:

- class creation;
- rename;
- recolor;
- display-order edits;
- deactivate-only lifecycle.

There was no class description field, no restore action, no usage report, no safe delete path, and no merge workflow for mutable references.

## Changes Made

- Added `description` and `archived_at` to `label_classes`.
- Added class usage reporting across:
  - active annotations;
  - deleted annotations;
  - annotation history events;
  - prediction proposals;
  - QC issues;
  - review-queue items;
  - immutable dataset versions;
  - registered model class maps.
- Added safe class actions:
  - archive;
  - restore;
  - delete unused;
  - merge into another active class.
- Merges now:
  - reassign active annotations;
  - append `class_merged` annotation events;
  - reassign prediction proposals;
  - update QC issue class references;
  - update review-queue class references;
  - archive the source class;
  - leave immutable dataset versions and model class maps untouched.
- Replaced the old inline class editor with a fuller class manager panel in the web app.

## Files Changed

- `apps/api/migrations/versions/0011_label_class_management_fields.py`
- `apps/api/reefvision/api/routes/projects.py`
- `apps/api/reefvision/db/models/label_class.py`
- `apps/api/reefvision/schemas/projects.py`
- `apps/api/reefvision/services/projects.py`
- `apps/api/reefvision/tests/test_projects.py`
- `apps/web/src/App.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/features/classes/ClassManagerPanel.tsx`
- `apps/web/src/styles/app.css`

## Migration

- New Alembic revision: `0011`
- Upgrade adds `description` and `archived_at` to `label_classes`.
- Downgrade removes both fields.

## Verification

Passed in this pass:

- `python -m pytest apps/api/reefvision/tests/test_projects.py -q`
- `python -m pytest apps/api/reefvision/tests/test_projects.py apps/api/reefvision/tests/test_quality_control.py apps/api/reefvision/tests/test_training_workspace.py -q`
- `python -m ruff check apps/api/reefvision/services/projects.py apps/api/reefvision/schemas/projects.py apps/api/reefvision/api/routes/projects.py apps/api/reefvision/tests/test_projects.py --fix`
- `python -m alembic -c apps/api/alembic.ini upgrade head`
- `python -m alembic -c apps/api/alembic.ini downgrade 0010`

## Known Limitations

- Reassign-and-delete for used classes is still not implemented as a distinct workflow.
- Open-affected-annotations and open-affected-predictions shortcuts are not wired into the class manager yet.
- Dataset and model compatibility is reported as warnings in the usage report, but there is not yet a dedicated compatibility inspector UI.
- Full `1.6.0` class-management scope is still incomplete until those remaining workflows are added.
