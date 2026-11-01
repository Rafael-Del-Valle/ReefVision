# ReefVision 1.6 — QC ranking configuration input validation

## Scope audit

The existing review-queue backend validates nonnegative finite score weights,
a finite positive weight total, and an optional review-confidence threshold in
the closed interval [0, 1]. The existing executable `qc_review_queue`
Workflow Builder node already uses those backend scientific constraints,
provenance, saved graphs/runs, explicit review gates and retry behavior.
This increment does not create another workflow node or bypass backend checks.

## Identified gap

The 1.6 dashboard exposed numeric inputs but allowed Generate queue to submit
negative weights, an all-zero ranking policy, or a confidence percentage outside
[0, 100]. HTML input min/max hints are not validation, and JavaScript's
`Number` conversion can yield non-finite values. A failed server request
could leave researchers uncertain whether their ranking was generated.

## Implementation

- Check every configured weight for finite, nonnegative values, and require
  their sum to be finite and strictly positive.
- Accept an omitted confidence threshold, or a finite percentage between 0
  and 100 inclusive. Convert percentages to backend fractions only after
  validation; 0% and 100% remain valid and distinct.
- Disable Generate queue while the scientific configuration is invalid and
  show a concrete validation error. Revalidate the captured request in the
  mutation handler as a defense in depth.
- Leave regeneration of an already saved queue and all existing review
  decisions, annotations, source QC runs and model weights unchanged.

## Verification and limits

Dashboard React regressions cover negative and all-zero ranking weights,
correction of invalid input, out-of-range percentages and exact 0%/100%
fraction conversion before API submission. Backend validation remains
authoritative for all standalone and saved-workflow requests. These frontend
checks do not establish that a generated ranking is biologically correct.

Release HOLD until exact-head CI passes, the independent 1.1/1.6 Alembic
revision-0038 collision is reconciled, native Windows MSI upgrade/rollback and
installed-GUI acceptance are performed, and representative biological-data
scientific validation and crash-safe QC recovery are complete.
