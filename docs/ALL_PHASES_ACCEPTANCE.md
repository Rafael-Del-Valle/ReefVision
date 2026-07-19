# ReefVision all-phase acceptance

## Provider-free acceptance

Run this command from the ReefVision repository root:

```powershell
.\scripts\run-all-phases-acceptance.ps1
```

This wrapper runs the static/backend/frontend acceptance suite and performs a database migration round trip using ReefVision's actual `REEFVISION_DATA_DIR` and `REEFVISION_DATABASE_FILENAME` settings.

The provider-free workflow covers:

- Ruff lint and formatting;
- strict mypy;
- focused tests for Phases 1 through 10;
- the complete backend test suite unless skipped;
- frontend formatting and TypeScript checks;
- frontend unit tests;
- the production frontend build unless skipped;
- an Alembic round trip through the current linear migration head;
- environment and commit metadata beneath `.desktop/acceptance/all-phases`.

Optional flags:

```powershell
.\scripts\run-all-phases-acceptance.ps1 -SkipFullSuites
.\scripts\run-all-phases-acceptance.ps1 -SkipFrontendBuild
.\scripts\run-all-phases-acceptance.ps1 -SkipMigrationRoundTrip
```

## Complete Windows release gate

Run the full release sequence, including browser and packaged-desktop checks, with:

```powershell
.\scripts\run-release-validation.ps1
```

The release runner preserves one log per gate plus `release-validation-summary.json` beneath `.artifacts/release-validation-<timestamp>`. It runs:

- environment bootstrap;
- Ruff lint and formatting;
- strict mypy;
- the complete pytest suite;
- `upgrade head -> downgrade 0019 -> upgrade head -> downgrade base -> upgrade head` against a disposable database;
- npm lockfile verification and clean installation;
- Prettier, TypeScript, Vitest, and the production frontend build;
- Chromium installation and Playwright browser tests;
- `cargo fmt --check` and target-specific `cargo check --locked`;
- Tauri MSI packaging;
- packaged API-sidecar smoke testing;
- MSI output inventory.

Useful release-runner options:

```powershell
.\scripts\run-release-validation.ps1 -SkipBootstrap
.\scripts\run-release-validation.ps1 -SkipPackaging
.\scripts\run-release-validation.ps1 -TargetTriple aarch64-pc-windows-msvc
```

## Manual and hardware acceptance

Passing either script does not replace:

- real YOLO and nnU-Net segmentation runs;
- representative manual coral measurement comparisons;
- real six-class and binary classifier training and inference;
- real ByteTrack and BoT-SORT fish-video validation;
- real SAM-family point-prompt and SAM 2 video acceptance;
- metric-depth and camera-calibration validation;
- COCO, panoptic, CVAT, LabelMe, and Roboflow round trips in external tools;
- multi-GPU scheduling tests on the intended workstation;
- clean-machine Windows installation and uninstall testing.

The all-phase pull request should remain a draft until the automated checks run successfully and the applicable real-model, hardware, scientific, and packaged-application gates are completed.
