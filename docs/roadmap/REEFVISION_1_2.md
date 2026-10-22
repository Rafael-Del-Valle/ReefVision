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
   **Added 2026-10-22:** connected yet independently identified branch segments,
   per-branch calibrated lengths, reviewed junctions, graph connectivity/QC,
   model-predicted branch proposals, Workflow Builder integration and exports.
   See [the dedicated connected branch specification](REEFVISION_1_2_CONNECTED_BRANCH_MEASUREMENTS.md).
   This requirement replaces the earlier suggestion to scope multi-branch
   centerline editing to 1.1; no functionality is claimed complete.
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

## Exploratory paired human–model counts (1.2 development)

`POST /api/v1/ecology/paired-count-comparison` compares paired caller-supplied
human-reference counts with model counts. It reports signed model-minus-human
bias, mean absolute error, and mean absolute percentage deviation, with
zero-reference pairs excluded only from percentage denominators.

With explicit experimental-unit IDs, it also reports descriptive tank/colony/site
summaries without treating individual images or fragments as independent
hypothesis-test replicates. This does not establish that declared units are
genuinely independent.

An executable Workflow Builder node, `ecology_paired_count_comparison`, persists
a typed `paired_count_comparison` artifact with source record IDs and project
identity. Its evidence level is strictly `caller_supplied_unverified`.
Verification of human/model sources against immutable reviewed annotations,
organism identity, calibration, and experimental-unit registration remains
future work. ICC, Bland–Altman agreement limits, and inferential claims are
outside this descriptive feature.

## Descriptive population summaries and stable scientific means (2026-10-19)

The existing standalone longitudinal endpoint and executable, persisted
`ecology_longitudinal_analysis` Workflow Builder node now include
`population_summaries` in their typed `longitudinal_analysis` result.
Only eligible declared experimental units contribute, with **one vote per
unit**, not one vote per photographed fragment or image. Summaries are
stratified by metric, physical unit and first/last **UTC sampling date**;
different sampling windows are not pooled. The number of contributing
organisms is reported separately from the independent-unit count.
Incomplete or mismatched unit windows remain excluded upstream.

Longitudinal unit summaries and human–model paired-count descriptive means
now use deterministic, overflow-safe compensated averaging. Regression tests
cover finite large values, unit weighting, and saved-workflow persistence.
No p-values, confidence intervals, survival rates, authenticated unit
independence or verified source/calibration status are implied.
`caller_supplied_unverified` remains mandatory, and these analysis
artifacts cannot enter verified-dataset ports without a separate review.

## Organism-and-experimental-unit-balanced paired counts (2026-10-19)

The exploratory paired-count API and persisted Workflow Builder artifact now
report nested descriptive means: repeated image pairs per organism, organisms
per declared independent unit, and independent units. Pair-weighted statistics
are retained for backwards compatibility. Zero human-reference pairs do not
contribute to percentage deviation; the response reports eligible organism and
unit denominators, with null percentages if no valid reference exists.
Human/model source record IDs must be disjoint across the comparison.
The caller still supplies unverified identities and experimental-unit labels:
these results cannot establish replication, model accuracy, or significance.

## Technical-replicate guard (2026-10-19)

Exploratory longitudinal and paired human-model schemas now reject declared
independent-unit types that describe technical image observations, including
images, video frames, crops, tiles, masks, annotations, cameras and sensors.
This applies to standalone API requests and to the same Pydantic contracts
used by the executable Workflow Builder adapters. Saved workflows that declare
an image/frame as the experimental unit fail without producing a successful
ecological analysis artifact. Valid tank/colony/site designations are still
caller-supplied and **not authenticated**; the safeguard does not prove
independence or substitute for verified study-design records. It does not
alter previously persisted artifacts. The full application and Windows
acceptance gates remain mandatory.

## Reproducible exploratory input provenance (2026-10-19)

Standalone longitudinal and paired-count analyses now include typed
`analysis_provenance` in their responses and in persisted Workflow Builder
artifacts. SHA-256 fingerprints cover normalized caller-supplied observations,
analysis parameters and algorithm version, with records sorted so changing input
order does not change the digest. The source record ID list is sorted for
stable comparison. A changed measurement, source identifier, reference kind or
algorithm version changes the fingerprint. Regression tests cover both
standalone endpoints and saved workflow execution.

This is a **reproducibility fingerprint**, not a cryptographic attestation of
record ownership, human review, calibration, specimen identity or biological
independence. It does not promote `caller_supplied_unverified` inputs into
verified datasets. Verified project-owned source links, immutable calibration
snapshots, identity histories and scientific review gates remain pending.

## Explicit experimental-unit coverage audit (2026-10-19)

The exploratory longitudinal API and the executable saved Workflow Builder
analysis artifact now include typed `unit_coverage` rows, one per declared
experimental unit and metric. Each row reports observed organisms, complete
follow-up organisms, missing follow-up organisms, eligibility and the exact
exclusion reason. An excluded tank remains visible but is **not** silently
counted as an eligible analytic replicate. The audit reconciles all unit/metric
decisions and rejects contradictory missing-follow-up versus sampling-window
reasons. Standalone and saved-workflow regressions cover the new fields.
All units remain caller-declared and unverified; this does not authenticate
biological identities, establish independent replication or add inference.

