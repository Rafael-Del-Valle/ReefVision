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

## Parent-colony revision integrity (2026-10-23)

The project-owned identity service rejects reclassification of a colony while
its latest revision is still referenced as the parent of any registered
fragment. Scientists may explicitly revise fragment parent assignments first;
the prior revisions remain append-only for audit. The registry additionally
fails closed when an externally imported or corrupted latest revision leaves
an invalid parent-colony link. This applies to the standalone registry API and
the existing executable, persisted `ecology_identity_registry_source`
Workflow Builder node: no successful registry artifact is emitted for broken
lineage. Tests cover both API and saved-workflow failure, plus legitimate
reviewed correction sequences. The registry remains
`registered_unverified`, never verified biological truth. No new migration
or cross-version merge is introduced. Exact-head CI, migration reconciliation,
source/calibration verification, and Windows acceptance remain outstanding.

## Registered independent-unit identity integrity (2026-10-23)

The append-only project-owned organism identity registry now rejects contradictory
**declared** experimental-unit assignments before creating a revision and when
reading a registry snapshot. For organism/individual/fragment-level unit types,
one declared unit ID cannot be assigned to multiple organisms. For a
colony-level unit, all fragments sharing that unit ID must resolve to the same
registered parent colony; a fragment without a registered parent cannot claim
a colony-level independent unit. Mixed parent colonies remain valid within a
tank or site, where they are not silently promoted into independent colonies.
Checks apply to new registrations, append-only corrections and malformed
imported histories. The existing typed `ecology_identity_registry_source`
Workflow Builder node fails closed without publishing an artifact if the
latest registry violates these rules; API and saved-workflow regressions cover
the behavior. The registry fingerprint, `registered_unverified` evidence level
and scientist-review gate remain unchanged. No database migration is needed.

These are consistency checks on researcher-entered labels, **not** proof of
independent experimental replication, verified source annotations, calibration,
or a reviewed study design. Those remain release blockers. The identity
registry is still isolated from the separate 1.1 scientific schema until
reviewed integration.


## Parent-colony uniqueness across colony-level units (2026-10-23)

The project-owned identity registry now rejects a parent colony assigned to
multiple purported independent **colony-level** unit IDs through different
fragments or its own colony record. It enforces both unit-to-parent and
parent-to-unit consistency on registration, append-only revision, and registry
read-back after external imports. Fragments from one parent may still occur
in distinct **tank** units when tanks are the declared experimental units.

Standalone API and executable saved Workflow Builder regressions cover
registration, revision, corrupt imports, and refusal to persist a successful
registry artifact for contradictory units. Typed outputs, deterministic
provenance, `registered_unverified` status, and scientist review are retained.
This safeguard prevents a form of pseudoreplication; it does not authenticate
biological independence or promote source evidence to verified status.

The seven files flagged by previous exact-head CI were also updated using
the reported Ruff formatter diff. Exact-head CI, real ecological dataset,
migration reconciliation with unmerged 1.1, and installed Windows scientific
acceptance remain outstanding.

## Canonical biological-unit alias safeguards (2026-10-23)

The project-owned organism identity registry now applies the **same**
biological-unit classifier as exploratory lineage analysis. Organism,
individual, fragment, and their plural/level variants refer to one
organism-level independent-unit class; colony/colonies and "colony-level"
refer to one colony-level class. Mixing biological levels in one label,
such as "colony/tank", fails closed rather than bypassing safeguards.
Different parents cannot share one colony unit, and one parent cannot
be split into independent colony units merely by changing label spelling.
Multiple parents within tanks remain legitimate. Unrecognized study-specific
unit labels remain caller-declared and require scientist review.

Standalone registration, revision, imported-record read-back, and the
executable saved Workflow Builder identity source share the same guard.
New regressions cover alias collisions and prevent successful workflow
artifacts for corrupted imported registries. The existing
`registered_unverified` designation, deterministic registry snapshot,
typed workflow ports, and review gate are unchanged. No schema migration
or model download is required. This is **not** verification of biological
identity, source annotations, calibration, or experimental independence.

The exact-head CI mypy failure at
`domain/longitudinal_monitoring.py:365` was also corrected by using a
distinct optional-ID variable for the observed row instead of assigning
a `str | None` into the loop's inferred `str` calendar key. CI and
Windows scientific acceptance must still be rechecked.


## Identity registry executable workflow and Alembic acceptance repair (2026-10-23)

Exact-head GitHub Actions for `7807566f71496955ad222699ee07aa62c21e961d`
completed 17 of 19 workflows successfully. The CI backend and ReefVision 1.0
acceptance backend jobs exposed six failing tests: five saved-workflow identity
source tests failed before reaching registry integrity checks because the
workflow executor injects internal `__workflow_run_id` and
`__workflow_node_run_id` parameters; the source adapter incorrectly rejected
all nonempty parameter dictionaries. The adapter now permits **only** those
two executor-injected trace keys while rejecting any caller-configured
parameters, including attempted `verified` promotion. A saved-workflow
regression requires such an attempted promotion to fail without publishing
an ecological registry artifact. Existing valid and corrupt-registry saved
workflow regressions must now exercise the actual source and scientific gates.

The sixth failure was a legacy migration test assuming the head remained
`0037`. The Track B branch test now asserts exactly one Alembic head,
`b12_identity_0001`, whose parent is `0037`. This does **not** reconcile
the separate unmerged 1.1 `0038` migration; integration must explicitly
resolve both lineages and rerun upgrade/downgrade and installed Windows
acceptance before any merge. No biological identity, annotation, calibration
or dataset is promoted to verified status by this correction. New-head CI
and scientific acceptance remain required.

## Imported technical-unit replay guard (2026-10-24)

The project-owned identity registry now revalidates the independent-unit type
of every latest database revision before returning an API snapshot or an
executable `ecology_identity_registry_source` Workflow Builder artifact.
Ordinary API writes already reject image/frame/camera/annotation units through
the Pydantic schema; an imported or externally altered revision could
previously bypass that input validator. The service now fails closed rather
than exposing the imported technical observation as a biological replicate.

Standalone API and persisted saved-workflow regressions inject a malformed
`video_frame` revision, require an explicit validation failure, and assert
that no successful identity-registry workflow artifact is produced. The
previous exact-head CI had 16 successes and three failures due to one Ruff
format mismatch in the identity-registry test; that mismatch was also
corrected in this increment. **New-head CI, full scientific verification,
migration compatibility, and installed Windows GUI acceptance remain
required.** This is a safeguard for registered-unverified identity metadata,
not a claim that independent sampling units have been authenticated.

## Imported identity revision continuity (2026-10-24)

The project-owned ecological identity service now verifies that every
organism's append-only revision chain begins at 1 and has no missing revision
numbers. The previous latest-only lookup could silently accept a corrupted
import with revision 1 followed by revision 3, or a revision 0 preceding the
original registration. All registry reads, registration/revision writes, and
the executable `ecology_identity_registry_source` Workflow Builder node now
fail closed when such a gap is present. This does not alter valid contiguous
revision histories, does not delete imported data, and does not promote
`registered_unverified` identities to scientific observations.

Regression coverage includes valid two-revision histories, project isolation,
both malformed revision patterns, API write refusal, and persisted saved-workflow
failure without a successful identity-registry artifact. Exact-head CI remains
required; tests committed are not equivalent to tests passed. Linking identities
to reviewed annotations, immutable calibration snapshots and registered
experimental designs is still unfinished. No Windows installed-GUI or real
longitudinal scientific acceptance is claimed.


## Full identity-revision provenance fingerprint (2026-10-24; development only)

The project-owned registry now exposes an additive `history_sha256` and
`history_revision_count` alongside its backwards-compatible latest-identity
`snapshot_sha256`. The history fingerprint covers **every** project-owned
revision, including revision IDs, lineage, experimental-unit declarations,
scientist-entered correction reasons and creation timestamps. A retroactive
change to an earlier revision changes the history digest even if the current
latest-identity snapshot remains identical. The existing executable, persisted
`ecology_identity_registry_source` Workflow Builder node emits the same typed
provenance as the standalone registry API. Defaults on the new schema fields
allow previously persisted unverified artifacts to deserialize.

This is a history-sensitive reproducibility checksum, **not** an immutable
external attestation or a verification of specimen identity, annotation
ownership, calibration or experimental-unit independence. Both outputs remain
`registered_unverified` and `scientist_review_required`. Focused regression
tests cover earlier-revision mutation and saved-workflow artifact parity.
The previous head's three failed Actions workflows shared three Ruff-format
violations; those exact lines were also corrected. Exact-head CI, real
scientific acceptance, cross-version migration reconciliation, installed
Windows GUI and release approval remain outstanding.


## Project-owned immutable image-source identity links (2026-10-24; development only)

An additive branch-local migration `b12_identity_0002` introduces append-only
organism-to-image evidence links. The new
`POST /api/v1/projects/{project_id}/ecology/organisms/{organism_key}/image-evidence`
requires a registered organism, its current expected identity revision, and a
source image owned by the same project. It captures the managed image's SHA-256,
the identity revision and the scientist-entered association reason. Duplicate
organism/image links, stale revisions and foreign-project images are rejected.
No image or identity record is modified or deleted.

The existing standalone registry and executable, persisted
`ecology_identity_registry_source` Workflow Builder node expose identical
typed `image_evidence_links`, `image_evidence_count` and deterministic
`image_evidence_sha256` provenance. A changed/missing source image or broken
imported link fails closed before a successful registry artifact can be emitted.
The earlier latest-identity and full-revision history fingerprints remain
backward-compatible; an independent image-evidence fingerprint changes when
a link is added. Saved-workflow and API regressions cover parity, project
isolation, duplicate/stale rejection, and source integrity.

