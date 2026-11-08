# ReefPose Phase 2C validation

Validated on 2026-11-08 from branch `feature/reefpose-core`. All biological
inputs used for this milestone were synthetic engineering fixtures. No claim of
scientific pose accuracy is made.

## Delivered vertical slice

- Project-scoped anatomical templates with immutable numbered revisions,
  canonical integrity hashes, stable landmark IDs, display names, descriptions,
  anatomical groups, repeated slots, reciprocal symmetry, required/optional
  status, and skeleton edges.
- An integrated React skeleton designer with add/remove/reorder controls,
  connection editing, graph preview, save/error state, and inspectable revision
  history.
- Existing video pose annotation reuses a selected template. Saved observations
  retain stable landmark IDs, source-image coordinates, occurrence identities,
  visibility state, and the exact schema ID/revision/hash binding.
- Scientist-verified pose rounds and immutable frozen datasets retain the full
  anatomy definition. Training exports, native ReefPose checkpoints, Model Hub
  metadata, and inference results retain stable IDs and connectivity; native
  checkpoints also retain symmetry and required/optional semantics.
- Existing legacy pose schemas are projected deterministically without changing
  their stored revisions. Pre-Phase-2C ReefPose anatomy hashes remain loadable,
  and reordered repeated landmarks resolve training targets by stable ID.
  SLEAP and Ultralytics provider paths remain intact.

The automated integration chain covers custom schema definition, verified
manual observations, frozen dataset creation, native ReefPose training,
checkpoint registration, checkpoint reload, and inference. The live browser
acceptance separately exercises graphical schema creation/revision and manual
stable-ID annotation persistence.

## GUI acceptance

An isolated copy of the Phase 2B acceptance data was migrated to revision 0038.
The real API background worker and Vite UI were run locally.

- `reefpose-phase2c-live.spec.ts`: passed. Through the GUI it created a
  three-landmark jellyfish schema, configured a repeated tentacle pair and
  reciprocal symmetry, added a skeleton edge, saved revision 1, renamed a
  display label into revision 2, inspected both revisions, extracted review
  frames, selected the schema, placed all landmarks, and saved the annotation.
  The API response was checked for the exact revision hash and stable IDs
  `bell_center`, `tentacle_left`, and `tentacle_right`.
- `reefpose-phase2b-live.spec.ts`: passed. Through the GUI it trained one native
  ReefPose epoch on CUDA/AMP, waited for the persisted workflow run, inspected
  Model Hub provenance, launched registered-checkpoint pose inference, and
  reviewed the generated landmarks.

These are Chromium browser acceptance runs against the actual local services.
They do not constitute native Tauri/Windows desktop GUI acceptance.

## RTX 3090 acceptance

The explicit CUDA integration test passed with PyTorch 2.11.0+cu128 and CUDA
12.8 on an NVIDIA GeForce RTX 3090. It used a synthetic, scientist-verified,
two-keypoint repeated-anatomy dataset, trained ReefPose-S for one epoch with AMP,
registered the checkpoint, reloaded it on CUDA, and returned two checkpoint
predictions for a 96 x 64 source image.

- Workflow time (training, registration, load, and inference): 2.0002 s
- Peak allocated CUDA memory: 18,968,064 bytes (18.09 MiB)
- Training loss / best selection loss: 0.170955 / 0.170955
- Checkpoint SHA-256:
  `6e222188cc70833d61c383847c27b9089581e60faa435e4253d2e1ff32e856d4`
- Registered model ID: `6a91312c-cd79-4202-994c-fcd9ef96e0bc`

This is engineering validation only; the elapsed value is not a standalone
inference-latency benchmark and must not be interpreted as biological accuracy.

## Automated validation

- Frontend lockfile policy: passed.
- Prettier format check: passed.
- TypeScript project check: passed.
- Vitest: 94 files, 498 tests passed.
- Production Vite build: passed (existing large-chunk advisory remains).
- Ruff format: 696 files passed.
- Ruff lint: passed.
- mypy: 422 source files passed.
- Focused custom-schema/checkpoint tests: passed.
- Explicit CUDA workflow/register/inference test: passed.
- Backend suite excluding the unavailable real interoperability runtime module:
  1,420 passed, 33 opt-in skips.

The unfiltered backend run initially reported 1,413 passed, 38 skipped, and
seven failures. One was an introduced hard-coded migration-head expectation and
was fixed and revalidated. The remaining six are all in
`test_pose_interoperability_runtime.py` and reproduce because optional
`sleap-io 0.9.2` is not installed in the isolated verification environment.
No dependency was installed or lockfile changed for this milestone.

## Remaining limitations

- Native Tauri/Windows desktop interaction has not been exercised; browser GUI
  acceptance is the current evidence.
- Biological accuracy, cross-species generalization, ambiguous repeated-part
  identity, and inter-annotator agreement require real labeled animal data.
- The real SLEAP/NWB/COCO/DLC/Ultralytics interoperability round-trip suite
  still requires its separately pinned optional environment.
- Revision history is inspectable and new revisions derive from the latest
  definition; the GUI does not branch an old revision into a parallel lineage.

## Recommended next phase

Phase 2D should be a scientific benchmarking and annotation-quality milestone:
curate independently reviewed multi-species datasets, measure OKS/mAP and PCK
per landmark/group, quantify visibility and repeated-identity errors, establish
inter-annotator baselines, calibrate confidence, and profile inference latency
separately by resolution and batch size. Native Windows desktop acceptance and
the pinned interoperability environment should be included in that matrix.