## Experimental-unit coverage integrity (2026-10-20)

The shared longitudinal analysis kernel now fails closed on duplicate
organism/metric completions, completed series without matching observations,
organisms reassigned between independent units across metrics, and eligible
units that contain missing follow-up. The same kernel powers the standalone
API and persisted `ecology_longitudinal_analysis` Workflow Builder node.
Focused regression tests exercise these invalid inputs. Unit identity and
biological independence are still caller-declared and unverified; no inference,
p-values, or verified-dataset promotion is introduced. Full CI and installed
Windows acceptance remain release gates.

## Traceable incomplete units and duplicate-decision guards (2026-10-20)

The existing longitudinal API and executable, persisted Workflow Builder node
now return sorted `missing_organism_ids` for each experimental-unit/metric
coverage record, alongside complete/incomplete organism counts. Incomplete
tanks remain excluded rather than becoming additional independent replicates.
The shared audit rejects duplicate eligible/excluded unit decisions, inflated
organism denominators, and forged completed series with only one observation.
The additive response field defaults to an empty list when older artifacts are
parsed. The longitudinal algorithm identifier advances to
`ecology-longitudinal-0003`, distinguishing this changed analysis contract
in reproducibility fingerprints. Regression tests cover the standalone
scientific kernel and persisted saved-workflow equality with the API.

All organism identities, unit assignments and observations remain
`caller_supplied_unverified`. The output is descriptive and requires scientist
review; it does not establish true experimental independence or verify
calibration/source records. Full application CI, scientific acceptance,
migration reconciliation and installed Windows GUI validation are outstanding.

## Strict ecological input contracts (2026-10-20)

Caller-supplied longitudinal observations and requests now reject unknown
scientific-evidence fields (including forged `verified`, `review_status`,
and `calibration_verified`) instead of silently discarding them. Both
longitudinal measurement values and paired human/model counts reject JSON
Booleans before Pydantic's numeric coercion. Valid zero and finite numeric
measurements remain supported. The existing standalone APIs and executable
Workflow Builder nodes share these schemas, so invalid inputs must fail
without producing a successful analysis artifact. Inputs remain
`caller_supplied_unverified` and require source and study-design review.
This is a schema hardening increment, not verification of source records.

## Same-day technical-replicate guard (2026-10-22)

The exploratory longitudinal calculator and its existing executable saved
Workflow Builder node now fail closed when one organism/metric has multiple
observations on the same **UTC sampling date**, even if timestamps differ.
Photographs are technical replicates, not independent biological time points;
there is no implicit first/last selection or unreviewed aggregation. Different
organisms and metrics may legitimately share a sampling date. Timezone offsets
are normalized before checking. A saved workflow fails without a successful
longitudinal-analysis artifact, and the standalone endpoint returns a domain
validation error. The provenance algorithm advances to
`ecology-longitudinal-0004`. This is an additive scientific safeguard with
no database schema migration; prior persisted unverified artifacts are not
rewritten. A future authenticated observation service must support explicit
scientist-reviewed technical-replicate aggregation and identity verification.

## UTC-date-aligned unit windows (2026-10-22)

An exploratory tank/colony/site summary requires matching first and last
**UTC sampling dates** for all constituent organisms, not identical acquisition
hours. Same-day photographs of *different* organisms can occur at different
times without incorrectly excluding their shared experimental unit. The unit
summary retains the earliest baseline and latest final capture timestamps as
an acquisition envelope, while each organism's change-per-day still uses its
own exact elapsed time. Different UTC sampling dates remain an exclusion, and
multiple photographs of the **same** organism/metric on one UTC date remain
prohibited pending reviewed technical-replicate resolution. Provenance advances
to `ecology-longitudinal-0005`. The standalone API and existing executable,
persisted Workflow Builder node use the same domain kernel. This is a
caller-supplied, unverified descriptive analysis; it does not authenticate
organism identity or true experimental independence.

## Caller-declared parent-colony identity safeguards (2026-10-22)

The exploratory paired-count API and executable, persisted Workflow Builder
node accept an optional `parent_colony_id` for each paired image. Once one
pair supplies lineage, every pair must. An organism cannot change parent;
one colony-level experimental unit cannot contain different parents; one
parent cannot be split into multiple independent colony-level units. An
organism/individual/fragment-level unit cannot contain distinct organisms.
Multiple fragments from the same parent may be distributed across different
tanks when tank is the declared unit. Existing unlabeled comparisons remain
compatible but unverified. The algorithm provenance advances to
`ecology-paired-count-0003` and includes lineage in canonical fingerprints.
Standalone and saved workflows share the same validation and fail closed on
conflicting identity declarations. These are caller-supplied labels, **not**
verified specimen identity, true independence, or reviewed human consensus.
No migration, external model acquisition, or verified-dataset promotion occurs.
