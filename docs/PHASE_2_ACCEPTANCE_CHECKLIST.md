# Phase 2: Editable Mask Annotations — Acceptance Checklist

## Implemented

- Polygon creation in source-image coordinates.
- Polygon closure by clicking the first node after at least three vertices.
- Polygon selection, class reassignment, undo, redo, and explicit whole-polygon deletion.
- Polygon vertex movement.
- Visible **Move nodes**, **Insert node**, and **Delete node** controls.
- Edge-based node insertion.
- Node-only deletion with a protected three-node minimum.
- The **Annotation type** selector acts as an exclusive filter for bounding boxes, polygons, and raster masks.
- Polygon mode suppresses raster-mask overlays.
- Raster paint and erase tools.
- One raster layer selected and reused by default.
- Explicit **Create another mask** action for additional raster instances.
- Immutable raster revisions.
- Autosave, revision-conflict handling, and persistence across application restarts.
- Polygon and raster class counts.
- Synchronization with the active image.
- Backend geometry validation, audit events, and soft deletion.
- Automated unit, API, migration, and frontend coverage for the implemented paths.

## Automated coverage

The validation suite covers polygon creation and closure, vertex movement, insertion and protected deletion, explicit whole-mask deletion, blocked keyboard deletion, exclusive annotation-type filtering, self-intersection rejection, duplicate-vertex rejection, out-of-bounds rejection, shared revision conflicts, autosave failure messaging, raster paint/erase behavior, immutable raster revisions, migrations, production builds, Rust checks, and MSI creation.

## Required acceptance command

Run from a clean `feat/editable-mask-annotations` checkout:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\phase2-acceptance.ps1
```

The runner:

1. verifies the branch and clean working tree;
2. runs `validate-pr.ps1 -BuildDesktopInstaller`;
3. launches the current packaged release executable;
4. walks through every packaged-desktop check below;
5. restarts ReefVision for persistence verification; and
6. writes a Markdown report under `.desktop/acceptance/`.

Use `-SkipBuild` only when the exact current commit has already passed the full build. Use `-NoLaunch` only for report-only troubleshooting; it is not sufficient for final acceptance.

## Remaining packaged-desktop acceptance work

1. Confirm move, insert, and delete-node edits persist after autosave and workspace switching.
2. Confirm a three-node polygon cannot lose another node.
3. Confirm Delete and Backspace do not remove a whole polygon.
4. Confirm **Delete selected masks** still removes the explicitly selected polygon.
5. Exercise invalid edits and verify visible rejection without annotation loss:
   - self-intersection;
   - duplicate vertices;
   - out-of-bounds coordinates;
   - attempted removal from a three-node polygon.
6. Confirm node and raster edits show Unsaved/Saving/Saved states and revision conflicts are visible.
7. Confirm **Annotation type** filters exclusively:
   - **Bounding boxes** shows only boxes;
   - **Polygons** shows only polygons and no raster overlays;
   - **Raster masks** shows only raster masks;
   - switching types does not modify stored annotations.
8. Confirm raster paint continues the selected/default mask, erase persists, and **Create another mask** is the only normal path that creates another raster instance.
9. Restart the complete application and verify all polygon geometry, raster instance counts, files, and revisions remain intact.

## Completion rule

Phase 2 is complete only when `scripts/phase2-acceptance.ps1` reports **PASS** at the current commit and the generated report contains no `FAIL` or `BLOCKED` result. Do not merge PR #3 before that evidence exists.
