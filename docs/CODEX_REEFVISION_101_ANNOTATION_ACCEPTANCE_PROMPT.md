# Codex execution prompt — ReefVision 1.0.1 annotation correction and stable release preparation

> Copy the entire document into Codex as a single high-effort task, with the repository connected and the working directory at its root.
> This is an IMPLEMENTATION request, not a plan-only request. Work through as many phases as are feasible and verified; do not stop after making a roadmap. Continue incrementally until blocked, and report exact blockers rather than claiming unexecuted tests passed.

## Authoritative task and release boundaries

Repository: Rafael-Del-Valle/ReefVision.
Existing draft PR: https://github.com/Rafael-Del-Valle/ReefVision/pull/44
Current branch: feat/reefvision-1.0.1-sam-class-review-import-20261010
Issue: https://github.com/Rafael-Del-Valle/ReefVision/issues/48

The user has NOT updated ReefVision 1.0.1 onto their laptop. **Do not touch user devices or assume a device upgrade has happened.**

The user wants the following fixes included in the **final stable v1.0.1**, not deferred to v1.0.2. Keep all Python/npm/Rust/Tauri/MSI version metadata at **1.0.1**. The publicly released **v1.0.1-rc.1** is a known-imperfect prerelease and must remain identifiable/unchanged. After complete validation and user release approval, prepare a distinct final stable v1.0.1 release from the final passing commit; do not overwrite the old prerelease tag or historical v1.0.0 assets. No premature merge, public release, stable tag, or disabling required tests.

Use the existing application, Tauri desktop shell, FastAPI, SQLAlchemy/Alembic, persisted workers, SAM 2.1 Transformers provider, Ultralytics training/deployment services, native project models, masks and annotation history. Preserve backward compatibility, scientist approval, on-disk data, original media, immutable datasets, provenance, project exchange and offline-first behavior.

Read AGENTS.md, docs/REEFVISION_PRODUCT_SPEC.md, docs/RELEASE_1.0.1.md, docs/REEFVISION_1_0_1_RELEASE_NOTES.md, and issue #48 before changing code. Explicit current user requests supersede old AGENTS.md exclusions that referred to 0.1-era missing segmentation.

## What is wrong today

1. Shift+1 calls SAM 2.1 to segment one existing or drawn bounding box. The mask is a pending raster-mask proposal, overlaid on existing masks. The acceptance button lives down in the generic Prediction Inspector, not beside the mask. This looks like a new duplicate mask and is confusing.
2. Shift+2 invokes a previously trained or imported detector. It does not improve from the user's just-created labels. "Run model inference" is grey when no project detector exists. The user wants automatic suggestions and controlled local model improvement.
3. There is no separate selected-existing-mask **refinement** workflow that replaces/tightens a mask only after explicit acceptance.
4. There is no verified-data-to-local-model learning cycle that accumulates annotations, trains, validates, then uses a demonstrably better version for full-image suggestions.

As of the most recent 1.0.1 development work, a small **first fix** has been started in AnnotationEditor.tsx: a visible pending-SAM accept/reject banner, actual raster proposal preview with isolation toggle, explanatory missing-detector message, and a frontend regression test. Do not assume it passes CI. Inspect the current branch head and verify/fix this work first. Be particularly careful about React Query refetch ordering, mask visual layering, format/type checks, class selection, permission to accept and cancellation.

## Non-negotiable scientific semantics

- The original image is immutable; all geometry stored in original-image pixels, not thumbnail/viewport coordinates.
- "Proposed", "edited pending", "accepted", "rejected" and "verified human" states must be explicit. Never count a prediction as verified until the researcher explicitly accepts it.
- The user's manually drawn masks are authoritative; never overwrite or duplicate a verified mask on a model click. Save accepted refinement atomically with version/history/provenance and preserve undo.
- For model self-improvement, train ONLY on explicitly human-verified annotations, or on curated model proposals the user accepted/corrected. Do not feed the model its own unreviewed output. Prevent circular self-training.
- Verify train/validation group splitting by original specimen/colony/video/acquisition group where known. Frames or multiple crops from the same specimen must not leak into validation.
- Model accuracy can improve with more data, but never claim monotonic accuracy or activate an untested worse checkpoint. Evaluate held-out data and require explicit promotion or validated thresholds.
- No pretrained weights bundled into the public MSI. On-demand SAM checkpoint download remains an explicitly selected provider exception, with URL/revision/license/SHA-256, progress, checksum and cache behavior documented.
- Allow usable CPU fallback and informative errors, no arbitrary CUDA requirement, no unbounded CPU inference from full-image massive grids.
- No surprise Internet access beyond the SAM selection flow. No external hosted service or cloud data uploads.
- Existing project IDs, class IDs, mask identities, measurement calibrations, counts, provenance and immutable snapshots must survive any migration.
- Keep release artifacts reproducible and pinned. Never skip PyInstaller/Tauri clean Windows install just to force green status.

