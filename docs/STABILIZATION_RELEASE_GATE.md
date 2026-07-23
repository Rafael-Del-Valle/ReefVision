# ReefVision stabilization and release-candidate gate

**Status:** feature freeze active

**Branch:** `feat/all-phases-advancement`

**Draft PR:** `#8`

**Freeze baseline:** `f52a90afeffda0f59df93c9dc5998f22a99b53c1`

## Purpose

ReefVision has enough implemented breadth for a private-beta candidate. The priority is now demonstrated reliability, scientific validation, Windows packaging, and a simpler primary journey. Major feature development remains frozen until every release-candidate gate below has evidence.

Existing production files may be modified to fix defects. New tests, validation tools, documentation, CI repairs, and release scripts are allowed. New production modules and new database migrations are blocked by `scripts/check-feature-freeze.py`.

The article-inspired Gemini/OpenAI/SAM 2 branches remain a compound workflow stage during the freeze. They must not be separated into new persisted graph nodes until the gates below pass and the freeze is explicitly lifted.

## Required order

### Gate 1 — complete automated validation

Run from the repository root on Windows:

```powershell
.\scripts\run-release-validation.ps1
```

Required results:

- Ruff lint passes.
- Ruff format check passes.
- Strict mypy passes.
- Complete backend pytest passes.
- Alembic upgrades to head, downgrades through the supported boundary, downgrades to base, and re-upgrades to head.
- Frontend lockfile validation and `npm ci` pass.
- Prettier, TypeScript, Vitest, production build, and Playwright pass.
- Rust formatting and `cargo check` pass.
- Tauri MSI packaging and packaged API-sidecar smoke pass.

The generated JSON summary and every individual log under `.artifacts/release-validation-*` are release evidence. A failed gate remains failed even when a later gate succeeds.

### Gate 2 — Windows MSI verification

Run:

```powershell
.\scripts\run-complete-release-validation.ps1 -PerformMachineInstall
```

Required evidence:

- MSI is produced for the intended target triple.
- Administrative extraction succeeds.
- Payload contains the desktop executable and `reefvision-api.exe`.
- Hash inventory is recorded.
- Installed application launches against a clean per-user data directory.
- API becomes healthy on loopback.
- The desktop can be closed and relaunched without losing the project database.
- Silent uninstall succeeds without deleting the managed user-data directory.

Signing is a separate release-policy decision. A signed candidate should also use `-RequireMsiSignature` and `-ExpectedPublisher`.

### Gate 3 — deterministic coral journey

The automated coral journey must cover:

1. Create an octocoral project.
2. Import representative PNG/TIFF images.
3. Confirm thumbnails and source checksums.
4. Save reviewed boxes and at least one mask.
5. Create an immutable, group-aware dataset version.
6. Export COCO instance data and verify image, class, box, mask, split, and manifest records.
7. Re-open the project after API restart and confirm all IDs, revisions, and managed files remain valid.

The focused test is `test_stabilization_coral_journey.py`. A passing synthetic journey does not replace the manual installed-app journey with Rafael's representative coral images.

### Gate 4 — real multi-model consensus

Use a manually reviewed subset with stable image IDs and ground-truth masks. Record:

- SAM 3 branch masks.
- Gemini box → SAM 2 masks.
- OpenAI box → SAM 2 masks.
- final consensus masks for `pixel_majority` and `intersection`.
- provider/model versions, prompts, thresholds, request counts, failures, latency, and estimated API cost.

Required scientific summaries:

- object precision and recall;
- mask IoU and Dice;
- boundary or thin-structure retention;
- false-positive and false-negative counts by biological class/state;
- human correction time;
- comparison against SAM 3 alone.

`auto_accept` remains false until the agreed acceptance limits pass. Provider agreement is not ground truth.

### Gate 5 — external interchange

Use `scripts/validate-external-interchange.ps1` with real consumers:

- import a ReefVision archive into CVAT;
- load every LabelMe JSON using the installed LabelMe parser and inspect representative images in the GUI;
- upload an explicitly authorized validation dataset to a private Roboflow segmentation project as predictions;
- re-export where supported and compare image dimensions, filenames, class mappings, instance counts, polygon/RLE geometry, and checksums.

Credentials must be supplied through environment variables. Reports must not contain secret values.

### Gate 6 — simplify the primary user journey

Only begin this UX pass after Gates 1–5 have evidence. The normal path should become:

```text
Create project
→ Import images
→ Define or confirm classes
→ Annotate/review
→ Create dataset
→ Train or select model
→ Evaluate
→ Predict and correct
→ Export/report
```

Acceptance criteria:

- one obvious primary action per screen;
- advanced JSON hidden behind an advanced section;
- consistent language for project, dataset, model, prediction, review, and export;
- clear readiness/error states for local providers and sidecars;
- no need to understand workflow internals for the standard coral journey;
- existing expert controls remain accessible.

### Gate 7 — lift freeze and modularize article branches

After Gates 1–6 pass:

1. Update `.reefvision-feature-freeze.json` through an explicit reviewed change.
2. Design durable artifacts for VLM detections and SAM 2 branch masks.
3. Add separately persisted nodes for SAM 3, Gemini detection, OpenAI detection, SAM 2 refinement, mask consensus, and human review.
4. Preserve cache keys, recovery, checksums, and per-branch cost/provenance.
5. Re-run all release-candidate gates.

## Current environment limitation

GitHub Actions runs for the current PR have been completing with no recorded steps, so they are runner/provisioning failures rather than usable code diagnostics. The authoritative validation environment is currently the executable Windows checkout at:

```text
C:\Users\rafae\Documents\ReefVision\reefvision
```

Do not mark a gate passed from source inspection alone. Store the command, commit SHA, environment versions, output report, and any manual observations for every pass.
