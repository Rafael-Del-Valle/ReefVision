# ReefVision 1.0.2 responsiveness evidence

This document records measurements from *production interaction kernels*. They are **not** proof of desktop GUI responsiveness or interactive user latency. Full installed-app operator checks remain separate (see `REEFVISION_1_0_2_INSTALLED_GUI_ACCEPTANCE.md`).

## Reproducible scenarios

| Area | Workload | Command |
| --- | --- | --- |
| Image navigation | 100,000 paginated navigation resolutions across a 100,000-page collection | `npx vitest run src/features/annotation-editor/annotationResponsiveness.test.ts` from `apps/web` |
| Zoom/pan transformations | 100,000 cursor-centered zoom/pan and coordinate round trips on an 8192×6144 source image | same Vitest command |
| Polygon duplication | 500 three-point polygons with new IDs and draft status | same Vitest command |
| Raster selection | Resolve one among 10,000 raster mask objects 100 times | same Vitest command |
| Raster revision writing | Five immutable 4096×3072 PNG revisions with a 200-point brush stroke | `PYTHONPATH=apps/api python scripts/measure-raster-edit-responsiveness.py` (Bash) |

The source geometry invariants and performance budgets are asserted in `annotationResponsiveness.test.ts`. The raster benchmark checks that each mask revision is valid and nonempty.

## Baseline observed from GitHub Actions

**Measured source commit:** `88ae9cf00ad0f96c9b6d0e7112f5005e737b139e`.

**Source:** [ReefVision 1.0 Acceptance — Desktop frontend and E2E job](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147180), Vitest `REEFVISION_RESPONSIVENESS` log line, on GitHub-hosted Ubuntu runner.

| Measurement | Observed runtime | Qualification |
| --- | ---: | --- |
| 100,000 gallery navigation resolutions | 5.922 ms | JS function runtime; not actual image decode/paint |
| 100,000 zoom/pan coordinate round trips | 24.971 ms | math-only; not DOM paint or GPU |
| Duplicate 500 polygon geometries | 2.693 ms | clipboard object transform, not database save |
| Select among 10,000 raster objects 100 times | 15.700 ms | selection lookup only |

The tested suite completed with **421 Vitest tests passed across 92 files** and **11 Playwright passed, 1 configured skip**. Numbers above are from a single CI run, **not a stable benchmark distribution, not a before/after speedup claim, and not a guarantee for high-resolution desktop GUI performance**.

**Raster PNG write benchmark:** Numeric results are outstanding until the new CI step completes. Do not substitute the 5-second packaged SAM inference result, which measures a different operation.

## Continuous evidence collection

The `reefvision-1.0-acceptance.yml` workflow now runs and uploads:
- `reefvision-1.0.2-frontend-responsiveness` — focused Vitest log and metadata with the source head and runner.
- `reefvision-1.0.2-raster-responsiveness` — Python JSON timings and metadata with source head and runner.

Both are tied to the PR source SHA in `metadata.txt`. Because pull-request workflows may test a merge ref, record both source head and GitHub run ID; do not claim the results reflect a newer source commit than the artifact metadata states.

## Remaining performance gate

For release acceptance, use a disposable installed Windows environment and representative high-resolution imagery. Record machine specification, GPU and driver, app version, selected test image resolution, annotation/mask counts, image-open latency, frame responsiveness, mask editing and save latencies, and whether source-pixel annotations remain aligned after pan/zoom. Compare a matching baseline only when such measurements actually exist.
