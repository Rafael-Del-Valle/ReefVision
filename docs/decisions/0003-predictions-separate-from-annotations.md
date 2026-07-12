# ADR 0003: Predictions remain separate from verified annotations

## Status

Accepted.

## Decision

A model prediction is not a verified annotation. Predictions are stored in a
separate table and only create annotations through an explicit review action.

## Consequences

- Prediction overlays must be visually distinct.
- Acceptance must be idempotent and preserve model provenance.
- Dataset exports use verified annotation snapshots, not pending predictions.
