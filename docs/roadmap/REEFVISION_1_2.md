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

## Longitudinal parent-colony lineage safeguards (2026-10-22)

Exploratory longitudinal observations may declare `parent_colony_id` in addition
to the existing organism and experimental-unit identifiers. The shared kernel
rejects partial lineage declarations, changes of an organism's declared parent,
different parent colonies inside one colony-level unit, and one parent colony
split across multiple purported independent colony units. Common plural and
`-level` biological unit labels are recognized; different fragments from one
parent in different tanks remain valid when tanks are the declared units.

The standalone API and persisted executable `ecology_longitudinal_analysis`
Workflow Builder node use the same fail-closed validation. The input fingerprint
includes declared parent identity and algorithm version
`ecology-longitudinal-0006`. These safeguards do **not** authenticate colony
identities, project-owned observations, calibration, independence or review;
`caller_supplied_unverified` remains mandatory. Scientific and Windows
acceptance are still outstanding.

## Strict JSON numeric scientific inputs (2026-10-22)

Exploratory longitudinal measurements and paired human–model count inputs now
reject coerced numeric strings, null, arrays and objects rather than silently
parsing them as scientific numbers. Finite JSON numbers and legitimate zero
values remain valid; booleans remain rejected. Both standalone API endpoints
and the existing executable, saved Workflow Builder analysis nodes share the
Pydantic contracts. New API and saved-workflow regressions require invalid
inputs to fail without producing successful analysis artifacts. This does not
authenticate source records, calibrations or organism identity, and does not
change the unverified-evidence/review gate. Full exact-head CI, Windows GUI and
scientific acceptance remain required.

## Cross-unit shared-parent disclosure (2026-10-23)

The exploratory longitudinal and paired human–model comparison responses now
report sorted `cross_unit_shared_parent_colony_ids` when a caller-declared
parent colony occurs in multiple declared experimental units. The same field
is persisted in their existing typed executable Workflow Builder artifacts.
Repeated photographs or fragments within one unit do not create a false
cross-unit flag. Shared parentage across **tanks** is disclosed for study-design
review, not automatically treated as a violation of tank-level independence.
Colony-level unit-splitting still fails closed under the existing lineage policy.
Inputs remain `caller_supplied_unverified`; the field neither authenticates
parentage nor justifies a statistical test. The existing algorithm fingerprints
already bind declared lineage and unit identifiers. Full CI, registered design,
verified identity/calibration, migration and installed Windows acceptance remain
required before release.

## Fail-closed compound sampling-level declarations (2026-10-23)

The exploratory longitudinal and paired human-model analyses now recognize
descriptive labels such as `colony replicate` and `fragment sample` as
colony-level and organism-level declarations for lineage checks. Previously,
extra descriptive words could bypass those checks. Compound declarations
mixing recognized biological levels (for example `colony/tank`,
`organism-colony`, or `tank and site`) are rejected rather than being
silently treated as a new, unguarded independent-unit type.

The shared domain validator is called by both standalone endpoints and the
executable Workflow Builder nodes. Regression tests cover standalone errors,
saved-workflow failure without a successful scientific artifact, and
legitimate fragments from one parent across different tank units. This is a
**caller-label QC safeguard only**: it does not authenticate colony identity,
sampling-unit independence, reviewed annotations, or calibration. Persisted
analysis artifacts retain their unverified evidence and review gates.

## Caller-declared expected-organism roster audit (2026-10-23)

The exploratory longitudinal API and executable `ecology_longitudinal_analysis`
Workflow Builder node now accept optional `expected_organism_ids_by_unit`,
a map from declared experimental-unit ID to its expected organism IDs.
A roster must cover exactly the observed units, contain unique canonical IDs,
assign each organism to only one unit, and include every observed organism.
It is deliberately **caller-supplied and unverified**, not a persistent
experimental-design registration or evidence of specimen identity.

For each observed unit/metric, completely unobserved expected organisms are
listed in `unit_coverage.unobserved_organism_ids` separately from observed
organisms lacking follow-up (`missing_organism_ids`). A unit with unobserved
roster members is excluded from descriptive unit/population means with
`missing_expected_organisms`; unobserved animals are **not** classified as
dead, missing tissue, or zero-valued measurements. Cross-metric rosters are
conservative: every declared organism is expected for every observed metric
within its unit. The analysis does not invent absent metric series.
An absent roster preserves the existing observed-only exploratory behavior.
Roster membership is normalized into SHA-256 provenance; the longitudinal
algorithm contract advances to `ecology-longitudinal-0007`. Both standalone
and saved-workflow artifacts retain `caller_supplied_unverified` evidence.
Full source ownership, verified study design, migrations, GUI and scientific
acceptance remain pending.


