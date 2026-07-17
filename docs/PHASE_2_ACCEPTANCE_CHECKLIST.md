# Phase 2: Editable Mask Annotations — Acceptance Checklist

## Implemented

- Polygon creation in source-image coordinates.
- Polygon closure by clicking the first node after at least three vertices.
- Polygon selection, class reassignment, undo, redo, and explicit whole-polygon deletion.
- Polygon vertex movement.
- Visible **Move nodes**, **Insert node**, and **Delete node** controls.
- Edge-based node insertion.
- Node-only deletion with a protected three-node minimum.
- Independent visibility toggles for boxes, polygons, and raster masks.
- Raster paint and erase tools.
- One raster layer selected and reused by default.
- Explicit **Create another mask** action for additional raster instances.
- Immutable raster revisions.
- Autosave, revision-conflict handling, and persistence across application restarts.
- Polygon and raster class counts.
- Synchronization with the active image.
- Backend geometry validation, audit events, and soft deletion.
- Automated unit, API, migration, and frontend coverage for the implemented paths.

## Remaining acceptance work

1. Run the full current-head validation and Windows MSI build.
2. Confirm in the packaged desktop app that:
   - clicking the first node closes a polygon and Enter does not;
   - Move nodes drags and persists a vertex;
   - Insert node adds one node on the clicked edge and persists it;
   - Delete node removes only the clicked node and never reduces a polygon below three nodes;
   - Delete and Backspace do not remove a whole polygon;
   - the explicit **Delete selected masks** action still removes a selected polygon;
   - boxes, polygons, and raster masks can each be hidden independently;
   - visibility changes do not modify or delete saved annotations;
   - raster paint continues the selected/default mask;
   - **Create another mask** is the only normal path that starts another raster instance;
   - raster erase, mask switching, and persistence still work.
3. Exercise invalid polygon edits in the desktop app:
   - self-intersection;
   - duplicate vertices;
   - out-of-bounds coordinates;
   - attempted removal from a three-node polygon.
4. Confirm autosave and revision-conflict messaging after polygon node edits and raster edits.
5. Reopen the project after a complete application restart and verify all mask geometry and revisions remain intact.

## Completion rule

Phase 2 is complete when the current-head validation passes and every packaged-desktop check above passes without annotation loss, silent geometry corruption, or unintended creation/deletion of mask instances.
