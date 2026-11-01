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

## Follow-up: cleared numeric weights (2026-11-01)

A remaining UI gap was found after the initial ranking validation: React's
numeric weight change handler called `Number(event.target.value)` immediately.
Clearing a weight field produces `""`, which JavaScript converts to zero.
This silently changes the researcher's intended scoring policy and makes a
missing value indistinguishable from an explicitly chosen zero.

The dashboard now retains raw weight input strings, maps blank fields to an
invalid value for validation, and only builds numeric score weights when
submitting an otherwise valid configuration. A blank input remains visibly
blank and disables queue generation; an explicit zero is permitted provided
the total of all weights is positive. The backend and existing executable
saved `qc_review_queue` workflow still enforce their original scientific
constraints, with typed outputs, provenance and human-review gates.

The new React regression checks blank-input preservation, absence of an API
request, correction to an explicit zero, and the exact numeric zero sent to
the standalone queue API. This change does not alter persisted queues,
reviewer decisions, source images, migration state or workflow graph formats.
Release HOLD remains until exact-head CI and the existing Windows, migration,
scientific and crash-recovery acceptance gates are satisfied.


## Follow-up: queue creation/regeneration response provenance (2026-11-01)

A successful HTTP response is not sufficient evidence that a newly generated or
regenerated queue belongs to the project and dataset the researcher requested.
Previously, the dashboard trusted the returned queue ID and could select it,
even if a stale or malformed server response referred to another project or
dataset. This is a distinct scope-isolation problem, not a new QC scoring
formula or a new Workflow Builder node.

Both generation and regeneration now validate the returned queue's nonempty ID,
project ID, scope type, and exact dataset-version binding **before** mutation
success can change the selected queue, open quick review, or invalidate queue
history. A mismatched response is surfaced as an error, and the existing
selection is preserved. Because the server may already have persisted the
queue, the error explicitly asks the researcher to inspect queue history before
retrying; the client does not delete, regenerate, or auto-approve any records.

React regressions cover foreign-project responses for both operations, plus
mismatched dataset, scope type and empty IDs for generation. The existing
standalone QC endpoints and typed executable saved `qc_review_queue`
Workflow Builder node remain authoritative and unchanged, including persisted
graphs/runs, provenance, retry identities and researcher approval gates.

CI must confirm frontend formatting, types, Vitest, E2E and production build.
Native installed-Windows GUI, cross-version migration reconciliation and
representative biological-science acceptance remain release blockers.