## Target toolbar actions and keyboard map

**Shift+1: Predict objects across the current full image.**
- Primary visible action: "Predict objects in image" with clear progress, stop/cancel, status and expected outputs.
- With no trained project detector: offer **SAM 2.1 automatic class-agnostic candidate masks** across the whole image. This should use genuine full-image automatic proposals or an explicitly bounded, carefully tested automatic tiling/point-grid inference with deduplication, not a single giant bounding box claimed to be an automatic detector.
- Where provider/backend does NOT have a reliable automatic generator, state the limitation in the UI and implement the provider properly; never fake predictions, use current class names without support, or silently enumerate unbounded GPU/CPU grids.
- With a trained project detector: run class-aware detector over the entire image and optionally refine its best object masks via SAM. Inference should use the selected active version and respect per-image/source provenance.
- Show proposals as a distinct overlay and queue. The researcher can choose class, edit boundary, accept, reject, accept selected/visible; undo an accepted operation. Suppress near-duplicate proposals over existing verified objects and overlapping proposals using mask-based IoU/NMS/instance matching with documented thresholds and edge cases. Never drop valid touching polyps just because boxes overlap.
- The button must NOT be grey simply because no YOLO detector has yet been registered. If SAM installation/runtime is missing, give an actionable "Choose/download SAM 2.1" path.

**Shift+2: Refine selected existing segmentation mask.**
- Primary visible action: "Refine selected mask". Only enabled when a single real **persisted editable mask** is selected. Clear disabled reason for zero, multiple, locked or invalid selection.
- Take the selected polygon or raster mask as a *guiding prior* (rasterized to source-image dimensions), together with an ROI and derived positive/negative prompts. Prefer a true SAM mask-input refinement path where supported. If current Transformers SAM 2 provider supports only points/boxes, produce a conservative, bounded candidate with validated prompts, and clearly disclose that it is a suggested alternative boundary rather than guaranteed tightening.
- Overlay ORIGINAL outline and PROPOSED outline with contrasting visual styles. Provide "Accept & Replace", "Edit", "Discard". The original stays visible/unchanged until acceptance; no extra mask record is created during preview.
- Accept must preserve class, species/state, instance identifier and reviewer provenance, calibration reference, image measurements, revision history and datasets. Choose transactionally updating or explicit supersession in the domain layer; expose rollback/undo. Do not silently delete holes, thin branches or fragmented masks.
- Recompute areas/perimeters/calibrated measurements from accepted geometry, mark dependent analysis artifacts stale when needed, maintain mask count consistency.
- Class selection must NEVER default to silently relabeling the existing mask. If user changes class, require explicit action.
- Separate refine and new instance segmentation modes so they cannot be confused.

**Standalone "Run trained detector" remains available**, but should be honestly labeled with why it is disabled if none is registered. Choose another label/shortcut if desired; bare 1–9 must keep selecting classes; respect focused form inputs to avoid shortcut collisions.

## Phase 0: establish reliable baseline and branch safeguards