**Critical limitation:** this links an organism *claim* to an immutable image
fingerprint; it does **not** verify which animal appears in the image, that an
annotation was reviewed, that calibration is immutable, or that a longitudinal
measurement is scientifically verified. All links are `linked_unverified`;
the registry remains `registered_unverified` and
`scientist_review_required`. No predictions or caller-supplied observations
are promoted to verified truth. Next: link specific reviewed mask/box
annotation revisions and calibration snapshots with scientist review and
registered experimental design. The new migration is isolated from unmerged
1.1 `0038` and requires explicit reconciliation, exact-head CI, scientific
dataset validation, and Windows installed-GUI acceptance.

## Image-source metadata QC (2026-10-24)

The project-owned organism-to-image evidence service now rejects malformed
source-image SHA-256 values (anything other than 64 hexadecimal characters)
and nonpositive source width, height or file size. Checks run both when
registering an image association and when reading a registry containing
existing links. A corrupt source cannot enter a successful persisted
`ecology_identity_registry_source` Workflow Builder artifact. Regression
tests cover API rejection before linking and failed saved-workflow execution
after source metadata corruption. This is a **database metadata QC gate**,
not a rehash of physical image bytes or confirmation of capture time,
reviewed annotation, calibration or biological identity. The evidence
remains `linked_unverified`; no scientific observation is promoted.
The migration lineage remains `b12_identity_0002` for this no-schema-change
increment and still needs reviewed reconciliation with unmerged 1.1.

## Project-owned annotation revision evidence (2026-10-24; development only)

Migration `b12_identity_0003` adds append-only, project-scoped evidence
linking an existing organism/image association to a **specific box or mask
annotation revision**. The new
`POST /api/v1/projects/{project_id}/ecology/organisms/{organism_key}/annotation-evidence`
requires the exact organism-owned image-evidence ID, annotation kind, source
annotation ID, expected revision and scientist-entered reason. The service
rejects missing, deleted, cross-image, stale, duplicate or model-generated
annotations. Image annotation status must be `reviewed`; mask status must
also be `verified`. These are *editor workflow statuses*, not independent
scientific verification or an immutable reviewed dataset.

The link captures a SHA-256 digest of the current canonical annotation
snapshot (geometry, class, source, revision and provenance) without copying,
editing or promoting the source annotation. Subsequent annotation edits,
deletion, source-kind changes, or revoked image review cause standalone
registry reads and the executable, persisted
`ecology_identity_registry_source` Workflow Builder node to fail closed
rather than emit a successful scientific artifact. The existing typed
`ecology_identity_registry` port now carries
`annotation_evidence_links`, `annotation_evidence_count` and
`annotation_evidence_sha256`. Default fields preserve deserialization of
earlier unverified workflow results. Both standalone and saved-workflow
artifacts remain `registered_unverified`, with
`scientist_review_required`; annotation links are `linked_unverified`.
No training weights are downloaded or deployed.

Focused regressions cover box and mask links, duplicate and cross-image
rejection, stale revisions, changed geometry, model-source refusal, review
revocation and saved-workflow artifact parity/failure. The prior
`92ca54e6` exact-head Actions finished **16/19 successful**, with three
backend failures sharing Ruff formatting in the image-evidence service/tests;
those reported formatting differences were corrected in this increment.
The new head has not been validated by CI or installed Windows GUI testing.
A verified calibration snapshot, independent reviewer decision, authenticated
study design and real longitudinal dataset remain required before any
calibrated measurement or inference can be labeled verified. The new migration
also requires reviewed reconciliation with unmerged 1.1 migration `0038`.

## Annotation geometry and class-ownership QC (2026-10-24)

The existing append-only organism-to-annotation evidence service now checks
source-pixel bounding boxes for finite, positive, in-image geometry, checks
stored mask polygon coordinates and positive area when present, and verifies
that any annotation label class belongs to the same project as its source
image. The same service validates both initial API linking and subsequent
identity-registry reads; saved executable Workflow Builder registry sources
fail without a successful artifact when imported or subsequently altered
annotation geometry is invalid. Focused regressions cover invalid box
coordinates, mutated mask polygons, and foreign-project class assignments.
The existing immutable annotation fingerprint and scientist-review-required
gate are retained. This is **source geometry QC only**, not calibrated area,
confirmed organism identity, an immutable calibration snapshot, or verified
longitudinal biological evidence. Calibration linking remains the next
scientific dependency. No new migration or model weights are involved.


## Frozen source-image calibration evidence (2026-10-24; development only)

Branch-local migration `b12_identity_0004` adds append-only calibration evidence
for an **existing, project-owned, reviewed-human annotation revision** already
linked to an organism. The
`POST /api/v1/projects/{project_id}/ecology/organisms/{organism_key}/calibration-evidence`
endpoint requires the annotation evidence ID, its expected SHA-256 and explicit
source-calibration confirmation. It reads ReefVision's existing saved
`measurement_calibration` image metadata; it does **not** introduce a
parallel calibration system or accept a detector candidate as a physical scale.

The record freezes a normalized calibration payload, source-image ID/SHA-256,
SHA-256 fingerprint, scientist-entered reason and creation time. A missing or
malformed calibration, nonfinite scale, camera-resolution mismatch, stale
annotation fingerprint, cross-organism link or duplicate association fails
closed. Subsequent changes to the source calibration or frozen snapshot also
invalidate the standalone identity-registry read and the **executable, typed,
persisted** `ecology_identity_registry_source` Workflow Builder output.
Deterministic `calibration_evidence_sha256`, counts and links are exposed
alongside existing identity/image/annotation fingerprints; saved-workflow
and standalone regression cases exercise parity and failure without a
successful scientific artifact.

**Scientific limitations:** a user-confirmed saved image scale is not
independently verified specimen identity, calibrated longitudinal measurement,
experimental-unit independence or an immutable verified dataset. These records
remain `linked_unverified`; the registry remains `registered_unverified`
with `scientist_review_required`. Source changes are conservatively treated
as invalidating evidence, even if a legitimate correction was made; no
automatic promotion or rewriting of historical records occurs.

The previous exact-head `68c15650` had **16 successful and 3 failed
GitHub Actions workflows**, all three stopping at two Ruff formatter
differences in ecological source/tests. Those exact diffs were corrected
before adding this calibration unit. The new head still needs exact-head
CI (including Ruff, pytest, typing, frontend and E2E), Alembic
upgrade/downgrade and SQLite FK checks, realistic calibration fixtures,
scientist acceptance, 1.1 `0038` migration reconciliation and installed
Windows GUI/installer acceptance. No new-head pass is claimed.


## Physical-unit and camera-signature calibration QC (2026-10-24)

The existing organism/annotation calibration-evidence path now rejects
source-image calibrations whose declared unit is `px`, `pixel` or
`pixels`. A pixels-per-pixel declaration cannot serve as a physical
length scale for longitudinal ecology. The same source validator rejects
nonfinite focal length and capture-distance values in optional camera
signatures, in addition to existing nonfinite scale and camera-resolution
checks. This validation runs both when linking evidence through the
standalone API and when re-reading existing evidence for the executable
`ecology_identity_registry_source` Workflow Builder node.

Regression tests exercise rejection of a previously linked calibration
changed to pixel units, rejection of nonfinite camera metadata before
linking, and revocation after linking. Saved workflows must fail without
a successful `ecology_identity_registry` artifact when these conditions
are detected. All evidence remains `linked_unverified` and subject to
`scientist_review_required`; this is input QC, not proof of biological
identity, a reviewed measurement or experimental independence.

At the preceding head `7ca157a5`, GitHub Actions completed 16/19
workflows successfully; CI, Pose Workflow Validation and ReefVision 1.0
Acceptance stopped at the same three E501 Ruff errors in
`services/ecology_identity.py`. This iteration corrects those lines
and adds the scientific checks above. Exact-head CI, complete migration
roundtrip, scientific data acceptance and installed Windows GUI checks
remain outstanding. No release-readiness claim is made.

## Recognized physical calibration dimensions (2026-10-24; development only)

The existing organism-to-annotation calibration evidence service now requires
a recognized **length** unit (nanometres, micrometres, millimetres, centimetres,
metres, kilometres, inches, feet or yards, including common abbreviations and
US/UK spelling variants). Previously, arbitrary non-length strings such as
`seconds` or `degrees` could pass the generic saved-image calibration schema
and be mistaken for physical organism measurements. Pixel units and compound
pixel-per-length expressions also fail closed. No automatic unit conversion
or inferred calibration is performed: the source scale and unit are frozen
exactly as supplied. A micro-symbol unit (`µm`) is explicitly supported.

Both standalone calibration-evidence linking and the executable, persisted
`ecology_identity_registry_source` Workflow Builder read use the same
dimensionality gate. A later source-unit mutation invalidates the existing
link and causes saved workflow execution to fail without a successful
ecological registry artifact. Focused regressions cover invalid units before
linking, accepted micro-symbol units, and post-link revocation.

The previous head `8728a41a` finished **16/19 Actions workflows successfully**;
CI, Pose Workflow Validation and ReefVision 1.0 Acceptance stopped at the
same three Ruff-format differences in the identity service and annotation/
calibration regression tests. This increment corrects those exact formatter
differences. **New-head CI and real scientific acceptance are still required.**
The linked records remain `linked_unverified`, with
`scientist_review_required`; no longitudinal measurement is promoted to
verified evidence. The 1.1 migration-lineage reconciliation, complete
backend/frontend/E2E and installed Windows GUI/installer checks remain open.

