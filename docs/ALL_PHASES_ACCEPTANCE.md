# ReefVision all-phase acceptance

## Windows entry point

Run this command from the ReefVision repository root:

```powershell
.\scripts\run-all-phases-acceptance.ps1
```

This wrapper runs the static/backend/frontend acceptance suite and then performs the database migration round trip using ReefVision's actual `REEFVISION_DATA_DIR` and `REEFVISION_DATABASE_FILENAME` settings.

## Automated checks

The acceptance workflow covers:

- Ruff lint and formatting;
- strict mypy;
- focused tests for Phases 1 through 10;
- the complete backend test suite unless skipped;
- frontend formatting and TypeScript checks;
- frontend unit tests;
- the production frontend build unless skipped;
- an Alembic `0019 -> 0023 -> 0019 -> head` round trip on a disposable database;
- environment and commit metadata written beneath `.desktop/acceptance/all-phases`.

Optional flags:

```powershell
.\scripts\run-all-phases-acceptance.ps1 -SkipFullSuites
.\scripts\run-all-phases-acceptance.ps1 -SkipFrontendBuild
.\scripts\run-all-phases-acceptance.ps1 -SkipMigrationRoundTrip
```

## Manual release gates

Passing the script does not replace the following checks:

- real YOLO and nnU-Net segmentation runs;
- representative manual coral measurement comparisons;
- real six-class and binary classifier training and inference;
- real ByteTrack and BoT-SORT fish-video validation;
- real SAM-family point-prompt acceptance;
- COCO archive testing in external tools;
- application restart-persistence testing;
- packaged Windows installation and smoke testing;
- Phase 10 workflow execution, artifact handoff, recovery, and GPU scheduling.

The all-phase pull request should remain a draft until automated checks run successfully and the applicable real-model and packaged-application gates are completed.
