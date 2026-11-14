# ReefVision 1.0.3 Final Laptop Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every safe laptop-only ReefVision 1.0.3 acceptance gap on PR #81 without changing the installed production 1.0.2 application or depending on GPU hardware.

**Architecture:** Preserve the already-tested product tree. Correct the generic Windows workflow at its version/provenance boundary, run a bounded multi-image CPU segmentation lifecycle through ReefVision, exercise the packaged desktop in an isolated data/runtime location, and record exact evidence without promoting synthetic or automated checks beyond what they prove.

**Tech Stack:** GitHub Actions, PowerShell/WiX MSI, Python 3.12/FastAPI/Ultralytics, React/Tauri, Playwright, Windows desktop automation.

**Spec:** `C:/Users/rafae/.codex/attachments/bafb46c5-7955-496f-accb-2999fe7fd33a/Pasted text.txt`

## Global Constraints

- Continue branch `fix/reefvision-training-architecture-picker-20261022` and draft PR #81 from `d7427fc99438f1dc7c41d450325dc512a4ced574`.
- RTX 3090, CUDA, GPU downloads, and GPU benchmarks are out of scope.
- Do not overwrite or uninstall the existing ReefVision 1.0.2 installation or user projects.
- Preserve source pixels, scientific provenance, class mapping, and verified-versus-predicted state.
- Use PASS, FAIL, BLOCKED, or UNVERIFIED from fresh evidence only.
- Do not merge, tag, publish, modify download links, or delete branches.

## Review Focus

- A future version must not inherit a literal 1.0.3 filename or ProductVersion assertion in the generic build workflow.
- Installer provenance must bind the downloaded MSI/CAB set to the workflow source SHA and exact hashes.
- Synthetic segmentation data must not leak held-out images or be described as representative scientific validation.
- A nonempty model output must still be rejected if polygons, class IDs, or source-pixel coordinates are invalid.
- Packaged GUI checks must use disposable data and must not mutate the installed 1.0.2 application or its projects.

---

### Task 1: Version- and provenance-safe Windows acceptance workflow

**Files:**
- Modify: `.github/workflows/build-desktop.yml`
- Modify: `scripts/check-windows-installer-acceptance-version.py`
- Modify: `apps/api/reefvision/tests/test_windows_installer_acceptance_version_103.py`

**Interfaces:**
- Produces: build-job outputs `release-version` and `release-slug`; clean-install inputs derived from `tauri.conf.json`; provenance/hash validation against `github.sha`.
- Consumes: Tauri `version`, `build-provenance.json`, MSI `ProductVersion` and `Media` table.

- [ ] Add repository-workflow and dynamic-version regression tests; run them and verify RED on the hardcoded 1.0.2 job.
- [ ] Derive and validate package version once in the build job; export it as job outputs.
- [ ] Make the disposable job use those outputs for labels, paths, MSI name, ProductVersion, acceptance root, and evidence artifact.
- [ ] Validate provenance version/source SHA/clean state/verification flag and exact MSI/CAB hashes before installation.
- [ ] Run focused Pytest, the standalone preflight, YAML parse, Ruff, and diff checks; commit.

### Task 2: Multi-image CPU segmentation lifecycle

**Files:**
- Create or modify only the smallest reusable acceptance harness and tests needed after inspecting existing acceptance patterns.
- Produce disposable evidence outside the repository.

**Interfaces:**
- Produces: leak-free train/validation/held-out image IDs, registered checkpoint ID, held-out proposal IDs and validated source-pixel polygons.
- Consumes: ReefVision project/dataset/training/model/inference services and the lightweight local Ultralytics segmentation architecture.

- [ ] Inspect existing detection/classification acceptance patterns and previous segmentation evidence.
- [ ] Test-first a deterministic varied synthetic dataset builder and its disjoint split/geometry contract if no representative local dataset exists.
- [ ] Run one bounded CPU training lifecycle; do not repeatedly raise epochs on unsuitable data.
- [ ] Reload the registered checkpoint and require at least one valid held-out polygon with correct class mapping, coordinates, and persistence.
- [ ] Record training, registration, proposal, representativeness, and scientific acceptance separately; commit harness changes if any.

### Task 3: Isolated packaged Windows and GUI acceptance

**Files:**
- Use the verified MSI/CAB set and disposable evidence directories; modify product/tests only for reproduced defects.

**Interfaces:**
- Produces: executable path, logs/screenshots, runtime/API/GUI results, and explicit UNVERIFIED entries.
- Consumes: installer provenance, extracted or sandboxed packaged runtime, disposable ReefVision data root.

- [ ] Verify hashes, disk space, installed-version conflict, isolation options, and data-root configuration.
- [ ] Do not install over or uninstall the existing 1.0.2 host application; use Windows Sandbox if available, otherwise administrative extraction for runtime/GUI checks and mark MSI install/upgrade/uninstall UNVERIFIED.
- [ ] Exercise safe packaged startup/backend, presets, project persistence, image/import/viewport/annotation, CPU inference, video tracking/masks, metrics, and read-only console checks where technically supported.
- [ ] For every defect, capture reproduction/root cause, add a failing regression, implement minimally, and rerun affected acceptance.

### Task 4: Release evidence, final verification, and PR handoff

**Files:**
- Modify: `docs/roadmap/REEFVISION_1_0_3_CONSOLIDATED.md`

**Interfaces:**
- Consumes: exact task outputs, final commit, installer provenance, and GitHub Actions status.
- Produces: P0-P7 matrix and laptop release-candidate decision.

- [ ] Update the roadmap with exact PASS/FAIL/BLOCKED/UNVERIFIED evidence and no GPU dependency.
- [ ] Run targeted gates for changed files plus broader gates justified by product changes.
- [ ] Perform a whole-branch review, commit logical changes, and push PR #81.
- [ ] Confirm remote SHA and final GitHub Actions status; keep the PR draft.