## Intermediate UTC sampling-date coverage QC (2026-10-23)

The exploratory longitudinal API and the existing executable, persisted
`ecology_longitudinal_analysis` Workflow Builder node now report two additive,
typed fields on each per-unit/per-metric `unit_coverage` record:
`observed_sampling_dates_by_organism` (sorted UTC calendar dates) and
`discordant_sampling_dates` (true when organisms in the same declared unit
have different observed date sets). This exposes gaps hidden by matching
first/last dates without treating images as independent replicates.

**Scientific boundary:** this flag describes *observed* date discordance only.
Without a registered planned sampling schedule, it does not prove a missed
visit, mortality, absence, or biased treatment assignment. Endpoint-only
descriptive summaries remain eligible when their first/last UTC dates agree,
while actual missing endpoints and unobserved expected organisms retain their
existing exclusion gates. The result stays `caller_supplied_unverified`.
The algorithm version advances to `ecology-longitudinal-0008`, so persisted
artifacts distinguish this reporting contract. Regression coverage includes
standalone API, input-order determinism, no-false-positive control and saved
Workflow Builder artifact parity. Full CI, verified identity/calibration and
installed Windows scientific acceptance remain outstanding.

## Derived technical-replicate label guard (2026-10-23)

The shared experimental-unit policy now also rejects ROI, bounding-box,
segmentation, model-prediction, keyframe, augmentation, thumbnail and
subimage/view labels as *independent biological experimental units*. Compound
labels such as `bounding_box` and `model_prediction` cannot bypass the guard.
The exploratory longitudinal and paired-count schemas use the same policy;
standalone schema regressions and persisted saved-workflow failure tests cover
these labels. Rejected saved runs must not emit a successful scientific
analysis artifact. This is a conservative pseudoreplication safeguard, **not**
validation of caller-declared tank, colony or site independence. No evidence
is promoted from `caller_supplied_unverified`, and the verified identity,
calibration, experimental-design registry, migration and installed Windows
acceptance requirements remain outstanding.


## Explicit planned sampling calendar QC (2026-10-23)

Standalone longitudinal analysis and its executable saved Workflow Builder node
now accept optional `expected_sampling_dates_by_unit` (unit ID to ISO UTC dates).
The calendar must cover exactly the observed units, have at least two unique
dates per unit, and include all observed UTC dates. Any off-calendar
observation is rejected. A unit/metric with missing scheduled observations is
excluded from eligible descriptive unit and population summaries, with
`missing_scheduled_dates_by_organism` and `expected_sampling_dates` reported
in the persisted coverage artifact. Missing visits never imply death, absence,
or zero abundance. Unscheduled historical analysis retains prior behavior.
This is an **unverified caller-declared calendar**, not a registered study
protocol; evidence remains `caller_supplied_unverified`. Canonical calendars
enter SHA-256 provenance; the algorithm advances to `ecology-longitudinal-0009`.
The authenticated specimen registry, calibrated verified source records,
registered designs, migration reconciliation and Windows acceptance remain
pending. No 1.1 environmental-context work is duplicated.

## Planned-visit endpoint QC precedence (2026-10-23)

When a caller explicitly declares a planned UTC sampling calendar, an organism
missing the scheduled first or last date is excluded as
`missing_scheduled_observations` rather than only
`nonmatching_sampling_window`. The exact missing UTC dates remain visible
in `unit_coverage.missing_scheduled_dates_by_organism`, and the unit does not
contribute to descriptive population means. Without a declared calendar,
discordant first/last sampling dates retain the existing
`nonmatching_sampling_window` exclusion. This fixes an actionable QC
classification without implying death, zero abundance, true independent
replication, or verified project-owned observations. Standalone API and
persisted executable Workflow Builder regression coverage is included;
full exact-head CI and Windows scientific acceptance remain release gates.


## Planned organism-visit sampling effort (2026-10-23)

The existing standalone longitudinal endpoint and **executable, persisted**
`ecology_longitudinal_analysis` Workflow Builder node now include typed
`planned_sampling_effort` rows, one per declared unit and metric **only when a
planned UTC sampling calendar is provided**. Each row reports the scheduled
sampling-date count, expected organism count, expected organism-visits,
observed organism-visits, missing organism-visits, observation coverage
fraction and whether an expected-organism roster was supplied. The denominator
is biological organism × scheduled date, **never image, mask or crop count**.
Completely unobserved roster organisms contribute their planned visits to the
missing denominator, not zero abundance or inferred mortality. Without a roster,
the denominator includes only observed organisms and cannot represent unknown
missing animals. All totals reconcile against the existing unit-coverage audit
and fail closed on contradictions. Input-order determinism and source SHA-256
provenance remain intact; scheduled-analysis algorithm version advances to
`ecology-longitudinal-0010`. Unscheduled legacy analysis remains `0008`
and returns an empty effort list. Standalone and saved-workflow regression tests
cover complete visits, missing intermediate visits, absent roster organisms,
legacy behavior and persisted artifact parity. This is **caller-supplied,
unverified descriptive sampling effort**, not an authenticated sampling design,
verified calibration, survival estimate, or treatment-effect inference.