## Source-linked projected measurement candidates (2026-10-24)

The read-only `GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates`
endpoint derives conservative bounding-box width/height and mask projected area
from current project-owned reviewed annotation revisions and frozen physical
calibration evidence. The existing executable `ecology_identity_registry_source`
Workflow Builder node now emits a second typed, persisted
`ecology_measurement_candidates` output port. API and saved-workflow outputs
share deterministic source fingerprints, parent-colony/experimental-unit labels,
source-image SHA-256, annotation/calibration revision hashes and explicit
scientist-review gates. No new migration is required: candidate results are
derived from existing b12 identity evidence and saved as workflow artifacts.

Perspective-homography cases are explicitly excluded pending proper per-point
reprojection, rather than incorrectly multiplied by a scalar. Missing or naive
capture timestamps are never fabricated into UTC biological observations.
All projected values remain `linked_unverified`: a box extent is not coral
centerline growth, image annotation review is not biological identity review,
and tank/colony independence is not proven. No survival, p-values or verified
longitudinal records are claimed. Scientific datasets, calibrated real-image
checks, complete CI and installed Windows acceptance remain outstanding.


## Source-linked UTC sampling-date QC (2026-10-24; development only)

The project-owned calibrated-measurement-candidates API and the executable,
persisted `ecology_identity_registry_source` Workflow Builder output now include
typed `sampling_date_qc` records for each organism/metric. The shared backend
audit normalizes timezone-aware capture timestamps to **UTC calendar dates**,
reports missing timestamps, mixed physical units, duplicate same-day technical
replicates and insufficient follow-up dates. A `date_series_candidate` status
requires at least two distinct UTC sampling dates, no missing timestamps,
no duplicate date measurements and consistent declared units. This is only
a date-series *screening result*, **not** a verified longitudinal observation
or a biological growth calculation. All records remain `linked_unverified`
with `scientist_review_required`; perspective exclusions remain explicit.
The deterministic input fingerprint includes the typed QC rows and uses
algorithm version `ecology-measurement-candidates-0002` while retaining the
additive response schema for compatibility. Standalone API, saved-workflow
artifact parity and scientific QC regressions cover the new output. Existing
migration `b12_identity_0004` is unchanged. Authenticated observation dates,
identity confirmation, experimental-unit registration, verified source datasets,
independent scientific review, full exact-head CI and installed Windows
acceptance remain outstanding.


## Source-linked projected endpoint-change candidates (2026-10-24; development only)

The existing project-owned calibrated-measurement-candidates API and the
executable, persisted `ecology_identity_registry_source` Workflow Builder
artifact now expose typed `projected_endpoint_changes`. Each descriptive
record compares the earliest and latest **UTC-dated** reviewed-source
projected geometry for one organism and metric, retaining the source image,
annotation evidence, calibration evidence, identity revision, experimental-unit
declaration, timepoint denominator, physical units, absolute/percentage
difference and elapsed days. The algorithm fingerprint advances to
`ecology-measurement-candidates-0003`; older artifacts deserialize with an
empty default field. No schema migration or new workflow node is necessary.

The shared QC now reports `identity_context_changed` and suppresses endpoint
changes if the organism's linked identity revision, parent-colony lineage or
declared experimental-unit assignment differs across dates. Mixed units,
missing/naive timestamps, same-day technical replicates and insufficient
follow-up dates likewise produce **no** endpoint change. No p-values,
mortality, survival, biological growth or treatment inference is calculated.
The output remains `linked_unverified` with
`scientist_review_required`: projected box width/height and mask area
are not validated colony growth, and the identity and sampling design are not
independently verified. Source provenance and prior review gates remain intact.
Focused pure scientific regression and saved-workflow payload-parity tests are
included. Exact-head CI, real acquisition-date datasets, migration-lineage
reconciliation and installed Windows acceptance remain outstanding.


## Provisional projected independent-unit coverage (2026-10-24; development only)

The source-linked calibrated-measurement API and existing executable, persisted
`ecology_measurement_candidates` Workflow Builder output now include typed
`projected_unit_summaries`. Each row represents one *declared* experimental
unit and metric, with organism denominators, incomplete follow-up IDs, parent
colony disclosures, physical units and UTC sampling windows. Descriptive
within-unit means require complete paired follow-up for **every organism**,
consistent physical units and matching sampling windows. An incomplete tank
is excluded as a whole rather than silently dropping a fragment. Image/frame/
camera and other technical replicate units are excluded; missing declarations
and incompatible windows are explicit. Multiple organism observations in one
tank produce **one unit summary**, not multiple independent replicates.

The result remains `linked_unverified` and
`scientist_review_required`: declared units have not been authenticated as
independent, and projected geometry is not verified biological growth. No
cross-unit pooling, survival estimates, p-values or model promotion are added.
The deterministic fingerprint advances to
`ecology-measurement-candidates-0004` and includes unit QC; the additive
field defaults to an empty list for older persisted artifacts. Focused QC
regressions and existing API/saved-workflow payload parity cover the new output.
Exact-head CI, migration reconciliation, independent scientific acceptance
and installed Windows GUI acceptance remain outstanding.

## Equal-weight source-linked projected population strata (2026-10-24; development only)

The project-owned calibrated-measurement API and existing executable,
persisted `ecology_measurement_candidates` Workflow Builder artifact now
include typed `projected_population_summaries`. Each descriptive row pools
**only eligible** projected-unit QC records with identical declared unit
type, physical metric and unit, and UTC first/final sampling dates.
Each declared unit receives **one vote**, irrespective of the number of
fragments, organisms, photographs or annotations within that unit.
Incomplete, technical-replicate and otherwise QC-excluded units cannot
contribute to a pooled mean. Separate strata are not silently combined.

Outputs disclose declared-unit and organism denominators, unit IDs,
parent-colony labels reused across units, and units missing parent-colony
provenance. Shared parents are a blocking concern for any independence
interpretation, not evidence of independent replication. The results remain
`linked_unverified` and `scientist_review_required`; they do not establish
independent experimental units, verified biological growth, inferential
statistics or treatment effects. The typed additive response defaults to an
empty list for older persisted artifacts; the deterministic source fingerprint
advances to `ecology-measurement-candidates-0005`. Existing typed Workflow
Builder output, saved-workflow persistence and standalone API share the same
service result. Scientific regressions cover equal unit weighting, exclusion,
stratification, parent-colony disclosure and API/saved-artifact parity.

The preceding head `0d55e260` completed **16/19 Actions workflows**.
Three backend gates (CI, Pose Workflow Validation and ReefVision 1.0
Acceptance) stopped at the same Ruff formatting differences in the unit
service and regression test. This iteration includes the exact formatter
corrections. Current-head CI, migration lineage reconciliation with unmerged
1.1, authenticated longitudinal review, representative scientific datasets,
installed Windows GUI/installer acceptance and independent scientific review
remain outstanding. This increment does not make 1.2 release-ready.

## Projected population dispersion and experimental-unit identity QC (2026-10-24)

The source-linked `projected_population_summaries` API and the existing
persisted, typed `ecology_measurement_candidates` Workflow Builder artifact
now report **sample standard deviation across declared experimental-unit
means**, not across fragments, images or annotations. For one eligible unit
the sample SD is null (not zero); for two or more units the denominator is
`n_units - 1`. The prior equal-weight means and sampling-window strata are
unchanged. A single organism/metric occurring in two eligible declared units
is rejected, even when the records are split across UTC sampling windows.
Different metrics of the same organism remain separate responses.

Machine-readable `design_review_blockers` disclose unauthenticated unit
independence, single-unit strata, shared parent colonies and missing
parent-colony provenance. `independent_unit_inference_allowed` is always
false for this unverified evidence; no standard error, confidence interval,
p-value or treatment inference is emitted. This is descriptive QC, not
independent experimental-design validation or biological growth verification.
The deterministic fingerprint advances to
`ecology-measurement-candidates-0006`; additive schema fields default for
older persisted artifacts. Standalone regression tests cover equal-unit
dispersion, one-unit suppression, parent-lineage warnings and duplicate
organism exclusion; the existing saved-workflow/API artifact-parity test
covers serialization through the executable typed port. Exact-head CI,
representative scientific review, full migration reconciliation and
installed Windows acceptance remain required.

## Numerically stable declared-unit dispersion (2026-10-24; development only)

The source-linked projected population summary now computes descriptive sample
standard deviation with a scaled Euclidean norm (math.hypot) rather than
squaring unit-mean deviations directly. This avoids an intermediate overflow
for large but finite projected changes whose standard deviation is representable
as a finite float. The denominator remains **n declared units - 1**, never
n fragments or n images; single-unit strata continue to return null SD.
The CI formatter discrepancies in the previous head's schema and regression
test were also corrected. A focused scientific regression covers finite
unit means around 10^155, where direct squared deviations would overflow,
and confirms the result still prohibits inferential claims. The existing
standalone API and saved Workflow Builder artifact share this service and
typed schema; no new migration or workflow port is needed. The evidence remains
linked_unverified, requires scientist review, and does not establish
independent replication or biological growth. Exact-head CI, scientific
acceptance, migration reconciliation and installed Windows GUI tests remain
required.

## Projected population type-safety and exact-head CI repair (2026-10-24)

