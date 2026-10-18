# ReefVision 1.2 — Ecological analysis roadmap

Status: started 2026-10-18; development only, not accepted or published.
Branch: `develop/reefvision-1.2`, independently based on main `9278d45e`.
Do not incorporate unrelated unmerged 1.0.x or 1.1 branches. Reconcile later.

## Purpose

Transform reviewed annotations, calibrated measurements and time-series
observations into reproducible ecological findings. Keep predictions apart
from verified research data. Report the independent sampling unit explicitly.

## Phases and acceptance

1. **Repeated-organism analysis (initial kernel implemented).** A conservative
   exploratory POST endpoint calculates first-to-last absolute and percentage
   changes per organism/metric. UTC timestamps, units and source identifiers
   are retained. Simultaneous records, duplicate sources and mixed units are
   rejected; a zero baseline gives a null percentage; singletons are incomplete.
   Current endpoint accepts caller-supplied observations without authenticating
   them. Unit tests cover scientific edge cases and one API contract test.
2. **Linked identity and provenance (pending).** Persist versioned organism,
   colony and sampled-location identities; link sightings to project-owned,
   verified image/mask/box annotations and immutable calibration snapshots.
   Introduce additive migration, ownership checks, backup/project exchange
   and a UI to confirm identity across sessions.
3. **Derived biological metrics (pending).** Reuse existing calibrated mask
   and centerline infrastructure to calculate colony extent, area, polyp
   density and change, with explicit geometric assumptions and unit QC.
4. **Population monitoring (pending).** Group by design-specified independent
   sampling units (organism, tank, colony, site), report denominators and
   missing follow-ups; avoid false survival and pseudoreplication.
5. **Scientific evaluation (pending).** Human–model agreement, reference
   consensus, bias, uncertainty and group-held-out model comparisons.
6. **Research reporting (pending).** Reproducible CSV, graphics and method
   packages with source IDs, QC, app/model/dataset versions and limitations.
7. **Acceptance (pending).** Full CI, real longitudinal datasets, installed
   Windows/GPU regression and independent ecological review.

## First increment

`POST /api/v1/ecology/longitudinal-analysis` accepts an array of observations
with an organism ID, metric, value/unit, timezone-aware date and source ID.
It returns organism-level endpoint changes and a clear
`caller_supplied_unverified` evidence designation. It does not persist data,
validate caller claims against project records, establish animal identity,
estimate survival, or infer statistical significance. Do not interpret this as
a released or scientifically validated monitoring workflow.

## Integration constraints

Continue development only on the dedicated branch and draft PR. Reuse 1.0.x
measurement and dataset services and plan to integrate 1.1's scientific record
framework once merged and accepted, rather than adding a duplicate store.
Do not merge, tag, publish or deploy without explicit owner approval.

## Descriptive experimental-unit safeguard (development increment)

The exploratory API accepts `experimental_unit_type` on the request and
`experimental_unit_id` on each observation. Saved Workflow Builder nodes can
supply the shared `experimental_unit_type` on each observation, with the same
unit ID on each repeated observation. If either is supplied, both must be consistently declared; one
organism cannot silently change experimental units. For a given metric, mixed
physical units are rejected. Only **within-unit** descriptive means of
organism-level endpoint changes are calculated, never fragment-level
inferential sample sizes. Units with any missing organism follow-up or
mismatched sampling windows are excluded with explicit reasons. The output
reports the number of distinct declared independent units and remains
`caller_supplied_unverified`. It is not a treatment-effect test and does not
establish that caller-designated units are genuinely independent. Future
verified design records and tank/parent-colony assignment are still required.
