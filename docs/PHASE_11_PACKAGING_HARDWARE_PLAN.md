# ReefVision Scientist-Ready Phase 11 — Packaging & Hardware Validation

## Goal

Prove that ReefVision works as a release-grade Windows desktop application, not only from a source checkout. Phase 11 separates software correctness, packaged-runtime correctness, hardware execution, clean-machine installation, upgrade/uninstall behavior, and stress evidence.

The Phase 10D visual smoke test is intentionally **deferred by user request**. It remains a Phase 10 closeout item and is not silently promoted to PASS.

## Phase 11A — Local release evidence and hardware preflight

- Generate a machine-readable Windows/CPU/GPU/runtime profile.
- Exercise PyTorch execution on CPU and CUDA without network access or model downloads.
- Require the expected GPU by name when requested (current target machine: RTX 3090).
- Run desktop/backend recovery regressions.
- Run Tauri/Rust format and tests.
- Optionally run the complete backend/frontend software gate.
- Optionally build the MSI from a clean committed source tree.
- Require packaged-backend/MSI verification and commit-matched build provenance.
- Generate the clean-install harness in `PlanOnly` mode without modifying the installed system.

Primary entry point:

`scripts/phase11-acceptance.ps1`

Hardware evidence collector:

`scripts/phase11-hardware-profile.py`

## Phase 11B — Runtime stress and persistence

Required evidence:

- large image import/open/save/reopen without corrupting the managed source;
- large video import and persisted metadata without loading the entire video into memory;
- background-job restart recovery;
- registered-model persistence across application restart;
- generated Results Package / Project Exchange portability after restart;
- explicit offline startup and offline local workflows with no network dependency;
- clear failures for operations that genuinely require a missing external resource.

Stress evidence must use isolated test data. Synthetic media can establish software/runtime behavior but does not establish biological accuracy.

## Phase 11C — Disposable Windows install / upgrade / uninstall

Use `scripts/acceptance-windows-clean-install.ps1` only on a disposable Windows VM or machine. The harness is intentionally marker-gated and refuses normal ReefVision data roots.

Required evidence:

- clean MSI install;
- Start-menu/desktop shortcut creation;
- first launch with bundled backend and no Python/Node/Rust requirement;
- frontend/backend loopback connectivity;
- project/image/annotation creation;
- restart persistence;
- Project Exchange export;
- upgrade from a previous compatible isolated-acceptance MSI when available;
- uninstall removes binaries, shortcuts, and registration;
- uninstall preserves isolated user data.

Administrative MSI extraction is package-readability evidence, not a substitute for this clean-machine gate.

## Phase 11D — CPU/CUDA packaged-provider matrix and closeout

Run representative production-provider operations from the packaged application/runtime on:

- CPU-only execution;
- NVIDIA CUDA execution on the RTX 3090;
- explicit unavailable-device rejection with no silent scientific fallback.

Record device name, PyTorch/CUDA versions, provider/model identity, execution duration, memory evidence where available, and whether fallback occurred.

Do not treat synthetic/provider execution as biological-performance validation.

## Exit criteria

Phase 11 is complete only when:

1. Phase 11A local evidence passes at the exact release candidate commit.
2. Phase 11B persistence/offline/stress evidence passes.
3. Phase 11C disposable-machine clean install/uninstall passes; upgrade may remain explicitly SKIPPED only when no safe prior isolated-acceptance MSI exists.
4. Phase 11D CPU/CUDA packaged-provider matrix passes on the intended hardware.
5. Installer SHA-256, source commit, build provenance, and evidence paths are recorded.
6. No deferred item is silently reported as PASS.
