# Review Queue Guide

## Purpose

The Review Queue ranks images that most likely need human attention. It is a prioritization aid, not an automated reviewer.

Generating a queue never:

- edits annotations;
- accepts predictions;
- rejects predictions;
- modifies dataset versions; or
- trains a model.

## Creating a queue

1. Open a project and switch to the `Review Queue` tab.
2. Choose `Entire project` or `Dataset version`.
3. Optionally select a completed QC run to seed unresolved severity signals.
4. Adjust the signal weights if the project needs a different ranking bias.
5. Select `Generate queue`.

The resulting queue is stored historically with its formula ID, formula version, weights, ruleset version, source QC run, and input checksums.

## Reading ranked items

Each ranked item stores:

- the final review score;
- the rank position;
- the highest unresolved QC severity linked to that image;
- a short reason summary;
- the raw signal values;
- the normalized signal values;
- the configured weights; and
- the contribution breakdown that explains the score.

The queue view lets you filter by:

- class;
- split;
- QC severity;
- review state; and
- model ID.

## Queue item workflow

Queue items move through explicit workflow states:

| State | Meaning |
|---|---|
| `pending` | The item is waiting for review. |
| `in_progress` | A reviewer has started working the item. |
| `completed` | The review workflow for the queue item is finished. |
| `skipped` | The reviewer intentionally postponed the item and stored a reason. |

Use the item actions to:

- `Open image` in annotation mode;
- `Start review`;
- `Mark complete`;
- `Skip` with a reason; or
- `Return to queue` after a skipped item becomes actionable again.

Changing a queue-item state does not modify annotations or prediction decisions by itself.

## Opening images from the queue

Opening a ranked image takes you into the annotation editor with a contextual banner that shows the score and the queue reason summary. Returning from the editor takes you back to the `Review Queue` tab rather than the gallery.

## Regenerating a queue

Use `Regenerate` after annotation changes, QC reruns, or prediction review changes. Regeneration creates a new historical queue instead of rewriting the old queue, which preserves prior ranking decisions for auditability.

## Scope behavior

Project-scope queues read the current working project state.

Dataset-version queues rank only the image membership frozen inside the selected dataset version and preserve split metadata from that version where available.

## What the queue does not claim

The current score is an explainable heuristic prioritization score. It is not a calibrated uncertainty estimate, not a training-loss metric, and not a guarantee that the top-ranked image contains an actual mistake.