The latest prior head (`8de92f66`) completed 16/19 GitHub Actions workflows;
CI, Pose Workflow Validation and ReefVision 1.0 Acceptance failed in strict
mypy on seven diagnostics in `ecology_measurement_candidates.py`. The repair
uses an explicitly typed organism/metric endpoint lookup, distinct keys for
organism ownership versus population strata, and a fail-closed check for
nullable eligible-unit means before descriptive aggregation. The existing
unit-balanced statistics, scientific review gates and `linked_unverified`
evidence status remain unchanged. Added regression coverage for eligible
rows with missing absolute or percentage means. This is a type-safety and
integrity repair, not verified longitudinal biology. Exact-new-head mypy,
focused scientific tests, saved-workflow tests, migrations and installed
Windows acceptance must pass before any release-ready claim.


## Exact-head projected endpoint QC consistency (2026-10-24)

The previous head `cb321536` completed 17/19 Actions workflows. Backend
pytest failed on a stale test expectation: the fixture's calibrated box
height is 5.0 mm, so a +2.5 mm endpoint difference is **50%**, not 40%.
The separate 6.25 mm box-width case correctly yields 40% for +2.5 mm.
The test now checks both physical baselines explicitly; the production
percentage formula remains unchanged. An unrelated video-pose frontend test
also failed and is not silently treated as a 1.2 science failure repair.

The existing projected endpoint kernel now recomputes sampling-date QC from
its current source-linked candidates and rejects missing, duplicated, forged
or stale audit rows before producing changes. This fails closed if capture
dates, units or identity revisions are altered after an earlier QC pass.
Focused regressions exercise stale and forged decisions. The standalone
source-linked API and existing executable, persisted typed Workflow Builder
use this same kernel, retain deterministic provenance and mandatory scientist
review, and do **not** promote projected geometry to verified growth. No new
migration or node is introduced. Exact-new-head CI, real biological review,
installed Windows GUI and complete release acceptance remain pending.

## Projected ecological unit source integrity (2026-10-24)

The source-linked projected-measurement service now recalculates endpoint
changes from current source candidates and sampling-date QC before accepting
them for experimental-unit aggregation. Missing, stale, edited, or duplicated
endpoint changes cannot silently become unit-level descriptive means.
Population aggregation also rejects repeated experimental-unit/metric records
across differing sampling windows or physical units, and rejects eligible rows
whose complete-organism denominator does not match their organism roster.
These checks apply to the existing standalone calibrated-candidate API and
the persisted, typed `ecology_identity_registry_source` Workflow Builder output;
focused regressions cover forged changes, duplicate unit records and inflated
organism counts. The provenance algorithm identifier advances to
`ecology-measurement-candidates-0007` so new artifacts cannot be confused
with earlier calculation contracts. No migration or new environmental store
is introduced. Source-linked projected geometry is **still unverified** and
cannot be interpreted as confirmed growth or independent replication; it
requires scientist review. CI, installed Windows GUI, and independent
scientific acceptance remain required.

## Cross-metric organism design consistency (2026-10-24)

The source-linked projected experimental-unit summarizer now checks each
organism's identity revision, parent colony, experimental-unit type and unit ID
**across all metric types**, in addition to the existing per-metric date QC.
Contradictory assignments fail closed before unit/population summaries are
calculated, preventing one specimen from silently contributing to different
experimental units through width, height or area measurements. Focused tests
cover valid paired metrics and conflicts in tank, parent colony and identity
revision. The shared service continues to power the standalone API and
persisted, typed Workflow Builder artifact; existing saved-workflow parity
regressions remain in scope. The deterministic provenance algorithm advances
to `ecology-measurement-candidates-0008`.

The same iteration corrects two exact Ruff formatting violations identified
in the previous GitHub Actions backend checks. The code and tests were pushed
for new exact-head CI; no CI success, authenticated independence, verified
biological growth, Windows installed-GUI acceptance or release readiness is
claimed until those checks are actually observed. Human verification of
identity/design assignments and immutable longitudinal observation records
remain outstanding.

## Historical identity-revision measurement gate (2026-10-24)

The project-owned calibrated measurement candidate service now **excludes**
previously linked annotation/calibration evidence when its source-image
identity revision no longer equals the organism's latest registered revision.
An append-only correction to parent-colony or experimental-unit assignment
must not silently relabel older projected measurements with the new identity
context. Exclusions report `identity_revision_requires_review` with the
calibration-evidence ID, preserving auditability without deleting source links.
The source registry remains readable; a scientist must explicitly re-review
the historical association before it can enter future analyses.

The existing standalone calibrated-measurement endpoint and executable,
persisted `ecology_identity_registry_source` Workflow Builder path share this
gate. A regression covers API results, historical revision retention,
provenance fingerprint change and saved-workflow artifact parity. The
fingerprint algorithm advances to `ecology-measurement-candidates-0009`.
The prior exact-head CI had 16/19 successful workflows; the three failures
were all Ruff formatting of a cross-metric test list comprehension, corrected
in this increment. New-head CI, migration reconciliation, true reviewed
longitudinal observations, scientific acceptance and Windows installed-GUI
validation remain required. This gate does **not** promote unverified data.

## UTC elapsed-time normalized projected slopes (2026-10-24)

The source-linked longitudinal candidate kernel now returns two optional,
typed endpoint fields: `projected_absolute_change_per_day` in the existing
metric unit per elapsed UTC day, and
`projected_baseline_percent_change_per_day` in baseline-relative percentage
points per elapsed UTC day. The denominator is the exact elapsed acquisition
time (including fractional days), **not** the number of photographed dates.
The calculations are descriptive endpoint slopes, **not** estimated biological
growth rates, survival, causal effects, or evidence of independent replication.
The existing `linked_unverified` level and mandatory scientist-review gate
remain unchanged. Nonfinite/zero-duration rates fail closed; older persisted
typed results lacking the optional fields remain deserializable as null.

The same typed response is used by the standalone calibrated-measurement API
and the persisted executable `ecology_identity_registry_source` Workflow
Builder artifact, with deterministic provenance advanced to
`ecology-measurement-candidates-0010`. Focused regressions cover 1-day and
3-day elapsed intervals, overflow, legacy typed artifact compatibility, and
review requirements; existing API/saved-workflow payload parity remains the
integration gate. The preceding head had 16/19 passing GitHub workflows, with
three Ruff-format failures; the exact offending comprehension is normalized
in this iteration. **Exact-head CI, real longitudinal scientific acceptance,
Windows installed-GUI testing, and authenticated observation records remain
outstanding.** No schema migration, environmental duplication, model weights,
or verified-dataset promotion are introduced.

## Source-image replay guard for projected longitudinal candidates (2026-10-25)

A single photograph cannot represent two independent biological sampling dates.
The source-linked UTC sampling-date audit now records `reused_image_ids` and
sets `qc_status=reused_image_across_dates` when one source image ID is assigned
to multiple UTC dates for the same organism and measurement metric. Such a
series produces **no projected endpoint change**, unit-level eligible mean, or
population-level contribution. The diagnostic list is deterministic and the
new optional field defaults to an empty list when older persisted workflow
artifacts are deserialized. Same-day technical replicate handling and valid
multi-image date series are unchanged.

The existing standalone calibrated-measurement API and executable persisted
`ecology_identity_registry_source` Workflow Builder node both use the same
QC/endpoint implementation. The source fingerprint algorithm is advanced to
`ecology-measurement-candidates-0011` so a change in scientific exclusion
rules is visible in provenance. Regression coverage includes replayed-image
exclusion, a distinct-image control, backward-compatible QC deserialization,
and existing standalone/saved-workflow parity. **All outputs remain
`linked_unverified` with `scientist_review_required`.** This is a source
integrity guard, not verified specimen re-identification or an independent
sampling-unit attestation. No migration, model acquisition, or environmental
provider was added. Full CI and Windows/scientific acceptance are still
required before any release claim.

## Content-addressed replay guard for projected observations (2026-10-25)

The source-linked sampling-date QC now also detects the **same SHA-256 image
content** assigned to multiple UTC observation dates for an organism/metric,
even when an imported copy has a different database image ID. This closes the
image-ID-only replay loophole: reimporting a photograph cannot manufacture a
longitudinal change or eligible experimental-unit/population summary. The
deterministic `reused_image_sha256` diagnostic and
`reused_image_content_across_dates` status remain explicitly unverified and
require scientist review; the previous `reused_image_across_dates` status takes
precedence when the exact image ID itself is reused. The new QC list defaults
to empty when deserializing historical persisted artifacts. Real distinct
image content remains eligible for provisional QC, subject to all existing
identity, calibration, UTC, and experimental-design guards.

The same service powers the standalone calibrated-measurement endpoint and the
executable saved `ecology_identity_registry_source` Workflow Builder node with
typed outputs, persisted provenance and review gates. The fingerprint algorithm
advances to `ecology-measurement-candidates-0012`. Regression coverage includes
reimported identical content, valid distinct-content controls, stale-QC
rejection, backward-compatible deserialization, and standalone/saved-workflow
payload parity. The preceding exact-head CI had **16/19 successful workflows**;
all three failures were the same Ruff import-order error, corrected alongside
this change. Exact-new-head CI, authenticated longitudinal observations,
scientific acceptance and Windows installed-GUI testing remain outstanding.
No migrations, cloud services, new model weights, or verified-dataset promotion.

## Projected population denominator and lineage-integrity repair (2026-10-25)

