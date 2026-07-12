# Prioritization vs Calibrated Uncertainty

## ReefVision Milestone 7 terminology

ReefVision Milestone 7 uses these terms:

- prioritization score;
- review score; and
- ranking score.

It does not claim calibrated uncertainty.

## Why the distinction matters

Calibrated uncertainty normally means a model output has been evaluated and shown to correspond reliably to real error probabilities under a documented calibration procedure.

The Milestone 7 queue does something different. It combines heuristic workflow signals such as:

- low proposal confidence;
- unresolved QC severity;
- disagreement between proposals and verified counts;
- missing provenance;
- stale review state; and
- recent import timing.

Those inputs are useful for triage, but they are not a validated probability that an image is wrong.

## What ReefVision can honestly claim today

ReefVision can currently claim that the review queue is:

- explainable;
- deterministic for identical inputs;
- historically preserved; and
- configurable through explicit signal weights.

ReefVision cannot currently claim that the queue is:

- uncertainty-calibrated;
- a probability of annotation error;
- a confidence interval;
- an active-learning objective with validated statistical guarantees.

## When this document should change

This language should change only after ReefVision implements and validates a real uncertainty-calibration workflow, including:

- a defined probabilistic output target;
- calibration data and methodology;
- held-out evaluation;
- documented calibration metrics; and
- tests showing the calibrated interpretation is justified.
