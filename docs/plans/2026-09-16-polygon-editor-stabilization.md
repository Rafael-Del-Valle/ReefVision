# ReefVision 1.0.3 Polygon Editor Stabilization Plan

**Milestone:** 1.0.3 annotation-editor stabilization

## Scope

Stabilize polygon creation and vertex editing without changing ReefVision's persistence contracts or scientific data model.

## Evidence / root cause

`PolygonMaskLayer` already handles `Delete` and `Backspace` for selected masks, but `EnhancedAnnotationEditor` installs a capture-phase key handler that stops those keys before the layer receives them. The integrated editor therefore disagrees with the lower-level component and leaves the keyboard deletion path unreachable in normal use.

The current first-node polygon closure is intentional and remains unchanged. Visible Move node / Insert node / Delete node modes also remain unchanged.

## File-level plan

1. `apps/web/src/features/annotation-editor/EnhancedAnnotationEditor.test.tsx`
   - Change the integration regression so Delete/Backspace must reach the polygon layer while Enter remains blocked for first-node closure.
2. `apps/web/src/features/annotation-editor/EnhancedAnnotationEditor.tsx`
   - Remove only the capture-phase suppression of Delete/Backspace; preserve the Enter suppression and visible vertex-mode behavior.
3. `apps/web/tests/e2e/milestone2-mask-acceptance.spec.ts`
   - Strengthen the polygon acceptance path to verify vertex movement changes geometry, whole-polygon keyboard deletion works, Undo restores the polygon, and the edited geometry survives save/reopen.

## Verification

Run the focused frontend unit tests, full Vitest suite, Playwright E2E suite, TypeScript typecheck, formatting check, and production build through the repository CI workflow. Do not claim completion while any acceptance test fails.