Exact-head CI on `fa84aaf7c0505a1391c2a7ccf9141593ac0a68b8`
completed 16/19 workflows successfully. The backend and ReefVision 1.0
acceptance jobs both identified the same scientific regression:
`test_projected_population_is_unit_weighted_and_stratified` accepted
duplicate `complete_organism_keys` because set equality alone concealed
repeated identifiers. The shared projected-population kernel now rejects
duplicate complete/incomplete organism keys before calculating biological
denominators. It also rejects duplicate parent-colony keys within a declared
unit, preventing a repeated label from masquerading as cross-unit parent
reuse. Focused regressions cover both failure modes. Existing standalone
candidate API and executable persisted `ecology_identity_registry_source`
Workflow Builder results use this shared kernel; no new node or migration
is required. All results remain `linked_unverified`, with mandatory scientist
review and no independent-unit inference.

The separate pose-interop frontend Vitest failure on that head is outside
Track B and is not claimed fixed here. Exact-head CI, real scientific
acceptance, migration reconciliation, and installed Windows GUI acceptance
remain outstanding. A committed regression is not a passed test.

## Cross-series image replay audit (2026-10-25; development only)

The projected UTC sampling-date QC now checks source-image IDs and SHA-256
content **across the entire candidate batch**, not merely within a single
organism/metric series. A reimported photograph cannot serve as an earlier
measurement for one organism and a later measurement for another organism or
metric without triggering exclusion of every affected series. Per-series
`reused_image_ids` and `reused_image_sha256` list the affected sources;
`reused_image_across_dates` retains precedence over the content-based status.
A legitimate image shared by multiple organisms on the **same UTC date** is
not rejected solely because its bytes or image ID appear more than once.

No affected series contributes a projected endpoint change or an eligible
experimental-unit/population mean. Previously calculated date-QC rows are
revalidated against the complete current candidate batch; stale rows cannot
authorize a projected change. The standalone source-linked measurement API
and executable saved `ecology_identity_registry_source` Workflow Builder
artifact use this shared kernel, typed diagnostics, persisted provenance and
scientist-review gate. The fingerprint algorithm advances to
`ecology-measurement-candidates-0013`. Regression coverage includes
cross-organism ID/content replay, valid same-day multi-organism imaging,
input-order invariance and stale-QC rejection. The existing saved-workflow
payload-parity test exercises the common source service; a dedicated
end-to-end replay fixture with multiple real imported images remains an
acceptance follow-up.

These are `linked_unverified` projected geometries, **not** verified
longitudinal biological observations, growth rates or evidence of true
experimental independence. Registered verified observation history,
immutable reviewed calibration/source linkage, migration reconciliation,
real scientific dataset acceptance and installed Windows GUI tests remain
release blockers. No cross-version merge, environmental-context duplication,
model acquisition or verified-dataset promotion occurs.

## Cross-metric organism assignment integrity (2026-10-25)

The projected-population aggregation boundary now checks each organism's
experimental-unit identity **across metrics and sampling strata**, not merely
within the same metric. An organism reported in tank A for width cannot be
reported in tank B (or as a colony-level independent unit) for height; the
analysis fails closed rather than treating these as distinct biological
replicates. Multiple metrics from the same organism and unchanged unit remain
valid as separate descriptive outcomes. This closes a direct-aggregator
pseudoreplication loophole; upstream source-linked unit aggregation already
rejects contradictory identity assignments across metrics. The shared
standalone/project source service and persisted Workflow Builder output retain
their typed provenance and scientist-review gate. Reproducibility fingerprint
algorithm advances to `ecology-measurement-candidates-0014`. A focused
regression checks both input orders, changed unit IDs/types and the valid
same-unit control. The previously failing Ruff-format line in the ecological
regression file was corrected as reported by exact-head Actions logs.

**Acceptance limits:** No new verified biological records, reviewed identity
reconciliation, inference, migration, physical Windows installed-GUI check or
release authorization is claimed. CI must validate the new exact head before
this increment can be considered tested; source data remain
`linked_unverified` and require scientist review.

## Same-day photograph provenance integrity (2026-10-25)

Source-linked projected measurements now reject a photograph that has
inconsistent acquisition instants under the same SHA-256 content, even when
all observations fall on the same UTC sampling date. They also reject one
image ID mapped to different source content or capture metadata. These checks
run across organism and metric series before endpoint changes and declared
experimental-unit summaries, so affected sources cannot create artificial
longitudinal changes. Equivalent timezone offsets describing the same UTC
instant remain valid; one photograph can still legitimately contain multiple
organisms. The sampling-date QC response exposes
`source_capture_conflict`, `conflicting_source_image_ids`, and
`conflicting_source_image_sha256`. The new arrays default to empty for
previously persisted typed Workflow Builder artifacts. Provenance advances to
`ecology-measurement-candidates-0015`. Standalone and saved executable
Workflow Builder paths use the same source-linked service and fail-closed
review gates; the existing saved-workflow artifact parity test covers the
additive fields. These are **unverified projected measurements**, not
confirmed organism growth or independently authenticated sampling units.
Full CI, real-data scientific review and installed Windows acceptance remain
required.


## Undated reimported photograph provenance QC (2026-10-25)

The existing source-linked calibrated measurement candidate kernel now
recognizes a SHA-256-identical photograph imported under another image ID
when one copy has a timezone-aware acquisition instant and the other has
missing or timezone-unaware capture metadata. Both affected organism/metric
series receive `source_capture_conflict` and the existing
`conflicting_source_image_sha256` audit field; neither can contribute a
projected endpoint or an eligible experimental-unit/population summary.
Identical bytes with the same UTC instant remain usable across multiple
organisms in one photograph. Reuse across distinct dates retains the stronger
`reused_image_content_across_dates` classification. This avoids promoting
unknown-time reimports into false longitudinal observations without adding a
new evidence store, model weights or review bypass.

The same source-linked kernel serves the standalone calibrated-measurement
endpoint and the existing executable, persisted `ecology_identity_registry_source`
Workflow Builder output. Scientific regression tests cover known/unknown
capture metadata, order independence, exclusion from unit summaries and
legitimate equivalent timezone offsets. The existing saved-workflow test
continues to require typed artifact parity with the standalone endpoint.
Scientific input fingerprint version advances to
`ecology-measurement-candidates-0016`. All evidence remains
`linked_unverified` and `scientist_review_required`; no biological growth,
true independence, or source verification is asserted. This branch is still
blocked on exact-head CI, migration reconciliation with 1.1, independent
scientific acceptance and installed Windows GUI/installer tests.


## Source-linked UTC visit coverage (2026-10-25; development only)

The existing project-scoped `GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates`
endpoint now includes additive typed `projected_visit_coverage` records, also
persisted by the existing executable `ecology_identity_registry_source` Workflow
Builder output port (`ecology_measurement_candidates`). For each observed UTC
sampling date, declared unit, metric and physical unit, the records list
organisms with linked calibrated measurements, organisms measured elsewhere in
that series but without a link on that date, undated source organisms and
same-day repeated measurements. Source measurement counts are distinct from
the organism denominators. Date normalization accepts equivalent timezone
offsets and never treats naive or missing timestamps as dated observations.
Rows with missing unit declarations or technical-replicate unit labels
are omitted rather than pooling unrelated organisms as a fictitious unit.
Rows and lists are deterministic under input reordering. The source-linked
reproducibility fingerprint advances to `ecology-measurement-candidates-0017`;
older persisted typed artifacts deserialize with an empty coverage list.

**Scientific limits:** the comparison set is *only organisms with any linked
measurement in the same declared unit/metric/physical-unit series*, not a
registered expected-specimen roster or sampling calendar. A missing linked
measurement does not imply organism absence, mortality, zero abundance or
a failed planned visit. Same-day repeats are diagnostic technical replicates,
not additional biological samples. Every row remains `linked_unverified`
with `scientist_review_required`; this does not authenticate capture-time
metadata, certify source geometry or convert projected changes to biological
growth. Tests cover UTC normalization, per-organism denominators, duplicate
captures, undated sources, stable order, legacy typed artifacts and standalone
API versus saved-workflow artifact parity.

The next high-priority work remains authenticated, scientist-reviewed
longitudinal observation histories and registered study sampling schedules.
Migration reconciliation with unmerged 1.1, full exact-head CI, independent
scientific review and installed Windows GUI/installer validation are required.

## Source-linked ecological QC and effort report (2026-10-25; development)

The project-owned calibrated measurement candidates endpoint now includes
an additive typed `candidate_report` with candidate, source-image, organism,
declared-unit, date-QC-passing-series, excluded-series and excluded-source
denominators, and per-status UTC sampling-date QC counts. Its deterministic
SHA-256 binds the summary to the original source input fingerprint. The new
`GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates/report.csv`
exports the QC-status counts with provenance and review-gate labels.

The executable `ecology_identity_registry_source` Workflow Builder node
now persists the same report on its dedicated typed `candidate_report` port
(`ecology_candidate_report`), while preserving the existing measurement
artifact with an additive optional report field. Old saved artifacts remain
readable. Source algorithm version advances to
`ecology-measurement-candidates-0018`. Regression tests cover standalone
API, CSV and saved-workflow parity, typed port registration and legacy
decoding. This is descriptive linked-evidence reporting only: no authenticated
biological independence, verified growth, mortality, or inferential statistics.
Full CI, migration reconciliation and installed Windows/scientific acceptance
remain outstanding; no merge, tag, release or deployment.

## Traceable per-series ecological QC CSV (2026-10-25)

