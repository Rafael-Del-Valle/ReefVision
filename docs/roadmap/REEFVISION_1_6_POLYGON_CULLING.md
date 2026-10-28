# ReefVision 1.6 — polygon viewport culling correctness

**Track D / issue #76; development-only.** No release acceptance is implied.

## Overlap audit

The 1.0–1.5 baseline already has annotation persistence, mask/polygon editing,
class visibility, and executable Workflow Builder infrastructure. The isolated
1.6 branch already culls dense bounding-box and raster-mask SVG overlays.
This change repairs a *display-only* correctness/performance gap rather than
introducing a second geometry or scientific measurement system.

## Gap and implementation

Imported polygon/rotated-box records can have missing or stale stored bounding
boxes while their editor SVG is drawn from `points`. The old culler retained
every missing-bounds polygon (poor performance in dense scenes) and could hide
a visible polygon if its stored bounds were stale.

For polygon-drawn overlays, compute conservative image-space extents from
finite vertex coordinates and use inclusive viewport intersection. Retain
malformed/short/incomplete geometry instead of assuming it is offscreen.
Raster-mask overlays with a valid content path use raster bounds, **not**
unrelated polygon points. The editor actually renders legacy raster records
with a null/absent/blank `mask_path` as polygon fallbacks when vertices exist.
Culling now shares the renderer's raster-eligibility predicate and uses those
drawn polygon vertices for fallback records, not stale raster bounds. Invalid
polygon vertices or unknown bounds remain conservatively visible for manual
inspection; null records are not drawable. Original mask records, IDs, class
visibility, reviewer decisions and saved annotations are not modified.

## Regression evidence

- `apps/web/src/features/annotation-editor/viewportCulling.test.ts`:
  10,000 missing-bounds polygon overlays, edge-touching geometry, stale
  metadata in both directions, malformed polygon points, raster-mask
  uncertainty, missing/blank raster paths with both stale-inside and
  stale-outside bounds, renderer/fallback agreement, and source-array
  preservation.
- An isolated TypeScript strict compilation and seven JavaScript assertions
  of the new geometry-selection algorithm passed on Linux/Node 22. This is
  **not** a complete repository Vitest or browser test.
- Require exact-commit frontend Vitest, TypeScript, Prettier, Playwright
  dense-scene interaction, and installed Windows GUI profiling before
  accepting the feature for release. Browser responsiveness and GPU memory
  have not been measured here.

## Workflow Builder contract

This is a viewport-only optimization. Existing standalone annotation/QC
APIs and the executable persisted `qc_review_queue` Workflow Builder node
remain the authoritative scientific paths; neither stored graph/runs nor
typed provenance artifacts are changed. Do not add a duplicate rendering
node to Workflow Builder.

**Remaining 1.6 release gates:** actual MSI upgrade/rollback, interactive
installed-GUI scientific acceptance, cross-version Alembic reconciliation,
and full lint/type/backend/frontend/E2E at the accepted SHA. Do not merge,
tag, publish, download pretrained weights, or modify user assets.

## 2026-10-28 — Raster fallback display/culling consistency

Read-only inspection of the actual `AnnotationEditor.tsx` SVG renderer found
that a `raster_mask` with `mask_path: null` is rendered as a polygon when
points exist. The preceding culler treated every `raster_mask` as a raster,
even with no path; that could hide a visible polygon or retain an offscreen
polygon. The shared `usesRasterMaskOverlay` predicate now selects the same
rendering geometry in both paths and treats absent/empty/whitespace paths as
non-renderable raster content. Standalone unit regressions cover both mismatch
directions and malformed polygon safety. This changes only viewport display,
not scientific data or Workflow Builder graph execution. Full exact-head
Vitest/TypeScript/E2E and installed-Windows-GUI validation remain required.
A separate Linux Node 22/TypeScript 5.8 strict source-representative harness
passed 12 raster/polygon-fallback assertions. This does **not** establish that
the full repository tests or React rendering passed.
