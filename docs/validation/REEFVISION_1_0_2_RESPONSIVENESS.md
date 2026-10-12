# ReefVision 1.0.2 responsiveness evidence

This document defines the reproducible scenarios used for the 1.0.2 release candidate. Numeric results are recorded only after the final candidate commit is fixed, so measurements always identify the code that produced them.

## Scenarios

| Area | Representative workload | Command |
| --- | --- | --- |
| Image switching | 100,000 paginated navigation resolutions across a 100,000-page collection | `npm --prefix apps/web test -- --run src/features/annotation-editor/annotationResponsiveness.test.ts` |
| Zoom and pan | 100,000 cursor-centered zoom, pan, and source/screen round trips on an 8192×6144 image | same frontend command |
| Polygon interaction | Duplicate 500 three-point polygons in source coordinates with new IDs and draft state | same frontend command |
| Raster selection | Resolve one selected object among 10,000 raster masks 100 times | same frontend command |
| Raster editing | Create five immutable 4096×3072 PNG mask revisions from a 200-point brush stroke | `PYTHONPATH=apps/api python scripts/measure-raster-edit-responsiveness.py` |

The frontend scenarios run production geometry, navigation, clipboard, and raster-selection functions. The raster scenario runs the production immutable revision writer. The test budget is deliberately broad and detects hangs or order-of-magnitude regressions; the measured values, machine details, exact commit, and comparison ruling belong in the final validation report.

## Final candidate results

Pending the exact-head validation run.
