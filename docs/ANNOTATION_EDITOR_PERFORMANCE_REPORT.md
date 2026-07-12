# ReefVision 1.6.0 Annotation Editor Performance Report

## Prior State

The prior `1.6.0` performance pass had already preserved:

- thumbnail-first image loading;
- full-image preloading;
- neighboring image prefetch;
- bounded image request behavior;
- editor-session loading per image instead of whole-project annotation loading.

Class visibility existed only as a basic per-class hidden list plus a global show-all reset.

## Changes Made In This Pass

- Kept visibility changes local to editor state so class show or hide does not refetch the annotation session.
- Applied class visibility to prediction-review rows and rendered prediction overlays in addition to saved annotations.
- Added immediate class visibility controls:
  - show all;
  - hide all;
  - invert;
  - reset;
  - per-class solo.
- Replaced repeated linear class lookups in render paths with a memoized class-id map.
- Added a memoized visible-annotation list and memoized visible-prediction list so hide or solo operations stay client-side.

## Files Changed

- `apps/web/src/features/annotation-editor/AnnotationEditor.tsx`
- `apps/web/src/features/annotation-editor/annotationEditorReducer.ts`
- `apps/web/src/features/annotation-editor/AnnotationEditor.test.tsx`
- `apps/web/src/features/annotation-editor/annotationEditorReducer.test.ts`

## Verified Behavior

Passed in this pass:

- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test`
- `npm --prefix apps/web run build`

The new editor tests verify that:

- box-mode class switching still does not mutate the last annotation;
- select-mode reassignment still works;
- visibility changes hide annotations and prediction rows locally;
- visibility changes do not trigger a new annotation-session fetch.

## Known Limitations

- This is not yet the full dense-rendering optimization pass requested for `1.6.0`.
- There is still no QC overlay layer with next/previous issue navigation inside the editor.
- Visibility persistence is currently session-local only; per-user and project-default scopes are still pending.
