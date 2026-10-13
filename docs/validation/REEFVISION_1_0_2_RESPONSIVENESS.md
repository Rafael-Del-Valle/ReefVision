# ReefVision 1.0.2 responsiveness evidence

These measurements exercise production interaction kernels. They do not prove desktop GUI responsiveness or operator-perceived latency. Installed-app trials remain separate in `REEFVISION_1_0_2_INSTALLED_GUI_ACCEPTANCE.md`.

## Reproducible scenarios

| Area | Workload | Command |
| --- | --- | --- |
| Image navigation | 100,000 paginated navigation resolutions across a 100,000-page collection | `npx vitest run src/features/annotation-editor/annotationResponsiveness.test.ts` from `apps/web` |
| Zoom and pan | 100,000 cursor-centered transforms and coordinate round trips on an 8192x6144 source image | Same Vitest command |
| Polygon duplication | 500 three-point polygons with new IDs and draft status | Same Vitest command |
| Raster selection | Resolve one among 10,000 raster mask objects 100 times | Same Vitest command |
| Raster revision writing | Five immutable 4096x3072 PNG revisions with a 200-point brush stroke | `PYTHONPATH=apps/api python scripts/measure-raster-edit-responsiveness.py` |

The tests assert geometry invariants and scenario-specific budgets. The raster benchmark verifies that each immutable revision is a valid, nonempty PNG.

## Latest verified prerequisite baseline

**Measured source:** `02db7df215960d3cc1f37c9cb62af6b66e40283d`, the exact head of [PR #58](https://github.com/Rafael-Del-Valle/ReefVision/pull/58).

**Run:** [ReefVision 1.0 Acceptance 38443527988](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38443527988), GitHub-hosted Ubuntu.

| Measurement | Observed runtime | Qualification |
| --- | ---: | --- |
| 100,000 gallery navigation resolutions | 4.840 ms | JavaScript function runtime; excludes image decoding and paint |
| 100,000 zoom/pan coordinate round trips | 18.462 ms | Math and state transforms; excludes DOM paint and GPU |
| Duplicate 500 polygon geometries | 2.169 ms | Clipboard transform; excludes API persistence |
| Select among 10,000 raster objects 100 times | 11.590 ms | Selection lookup only |
| Immutable 4096x3072 raster PNG write | median 118.840 ms; min 118.600; max 122.952 | Five Linux/Python 3.12.15 runs; excludes desktop UI |

The full source run also passed 436 Vitest tests in 92 files and 12 Playwright cases with one configured skip. Downloadable evidence is in [frontend artifact 11837481955](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38443527988/artifacts/11837481955) and [raster artifact 11838210436](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38443527988/artifacts/11838210436).

The scientific integration does not intentionally alter these kernels, but the combined candidate must publish fresh exact-head benchmark artifacts before release review.

## Installed performance gate

Use a disposable installed Windows environment and representative high-resolution imagery. Record the candidate SHA, artifact ID, MSI hash, machine, GPU and driver, display scaling, image resolution, annotation counts, and at least three trials for first image display, navigation, zoom/pan, polygon editing, raster editing, and mask persistence. Report median and range. Confirm that source-pixel annotations stay aligned throughout. Compare with a baseline only when the machine and workload match.
