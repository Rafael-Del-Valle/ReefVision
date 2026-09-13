# ReefVision 1.0.1 implementation and validation ledger

Source baseline: `8d4a39d`, branch `release/reefvision-1.0-finalize-20260910`.
Existing `v1.0.0`: `6be8880e76bd033f18114f4df0cb7278a593ac51`; immutable.

The user's 1.0.1 release scope supersedes historical 0.1 exclusions in the
product specification. Keep source images, checkpoints, datasets, applied
migrations and release history. Work in the explicitly requested checkout.

## Milestones and file ownership

- [x] P0 lifecycle: `jobs/training.py`, `jobs/worker.py`, `repositories/jobs.py`,
  `storage/training.py`, training recovery/workspace and provider dependency tests.
  Read complete CSV rows and ZIP checkpoint integrity without loading pickle.
  Share artifact collection and idempotent completion. Exclude training from
  generic requeue. Cancellation wins unless the run is already completed.
  Guard repeated final callbacks and preserve Windows workers=0 and headless Agg.
  Red/green regressions demonstrated; independent review caught decompression
  failure propagation, now covered. Recovery 20 passed; broader focused suite
  45 passed before the last decompression regression; Ruff and mypy passed.
- [x] Polygon Fill: deterministic image seed -> connected region -> contour ->
  conservative simplification -> existing polygon annotation. Keep normal save,
  class/instance, selection, undo/redo, delete, editing and export contracts.
  Add reusable conversion and frontend workflow tests; no SAM dependency.
- [x] Architecture/preflight and UI audit: inspect `services/training.py`,
  architecture tests, Training workspace/polling and annotation editor regressions.
  Reproduce actual failures before changing stable functionality.
- [ ] Version and source gates: authoritative Python, npm, Cargo/Tauri and
  installer versions; retain historical 1.0.0 notes. Add 1.0.1 notes/evidence.
  Full pytest, Ruff apps/api, mypy, frontend typecheck/tests/build, applicable
  Playwright and migration checks, and `git diff --check`.
- [x] Hardware: isolated synthetic dataset, real YOLO11 Nano CPU/CUDA,
  AMP/FP32, two epochs, live progress, final validation/artifacts, cancellation,
  interrupted recovery and completed persistence. Record torch.version.cuda.
- [ ] Packaging only after source gates: commit exact candidate; production
  1.0.1 MSI/CAB, embedded metadata and hash/manifests; Windows lifecycle/VM
  acceptance if available. Record unavailable acceptance separately.
- [ ] Tag readiness: report exact candidate before preparing v1.0.1; never tag
  before all required source, hardware and installer acceptance passes.

## Review and evidence rules

Each implementation milestone gets targeted red/green tests and a reviewed
logical commit. Use `.venv/Scripts/python.exe` for Python. Full validation
results, commands, artifacts, hashes and remaining manual checks belong in the
1.0.1 release evidence report. Never describe simulated callbacks as real GPU
training or a host installation as clean-VM acceptance.

## Verified milestones

- Lifecycle commit `901ec7b`; architecture/training UI commit `2643568`;
  polygon Fill and guarded workspace exit commit `e94bca6`.
- Six real hardware cases passed; report and per-case logs are under
  `.artifacts/training-lifecycle-1.0.1-a`. CPU FP32, CUDA FP32, CUDA AMP,
  interrupted incomplete, cancelled, and recovered real 50/50 completion.
- Frontend latest full suite: 140 passed; production build and TypeScript passed.
  Playwright: seven passed before final guarded dropdown regression; rerunning
  after it. Existing Starlette deprecation and Vite chunk-size warnings remain.
- Alembic fresh upgrade/head -> base -> head passed; no new migrations.
- Windows clean-install harness: 18 assertions passed. This is harness testing,
  not install/VM acceptance. No disposable Windows VM is connected here.
- Initial backend full run collected a test before its final 400-vs-422
  assertion correction: 420 passed, one failed. A subsequent collection attempt
  exposed default-app import writing to shared developer storage; isolate that
  test bootstrap and rerun the complete suite before building.
- Release tooling review requires clean build-time source provenance, version
  checks at MSI/Desktop/API layers, and hash verification before finalizing.
  Hardware harness now asserts pre-recovery state and intentional exit codes;
  normal crashes can no longer pass merely because restart recovery succeeds.