## Planned singleton visit QC (2026-10-23; development only)

A declared UTC sampling calendar now takes precedence over generic missing-follow-up
classification even when an organism has **only one observation**. The existing
standalone `POST /api/v1/ecology/longitudinal-analysis` and executable saved
`ecology_longitudinal_analysis` Workflow Builder node share the same kernel.
An incomplete singleton remains visible in `missing_organism_ids` and
`missing_followup_organism_count`, while its missing planned dates are
reported explicitly in `missing_scheduled_dates_by_organism`. Its declared
experimental unit remains excluded from population summaries; the planned
organism-visit denominator still counts the missing visits, never mortality or
zero abundance. Expected-roster omissions retain higher priority.

For scheduled analyses, the changed scientific QC contract increments
`analysis_provenance.algorithm_version` to `ecology-longitudinal-0011`;
unscheduled legacy analysis retains `ecology-longitudinal-0008`. API and
saved-workflow regression cases cover singleton calendar gaps, consistent
persisted QC/provenance, and unchanged unscheduled exclusions. A Ruff line
length failure from the preceding iteration was also corrected.

This is a **caller-supplied, unverified** descriptive analysis. No verified
organism registry, project-owned annotation or immutable calibration link,
authenticated study design, or biological survival inference is introduced.
Exact-head CI, representative scientific dataset validation, migration
reconciliation, and installed Windows GUI/installer acceptance are still
required before release approval.

## Explicit scheduled-unit identity guard (2026-10-23; development only)

The optional planned UTC sampling calendar now fails closed with a specific
validation error if **any** observation lacks its declared experimental-unit
ID. The domain validator narrows the optional ID before calendar indexing,
addressing the strict mypy failure observed on previous head
`dacd98dc892ba959e38a9420ddfdf567e1228997` (11/14 Actions workflows
passed; the other three failed strict typing). API and executable saved-workflow
regressions assert the missing-ID rejection; a failed saved run must not
produce a successful `longitudinal_analysis` artifact. No change to
sampling calculations, provenance algorithm versions, or historical results.

This check does **not** authenticate experimental units, organisms, reviewed
source annotations, or calibration. Persistent project-owned identity,
verified longitudinal records, registered study designs, source review gates,
full exact-head CI and installed Windows acceptance remain outstanding.

## Per-visit organism sampling coverage (2026-10-23)

The exploratory longitudinal API and executable, persisted
`ecology_longitudinal_analysis` Workflow Builder artifact now include typed
`planned_sampling_date_coverage` rows for every declared UTC visit, metric
and experimental unit. Each row reports the expected and observed organism
denominators, sorted observed/missing organism IDs and the observed fraction.
When a caller-declared roster exists, organisms never observed for a metric
are counted as missing measurements on every planned date. Without a roster,
the denominator is explicitly limited to organisms observed for that metric.
Results are deterministic, and the scheduled analysis algorithm identifier
advances to `ecology-longitudinal-0012` for reproducibility.

These are **sampling-effort QC counts**, not observed abundance, organism
mortality, verified specimen identity, biological independence or evidence of
zero polyp counts. The existing `caller_supplied_unverified` review gate
remains mandatory. This feature reuses the existing typed Workflow Builder
analysis node rather than adding a duplicate node. The persistent identity,
calibration and study-design registry remain unfinished, as do installed
Windows and complete scientific acceptance tests.

## Versioned project-owned organism identity foundation (2026-10-23)

An additive Track B migration `b12_identity_0001` (branch-local descendant of
`0037`) introduces append-only project-scoped organism/colony identity revisions.
Registration and revision APIs validate project ownership, same-project parent
colony registration, complete experimental-unit labels and technical-replicate
rejection. Revision updates require an expected version and preserve history.
A read-only executable Workflow Builder source persists a typed
`ecology_identity_registry` artifact with a deterministic snapshot fingerprint,
`registered_unverified` evidence level and explicit scientist-review gate.
Saved-workflow and standalone acceptance tests exercise project isolation,
revision history and provenance. **This is not verified biological identity**:
annotation/calibration linkage, immutable evidence review, experiment-design
attestation, UI, migration reconciliation with unmerged 1.1 `0038`, real study
acceptance and installed Windows checks remain pending. The exploratory
longitudinal and human/model analyses still reject promotion to verified truth.