- Inspect branch/pr/head, worktree, latest CI and release status, current routes and model capability matrix.
- Use existing development feature branch and make small reviewable commits. Do NOT alter the public release's tag or upload a replacement MSI until the acceptance gate is entirely satisfied and user explicitly approves.
- Reproduce the current mask-review failure using an existing or new deterministic frontend test. Verify that before acceptance the stored annotation count is unchanged and after explicit approval it increments only once.
- Confirm SAM raster proposal backend review path is SemanticPredictionService; accepted SAM raster masks should not fall through box-only annotation review.
- Verify that the pending mask content is rendered via predictionMaskUrl, anchored at source-image coordinates; avoid loading remote resources accidentally or sending unsafe absolute paths.
- Run formatting and relevant unit tests before further changes. Fix frontend regressions rather than bypassing tests.
- Record exact initial and final commits; be honest about unsupported checks.

## Phase 1: complete SAM proposal review fixes (P0)

Likely paths:
apps/web/src/features/annotation-editor/AnnotationEditor.tsx,
AnnotationEditor.test.tsx,
PredictionInspector.tsx,
styles/app.css,
apps/web/src/api/client.ts,
apps/api/reefvision/api/routes/predictions.py,
services/semantic_predictions.py.

Acceptance:
- New raster proposal is initially shown with "Not saved" status, distinct from existing verified mask overlays.
- Clear adjacent Accept/Reject/Edit buttons without scrolling to hidden inspector; expose loading/error/retry states and class choice.
- Confirm clicking Accept calls correct raster service and stores ONE accepted mask; clicking Reject preserves old masks and stores NO new one. Both clear candidate overlays after response and survive editor restart.
- Invalid class/geometry, network failure and stale revision cannot lose annotations. Don't auto-accept on prompt completion.
- Overlay mask pixels, not only a rectangular bounding-box outline; permit temporarily isolating existing masks.
- Exercise accepting a proposal over an already masked object; warn about potential duplicate and allow cancelling, or implement safe matching/refinement path.
- Regression test pending raster mask accepting/rejecting; more than one SAM request; style can be set to an adjacent compact panel, not modal obstruction.
- Check accessibility of keyboard controls and mobile/minimum desktop window width.

## Phase 2: implement an actual full-image SAM automatic-proposal backend

Provider design:
- Expose an explicit, typed request carrying project, image, variant, generation policy, allowed classes (optional), points-per-side/tiles, min-region area, confidence/stability, max candidates and deduplication thresholds.
- Implement reproducible bounded candidate generation. Use genuine automatic mask generator from supported SAM 2.1 provider stack where possible. Confirm exact Transformers pinned version APIs and model/provider license; don't invent methods.
- If only point/box prompting is available, wrap controlled whole-image candidate generation with active stopping criteria, bounded memory/time, tiling for large microscopy/coral photographs, dedup and optional reuse of existing masks to guide sampling.
- Provide job-based (persistent, retryable, cancellation-aware) execution rather than freezing the FastAPI event loop/desktop UI; limit concurrent inference per GPU/CPU and gracefully handle out-of-memory conditions. Existing isolated worker contracts preferred.
- Cache the SAM model once per worker; avoid repeated checkpoint loading between every tile. Surface progress: loading, tiles processed, candidate extraction, filtering, completed, cancelled/failed.
- Persist each candidate as a distinct raster/polygon prediction proposal with source-image coordinates, class-agnostic label until assigned, score/stability/IoU where available, variant/checkpoint SHA, parameters, training dataset and run IDs.
- No naive conversion from mask to box that loses segmentation. Create stable mask checksum and path using existing storage layer and version metadata; maintain backward compatibility with current proposal review routes.
- No inference leakage from human annotation state unless explicitly used for seed prompts; do not overwrite those annotations.
- Validate candidates against known accepted masks and avoid duplicate candidates, with configurable sensitivity and scientific boundary considerations for adjacent polyps.
- Test 0 proposals, one, many, duplicate/touching objects, very large images, non-square images, tile edge effects, CPU timeout/cancellation, GPU fallback, corrupt checkpoints, backend restart and persisted jobs.
- End-to-end assertion that Shift+1 produces multiple genuine proposals on a representative test image with no detector registered. If absence of provider, show precise missing capability/error instead of grey non-action.

## Phase 3: implement non-destructive selected-mask refinement