A second read-only standalone export, `GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates/report-series.csv`, emits one deterministic row per organism/metric UTC-date QC decision. Unlike the existing aggregate `report.csv`, it includes source image IDs, units, observed and duplicate UTC dates, missing capture timestamps, replay/conflicting source identifiers, and explicit review/evidence status. Arrays are encoded as JSON within CSV cells to preserve identifiers containing delimiters. Input/report SHA-256 references bind the export to the already persisted typed `ecology_measurement_candidates` and `ecology_candidate_report` Workflow Builder artifacts; no separate untyped workflow path is introduced. CSV generation fails closed on inconsistent report/QC totals, duplicate series, or a mismatched source fingerprint, and escapes user-controlled organism identifiers that could be interpreted as spreadsheet formulas. The aggregate CSV endpoint is unchanged.

This is a reproducible **unverified candidate-QC export**, not an authenticated longitudinal observation, verified growth result, statistical inference, or independent-unit confirmation. Tests cover standalone/typed saved-workflow equality, stable ordering, corruption rejection and spreadsheet safety. Full CI, scientific review, and installed Windows acceptance remain release blockers.

## Per-series CSV source reconciliation (2026-10-25)

The source-linked QC CSV renderer now checks every persisted per-organism/metric
sampling-date decision against the candidate measurement records, not just the
aggregate status histogram. It rejects forged or stale image IDs, timestamp/QC
decisions, candidate denominators, experimental-unit/source counts and report
SHA-256 totals. The same typed evidence is used by the standalone endpoint and
the executable saved Workflow Builder source node; no new node or data store
is introduced. Regression tests cover source tampering, stale reports,
saved-workflow parity and spreadsheet-safe CSV identifiers.

This is **fail-closed internal consistency**, not cryptographic authentication
of the original project images or proof of reviewed growth. All outputs remain
`linked_unverified` with `scientist_review_required`. Full exact-head CI,
scientific acceptance, registered sampling designs and installed Windows GUI
checks remain release blockers.


## Full source-fingerprint reconciliation for detailed QC exports (2026-10-25)

New calibrated-measurement candidate responses persist the image-evidence and
annotation-evidence registry digests alongside their existing registry history
and calibration digests. A typed optional `source_fingerprint_contract` marks
records whose complete `ecology-measurement-candidates-0018` input SHA-256 can
be recomputed from all linked candidates, date-QC decisions, projected
coverage/changes, unit/population summaries and exclusions. The detailed
`report-series.csv` exporter now **fails closed** on changed measurement values
or stale linked source digests, even when aggregate QC denominators are unchanged.
Its `source_fingerprint_rechecked` column distinguishes new rechecked exports
(`true`) from older persisted Workflow Builder artifacts (`false`). Legacy
artifacts remain readable and exportable but are not silently described as
revalidated. Existing standalone API and saved-workflow outputs share the same
typed contract; regression coverage checks tampering, compatibility and parity.

This is an internal consistency and reproducibility check, **not** an
authentication signature, independent scientific review, verified organism
identity, or permission to promote unverified observations into a verified
dataset. All research and Windows release acceptance gates remain outstanding.


## Source-reference scale consistency for ecological measurements (2026-10-25)

The project-owned ecological identity/calibration evidence service now checks
that a saved physical reference segment agrees with the
`distance_per_pixel` scale used to derive source-linked coral measurements.
When both `reference_length` and `reference_pixel_length` are present, their
ratio must be finite, positive and within 1% relative tolerance of the saved
scale (allowing modest rounding of manually entered scales). A contradictory
reference blocks creation of ecological calibration evidence. If the source
calibration changes after linking, registry reads, calibrated-measurement
candidate API results and the executable saved `ecology_identity_registry_source`
Workflow Builder fail closed rather than exposing physically inconsistent
length/area evidence. The generic calibration editor is unchanged; this
is a stricter scientific evidence boundary, not a silent data rewrite.

Regression coverage includes rejecting a 5 mm / 20 px reference paired with
0.5 mm/px, accepting a rounded 0.2501 mm/px scale, standalone/saved-workflow
artifact parity and revocation after a conflicting source edit. No new database
schema, model weights, cloud services or verified-dataset promotion. All
ecological results remain `linked_unverified` and require scientist review.
The exact-head Ruff-format failure in
`test_ecology_candidate_report_series_1_2.py` was also corrected. Exact-head
CI, verified longitudinal observation histories, registered study designs,
independent scientific review and installed Windows acceptance remain required.

## Scientific mask polygon topology gate (2026-10-25)

Ecological annotation evidence now checks a polygon ring for zero projected
area, repeated non-closure vertices, overlapping/backtracking edges and
self-intersections. A conventional repeated closing vertex, concave outlines
and forward collinear vertices remain valid. For bounded offline execution,
the scientific evidence gate limits rings to 4096 vertices; simplify longer
rings before linking. This check applies when creating a source link and
when re-reading it for standalone registry and saved executable Workflow
Builder sources, so changed/invalid source geometry fails closed rather than
creating an apparently usable ecological artifact. This is a topology QC
gate, **not** a substitute for independent mask-area verification or
biological review. Linked evidence remains `linked_unverified` and requires
scientist review. No new migration, model weights or 1.1 environmental
dependency is introduced.

## Polygon/bounding-box evidence consistency (2026-10-25; development)

The existing ecological mask evidence gate now also rejects a valid
source-pixel polygon when any vertex lies outside the same annotation's
saved bounding box (allowing one pixel for raster/vector rounding).
This catches contradictory imported or subsequently edited geometry
that previously passed image-bound and polygon-topology validation.
Missing mask bounding boxes retain the existing polygon-only validation
path; non-polygon raster masks are unaffected. Standalone identity
registry reads and the existing executable, persisted
`ecology_identity_registry_source` Workflow Builder node both use the
same fail-closed source validation. API and saved-workflow regressions
cover pre-link rejection, post-link revocation, and tolerated rounding.
The same iteration corrects the `I001` import-order failure in
`services/ecology_identity.py` observed in all three failed exact-head
workflows at commit `2d5e4f5568a17e35dab71f84ec50bacee42cadef`.

These checks validate **internal source geometry consistency only**.
They do not establish raster-mask area accuracy, verified biological
identity, longitudinal growth, or independent experimental units.
All linked records remain unverified and scientist review is required.
Exact-head CI and Windows/scientific release acceptance must still pass.


## Tight polygon-to-bounding-box QC (2026-10-25; development only)

Source-linked polygon masks now require their saved source-pixel bounding box
to agree with **all four polygon extrema** within one pixel of raster/rounding
tolerance. The previous enclosure-only rule allowed a stale or oversized
bounding box to pass when every vertex remained inside it. Imported or
externally mutated mask evidence fails closed on both initial annotation
linkage and registry read-back. The same existing typed, persisted
`ecology_identity_registry_source` Workflow Builder node refuses to publish
a successful registry artifact when linked geometry becomes inconsistent.
Regression tests cover each bound, post-link changes, and standalone versus
saved-workflow behavior. Previously supported one-pixel rounding remains valid.

This check is geometric QC, **not** proof of reviewed biological identity,
accurate raster area, calibrated growth, or independent replication. Evidence
remains `linked_unverified` with scientist review required. The preceding
exact-head CI had 16/19 successful workflows; three backend gates failed on
Ruff formatting in the polygon QC module and its tests. The exact reported
formatter corrections are included in this change. New-head CI, migration
reconciliation, representative ecological datasets and installed Windows GUI
scientific acceptance remain mandatory.


## Exact-head CI typing gate: projected visit coverage (2026-10-25)

The 2026-10-25 exact-head check at `f74cb7664a9fdd7ca841b93833da3c0fec242dfc`
completed 16 of 19 GitHub Actions workflows successfully. The three failures
(`CI`, `Pose Workflow Validation`, and `ReefVision 1.0 Acceptance`)
all stop at strict mypy typing in
`apps/api/reefvision/services/ecology_measurement_candidates.py`. A
`key` local bound to a four-part sampling-group tuple is rebound to an
organism-ID string inside `summarize_projected_visit_coverage`, which mypy
rejects as incompatible with the inferred tuple type. The planned repair
uses distinct `group_key` and `organism_key` locals without changing
coverage counts, UTC normalization, provenance, review gates, API schemas,
or Workflow Builder artifact contracts. Existing focused API/workflow tests
and the three failing CI typing gates are the regression checks. A code
commit and green exact-head CI are required before this is considered fixed.

This repair does **not** constitute 1.2 release acceptance. Authenticated,
scientist-reviewed longitudinal observations, registered study design,
real-dataset verification, Windows installed-GUI checks, and migration
reconciliation remain outstanding.

## Track B exact-head CI regression repair (2026-10-25)

GitHub Actions at `bf82d0aaa0307b5a7f998172b0f7745d5d6524ef` completed
**17/19 workflows successfully**. The CI and ReefVision 1.0 Acceptance
workflows failed three ecological backend cases (1458 passed, 32 skipped):
(1) calibration source mutation now correctly fails earlier with a specific
reference-scale conflict, but the older test expected only the generic stale
snapshot error; (2) the detailed QC CSV exporter rehashed caller-reordered
sampling-date QC rows without restoring the producer's deterministic
organism/metric order; (3) a forged top-level candidate count raised an
aggregate-report error instead of the dedicated candidate-count error.

