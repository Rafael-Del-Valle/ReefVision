# ReefVision 1.0.2 release notes

**Status:** In development. This is not a published release.

ReefVision 1.0.2 builds from the complete 1.0.1 implementation at commit `70da46deceebe56ecc1c58240e950c08ae581360`. It focuses on everyday annotation navigation and reliability while retaining the annotation intelligence, SAM refinement, verified learning, held-out evaluation, and local-model policy delivered in 1.0.1.

## Planned user-visible changes

- Reliable first-image selection and per-project recent-image restoration.
- Viewer-scoped Arrow, Home, End, and Escape navigation with optional wrapping.
- Alt plus left-drag and middle-button panning, cursor-centered wheel zoom, Fit, Actual Size, and Reset View.
- Internal annotation copy, paste, and duplicate commands with undo/redo and safe source-pixel bounds.
- A keyboard-shortcuts reference, shortcut tooltips, and clearer active-tool feedback.
- Better recovery for missing or corrupt image assets and asynchronous image switching.

## Scientific safeguards

Original images remain immutable. Clipboard-created annotations receive new identities and do not inherit verification, review, audit, prediction-acceptance, or evaluation-only status. Geometry remains in source-image pixels and is never silently rescaled between images. Navigation does not change annotations, model state, immutable snapshots, promotion state, or held-out evaluation data.

## Upgrade compatibility

The planned change uses existing persistence contracts and requires no database migration. Existing 1.0.1 projects, classes, annotations, masks, provenance, and dataset versions remain compatible. Historical 1.0.0 and 1.0.1 release artifacts are unchanged.

## Current limitations

The annotation clipboard is internal to the running ReefVision application and does not promise cross-application clipboard interchange. Platform-reserved Alt or mouse gestures may vary. Exact-head automated tests, Windows package validation, and any unavailable physical desktop checks will be recorded in `docs/RELEASE_1.0.2.md` before release review.
