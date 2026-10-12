# ReefVision 1.0.2 — Installed GUI operator acceptance

**Status: NOT EXECUTED.** This is a repeatable sign-off checklist, not evidence of a passed test. The [automated Windows clean-install runner](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147093) passed the MSI installation, application launch, persistence, uninstall, and packaged SAM CPU checks, but it did not exercise all new 1.0.2 interactive tools.

## Setup and evidence

- Use an isolated/disposable Windows environment, not the maintainer's personal workstation. Preserve public 1.0.0/1.0.1 and user datasets.
- Obtain the *complete* MSI and all CABs from the same GitHub Actions artifact produced for the candidate SHA, verify archive digest and `ProductVersion=1.0.2`.
- Record source head SHA, workflow run ID, binary hash, timestamp, Windows build, screen scaling, GPU/CPU/RAM, driver, and whether the bundled or externally acquired SAM was used.
- Create a scratch project containing (a) an empty collection, (b) two small images, (c) one 8192×6144 image, (d) a missing/deleted image entry, (e) saved box, polygon and raster-mask annotations with a mix of draft and explicitly verified status.
- Capture a short screen recording or screenshots and event/report logs without revealing unrelated user data.

## Required interaction cases

| ID | Operator action | Expected evidence | Result |
| --- | --- | --- | --- |
| GUI-01 | Open empty, fresh and previously used projects; reopen after restart | Valid first image loads; recent selection restores; empty state is clear, no stale project image | NOT RUN |
| GUI-02 | Navigate Left/Right, Home/End and gallery thumbnails; jump quickly between images | Active viewer, thumbnail, inspector and annotation layer all agree; no stale overlay | NOT RUN |
| GUI-03 | Navigate with input focused, modal open and gallery collapsed; toggle wrap preference | Text fields don't trigger shortcuts; wrap choice persists; focus behavior is predictable | NOT RUN |
| GUI-04 | Alt+left-drag and middle-drag pan; wheel zoom around cursor; Fit/Actual Size/Reset | Image and annotation overlays move together; saved source coordinates stay unchanged | NOT RUN |
| GUI-05 | Select, copy/paste/duplicate/delete a box and polygon; undo/redo | New IDs, correct class, reversible history, valid source geometry, no inherited verified audit status | NOT RUN |
| GUI-06 | Duplicate a raster mask and restart app | Independent immutable PNG/revision; duplicated annotation draft; source mask unchanged | NOT RUN |
| GUI-07 | With verified reference objects, build a learning snapshot after duplicating draft objects | Only verified originals participate; no evaluation-only predictions enter training data | NOT RUN |
| GUI-08 | Use Shift+1 full-image SAM proposals, edit/accept/reject; Shift+2 selected-mask refinement and discard | Predictions remain pending until accepted; refinement non-destructive until replacement; class number keys preserved | NOT RUN |
| GUI-09 | Rapid navigation, lost mouse focus, pan cancellation, extreme zoom on high-resolution image | No stuck drag, crashes, stale selection, misregistered drawing, or lost unsaved edits | NOT RUN |
| GUI-10 | Persist changes, close, reopen and uninstall from disposable Windows environment | Scratch scientific data persists appropriately and is retained according to uninstaller contract | NOT RUN |

**Never** mark a case PASS without observed GUI behavior and retained evidence. Automated Vitest/Playwright and a process-launch smoke are separate coverage.

## GPU-specific acceptance (not completed by standard Windows CPU runner)

- On available NVIDIA hardware, record `nvidia-smi` GPU/driver info and supported CUDA/PyTorch environment.
- Run **user-initiated** SAM acquisition or previously registered local checkpoint on GPU, plus Shift+1/Shift+2 actions and inference/device fallback.
- Exercise training with a small **verified-only** scratch dataset, inspect device selection, memory/recovery behavior, and confirm trained candidates are never automatically promoted.
- Capture logs and resulting model provenance. If no suitable GPU runner or operator session exists, explicitly report NOT RUN; a CPU SAM pass does not count as GPU acceptance.

## Performance capture

Record at least three independent trials of image opening, zoom/pan, polygon editing, raster editing and mask persistence with fixed input image and annotation counts. Report median, min/max, units, machine and candidate SHA. Do not extrapolate the CI microbenchmarks into full GUI latency. See [responsiveness evidence](REEFVISION_1_0_2_RESPONSIVENESS.md).

## Sign-off

- Operator / date:
- Candidate commit / workflow run / MSI hash:
- Evidence links:
- Passed case IDs:
- Failed case IDs and reproducible steps:
- Skipped case IDs and reasons:
- GPU acceptance evidence or reason untested:
- Release recommendation: HOLD / READY FOR MAINTAINER REVIEW

Release publication, PR merge, tags, and personal-device installation still require explicit maintainer approval.