Backend:
- Add a typed preview request referencing an existing mask UUID and source revision, with provider + optional positive/negative prompt points.
- Load the canonical polygon or raster mask through existing managed storage, convert to fixed-size mask prior where compatible with model, derive ROI and confidence checks. Validate original image shape, class and mask path securely.
- Infer candidate geometry, return candidate token/ID and metrics (old area, proposed area, IoU, bounds, edge-change percentage, warnings). The preview operation must not mutate persistent verified annotation state or affect counts.
- Add explicit Accept & Replace endpoint taking candidate ID plus expected mask revision (optimistic locking), edit/correct endpoint, discard. Update existing mask transactionally or preserve explicit supersession mapping. Record before/after JSON and mask SHA, editor identity, timestamp, provider model/checkpoint and prompt provenance.
- Reject conflicts, expired candidates, source mask changes, unknown classes, drastic uncontrolled area changes and invalid geometry. Allow confirm override when scientifically justified; never silently truncate contours.
- Hook into undo/redo event machinery and recalculation/dataset workflows.
- Frontend: selected mask only, compare-mode with toggles and intensity slider, before/after area and calibration-aware unit readout, clear accept/replace or discard controls, keyboard, disable/enable reasons.
- Tests for polygon, raster, thin branches, occlusion, repeated landmarks, fragmented masks, mask holes, zero-area, 1px masks, adjacent polyp masks and restart recovery.

## Phase 4: learning from verified project annotations (scientist-in-the-loop)

This is **not** simply re-calling SAM after every drawn mask. Implement:
1. Track reviewed/edited annotations that can contribute to a versioned project training dataset, plus explicit ignored/background/excluded regions where supported.
2. Create immutable dataset snapshots with class-map and source-image provenance, group-aware splits and checksums, and a proper minimum-data sufficiency report.
3. Choose an initial locally trainable detection/instance-segmentation architecture from the existing provider stack. No generic downloadable pretrained detector weights added. Train from user-registered local checkpoint or from scratch with documented data/compute limitations.
4. Offer "Improve predictions" manual action plus optional configurable auto-trigger when user-verified new examples reach meaningful per-class threshold. Config includes minimum images, minimum objects per class, grouping, validation size and training budget. Never silently auto-train on every click, block editing, monopolize the GPU, or save a candidate as active with no evaluation.
5. Persist training jobs and progress, cancellation, failure recovery, current active model ID, training dataset version and validation metrics. Reuse existing Training Workspace, experiment logging and model registry.
6. Evaluate candidate vs incumbent on untouched held-out verified examples (precision, recall, per-class AP/IoU, count bias, uncertainty/calibration and failure review). Do not hide failures or overstate performance with tiny samples. Automatically *propose* promotion only when prespecified thresholds/guardrails are met; manual choice remains available.
7. On deployment, record exact dataset/version/model/checkpoint/device/inference parameters per proposal. Support review corrections and continuing improvement without feedback contamination.
8. Preserve human-only reference counts, error distributions and cross-annotator comparison; model-assisted masks are not human ground truth until explicitly verified.
9. Provide visual progress and "why not ready?" state: e.g., no verified examples, insufficient class diversity, missing training backend, no local weights, active training, failed validation or no improvement.
10. Integration tests for training from zero/few examples, two classes, multi-image and group separation, no cross-split leakage, corrupted checkpoint, cancellation, restart, unsupported provider, model promotion and rollback. GPU performance tests are optional but indicate real hardware used.

Any auto-improvement is evaluated, not assumed; if dataset is too small, keep SAM class-agnostic suggestions and explain that learning is not yet ready.

## Phase 5: end-to-end UI, onboarding, and robustness

- Replace misleading current Shift+1 and Shift+2 help text/tooltips with final behaviors ONLY after implementation; do not break features temporarily.
- Explicitly separate: (a) Generate full-image suggestions; (b) Refine selected mask; (c) Run trained detector; (d) single-object new mask if retained as alternative toolbar control. Don't reuse ambiguous labels.
- Support a bottom/side predicted-object gallery, pending count, confidence and class filters, keyboard navigation, zoom-to-candidate, accept/reject/correct, live counts after save and visible split of human vs model-origin verified labels.
- Show model/source/provenance with easy inspect. Provide a clear "unverified" watermark/visual distinction.
- Detect unsaved edits and gate navigation, background job interactions and crashes. Avoid double submission, stale React Query state and rapid repeated shortcut clicks.
- Tests cover image changes mid-inference, reselecting same mask, overlay visibility persistence, no stale proposal acceptance on the wrong image, rapid accept/reject, long operations, provider download failures, local cache reuse, side-by-side comparison after restart, and app data preserved through MSI uninstall.
- Keep Windows app responsive on 1,600px and larger coral images, with no accidental UI layout regression.

