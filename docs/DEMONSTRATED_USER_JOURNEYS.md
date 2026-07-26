# ReefVision demonstrated user journeys

This file is the release-candidate evidence ledger. A journey is **not demonstrated** until the exact commit, environment, command or manual procedure, artifacts, and observed result are recorded.

Allowed statuses:

- `not-run`
- `failed`
- `blocked`
- `passed-synthetic`
- `passed-real`
- `passed-installed`

Only `passed-real` and `passed-installed` satisfy release evidence where real data, hardware, providers, external applications, or Windows packaging are required.

## Evidence requirements

For every run, record:

- commit SHA;
- date and operator;
- operating system and hardware;
- Python, Node, npm, Rust, CUDA, PyTorch, Ultralytics, Tauri, and provider versions as applicable;
- exact command or numbered manual procedure;
- input dataset or media identifier and checksum manifest;
- output report or artifact path;
- pass/fail observations and unresolved defects.

Never record credentials, API keys, private image contents, or secrets in this file.

## Journey ledger

| ID | Journey | Minimum evidence | Current status | Evidence |
|---|---|---|---|---|
| J01 | Clean Windows installation and launch | Installed MSI, packaged sidecar health, relaunch | not-run | — |
| J02 | Octocoral project creation and image import | Representative PNG/TIFF set, checksums, thumbnails | passed-synthetic | `test_stabilization_coral_journey.py`; real installed-app run still required |
| J03 | Box, polygon, and raster annotation lifecycle | Manual edits, revisions, reload, restart | not-run | — |
| J04 | Immutable dataset creation and group-aware splitting | Manifest, frozen annotations, restart comparison | passed-synthetic | Covered by stabilization coral journey; representative project still required |
| J05 | Detection dataset export and real YOLO training | Real dataset, checkpoint, metrics, report | not-run | — |
| J06 | Segmentation dataset export and real YOLO training | Real masks, checkpoint, class-wise mask metrics | not-run | — |
| J07 | Prediction review and correction | Real detector and segmenter proposals, accept/reject audit | not-run | — |
| J08 | Coral measurement comparison | Representative masks, manual comparison, exported table | not-run | — |
| J09 | Six-class and binary classification | Real training, confusion, calibration, reviewed inference | not-run | — |
| J10 | Fish tracking and behavior | Real video, ByteTrack and BoT-SORT, reviewed ground truth | not-run | — |
| J11 | SAM-family Prompt Assist | Real local checkpoint, positive/negative prompts, reviewed masks | not-run | — |
| J12 | Depth Anything generation | Real checkpoint, relative/metric boundary checks | not-run | — |
| J13 | Active-learning cycle | Real embeddings, explainable selection, annotation, dataset promotion | not-run | — |
| J14 | External COCO/CVAT/LabelMe/Roboflow interchange | Real external consumers and round-trip comparison | not-run | — |
| J15 | Workflow graph validation and execution | Persisted graph using proven services, lineage, restart | not-run | — |
| J16 | Backup, verification, and restore | Restored project in new managed location | not-run | — |
| J17 | MSI build, verification, uninstall | Build report, hashes, install, relaunch, uninstall, retained data | not-run | — |

## Release rule

A release candidate may not claim support for a journey that is `not-run`, `failed`, or `blocked`. Such capability must be one of the following:

1. completed and evidenced;
2. visibly labeled experimental or unavailable;
3. removed from the release candidate.

Synthetic coverage remains valuable, but wording in the README, UI, reports, and PR description must not present a synthetic contract test as real scientific or installed-app validation.

## Deferred skeleton workbench

The coral-skeleton workbench is not part of the current release candidate. Its encoded source payload was incomplete because one of ten required parts was absent. The payload workflow, publisher script, and orphaned parts were removed. The feature may return only as normal source files in a focused PR containing:

- readable implementation files;
- focused unit and integration tests;
- representative coral skeleton fixtures;
- manual comparison with traced reference skeletons;
- a documented user journey and limitations;
- passing release-domain checks.