The repair keeps the strict calibration validator unchanged, updates the two
API/saved-workflow test expectations to the more specific scientific failure,
checks candidate-count integrity before report totals, and canonicalizes only
the **unique** sampling-date QC row order for the complete source digest.
Source values, linked evidence, other digest fields, mandatory review gates,
experimental-unit denominators and the typed persisted Workflow Builder
contract remain unchanged. Existing tests exercise deterministic reordered
CSV output, tampering rejection and standalone/saved-workflow parity.

The separate frontend CI failure is in an external pose-import UI test; it is
not ecological code and is left untouched for its owning track. Exact-head
CI, independent scientific review and installed Windows acceptance are still
required; **1.2 is not release-ready**.

## Full append-only organism identity chronology (2026-10-25; development)

The project-scoped `identity-registry` standalone API and existing executable,
typed, persisted `ecology_identity_registry_source` Workflow Builder node now
return `identity_history`: the full, deterministic append-only revision
sequence, including superseded tank/colony assignments, correction reasons
and timestamps. Previously only latest identities plus a revision count and
SHA-256 history fingerprint were visible. The additive typed field defaults
to an empty list when older saved workflow artifacts are decoded. Existing
fingerprints, linked annotation/calibration evidence, typed workflow ports,
and project ownership remain unchanged. No migration is needed because
the append-only records already exist. Regression tests cover revised
fragment identity, earlier tank assignment retention, saved-workflow parity,
and legacy deserialization.

These are **registered, unverified identity claims**, not authenticated
scientist approval or a verified experimental design. All outputs retain
`registered_unverified` and `scientist_review_required`. Verified observation
histories, design registration, real-dataset acceptance, 1.1 migration
reconciliation and installed Windows scientific/GUI acceptance remain pending.


## Auditable ecological identity-history CSV (2026-10-25; development)

The project-owned registry now exposes a read-only
`GET /api/v1/projects/{project_id}/ecology/identity-registry/history.csv`
export of **every append-only organism revision**, including superseded
experimental-unit assignments, parent-colony links, revision reasons and
timestamps. Unlike the latest-only identity view, this preserves the full
correction chronology for scientific review. The exporter recomputes the
existing `ecology-identity-history-0001` revision SHA-256 and latest-identity
snapshot SHA-256, verifies project scope, contiguous revisions, counts and
latest-record parity, and fails closed on corrupted or incomplete legacy
workflow artifacts. Formula-like user-supplied study labels and reasons are
spreadsheet-escaped. The export is deterministic and has no cloud dependency.

The **same typed `ecology_identity_registry` payload** (including
`identity_history`, `history_sha256` and review gates) is already persisted
by the executable `ecology_identity_registry_source` Workflow Builder node;
no parallel workflow engine, new node or migration is introduced. New
regressions compare standalone CSV to the CSV rendered from a persisted
saved-workflow artifact, verify historical tank reassignment, tampering and
legacy rejection, and check spreadsheet safety. The prior head's three
failed GitHub Actions workflows were all blocked at one Ruff formatting
discrepancy in the identity-history test; the exact extra blank line was
corrected in this iteration.

**Limitations:** identity assignments and correction reasons are still
`registered_unverified`, require `scientist_review_required`, and do not
authenticate a human reviewer, certify true experimental independence or
promote observations to verified growth. Full exact-head CI, independently
reviewed study design/longitudinal measurements, 1.1 migration reconciliation,
and installed Windows GUI/installer scientific acceptance remain mandatory.

## Experimental-design revision QC (2026-10-25; development only)

The project-owned ecological identity registry and existing executable typed
`ecology_identity_registry_source` Workflow Builder node now publish
`design_history_status`, `design_change_count`, and ordered
`design_change_events` derived from complete append-only revisions. They
flag organism-kind, parent-colony, experimental-unit type and ID changes,
including tank reassignment and reversion. Reason-only corrections are not
counted. Older persisted artifacts default to `history_unavailable`, never
false design stability. The identity-history CSV discloses status/count and
checks derived events against fingerprint-verified revision history.

These registered changes are **unverified** and require scientist review;
no independent experimental design, signed approval, or longitudinal growth
is certified. Existing candidate exclusions and immutable evidence remain
unchanged. No migration, cloud service, or 1.1 environmental duplication.
Scientific, installed Windows GUI and full release acceptance remain pending.


## Registered cross-unit parent-colony audit (2026-10-25; development only)

The project-scoped identity registry now discloses sorted
`cross_unit_shared_parent_colony_keys` for registered fragments assigned
to distinct declared units **at the same biological sampling level**.
A parent represented in multiple tanks is flagged for scientist review;
multiple fragments within one tank are not independent repeats and do not
create a false cross-unit signal. Tank and site levels are not conflated.
The additive `cross_unit_parent_audit_status` distinguishes
`shared_parent_requires_review`, `no_cross_unit_parent_reuse`, and
`unavailable` (legacy persisted workflow artifacts).

The standalone registry API, existing executable typed/persisted
`ecology_identity_registry_source` Workflow Builder node, and CSV history
export share the same audit. The CSV recomputes modern audit fields against
fingerprint-checked latest identities and rejects mismatches. The result
remains `registered_unverified` with `scientist_review_required`; it is
not a determination of biological dependence or a substitute for registered
experimental designs and independent review. No migration or cloud service
is introduced.

At the previous exact head `9fc087de5002`, 16/19 workflows passed and
the three failing backend gates stopped at Ruff formatting in the
design-change implementation/test. This increment also corrects the
reported formatting. New exact-head CI, real-data scientific acceptance
and installed Windows GUI/installer checks remain outstanding.

## Actionable cross-unit parent review evidence (2026-10-25; development only)

The existing registered parent-colony audit now includes typed
`cross_unit_parent_details` for every flagged parent **at each declared
sampling level**: normalized level, sorted distinct unit IDs and sorted
contributing fragment keys. This lets a scientist review exactly which
fragments and units generated a pseudoreplication warning, rather than
receiving only a parent key. Tank/aquarium aliases are grouped; tank and
site levels remain separate. Repeat fragments within a single tank do not
produce a false cross-unit finding.

The existing project-owned registry API and executable, persisted
`ecology_identity_registry_source` Workflow Builder node share these typed
results. The deterministic identity-history CSV includes the detail as
JSON and recomputes it against fingerprint-verified current identities,
failing closed on tampering. Legacy workflow artifacts deserialize with
empty details and an `unavailable` audit status; they do not claim a
clean experimental design. No new migration, model weights or 1.1
environmental integration is introduced.

These details are `registered_unverified` and require scientist review.
They do not establish actual biological dependence, simultaneous
sampling, verified experimental-unit assignments or valid statistical
replication. Full exact-head CI, real-dataset scientific review and
installed Windows GUI acceptance remain required.

Backward compatibility note: pre-detail saved workflow artifacts may contain
a modern shared-parent status but no `cross_unit_parent_details` field. Their
CSV export reconstructs details from fingerprint-verified identities rather
than falsely treating missing detail as an empty result. Artifacts explicitly
carrying details are compared against the recomputation and rejected if
tampered. This is an additive artifact contract, not a verification upgrade.

## Track B — Cross-unit parent audit regression correction (2026-10-25; development)

Exact-head Actions at `a173924446a61ed4a3cd27f11bc3505582100593`
completed **17/19** workflows; the two backend failures were the same
`test_no_false_cross_unit_parent_claims_and_csv_tampering` assertion
(1 failed, 1470 passed, 32 skipped). The test assigned an empty detail
list to an already-empty, scientifically valid no-cross-unit registry and
incorrectly expected the CSV exporter to reject that no-op. The exporter
correctly accepted it.

The regression now exercises actual falsification: an invented second
tank in a no-cross-unit registry, removal of shared-parent evidence in a
registry that genuinely spans tanks, and omission of a contributing
fragment. Each must fail the existing deterministic identity-derived
audit, while the explicit legacy status-only saved-workflow artifact
continues to reconstruct details from fingerprint-verified identities.
No production behavior, scientific denominators, workflow port types,
identity records, migrations, or verification status change. The same
standalone CSV and persisted saved-workflow tests remain the acceptance
contract. New exact-head CI must pass before considering the repair
validated; scientist-reviewed study design, longitudinal observations,
and installed Windows acceptance are still outstanding.


## Historical cross-unit parent registration audit (2026-10-26)

The existing project-owned identity registry API and executable, persisted
`ecology_identity_registry_source` Workflow Builder node now separately
disclose **historical** parent-colony registrations spanning multiple
declared experimental units at the same normalized sampling level. Every
contributing fragment revision, original unit type, and unit ID is retained
in a deterministic typed audit. Unlike the current-snapshot shared-parent
audit, this catches a previously registered tank assignment that was later
corrected or reverted. It is a warning about **recorded revision history**,
not evidence that a specimen physically moved, two tanks were occupied
simultaneously, or the treatments were statistically independent.

The identity-history CSV includes the historical audit status and full
revision evidence; export recalculates the audit from SHA-256-checked history
and rejects altered evidence. Older saved artifacts default to an explicit
`unavailable` status rather than falsely reporting no historical reuse.
Standalone API, saved Workflow Builder replay, CSV parity, alias handling,
tamper rejection and legacy deserialization have regression coverage.
No new migration, inference, external service, model weights or verified-data
promotion is introduced. Evidence remains `registered_unverified` with
`scientist_review_required`. Source-linked scientist-reviewed longitudinal
measurements, design attestation, cross-branch migration reconciliation,
scientific acceptance and installed Windows GUI/installer validation remain
required before 1.2 release approval.

## Source-rechecked projected endpoint CSV (2026-10-26)