## Phase 6: validation and release readiness — gate, do not publish

Run baseline+final focused tests and full validated gate:
- Python Ruff check and format check; mypy package mode; all backend pytest; database migrations fresh upgrade/downgrade/back-to-head.
- Prettier format:check, TypeScript typecheck, all Vitest, relevant Playwright desktop frontend E2E, production Vite build.
- SAM live real checkpoint download and inference, CPU and native Windows pinned Python provider tests. Do not call mock-only tests live acceptance.
- Tauri Windows MSI with actual PyInstaller backend, no prebundled checkpoints; verify all CABs declared by MSI's Media table, all payload SHA-256 and version consistency 1.0.1.
- Full clean Windows installation on a distinct runner without Python/Node/Rust in PATH, launched API and GUI, actual SAM download/inference, full-image proposals, selected-mask refinement, human accept/reject and no double-counting, project/reviewer history, restart/persistence, project exchange and uninstall/data retention.
- If safe, test v1.0.0 -> new v1.0.1 upgrade in an isolated disposable Windows VM with backup and migration evidence; do not expose actual user data to upgrade tests.
- If hardware GUI smoke can't run in hosted CI, clearly flag that as pending and provide a reproducible operator script rather than claiming it passed.
- Keep PR #44 draft until all source/hardware/installer evidence is recorded. Update docs/RELEASE_1.0.1.md, changelog and the issue #48 acceptance boxes. Version remains 1.0.1; old v1.0.1-rc.1 prerelease untouched.
- Do not merge, retag, release or overwrite GitHub release assets without the user's explicit approval after gates pass.

## Working strategy to maximize useful Codex implementation effort

- Begin by inspecting current branch head, checking open local edits, and listing relevant backend/frontend files. Work on the existing feature branch only, unless the user has other local uncommitted changes. Never reset a dirty worktree.
- State phase, target files, test strategy and risks; then **implement** immediately. Red test -> smallest correct code -> green test -> broader validation -> commit.
- Divide into Phase 1 through Phase 6, with compact but complete reports. Work continuously through all phases you can reasonably complete within the available task context/tokens. Don't spend effort writing repeated planning documents or speculative status summaries.
- Prefer reuse of current service modules, UI components, alembic tables, job/store contracts, model providers and exports to new abstractions. Keep paths and Windows handling correct. Avoid dependency downloads unless required and permitted by the current model policy.
- When stuck on dependency/GUI automation constraints, implement backend and typed API contracts plus tests that can run; report the exact residual work. Stop before unsafe commits or data migrations that cannot be validated.
- Each substantive milestone gets a focused commit and clear comparison. No push to main. Do not use long single-file rewrites to disguise broken test coverage.
- Run tests and provide command, result, count, commit, and workflow links. Never invent "all passed" from a partial run. If a test fails, diagnose and fix it before moving on.
- At the end: record completed functionality, remaining incomplete functionality, changed file list, new/altered DB migrations, versions, experiment/model safeguards, acceptance results and exact commands to reproduce failures. Only declare "release ready" when every mandatory gate is green. Otherwise say HOLD.

## First immediate task after reading this prompt

1. Inspect the current branch and latest CI for the just-added SAM review acceptance banner/test. Fix any TypeScript, lint, E2E or test failures.
2. Verify backend SAM raster-mask accept/reject persistence and prevent overlapping duplicates without explicit acceptance.
3. Prove Shift+1 does not automatically save an overlapping mask and exposes Accept/Reject adjacent to the source canvas.
4. Implement the genuine full-image proposal provider and UI, then selected-mask refinement and verified-label learning loop.
5. Continue into full tests and MSI acceptance; report what remains and do not publish prematurely.

This instruction is intentionally ambitious; prioritize validated correctness and user data protection over checking off unimplemented features.