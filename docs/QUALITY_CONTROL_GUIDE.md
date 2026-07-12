# Quality Control Guide

## Purpose

ReefVision quality control creates historical diagnostic runs for either:

- the current mutable project state; or
- one immutable dataset version.

Quality-control findings are recommendations and audit records only. They never auto-edit verified annotations, never auto-review predictions, and never mutate immutable dataset versions.

## What a run preserves

Every QC run stores:

- the project or dataset-version scope;
- the selected rule categories and explicit rule IDs;
- the current QC ruleset version;
- the configured thresholds;
- practical input checksums;
- run timestamps and status;
- issue counts and summary data;
- failure or cancellation details where applicable.

Every issue stores:

- the rule ID and rule version;
- severity and lifecycle status;
- image, annotation, prediction, and class references where available;
- measured values and thresholds;
- a fingerprint so the same finding can be compared across runs.

## Running quality control

1. Open a project and switch to the `Quality Control` tab.
2. Choose `Entire project` or `Dataset version`.
3. If needed, pick the dataset version to evaluate.
4. Enable or disable rule categories.
5. Adjust thresholds for geometry, overlap, or outlier sensitivity.
6. Select `Run quality control`.
7. Wait for the run to finish, or cancel while the run is still safe to stop.

Project-scope runs evaluate the current working project state. Dataset-version runs evaluate the frozen snapshot referenced by that version and do not rewrite the version.

## Working with issues

Use the issue panel to:

- filter by severity;
- filter by rule ID;
- filter by class ID;
- filter by image ID;
- filter by issue status;
- inspect measured values and threshold values;
- open the affected image directly in the annotation editor.

Opening an image from QC highlights the related annotations or predictions when ReefVision has those IDs available. Returning from annotation mode takes you back to the `Quality Control` tab instead of the gallery.

## Acknowledge, dismiss, and rerun

`Acknowledge` marks that a person has seen the finding. It does not resolve the issue.

`Dismiss` records that the finding is not actionable for the current workflow. The dismissal reason is preserved with the issue.

After correcting project data, run QC again. ReefVision creates a new historical run and compares issue fingerprints across runs. If a prior issue no longer appears, the older issue is marked `resolved_in_later_run` while the old run remains inspectable.

## Run statuses

| Status | Meaning |
|---|---|
| `queued` | The QC job has been created and is waiting for the worker. |
| `running` | Rules are actively being evaluated. |
| `cancel_requested` | Cancellation was requested and the worker is winding down. |
| `succeeded` | The run completed and issue records were persisted. |
| `failed` | Execution stopped with an error message preserved on the run. |
| `cancelled` | The run ended before completion and does not count as a successful report. |

## Issue statuses

| Status | Meaning |
|---|---|
| `open` | The issue is newly reported and unreviewed. |
| `acknowledged` | A reviewer has seen the issue. |
| `dismissed` | A reviewer marked the issue non-actionable and stored a reason. |
| `resolved_in_later_run` | A newer run no longer reported the same fingerprinted issue. |
| `no_longer_applicable` | Reserved for future workflows that can invalidate an issue without deleting history. |

## Comparing runs

Select a newer run in the comparison selector to see:

- added findings;
- resolved findings; and
- unchanged findings.

Comparisons operate on issue fingerprints, not only titles, so threshold changes and measured-value changes remain auditable.

## What QC does not do

QC does not:

- save annotation edits for you;
- auto-accept or auto-reject predictions;
- change review status just because an image was opened;
- rewrite historical runs;
- alter dataset-version contents;
- train or retrain a model.