The existing project `calibrated-measurement-candidates/report-series.csv`
now appends source-linked projected endpoint arithmetic (absolute/percentage
changes, elapsed days, descriptive per-day change), baseline/final image IDs,
and a JSON cell containing the complete typed endpoint evidence including
annotation/calibration IDs and UTC instants. Existing QC columns remain.
Excluded series have blank endpoint cells; older saved artifacts lacking
endpoint records are marked `legacy_unavailable` instead of being backfilled.

The renderer recomputes endpoint arithmetic from linked candidates and
cross-checks persisted results even if an artifact fingerprint is rewritten.
The standalone API and executable saved Workflow Builder source share the
typed `ecology_measurement_candidates` artifact. Focused tests cover API/CSV
and saved-workflow parity, dated arithmetic, missing/forged endpoint records
and legacy compatibility. These are **unverified projected geometry changes**,
not biological growth, survival, independent replication or inference.
Scientist review, full CI and installed Windows acceptance remain required.

## Source-derived projected aggregate integrity (2026-10-26; development)

The existing calibrated-measurement-candidate series CSV exporter now
**recomputes per-date visit coverage, declared experimental-unit summaries,
and equal-unit-weighted population summaries from linked measurement
candidates** before exporting a modern fingerprinted artifact. It already
recomputed sampling-date QC and projected endpoint arithmetic. A self-consistent
but falsified source digest/report digest cannot legitimize invented visit
counts, altered unit means or fabricated population means. The exporter fails
closed on any disagreement with source-derived results.

This check operates on the same typed persisted
`ecology_measurement_candidates` artifact produced by the existing
executable Workflow Builder source and consumed by the standalone CSV API;
no duplicate analysis node or storage model is introduced. New regression
cases deliberately re-sign modified visit, unit and population evidence and
require scientific validation errors. Legacy artifacts without the modern
source-fingerprint contract remain readable and explicitly report
`source_fingerprint_rechecked=false`; they are **not** retrospectively
certified. The previous exact-head CI at `dd4592a1` had 16/19 workflows
successful and three backend gates failing on Ruff formatting in the
candidate exporter and projected CSV regression; those reported formatting
differences were corrected in this iteration.

This remains `linked_unverified` projected geometry, not reviewed biological
growth or an authenticated study design. Full new-head CI, real-data scientific
review, migration reconciliation and installed Windows GUI/installer
acceptance remain outstanding. No version completion or release is claimed.


## Signed longitudinal endpoint falsification regression (2026-10-26)

The existing projected series CSV scientific acceptance suite now tests three
re-signed forgeries: altered endpoint change magnitude, substituted baseline
image identity, and substituted final calibration evidence identity. Each
must fail the existing source-candidate recomputation even when the input
and report SHA-256 fingerprints are recalculated to match the falsified
artifact. The same typed candidate artifact is produced by the standalone
API and executable, persisted Workflow Builder source; no parallel analysis
node, migration, or unverified-to-verified promotion is introduced.

This iteration also fixes the exact Ruff formatter discrepancy reported by
all three failed backend workflows at predecessor head `f2ad045e`.
New-head CI must pass before these regressions are considered validated.
These checks establish only internal consistency of linked, unverified
projected geometry; independent scientist review, registered experimental
design, verified biological growth and installed Windows acceptance remain
outstanding. ReefVision 1.2 is not release-ready.

## Projected ecological report type-check repair (2026-10-26)

The latest completed pre-change CI for `01cda88a` reported 16/19 successful
workflows; the remaining three failed at the same five mypy diagnostics in
`ecology_candidate_report_export.py`. A heterogeneous aggregate audit loop
reused `expected`, previously inferred as a single endpoint dictionary or
`None`, for lists of projected coverage, unit and population model rows.
The repair gives aggregate loop variables distinct names (`actual_rows`,
`expected_rows`) so static analysis can infer their model-list types without
altering scientific comparisons, provenance, source re-derivation, or review
gates. Source read-back is confirmed; exact-head mypy, tests and Windows
acceptance are still pending. This is not a release-ready milestone.

## Prevent biological sampling-level aliases from doubling a tank (2026-10-26)

The existing source-linked projected population summary now compares the
**biological sampling level**, not only the literal unit-type label, when
checking whether a declared experimental unit/metric is duplicated. Thus
`tank`, `aquarium`, `aquaria`, `tanks`, and `Tank-level` with the same
unit ID cannot become separate apparent independent replicates. The
population summary fails closed with a scientific validation error instead
of reporting a misleading denominator. Different tank IDs remain allowed;
different biological levels remain distinct. This reuses the existing
`classify_ecological_unit_level` policy and existing standalone API,
persisted typed Workflow Builder artifact and scientist-review gates.

This is a narrow validation correction: successful artifact shapes and the
`ecology-measurement-candidates-0018` fingerprint contract remain unchanged;
older artifacts that would double-count an aliased physical unit are not
certified by export-time recomputation. Regression tests cover biological
aliases, order invariance, distinct units, and registered identity API /
saved-workflow compatibility. The latest **pre-change** head `233e16af`
completed 19/19 GitHub Actions workflows successfully; new-head tests
and Windows installed-GUI/scientific acceptance must be checked separately.
This does not authenticate study design or promote unverified growth.

## Canonical population sampling levels (2026-10-26)

Projected ecological population summaries now normalize known biological-unit
aliases (for example, `tank`, `aquarium`, `aquaria`, and `tank-level`) before
forming descriptive strata or checking organism ownership across metrics.
Distinct physical tank IDs are pooled as one *descriptive* tank-level stratum
with one contribution per tank, rather than incorrectly appearing as separate
strata because their unit labels differ. A physical tank cannot contribute
twice under aliases for the same metric. An organism measured across different
metrics may retain the same tank under aliases, but reassignment to a different
physical tank still fails closed. Unknown study-specific unit labels remain
unverified; alias normalization is not independent-design authentication.

Regression tests cover alias pooling, duplicate-unit rejection, cross-metric
ownership, conflicting tank reassignment, and existing API/saved Workflow
Builder artifact behavior. The calculation still requires scientist review,
remains local/offline, and cannot promote candidate measurements into verified
research datasets. No migration or new Workflow Builder node is required:
existing executable typed candidate artifacts and standalone API reuse the
same population calculator. Full exact-head CI, scientific acceptance and
installed Windows acceptance remain outstanding until verified.

## Canonical observed-visit coverage for biological-unit aliases (2026-10-26)

The existing source-linked projected-visit coverage calculator now groups
registered measurements by **canonical biological sampling level** before
constructing observed UTC-date rosters. A physical tank described as `tank`
for one fragment and `aquarium` for another no longer produces two isolated
rosters that conceal each other's missing linked measurements. Same-day
repeat images of the same organism across aliases are still counted as
technical replicates, and different physical tank IDs remain separate.
Unknown study-specific unit labels are preserved without authentication.
The original technical image/frame/annotation unit exclusions remain active.

The result is strictly a coverage audit of **linked measurements**, not a
registered study-visit schedule or evidence of organism absence, mortality,
survival, or biological growth. All output retains `linked_unverified`
and `scientist_review_required`. The standalone calibrated-candidate API
and the persisted typed executable Workflow Builder artifact already use
this shared service; no parallel node, migration, or environmental context
subsystem is introduced. Added focused regressions for cross-alias missing
measurement coverage, same-day repeat images, distinct tanks, and
standalone/saved-workflow response parity. Fixed the predecessor exact-head
Ruff formatting gate in the existing alias regression test.

Pre-change PR #74 HEAD `e12150e3` had 16/19 successful Actions workflows;
CI, Pose Workflow Validation, and ReefVision 1.0 Acceptance failed at Ruff
formatting of the alias regression test. New exact-head CI and scientific,
migration, and installed Windows GUI acceptance are **not yet established**.
No verified dataset promotion or release-readiness is claimed.

## Canonical source-derived projected unit aggregation (2026-10-26; development)

The existing source-linked `summarize_projected_unit_summaries` now groups
known biological sampling-level aliases (e.g., `tank` and `aquarium`)
**before** calculating descriptive unit means. Previously, two different
fragments in the same physical tank could produce two separate provisional
unit rows and a downstream duplicate-unit failure, despite valid linked
measurements. One tank now contributes one descriptive unit mean across
its fragments. Raw sampling-level labels remain intact in the underlying
candidate/endpoint evidence, and no original registered identity is rewritten.

Across different measurement metrics, one organism may retain its physical
tank while its registered label uses a recognized alias. Different physical
tank IDs, ambiguous mixed-level declarations and unreviewed provenance still
fail closed. Per-organism changes of declared sampling level *within a single
time series* continue to require review through existing date/identity QC;
this update does not silently approve identity revisions or movement.

Four focused regression cases exercise pooled fragment means, equal-unit
population denominators, multi-metric aliases, cross-tank reassignment,
mixed-level rejection and deterministic order. The existing standalone
calibrated-candidate API and executable, persisted typed Workflow Builder
source both use this shared calculation. No new node, migration, model
download or environmental subsystem was introduced.

**Acceptance pending:** exact-head CI (pre-change 1.2 HEAD `de51e992`
completed 18/19 Actions workflows; CI frontend failed at the pre-existing
`VideoTrackingWorkspace.test.tsx` pose-frame import test, while backend,
Pose Workflow Validation and Windows Desktop Build passed). Independent
real-data scientific review, authenticated study-design/observation
verification, migration lineage and installed Windows GUI acceptance are
still required. Outputs remain `linked_unverified` with
`scientist_review_required`; not biological growth or independent inference.
