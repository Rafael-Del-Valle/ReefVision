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

Technical/biological compound labels (e.g. `camera tank`, `image-tank`
or `frame aquarium`) are **not** normalized into eligible biological units:
the original technical label remains visible and its unit summary stays
`technical_replicate_unit`, excluded from population aggregation. Three
additional parameterized cases guard against technical-replicate laundering.

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


## Fail-closed experimental-unit lineage at population aggregation (2026-10-26)

The existing source-linked projected population calculator now independently
checks every *candidate* unit summary before allowing it to contribute to
descriptive population statistics. This guards the aggregation boundary even
when an intermediate typed summary is constructed or modified outside the
normal source-candidate producer:

- A technical image/frame/camera unit cannot masquerade as a biological unit.
- An organism-level independent unit cannot contain two distinct fragments.
- A colony-level unit cannot contain fragments from different parent colonies.
- A single parent colony cannot be split across multiple independent
  colony-level unit IDs, including aliases such as `colony` and `colonies`.
- A shared parent across different **tank-level** units remains permitted but
  explicitly flagged for scientist review, not silently treated as independent.

The same shared calculation is used by the standalone calibrated-candidate API
and the existing executable, typed, persisted
`ecology_measurement_candidates` Workflow Builder source. Source-linked and
directly forged intermediate-summary regressions were added; the preceding
head's three backend workflows all failed at one Ruff formatting discrepancy
in the alias regression test, which was corrected here. No migration, separate
analysis engine, environmental context, new model weights, or change to
successful `ecology-measurement-candidates-0018` artifacts is introduced.

**Acceptance:** exact-head Ruff/mypy/pytest, saved-workflow parity, real
scientist-reviewed data, registered design/identity verification, 1.1
migration reconciliation and installed Windows GUI/installer tests are still
required. Linked projected geometry remains `linked_unverified` with
`scientist_review_required`; no biological growth or inferential validity
is claimed.


## Reject padded or blank biological identifiers in projected population summaries (2026-10-26)

The existing population-aggregation boundary now fails closed when an eligible
source-linked or caller-constructed intermediate unit has a blank, leading-
or trailing-whitespace experimental-unit ID, organism key, or parent-colony
key. An ID such as `tank-1 ` is not a second physical tank distinct from
`tank-1`; silently trimming would rewrite source lineage, while counting it
separately risks pseudoreplication. Invalid identities therefore require
scientist review instead of being normalized or promoted to an independent
replicate. This check is shared by the existing standalone source-derived
calculation and executable persisted `ecology_measurement_candidates`
Workflow Builder node; no parallel implementation, schema migration, model
weights or 1.1 environmental context were added.

Six forged-intermediate-summary cases and one complete source-linked time
series with a padded tank ID were added as regressions. Existing standalone
API and saved-workflow acceptance tests remain in the 1.2 suite. The same
iteration fixes the exact Ruff formatting discrepancy that caused the three
backend workflow failures at predecessor SHA `c99544ce` (16/19 successful
workflows). These new tests are committed but not claimed to have passed
until exact-head CI executes. Local cloning/testing remains blocked by
GitHub DNS resolution. Independent scientific review, authenticated design,
migration reconciliation and installed Windows GUI/installer acceptance
remain outstanding. **1.2 is not release-ready.**


## Cross-metric projected parent-colony provenance guard (2026-10-26)

At the population-aggregation boundary, an eligible intermediate unit row
must not claim more distinct parent colonies than complete organisms. When
the **same canonical biological unit and identical complete organism roster**
appear under multiple measurement metrics, their declared parent-colony set
must also agree (order and known tank/aquarium aliases are immaterial).
This prevents caller-constructed or re-signed intermediate summaries from
silently changing parentage between width, height and projected-area
analyses. Different metric-specific organism rosters are **not** assumed
identical; no parent-to-organism assignment is invented from aggregates.

The existing source-linked candidate calculation, standalone API and
executable saved Workflow Builder use the same population service; no
new analysis node, migration, environmental provider or pretrained model
is introduced. Added order-invariant forgery and valid-roster regressions,
and applied the exact Ruff formatting correction reported at predecessor
head `40f4bf47` (16/19 workflows passed; three failed at one test formatting
line). The new head's CI and installed Windows/scientific acceptance
remain to be verified. All outputs remain `linked_unverified` and gated
for scientist review; this does **not** authenticate experimental design
or make ReefVision 1.2 release-ready.


## Cross-metric overlapping-roster parent feasibility guard (2026-10-26)

The projected population aggregation boundary now checks an additional necessary
condition for **overlapping but non-identical** organism rosters. Where a unit
summary reports as many distinct known parent colonies as complete organisms,
each organism's parent must belong to that summary's parent set. The feasible
parent sets for an organism are intersected across measurement metrics; an empty
intersection rejects the candidate before any population mean is exported.
This is order-independent and recognizes tank/aquarium aliases without counting
an organism twice. The calculation **does not** assign individual parentage
from aggregate sets or claim independence. A partially reported parent list
cannot establish complete organism-parent mappings, so it does not constrain
this intersection. Scientist review and linked-unverified provenance remain.

Three focused regression scenarios were committed: disjoint overlapping
parent candidates must fail, compatible overlapping candidates must remain
reviewable, and incomplete parent rosters must not imply invented mappings.
The prior exact-head CI at `6d718e62` finished 16/19 workflows successfully;
three failed solely on a Ruff formatting discrepancy in the existing alias
population regression. That exact formatting change was committed alongside
the new tests. Current-head CI and installed Windows/scientific acceptance
must still pass; **1.2 remains NOT RELEASE-READY**.


## Jointly feasible cross-metric parent-colony rosters (2026-10-26)

The existing source-linked projected population calculator now checks whether
**fully enumerated distinct-parent rosters** from different measurement metrics
admit a joint one-to-one organism-to-parent assignment. Intersecting candidate
parent sets for each organism individually was insufficient: three overlapping
metric rosters could each leave a nonempty candidate set while jointly forcing
two organisms to claim the same distinct parent within one metric.

The validation uses a deterministic bipartite matching feasibility check for
each fully enumerated roster after collecting cross-metric candidate constraints.
A scientifically impossible aggregate now fails closed rather than contributing
to a descriptive population summary. It does **not** infer, persist, or verify
any individual organism-parent mapping. Partially known parent rosters remain
reviewable and do not invent missing lineage. The calculation remains shared by
the existing standalone calibrated-candidate API and the executable, persisted,
typed `ecology_measurement_candidates` Workflow Builder source. No new node,
schema migration, model acquisition, 1.1 environmental provider, or verified
dataset promotion is introduced.

Focused regression tests cover impossible three-metric rosters in both input
orders, feasible rosters in both orders, and incomplete lineage. The preceding
exact-head CI at `8c08fd44` completed 16/19 workflows successfully; CI,
Pose Workflow Validation and ReefVision 1.0 Acceptance all failed at one Ruff
formatting discrepancy in the earlier alias test (line 554). The exact Ruff
formatting correction was committed with these tests. The new head's tests,
Ruff/mypy, scientific acceptance, migration reconciliation and installed
Windows GUI/installer acceptance remain pending. All source-linked projected
measurements remain `linked_unverified`, with
`scientist_review_required`; **1.2 is not release-ready**.


## Iterative parent-roster matching and CI repair (2026-10-26)

The source-linked projected population calculator checks joint feasibility of
parent-colony rosters across measurement metrics without assigning unobserved
parents to organisms. Replaced a recursive loop-captured matcher with an
iterative augmenting-path matcher: this addresses three exact-head Ruff B023
failures and avoids recursion-depth failure on large rosters. Added focused
regressions for reassignable parent candidates, impossible parent candidates,
and a 1,300-organism augmenting chain; existing source-derived standalone
and saved Workflow Builder acceptance cases remain applicable. The
algorithm remains a necessary consistency check, **not** verified lineage
or a guarantee of globally consistent parentage across all partial rosters.
Inputs and outputs remain `linked_unverified` with scientist review required.

Previous head `95e01646511471c1a26029e4042d3b6037af593e` had 16/19 completed
Actions workflows successful; the three failures stopped at Ruff B023 in
`ecology_measurement_candidates.py`. New-head CI, real-data scientific review,
migration reconciliation and installed Windows GUI acceptance remain required.


## Strict sampling-level provenance and exact-head formatting repair (2026-10-26)

The source-linked projected population aggregation boundary now rejects an
eligible intermediate experimental-unit **type** with leading or trailing
whitespace, matching the existing fail-closed rule for padded unit, organism,
and parent-colony identifiers. A researcher-entered sampling level is not
silently rewritten during export; it requires correction/review. Recognized
biological aliases remain supported when recorded without padding. The
existing standalone calibrated-candidate service and executable, persisted,
typed `ecology_measurement_candidates` Workflow Builder source use this
shared boundary; outputs remain `linked_unverified` and require scientist
review. Focused parameterized regressions cover padded tank/alias labels.

The predecessor exact-head `412e8c35` completed 16/19 Actions workflows;
CI, Pose Workflow Validation and ReefVision 1.0 Acceptance stopped at Ruff
formatting of two 1.2 files. This commit applies the **exact** Ruff-suggested
formatting to those files without changing the iterative parent-matching
algorithm. New-head CI and scientific/Windows installed-GUI acceptance must
still be independently verified. No migrations, 1.1 cross-merge, model
weights, verified dataset promotion or release actions are introduced.

## Source-level calibrated candidate CSV export (2026-10-26)

The existing project-owned `GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates`
response now has a companion `/measurements.csv` endpoint. It exports **one
source-linked projected measurement per row** (not one biological replicate per
row): organism and parent-colony keys, declared sampling level/ID, image and
annotation identities/revisions/SHA-256, calibration evidence and SHA-256,
metric/value/unit, UTC capture status, per-series date QC, evidence/review
status, source input fingerprint, report fingerprint, and whether the full
source fingerprint was rechecked. Missing or timezone-ambiguous capture
metadata cannot be silently rendered as a dated observation.

The serializer reuses the existing scientific QC, derived-value and
fingerprint reconciliation from the series-report exporter rather than
introducing an independent verification pathway. It sorts rows
deterministically and protects user-controlled CSV text from spreadsheet
formula execution. Existing `ecology_identity_registry_source` Workflow
Builder runs already persist the same typed
`ecology_measurement_candidates` payload; the serializer accepts that
persisted payload unchanged. API/Workflow parity, altered-source rejection,
empty-project behavior and timezone checks have focused regression tests.

This is an **unverified projected-geometry research export**, not a growth
estimate, independent experimental-unit count, or reviewed biological dataset.
All rows retain `linked_unverified` and `scientist_review_required`.
No new migration, weights, environmental context, branch merge, or release
action is involved. Before this iteration, exact head
`5ac2bb6dad3fc040a889970168c69d721204035f` had **19/19 completed
GitHub Actions workflows successful**. The new export head still requires
exact-head CI, independent scientific review, migration reconciliation and
installed Windows GUI acceptance; **1.2 remains not release-ready**.

### Executable Workflow Builder export (same 1.2 increment)

The `ecology_measurement_csv_export` node now accepts a typed
`ecology_measurement_candidates` artifact on its `candidates` input
(e.g., from `ecology_identity_registry_source.measurement_candidates`).
It executes the **same** source-QC and fingerprint-validated CSV serializer
as the standalone endpoint and persists a typed `ecology_measurement_csv`
artifact containing the CSV text, project ID, source/report digests,
fingerprint-check status, `linked_unverified` evidence level and
`scientist_review_required` review gate. It rejects foreign project
sources and scientist-supplied parameters; the graph's typed ports block
direct connection to verified-dataset inputs.

Focused acceptance covers the node registry, executable graph planning,
saved-workflow execution and artifact parity with the standalone CSV,
plus attempted verified-dataset port connection. These tests must pass
exact-head CI before any acceptance claim. No source is promoted to
verified biological truth by exporting it.

## Source-measurement CSV CI repair and reproducibility regression (2026-10-26)

The source-linked `measurements.csv` export and its executable, typed,
persisted `ecology_measurement_csv_export` Workflow Builder node retain their
existing provenance and scientist-review contracts. Exact-head CI at
`879a3a5ee5bc15a6b81c8eec791d02867e359fa4` completed **16/19 workflows**;
the three failing backend jobs all stopped at Ruff formatting in the same
source CSV renderer and saved-workflow acceptance test, before executing the
backend scientific suite. Applied the exact formatter changes from those logs.

Added a focused standalone regression requiring byte-identical CSV output
when the same valid source-linked sampling-date QC records are presented in
reverse order. The source fingerprint contract intentionally canonicalizes
QC series, so record ordering must not change exported scientific evidence.
The existing saved-workflow test continues to check CSV/API parity and that
an unverified export cannot enter a verified-dataset port. No database schema,
new workflow node, model weights or 1.1 environmental context is introduced.

**Validation boundary:** formatter changes are based on the failed GitHub
Actions log, and the new test is committed for exact-head CI; local Ruff and
full-repository tests are unavailable in the current runner. All outputs remain
`linked_unverified` with `scientist_review_required`. Complete CI, migration
reconciliation, representative scientific acceptance, and installed Windows
GUI/installer validation remain outstanding. This is not a release claim.


## Cross-metric two-parent cycle integrity (2026-10-26)

The projected population calculator now rejects a previously undetected
contradiction in **overlapping full two-organism/two-parent rosters**. Each
metric-specific row could individually admit a one-to-one parent assignment
while three rows jointly formed an impossible odd cycle (A differs from B,
B differs from C, and A differs from C with only two candidate parents).
The new iterative, per-parent-pair constraint graph checks connected
components for a consistent two-coloring and candidate-parent domains.
Feasible chains remain descriptive and unverified; no actual organism-to-parent
assignment is inferred or written. This is an additional conservative check,
**not** a complete solver for arbitrary larger overlapping lineage rosters.

The change reuses the existing projected population calculator, source-linked
standalone endpoint, and executable/persisted
`ecology_identity_registry_source` Workflow Builder node. Focused regression
tests cover the impossible three-metric cycle in either input order and a
feasible overlapping chain. Previously validated exact-head CI for
`e4507bf4fe2e2fd5916f5d799615207506e13b11` completed **19/19 successful**
Actions workflows; tests on this new head still require GitHub CI.
All projected population outputs remain `linked_unverified`,
`scientist_review_required`, and
`independent_unit_inference_allowed=false`. This change does not authenticate
biological lineage, supply verified longitudinal growth, reconcile migrations,
or satisfy physical Windows/scientific acceptance.

## Bounded exact cross-metric three-parent lineage feasibility (2026-10-26)

The existing projected ecological population boundary now detects a previously
missed *global* contradiction across overlapping **fully enumerated** parent
rosters of three or more organisms. Three metric-specific triples may each
admit a one-to-one organism/parent assignment, while their combined constraints
require four fragments to have four distinct parents drawn from only three.
The existing per-roster matching and two-parent bipartite checks alone could
not reject that contradiction.

A deterministic, bounded exact constraint search now checks the combined
full-roster system when there are at most 12 distinct organisms and 24 full
rosters. It forward-checks every partial assignment against the existing
iterative matching algorithm and rejects **only proven infeasible** systems.
Systems beyond those bounds, or exhausting 10,000 search states, remain
**unverified**, not falsely declared impossible or scientifically verified.
No inferred organism-to-parent assignments are persisted or exposed. Partially
known parent rosters still cannot assert a unique mapping.

Regression tests cover an impossible overlapping three-parent system and a
feasible system in both input orders. Existing source-derived standalone
endpoint and executable/persisted typed Workflow Builder share the updated
population calculation and continue to require scientist review; no new
workflow node or migration is needed. All results remain
`linked_unverified`, `scientist_review_required`, with independent-unit
inference disabled.

**CI repair:** predecessor `899440e9ec2183687946e9e6fb87a08a57abbf04`
completed 16/19 GitHub Actions workflows; all three failed at the same
Ruff E501 long string in the two-parent guard. That exact formatting error
was corrected in this increment. The bounded solver was separately checked
against small exhaustive-assignment reference cases, but full repository
Ruff/mypy/pytest and new-head CI must independently pass. Scientific review,
authenticated observations, migration reconciliation, and installed Windows
GUI/installer acceptance remain outstanding. **1.2 is NOT RELEASE-READY.**

## Component-scoped cross-metric lineage feasibility (2026-10-26)

The bounded exact parent-roster validator now checks **each connected
organism-roster component independently**. Previously, more than 24 full
parent rosters anywhere in the project caused the global check to return
without inspecting even a small, proven-impossible lineage subset. Unrelated
tanks/organisms therefore could hide a contradiction in a three-parent
overlap. Identical roster constraints are deduplicated before budgeting.
Each connected component still respects the existing 12-organism,
24-distinct-roster, 10,000-search-state limits; exceeding those limits is
**unverified**, not proof of feasibility. No parent assignment is inferred.

The existing standalone projected-population API and persisted, typed
Workflow Builder measurement-candidate source share this calculation.
Added order-independent scientific regressions with 25 full rosters:
three mutually contradictory overlapping rosters and 22 unrelated control
tanks. Also corrected the exact Ruff formatting reported by predecessor
head `e63c9c947b40d84e90fb01dbb21826a04b159845` (16/19 workflows
successful, three stopped at Ruff format). New-head backend/Workflow Builder
tests and CI must pass before acceptance. No migration, verified-dataset
promotion, environmental subsystem, model download, or release is introduced.
All results remain `linked_unverified`, `scientist_review_required`,
with independent-unit inference prohibited. Installed Windows GUI,
migration reconciliation and independent scientific review remain required.

## Unit-balanced projected population CSV (2026-10-26)

The source-linked candidate service now supports a reproducible
`GET /api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates/population.csv`
export. It includes both eligible and excluded **declared experimental-unit**
rows, with explicit missing-follow-up and sampling-window exclusion reasons,
plus stratified population rows weighted equally by eligible declared units.
Physical units, parent-colony reuse, design-review blockers, QC, source/report
SHA-256 hashes and the scientist-review gate are retained. Excluded units
have blank means and zero contributors; single-unit strata have no sample SD.

The executable `ecology_population_csv_export` Workflow Builder node accepts
typed `ecology_measurement_candidates` and persists a typed
`ecology_population_csv` artifact with identical bytes to the standalone
endpoint. The shared renderer independently rechecks the complete source
fingerprint and all derived summaries; legacy non-recheckable artifacts fail
closed. It cannot connect directly to verified-dataset ports.

**Scientific limitation:** these are projected 2D geometry descriptions, not
verified coral growth, survival, population abundance or independent replicates.
No p-values or statistical inference are emitted. Registered unit labels and
source calibrations still require independent scientist verification. No new
migration or 1.1 environmental subsystem is introduced. Exact-head CI,
installed-Windows acceptance and full scoped 1.2 review remain outstanding.

## Population CSV workflow type and CI integration repair (2026-10-27)

The previous 1.2 HEAD `9360c2512759323844d27a0cb9e421a9a3625c98`
completed **15 of 19** GitHub Actions workflows. Three backend workflows
stopped at Ruff formatting of the new population CSV response header. The
Milestone 10 workflow suite separately reported **22 failed, 21 passed**:
the population export node registered `ecology_population_csv` but the strict
`WorkflowDataType` union did not include that artifact type. Node-registry
construction therefore failed across unrelated saved-workflow tests.

This increment registers `ecology_population_csv` in the shared strict
workflow type contract, applies the exact Ruff-required response-header format,
and adds a regression that constructs a typed population CSV output port.
The existing source-to-export Workflow Builder node, persisted artifact,
standalone CSV endpoint, provenance recheck, project ownership and
scientist-review gate are preserved; no duplicate ecological/environmental
store or migration is added. The output remains `linked_unverified` and cannot
be promoted directly to a verified dataset.

The fixes are source-reviewed and pushed, **not yet accepted as passing** until
the exact new HEAD's CI, focused saved-workflow and backend tests complete.
Real authenticated longitudinal scientific review, migration reconciliation,
and installed Windows GUI/installer checks remain outstanding.
**ReefVision 1.2 is NOT RELEASE-READY.**

## Population CSV strict typing and export parity (2026-10-27)

The previous 1.2 head `2be50971` completed 16/19 workflows successfully.
CI, Pose Workflow Validation, and ReefVision 1.0 Acceptance all failed
at strict mypy on 14 errors in `ecology_population_export.py`. The CSV
renderer had reused the same `row` loop variable for two distinct
Pydantic result types, causing mypy to treat population strata as
per-unit summaries. The population loop now has a distinct typed variable,
and the optional experimental-unit type is normalized to an empty string
only at the CSV identifier boundary. This does not change scientific
inference, the underlying model, the persisted workflow node, or review gates.

A focused regression asserts that exported population-stratum fields
match the typed source summary (including unit IDs, sampling windows,
parent-colony disclosures, contributor denominators and mean changes).
Existing standalone API and saved-workflow CSV parity tests remain in
place. The changes are **not** accepted until exact-head CI passes; no
local full-repository or installed Windows acceptance was performed.

## Population CSV re-signed replication-evidence regression (2026-10-27)

The exact-head CI audit at `d47b4292` found 16/19 successful workflows;
CI, Pose Workflow Validation and ReefVision 1.0 Acceptance all failed on
Ruff formatting of the same population CSV scientific parity test. The test
formatting was corrected without weakening the underlying assertions.

Five parameterized regression cases now independently re-sign a tampered
population artifact and require the existing source-derived consistency
checks to reject inflated declared-unit and organism denominators, fabricated
shared-parent lineage, removed scientific design-review blockers, and an
invented sample standard deviation for a single declared experimental unit.
These checks apply to the shared CSV renderer used by the standalone API and
the persisted Workflow Builder export. They **do not** verify biological
independence, convert linked candidates into reviewed growth observations,
or allow inferential statistics. The exact new-head CI, scientist review,
migration reconciliation and native Windows acceptance remain release gates.

## Population export provenance regression hardening (2026-10-27)

The population CSV acceptance suite now checks nine re-signed forged scientific
summaries rather than five, including fabricated independent-unit IDs, parent
colony lineage, missing-parent declarations and percent-change means. The
existing renderer re-derives population aggregates from source-linked candidates
and rejects these mutations despite a recalculated fingerprint. This is
regression coverage for an existing safeguard, **not** verification of source
identity, biological independence, or scientist approval. The same renderer is
used by the standalone CSV API and the executable persisted Workflow Builder
node. Corrected the Ruff formatting error in this test file reported by the
previous exact-head CI; latest-head CI and installed Windows acceptance are
still required before any release-ready declaration.

## Population CSV auditable source lineage (2026-10-27)

The existing project-owned `population.csv` endpoint and executable,
persisted `ecology_population_csv_export` Workflow Builder node now emit
CSV schema `ecology-population-export-0002`. Each declared-unit and
population-stratum row includes an explicit
`source_fingerprint_rechecked=true` flag and the source registry-history,
image-evidence, annotation-evidence and calibration-evidence SHA-256
references. This makes the previously implicit audit chain visible in
exported research tables and retains byte-for-byte standalone/saved-workflow
CSV parity. Optional unavailable legacy evidence hashes are exported as
empty cells, never invented identifiers. The renderer still rejects
non-recheckable legacy source contracts.

A focused regression checks both row types and their exact source hash
values, then alters a calibration-evidence digest without re-signing the
source and requires fail-closed fingerprint validation. The previous head
`8486c37d` completed **16/19 GitHub Actions workflows**; CI, Pose
Workflow Validation and ReefVision 1.0 Acceptance all stopped at the same
Ruff extra-blank-line error in the population CSV test. This increment
also removes that exact formatting defect. Latest-head CI and native
Windows GUI/installer acceptance remain unverified.

The added hash references prove reproducible linkage only, **not** human
review, calibrated growth accuracy, authenticated organism identity, or
independent biological replication. All results remain
`linked_unverified` / `scientist_review_required`, with independent-unit
inference prohibited. No new migration, environmental subsystem, model
download, branch merge, tag or release is introduced.

## Population CSV source-denominator audit and exact-head CI repair (2026-10-27)

The predecessor 1.2 head `4b0dd8217b354c80c86cf8e8c9981c304afb21ef`
completed **16/19** GitHub Actions workflows. CI, Pose Workflow Validation,
and ReefVision 1.0 Acceptance stopped at the same Ruff formatting failure
in `test_ecology_population_export_1_2.py` (a three-line set literal). The
exact formatter-requested one-line form is applied here.

The existing standalone `population.csv` endpoint and executable, persisted,
typed `ecology_population_csv_export` Workflow Builder node now expose the
source fingerprint contract and source candidate/image/organism/exclusion
counts alongside the already rechecked registry, image, annotation and
calibration evidence digests. The export schema is explicitly advanced to
`ecology-population-export-0003`; previous `0002` column consumers must
account for the new columns. Source denominators are **not** statistical
replicate counts: a regression checks that two source images of one organism
in one tank still yield exactly one declared experimental unit. The existing
standalone and saved-workflow byte-parity and verified-dataset-port rejection
tests remain applicable. No new workflow type, migration or environmental
provider is introduced.

The source report's candidate/image/organism/exclusion denominators are
revalidated by the shared series-QC exporter before rendering, so altered
counts fail closed rather than being silently displayed as scientific facts.
All outputs remain `linked_unverified`, `scientist_review_required`, and
`independent_unit_inference_allowed=false`. These counts do **not** certify
organism identity, biological independence, calibrated growth, or scientist
review. New-head CI, authenticated longitudinal measurements, migration
reconciliation, independent ecological acceptance, and installed Windows
GUI/installer validation remain outstanding. **1.2 is NOT RELEASE-READY.**

## Population CSV source-versus-analytic denominators and strict typing (2026-10-27)

At prior head `faa80976720905e18586c89c872bb3dd22e96ccb`, 16/19 GitHub
Actions workflows succeeded. CI, Pose Workflow Validation and 1.0 Acceptance
failed at the same strict-mypy invariant-list error in the CSV serializer:
`list[Literal[...]]` could not be passed to `_array(list[str])`.
The serializer now accepts covariant `Sequence[str]` without casting or
loosening the typed ecological summary schema.

The existing standalone population CSV API and executable, persisted
`ecology_population_csv_export` Workflow Builder node share schema
`ecology-population-export-0004`, adding independently rechecked source
`source_declared_experimental_unit_count`,
`source_date_qc_pass_series_count` and `source_excluded_series_count`
columns to every row. These describe *source design declarations and
organism/metric QC series*, not eligible independent statistical replicates.
They are intentionally distinct from row-level `declared_unit_count`:
excluded units do not contribute to analytic means. Regression assertions
check the values and the two-image/one-organism/one-tank denominator boundary.
Previously exported CSV consumers must account for the new schema version.

No migration, new workflow node, external provider or model weights are added.
All outputs remain `linked_unverified`, `scientist_review_required`, and
`independent_unit_inference_allowed=false`. Source registry and annotation
links do not establish biological independence or scientifically verified
longitudinal growth. Latest-head CI, scientist-reviewed datasets, independent
migration reconciliation and native installed Windows acceptance remain
release blockers; no release-ready claim is made.

## Population CSV row-width integrity and CI repair (2026-10-27)

The preceding 1.2 head `1b850bbe173b179be7313aa63f30c0303b20c0f9`
completed **16 of 19** GitHub Actions workflows successfully. CI, Pose
Workflow Validation and ReefVision 1.0 Acceptance all failed at the **same
Ruff format diff** in `test_ecology_population_export_1_2.py`: collapse the
`source_declared_experimental_unit_count` string conversion to one line.
The exact formatter-requested change has been applied.

The shared `ecology_population_csv_export` Workflow Builder renderer and
standalone `population.csv` endpoint now enforce the declared CSV column
count **for every experimental-unit and population-stratum row** before
writing it. A later schema edit that adds or removes a header column without
updating both row serializers must fail closed rather than silently shift
scientific fields, omit the review gate, or mislabel replicate denominators.
The schema remains `ecology-population-export-0004`, with one centralized
version constant; this is a compatibility-preserving integrity check.

Two parameterized regressions deliberately shorten and extend the header
contract and require a `ValidationError` rather than a malformed CSV.
Existing API/saved-workflow byte-parity, source-fingerprint recheck,
project ownership, review-gate and independent-unit safeguards remain
applicable. Source code and test changes are pushed, but latest-head CI,
installed Windows GUI/installer validation, authenticated longitudinal
observations, migration reconciliation and independent ecological review
are still required. **1.2 is NOT RELEASE-READY.**

## Population CSV scientific-row fail-closed validation (2026-10-27)

The shared population CSV serializer now rejects duplicate CSV column names,
invalid row kinds, non-integer or contradictory experimental-unit/organism
denominators, and any attempt to label exported rows as verified or inferential.
A declared-unit row may represent zero excluded units or one eligible unit;
a population stratum must have at least one declared unit and at least one
contributing organism per eligible unit. The exporter also retains the
previous exact 40-column count contract. These guards run identically for
the standalone population CSV API and the persisted executable
`ecology_population_csv_export` Workflow Builder node.

Eight focused regression scenarios exercise duplicate header names and
forged scientific-row fields before CSV emission. The previous head
`f729bd7b4bb06a8461e49561509ad4df6e7cc496` completed 16/19
GitHub Actions workflows; three backend failures all traced to Ruff's
required trailing commas in `ecology_population_export.py`. Those two
formatting differences were corrected in this increment. No new migration
or independent-unit inference was introduced. All output remains
`linked_unverified` and `scientist_review_required`; exact-head CI,
scientific dataset validation, 1.1 migration reconciliation, and installed
Windows GUI acceptance remain release blockers.

## 2026-10-27 — CI regression: forged missing-parent declarations

The `aa2c978b` exact-head CI run passed Ruff, mypy, 1,577 backend tests,
and 17 of 19 workflows, but one parameterized population-export test
incorrectly expected every re-signed forged aggregate to fail at the
population-recomputation guard. A forged `units_missing_parent_colony` entry
is rejected earlier by the candidate report's source-total fingerprint
integrity guard. The regression now asserts the specific earlier rejection
for that case and retains population-recomputation assertions for the other
eight forged-aggregate cases. The exporter and its standalone API and saved
Workflow Builder execution remain unchanged; no scientific verification or
release-readiness is implied. Re-run exact-head CI before claiming success.

## 2026-10-27 — Paired-count whole-organism input integrity

The preceding 1.2 head `219d523d800e7f74f36553beeaa442f246a868d6`
completed **19/19 PR-triggered GitHub Actions workflows successfully**.
That CI success is a development gate, not release or scientific acceptance.

The shared `PairedCountObservation` contract now rejects finite fractional
human-reference or model **organism counts** (for example, 10.5 polyps).
Nonnegative integral JSON numbers, including `10` and `10.0`, remain
accepted; the prior finite-large-value regression is unchanged. The check
runs through the same Pydantic schema for the standalone paired-count API
and the executable persisted `ecology_paired_count_comparison` Workflow
Builder node. This prevents fractional count estimates from being presented
as literal organism counts without changing descriptive statistics,
source/provenance fingerprints for valid inputs, or the typed workflow ports.

New focused tests exercise both count fields through schema and HTTP 422,
integral floating-point compatibility, and fail-closed saved-workflow
execution without a successful comparison artifact. All outputs remain
`caller_supplied_unverified` and require source verification; this is **not**
a review or calibration gate. Exact new-head CI, authenticated organism
identity, independently reviewed measurements/design, migration reconciliation,
and installed Windows GUI/installer acceptance remain outstanding.
**ReefVision 1.2 is NOT RELEASE-READY.**


## 2026-10-27 — Canonical experimental-unit aliases for exploratory analyses

The exploratory longitudinal and paired human–model count analyses now accept
known **equivalent biological sampling-level labels** across observations:
`tank`, `aquarium`, `aquaria` and `Tank-level` describe the same declared
tank-level design. Previously, one physical tank could be rejected as mixed
unit types merely because individual observation records used these aliases.
Without an explicit request label, mixed known aliases resolve to the
deterministic canonical biological level; a compatible explicitly supplied
request label is retained. Existing homogeneous inputs preserve their
original response label and provenance algorithm version.

The shared `ecology_lineage_policy` helper also recognizes equivalent
organism/fragment, colony/colonies and site/transect levels. **Different
biological levels, unrecognized differing study-specific labels and
technical image/frame/camera unit declarations still fail closed.** Organism
membership and parent-colony constraints continue to operate on the
unchanged experimental-unit IDs, so a tank is not counted twice because
of spelling. Raw per-observation labels remain in the canonical input
fingerprint, allowing a source-declaration correction to change provenance.

Both standalone APIs and their existing executable, typed, persisted
`ecology_longitudinal_analysis` and `ecology_paired_count_comparison`
Workflow Builder nodes use the same scientific policy. New regressions cover
known aliases, explicit request aliases, source fingerprint differences,
incompatible-level rejection, saved-workflow artifact parity, and fail-closed
workflow execution. No new workflow node, migration, environmental context,
external model weights or verified-dataset promotion is introduced.

**Evidence limitation:** this normalizes researcher-entered *labels*, not
biological independence, true tank assignment, reviewed identity, calibrated
growth or authenticated study design. Results remain
`caller_supplied_unverified`; paired counts retain
`requires_source_verification`. The new commit needs exact-head CI, real
ecological data/scientist acceptance, 1.1 migration reconciliation and
installed Windows GUI/installer testing. **1.2 is NOT RELEASE-READY.**

## 2026-10-27 — Pose/tracklet technical-replicate pseudoreplication guard

The shared ecological experimental-unit validator now also rejects
`keypoint`, `tracklet`, `heatmap`, `polygon`, `screenshot`, and
`subframe` (including plurals) as independent biological sampling-unit
labels. Compound declarations such as `pose_keypoint`,
`tracking_tracklet`, `prediction_heatmap`, and
`segmentation_polygon` fail closed rather than inflating organism,
colony, tank or site denominators with model/annotation-derived outputs.
Real biological-unit declarations remain supported; this does **not**
authenticate independence or the underlying study design.

The validator is shared by the standalone longitudinal and paired-count
schemas, the project-owned identity-registration API, imported registry
revalidation, and their existing executable, persisted Workflow Builder
nodes. Focused parameterized regressions cover schema rejection, identity
writes, corrupted imported identity revisions, and saved-workflow failure
without successful scientific artifacts. Existing typed ports, source
fingerprints and `registered_unverified`/`caller_supplied_unverified`
review gates remain unchanged. No database migration, duplicate 1.1
environmental store, model download, or verified-dataset promotion is
introduced.

The preceding head `cd7109bcbd4588ab8b6192ac6046dd977fbdb29d`
completed **16/19** GitHub Actions workflows. All three backend failures
stopped at one Ruff I001 import-order error in
`test_ecology_unit_type_aliases_1_2.py`; this iteration applies the
exact import split reported by the runner. The new head still requires
exact-head CI, representative real-image ecological acceptance, migration
reconciliation with 1.1, scientist review, and installed Windows GUI/installer
checks. **1.2 is NOT RELEASE-READY; 1.3 remains unstarted.**


## 2026-10-27 — Compact technical-replicate unit labels and exact-head CI repair

The preceding Track B head `60996e4bc784130e79b32500613b666aabbff760`
completed **16/19** GitHub Actions workflows. The three backend failures
(CI, Pose Workflow Validation and ReefVision 1.0 Acceptance) shared two
Ruff format differences in `test_ecology_identity_registry_1_2.py` and
`test_ecology_unit_type_aliases_1_2.py`; the exact runner-requested
formatting changes have been applied.

The shared experimental-unit validator now rejects common **camel-case and
separator-free technical observation labels**, including `VideoFrame`,
`poseKeypoint`, `trackingTracklet`, `segmentationMask`, `modelPrediction`,
`boundingBox`, `imagePatch`, `videoframe` and `segmentationmask`.
Previously, a separator-free label could evade the token-based technical
replicate check and be declared a biological independent unit. This remains
a conservative label-level safeguard, **not experimental-design verification**.

Focused regression coverage checks the shared policy, project-owned identity
registry import/revalidation, standalone longitudinal and paired-count APIs,
and persisted executable Workflow Builder runs. Invalid sampling declarations
must fail without a successful ecological analysis or registry artifact;
valid tank/colony/organism/site declarations, typed ports, provenance,
review gates and existing schema versions are unchanged. No new migration,
model weights, environmental context, or verified-dataset promotion is added.

**Validation pending:** exact-head CI, independent biological-study review,
1.1 migration reconciliation and installed Windows GUI/installer checks.
**1.2 is NOT RELEASE-READY; 1.3 remains unstarted.**

## 2026-10-27 — CamelCase biological-unit classification and CI E501 repair

The previous Track B head `345fe8823774165a5a70843958dd0f86253cc152`
completed **16/19** PR-triggered GitHub Actions workflows. The three backend
failures all stopped at the same Ruff E501 line-length error in
`test_ecology_unit_type_aliases_1_2.py:222`; the long project-creation
expression is now wrapped without changing test behavior.

The shared lineage classifier now separates CamelCase biological unit labels
before classifying their declared level. `TankLevel` and `ParentColony`
resolve to their known tank and colony levels; previously, these were treated
as unknown study-specific labels. More importantly, `TankColony` and
`OrganismTank` now fail closed as **ambiguous mixed biological levels**,
rather than bypassing the colony/organism pseudoreplication rules as an
unrecognized single label. Raw declarations remain unchanged for source
provenance. This is label-level QC, **not proof of experimental independence**.

Focused tests cover alias equivalence, ambiguous lineage rejection, both
standalone ecological APIs, and saved executable Workflow Builder failure
without a successful scientific artifact. Existing typed ports, persisted
provenance, review gates and unverified evidence classifications are retained;
no schema migration, external model, environmental store or verified-dataset
promotion is introduced. New-head CI and scientist-reviewed real-image
ecological acceptance, 1.1 migration reconciliation and native Windows
installer/GUI validation remain outstanding. **1.2 is NOT RELEASE-READY.**


## UTC elapsed-time correction for projected endpoint rates (2026-10-27)

The source-linked projected endpoint kernel now orders captures by their **UTC
instants** and calculates elapsed days after converting both endpoints to UTC.
Subtracting two local datetimes that share a timezone object can otherwise
ignore a daylight-saving offset transition, changing projected change-per-day
by an hour while retaining apparently valid sampling dates. A portable
synthetic-offset regression covers a 47-hour interval spanning two local
calendar days, the derived slope, signed source CSV rechecks, and the unchanged
`linked_unverified` scientist-review gate.

The source fingerprint algorithm advances from
`ecology-measurement-candidates-0018` to `0019`. The response schema still
**deserializes prior 0018 artifacts**, but old calculated rates are not silently
re-signed or promoted; source/derived integrity checks remain mandatory.
This is a correctness fix for provisional projected geometry, **not** verified
biological growth, independent replication or an accepted longitudinal study.
Existing executable Workflow Builder source/export nodes share the corrected
kernel and persisted evidence contract; full exact-head CI, real ecological
data, migration reconciliation and installed Windows GUI acceptance remain
release blockers.


## Capture-time evidence consistency and bidirectional offset tests (2026-10-27)

The previous head `cee8e64841c7692e92a823dbb13540de52777b2d`
completed **16/19** PR-triggered GitHub Actions workflows. The three
backend failures all stopped at Ruff formatting, not scientific test failures:
`ecology_measurement_candidates.py` and
`test_ecology_projected_series_csv_1_2.py` were the two unformatted files.
The formatter-requested edits have been applied.

Source-linked projected measurement candidates now fail schema revalidation
when `capture_time_status="timezone_aware"` lacks a timezone-aware
timestamp, or when `missing` / `timezone_missing` contradictorily carries
a timestamp. This prevents an imported or saved source record from claiming
both dated and undated acquisition evidence. Existing valid undated
(`timezone_missing` with no timestamp) artifacts remain readable; no
historical record is silently promoted to verified evidence.

The UTC elapsed-time regression now checks both spring-forward **47-hour**
and fall-back **49-hour** real intervals across two local calendar days,
including projected rates, source fingerprint rechecks and reproducible CSV
serialization. The standalone source-linked measurement API and existing
executable, persisted Workflow Builder measurement/report nodes use the
same typed schema and UTC calculation kernel. No new node, migration, or
environmental data store was introduced. Existing review gates remain
`scientist_review_required` and evidence remains `linked_unverified`.

**Release HOLD:** exact-head CI and saved-workflow compatibility still
require verification, as do authenticated scientist-reviewed measurements,
registered experimental-design acceptance, 1.1 migration reconciliation,
real ecological datasets, and installed Windows MSI/GUI checks. Neither
1.2 nor 1.3 is release-ready.

## Case-insensitive source photograph digest QC (2026-10-27)

SHA-256 hexadecimal casing is not biological evidence: a photograph reimported
with an uppercase content digest is the same source as its lowercase digest.
The source-linked sampling-date QC now compares case-folded image-content
digests for cross-series reused-photo dates, inconsistent capture instants,
missing-versus-dated acquisition metadata, and same-ID metadata consistency.
QC reports canonical lowercase digest identifiers, but source candidate fields
and raw source fingerprints retain their original spelling for provenance.
Legitimate multi-organism observations from the same photograph at the same
UTC instant remain eligible as provisional date-series candidates.

Focused regressions cover uppercase reimports across dates, legitimate
same-instant offsets, same-image-ID aliases, undated reimports, and rehydration
from an executed saved Workflow Builder source artifact. The standalone
measurement API and executable Workflow Builder share this QC kernel; the
persisted-workflow test does **not** constitute scientist review or a verified
growth workflow. Existing `linked_unverified` evidence and
`scientist_review_required` gates remain unchanged. The preceding head
`c4f716400568a893a326daf99d022e682c6065bf` completed 16/19
PR-triggered workflows; three backend failures were the same Ruff format
difference in `test_ecology_projected_series_csv_1_2.py`, corrected here.
Exact new-head CI, migration reconciliation, independently reviewed
longitudinal measurements, and installed Windows acceptance remain pending.
**1.2 is NOT RELEASE-READY; 1.3 is not started.**


## Canonical source-linked sampling levels and provenance v0020 (2026-10-27)

The prior exact 1.2 head `790114fa17459e0d47fdba10475e916f32d470bc`
completed **16/19** GitHub Actions workflows. The three backend failures
stopped at the same Ruff formatter difference in
`test_ecology_digest_case_qc_1_2.py`; all six runner-requested formatting
edits were applied before this scientific increment.

The source-linked `summarize_sampling_date_qc` kernel now compares **canonical
biological sampling levels**, not the raw spelling of otherwise equivalent
labels. A registered tank photographed under the declarations `tank`,
`aquarium`, `aquaria`, or `TankLevel` is one provisional longitudinal
experimental unit when the identity revision, parent and unit ID are
otherwise unchanged. Previously, raw-label comparison marked the series
`identity_context_changed`, even though the existing visit-coverage and
unit-summary kernels correctly grouped these aliases. Genuine
`tank`-versus-`colony` changes still fail the date-series gate.

Raw per-candidate labels remain unchanged and contribute to source SHA-256
fingerprints; correcting a label changes the source fingerprint without
creating a second independent replicate. The source fingerprint contract
advances to `ecology-measurement-candidates-0020`; saved v0018/v0019
artifacts remain deserializable, but a historical artifact with an obsolete
derived QC decision is **not** silently re-signed or promoted by CSV export.
The existing standalone API and executable, persisted
`ecology_identity_registry_source` Workflow Builder node use the same
shared QC kernel. Focused regressions cover equivalent aliases, true
biological-level conflicts, signed CSV source/derived reconciliation,
distinct source fingerprints and replay of the persisted workflow source
artifact. No new workflow node, migration or 1.1 environmental store is
introduced.

**Scientific boundary:** all projected measurements and derived changes remain
`linked_unverified`, with `scientist_review_required`; canonical labels
do not prove true biological independence, verified identity, growth, or
calibration accuracy. Exact-head CI, authenticated scientist-reviewed
longitudinal observations, registered study-design acceptance, 1.1 migration
reconciliation, independent real-data review, and native Windows installer/GUI
acceptance are still required. **1.2 is NOT RELEASE-READY; 1.3 has not started.**


## Canonical biological-unit report denominators (2026-10-27)

Source-linked candidate reports now count a physical declared biological unit
once when a source series uses equivalent labels such as `tank` and
`aquarium`. The count no longer inflates merely because a researcher corrected
the spelling of the sampling level between captures. Original labels remain
in the source fingerprint; this does **not** authenticate independence.
The source fingerprint contract advances to
`ecology-measurement-candidates-0021`. CSV rechecks use canonical unit counts
only for 0021; historical signed 0018–0020 reports retain their original
literal-label denominator and remain readable without silently rewriting
research records. Focused tests cover aliases, legacy signed reports, forged
re-signed denominators and existing saved-workflow evidence. Source-linked
measurements remain `linked_unverified`, with scientist review required.
Full CI, registered study designs, migrations and installed Windows GUI
acceptance remain outstanding.

## Strict source-linked measurement and acquisition-time inputs (2026-10-27)

The typed `EcologyMeasurementCandidate` contract now rejects coerced
calibrated values (Boolean, numeric strings, nulls and structured values)
rather than silently converting them into apparent measurements. Positive
finite JSON numbers remain valid. Capture times must be explicit ISO 8601
calendar timestamps or already typed `datetime` objects; Unix epoch
numbers, numeric timestamp strings and date-only values are rejected.
Valid timezone-offset timestamps and genuinely undated historical records
remain supported, with the existing capture-status consistency checks.

The standalone project-owned candidate API and executable saved
`ecology_identity_registry_source` Workflow Builder node already share
this Pydantic evidence schema; no duplicate workflow node or environmental
store is introduced. Focused tests cover eleven malformed inputs, valid
offset/undated records, successful API-versus-saved-workflow parity, and
fail-closed rehydration of tampered persisted source payloads. These
regressions do **not** establish a scientist-approved measurement record.
All source-linked projected values remain `linked_unverified`, require
`scientist_review_required`, and cannot be promoted into immutable verified
training data. No migration or historical artifact rewrite is introduced.
Exact-head CI, independent real-data acceptance, migration reconciliation,
and native Windows installer/GUI tests remain mandatory.
**ReefVision 1.2 is NOT RELEASE-READY; 1.3 has not started.**

## Source-evidence SHA-256 syntax gate (2026-10-27; development only)

The typed `EcologyMeasurementCandidate` contract now rejects malformed
`image_sha256`, `annotation_sha256`, and `calibration_sha256` values
before accepting a source-linked projected measurement. All three fields
require exactly 64 ASCII hexadecimal characters: truncated/overlong values,
non-hex characters, Unicode lookalikes and non-string values fail closed.
Valid mixed-case hexadecimal digests are preserved byte-for-byte in original
source provenance; the existing date-quality guard continues to compare
image content digests case-insensitively. This is a **syntax and artifact
rehydration safeguard**, not a fresh hash of image bytes or independent
verification of reviewed annotation, calibration or organism identity.

Regression coverage exercises 27 malformed field/value combinations,
valid mixed-case digests, and tampered persisted Workflow Builder source
artifacts, while the existing standalone candidate endpoint and executable
source node retain their typed `ecology_measurement_candidates` contract,
`linked_unverified` evidence level and `scientist_review_required` gate.
The three backend workflows on the preceding exact head
`fa46b91c9734bbfb18cf7ca425e1d8192503037f` failed only Ruff formatting;
the two reported files were corrected in this increment. New-head CI,
authenticated longitudinal source review, experimental-design attestation,
migration reconciliation with unmerged 1.1, real scientific acceptance and
installed Windows GUI/installer testing remain release blockers. No merge,
release, model download or verified-dataset promotion occurred.

## Exact source-revision identity validation (2026-10-27; development only)

The source-linked `EcologyMeasurementCandidate` schema now requires
`identity_revision` and `annotation_revision` to be **explicit positive
JSON integers**. Boolean `true` (which Python otherwise interprets as
integer 1), numeric strings, floats, nulls and containers cannot silently
become an identity/annotation revision. Positive integers remain unchanged;
the existing producer, standalone candidate API and typed persisted
`ecology_measurement_candidates` Workflow Builder source share this schema.
No database migration or environmental-context duplication is introduced.

Added 14 direct rejection cases, six valid revision cases, and four saved
executable-workflow artifact tampering/replay rejection cases. The preceding
exact head `cbf29bad1035b988d93a2a39261e2acfc025ba23` passed 16/19
GitHub Actions workflows; three backend workflows failed at Ruff RUF001
because a fullwidth-character negative test used a literal confusable.
The negative test now uses the ASCII Unicode escape `\\uff41` to preserve
the runtime adversarial value without violating the lint policy.

This guards **revision syntax and artifact rehydration only**, not the
existence, ownership, immutable hash, biological identity or scientist review
of source annotations. All output remains `linked_unverified` and
`scientist_review_required`. Full exact-head CI, authenticated longitudinal
source review, registered experimental design, migration reconciliation,
real coral data acceptance and installed Windows GUI/installer testing remain
mandatory. No merge, tag, release, installation or deployment is authorized.


## Frozen source-image acquisition and geometry metadata (2026-10-28; development only)

A linked image's content SHA-256 was already immutable, but the source image
capture timestamp, positive pixel dimensions, byte size, and media type could
still change after linking. Such edits could retroactively change UTC
longitudinal sampling dates or calibrated projected measurements without
requiring a new organism/source evidence decision. New image links now store a
SHA-256 of this metadata, including explicit missing/naive/aware capture-time
status and UTC-normalized aware timestamps. Registry reads fail closed if the
linked source metadata changes; the existing standalone registry and saved
executable Workflow Builder source share this check.

Migration `b12_identity_0005` adds a nullable fingerprint column. Historical
links remain **legacy_unfrozen** (NULL) rather than receiving a fabricated
snapshot from today's mutable image metadata. The API and persisted workflow
registry expose `source_metadata_evidence_status` and the optional fingerprint;
the registry evidence fingerprint advances to
`ecology-image-evidence-0002`. No historical record is overwritten, no source
is promoted to verified, and no inference of acquisition time is made. Focused
regressions cover missing-to-dated and dated-to-different capture timestamps,
positive dimension drift, legacy disclosure, and saved-workflow fail-closed
behavior. Legacy acquisition evidence still requires explicit scientist review
and a future migration/relink policy before verified longitudinal acceptance.

The previous exact head `25b93af8e3cd3602e18496c633bf05b89409bacd`
completed 16/19 Actions workflows. The three backend failures were solely
Ruff formatting of the SHA-256 validator decorator and negative-test
function signature; both formatting differences are corrected in this slice.
Exact-head CI, independent biological verification, migration reconciliation
with unmerged 1.1, and native Windows MSI/GUI acceptance remain outstanding.
**ReefVision 1.2 is NOT RELEASE-READY; 1.3 has not started.**


## 2026-10-28 Track B — typed registry evidence digest QC

After auditing exact-head PR #74 CI, repaired Ruff I001 import ordering in
`test_ecology_image_evidence_1_2.py`. The preceding SHA
`c7588b4ecdc85daaebe8657065a730fd8bcd79c5` had 16/19 successful
Actions workflows; three backend workflows failed at that single import block.

The `EcologyIdentityRegistryResponse` linked image, annotation and calibration
rows now require exact 64-character ASCII hexadecimal SHA-256 strings for
image-content, annotation-revision and calibration fingerprints. This closes a
persisted-artifact rehydration gap: a saved executable Workflow Builder registry
artifact containing a truncated or malformed linked evidence digest must not
pass typed validation. Original mixed-case valid digests remain unchanged.
The existing `linked_unverified` / `registered_unverified` evidence levels and
`scientist_review_required` gate are preserved; syntactic validation does
**not** verify the underlying source bytes, annotation approval, or a
well-formed but substituted hash.

Focused regression coverage executes the existing project-scoped registry
source as a saved Workflow Builder graph, compares the persisted artifact to
the standalone API, and checks malformed values in all four linked digest
locations. No new workflow node, migration, 1.1 environment store or
experimental-unit assumption was introduced. Exact-head CI and physical
Windows acceptance must be checked independently before any release claim.

## 2026-10-28 Track B — saved registry evidence relationship integrity

The source registry's typed response now rejects cross-project biological
identities and linked evidence, duplicate source-link identities, mismatched
explicit evidence counts, orphaned image/annotation/calibration references,
calibrations attached to the wrong image bytes, and image links referring to
unknown recorded identity revisions. This protects deserialized executable
Workflow Builder source artifacts as well as the standalone project registry;
the existing typed node, persisted output, and scientist-review gate are reused
rather than introducing a second scientific evidence path. Older artifacts
that omitted later-added link collections/counts remain readable, but fields
actually present must be internally consistent. The image SHA-256 comparison
is case-insensitive for content equality while original provenance is retained.

The previous exact HEAD `bf2b36f5fe859fe3a98feac5a34ca2b68b414d35`
completed 16 of 19 Actions workflows; all three backend failures were Ruff
formatting of two test expressions, corrected in this increment. Added
standalone-API versus saved-workflow parity and tampered-artifact regression
cases for project ownership, source joins, count integrity and identity history.
These checks do not verify source file bytes, researcher approval, calibrated
biological growth or true experimental independence. Full exact-head CI,
1.1 migration reconciliation, authenticated scientist review and physical
Windows installer/GUI acceptance remain required. **1.2 is NOT RELEASE-READY;
1.3 has not started.**


## 2026-10-28 Track B — revision-history artifact reconciliation

The existing project-owned `ecology_identity_registry_source` Workflow Builder
node and standalone identity-registry API share a typed evidence contract.
Persisted artifacts now reject missing/extra organism histories, noncontiguous
revisions, latest-identity snapshots that disagree with the append-only history,
and image links to nonexistent or future revisions. An explicitly present empty
history is not treated as an old artifact that omitted the history field.

When the existing `history_sha256` is present, rehydration recomputes the
producer's canonical `ecology-identity-history-0001` digest, preventing a
changed historical experimental-unit assignment or note from passing with the
original hash. Legacy saved artifacts that omit history remain readable, but
linked images still require a known organism and plausible prior revision.
These checks do not cryptographically authenticate a researcher, establish
true independent experimental units, or promote unverified biological evidence.

Focused regressions cover standalone API versus executed saved-workflow
parity, retroactive history edits, contradictory latest identity, future/orphan
image revisions, explicitly empty histories, discontinuous revisions and
legacy compatibility. The previous exact HEAD `acb0cb052580e4f010c8355790f2a9c83a7d1ce1`
completed **16/19** Actions workflows; three backend failures were the same
Ruff SIM102 nested-if and E501 overlong-line diagnostics, corrected in this
increment. New-head CI and real-data scientific/Windows acceptance remain
pending. **1.2 is NOT RELEASE-READY; 1.3 has not started.**

## 2026-10-28 Track B — signed identity and linked-evidence replay integrity

The previous exact HEAD `d5cfaeeb478eebe1d734444d45b43125b0796a15` passed **16/19** Actions workflows;
three backend failures were exclusively a Ruff formatting difference in
`schemas/ecology_identity.py`, corrected in this increment.

The existing `EcologyIdentityRegistryResponse` now verifies the producer's
latest-identity `snapshot_sha256` even for saved artifacts without identity
history, and verifies signed annotation and calibration collection SHA-256
digests when their rows are present. This prevents tampered biological identity
kind or experimental-unit context, source annotation notes, calibration link
notes, and substituted digests from silently passing Workflow Builder artifact
rehydration. The standalone registry API and existing executable typed
`ecology_identity_registry_source` node share this schema; no duplicate
node, migration, environmental store, or model download was added.

Historical artifacts missing optional collection digests remain readable but
`registered_unverified` with `scientist_review_required`; no retrospective
verification is inferred. This is internal fingerprint consistency, not
authentication of source image bytes, researcher identity, calibration
accuracy or independent biological replication. Historical image-link
v0001/v0002 digest compatibility still needs separate review. Focused
regressions cover API/saved-workflow parity, altered identities and linked
evidence, substituted signatures and legacy unsigned compatibility. Exact-head
CI, independent real-data scientist review, 1.1 migration reconciliation and
physical Windows installer/GUI acceptance remain release blockers.
**1.2 NOT RELEASE-READY; 1.3 not started.**


## Signed image-evidence replay integrity (2026-10-28)

The existing standalone ecological identity registry and executable, persisted
`ecology_identity_registry_source` Workflow Builder node now revalidate the
producer's signed image-link collection when an `image_evidence_sha256`
field is present. This includes source-image SHA-256, organism/revision
attribution, acquisition metadata fingerprint, explicit frozen/legacy status,
source identifiers, and original link notes. Changed saved-workflow image
records or substituted collection fingerprints fail closed during Pydantic
artifact rehydration; neither path can silently turn tampered source links
into longitudinal measurement provenance.

Historical signed `ecology-image-evidence-0001` artifacts remain readable
**only** when all image links explicitly lack a frozen acquisition-metadata
fingerprint. Modern `ecology-image-evidence-0002` signatures are preferred;
modern links cannot bypass validation by claiming the legacy digest. Missing
optional signatures on older artifacts are not retroactively authenticated.
Regression coverage exercises standalone API versus executed saved-workflow
parity, changed source hashes/notes/metadata digests, substituted signatures,
legacy signed replay and modern legacy-unfrozen records. The preceding head
`657de8009ec86286d8bcd3592316d336dba10428` completed 16/19 Actions;
three backend jobs failed on one Ruff formatting violation, corrected in this
iteration. Exact new-head CI, independent scientific review, migration
reconciliation, and installed Windows GUI acceptance remain pending.

**Boundary:** SHA-256 consistency is not independent authentication of source
bytes, organism identity, calibration correctness, or scientist verification.
All ecological evidence remains unverified and requires review. No merge,
installer publication, or cross-version integration is authorized.


## 2026-10-28 Track B — saved-workflow experimental-design audit integrity

Audited draft PR #74 and the existing source-linked ecological registry, design
revision service, CSV history exporter, and executable
`ecology_identity_registry_source` Workflow Builder node. The previous exact
head `1496d333a68f69588bc9ad59aa4a811f690a499e` completed **16/19**
Actions workflows. The three backend failures were caused by Ruff formatting
differences in `schemas/ecology_identity.py` and
`test_ecology_image_registry_replay_1_2.py`; applied the reported formatting
changes without changing historical evidence semantics.

**New scientific safeguard:** Pydantic artifact rehydration now independently
rederives declared design-change events and counts, current cross-unit shared
parent-colony warnings, and historical cross-unit parent warnings from the
persisted identity and revision evidence. Contradictory "no design change",
"no shared parent", or "no historical reuse" claims fail closed. This closes a
gap where an executed saved workflow's persisted typed artifact could hide
pseudoreplication warnings even though the standalone CSV exporter performed
these consistency checks. No new workflow node or environmental data store
was created; standalone and saved-workflow paths share the existing typed
source, evidence provenance and `scientist_review_required` gate.

Regression cases register a colony with fragments in different tanks, revise
a tank assignment, execute and persist a saved workflow, and attempt to erase
eight design/current-parent/historical-parent audit fields. Legacy artifacts
omitting audit fields still deserialize as **unavailable**, never as a verified
negative finding; inconsistent "unavailable" audit payloads are rejected.
Known design/historical audit claims require replayable identity history.

**Boundary:** Registered unit IDs, parent relationships and their deterministic
audits do not establish true biological independence, verified specimen
identity, observed transfers or scientifically reviewed measurements.
All evidence remains `registered_unverified` /
`scientist_review_required`. Exact-head CI, registered study-design review,
authenticated longitudinal calibrated measurements, migration reconciliation
with unmerged 1.1, real-data acceptance, and installed Windows GUI/MSI checks
remain required. **1.2 NOT RELEASE-READY; 1.3 not started.**


## 2026-10-28 Track B — frozen calibration snapshot replay validation

**Audit:** Draft PR #74 remained open on `develop/reefvision-1.2`; the prior
head `b178e404a073e780604314be421bfab1183068d6` completed 16/19
GitHub Actions workflows. All three backend failures stopped at Ruff format,
with two affected files and exact formatting differences retrieved from job
logs. The formatter corrections were applied without changing the design
audit's scientific meaning.

**Scientific correction:** The existing project-owned registry producer
computes each calibration's `ecology-calibration-source-0001` SHA-256 over
the frozen calibration JSON, source image ID and image SHA-256. The persisted
registry collection fingerprint previously included only that per-source
digest, not the calibration JSON values themselves. A replayed saved-workflow
artifact could therefore change the physical distance-per-pixel, length
unit or reference segment while leaving the collection fingerprint intact.
`EcologyCalibrationEvidenceRow` now independently recomputes and verifies
the per-source digest during typed deserialization. Altered calibration
values or substituted per-source digests fail closed even if an older
artifact omits the optional collection signature.

**Integration and regression:** The existing standalone
`GET /api/v1/projects/{project_id}/ecology/identity-registry` and the
executable, persisted `ecology_identity_registry_source` Workflow Builder
node use this same typed schema. A source-backed API/saved-workflow regression
checks identical persisted evidence, three altered physical-calibration
fields, an unsigned legacy collection, and a substituted per-source digest.
No duplicate environmental context, workflow node, model weights, database
migration or independent-unit claim was added.

**Boundary:** Matching SHA-256 proves internal consistency of the frozen
snapshot, not scientific review, physical calibration accuracy, independent
source authentication or biological growth. Evidence remains
`registered_unverified`/`linked_unverified` with
`scientist_review_required`. Exact-head full CI, source-backed ecological
review, migration reconciliation with 1.1, full backend/frontend/E2E
acceptance and installed Windows GUI/MSI-CAB checks remain outstanding.
**1.2 NOT RELEASE-READY; 1.3 not started.**


## 2026-10-28 Track B — strict typing repair for ecological evidence replay

Pre-edit exact-head CI at `0f1601008fd350261b38f03aa6e0ed7c16c0bb19`
completed **16/19** PR-triggered workflows. CI, Pose Workflow Validation,
and ReefVision 1.0 Acceptance failed at strict mypy, not Ruff. The backend
reported **17 typing errors** in `schemas/ecology_identity.py`, all caused
by reused function-scoped loop variables across annotation, calibration,
identity-history, image-evidence, and historical-parent audit collections.
Ruff lint and formatting had already passed on that head.

The registry validator now uses distinct, semantically named local variables
for calibration links, identity revisions, image links, and historical parent
findings. The validated relationships, snapshot digests, design warnings,
scientist-review gates, legacy handling and Workflow Builder artifact contract
are unchanged. This is a strict typing / CI unblock, not a claim of new
scientific verification or a release-ready transition. Existing standalone
registry and saved executable `ecology_identity_registry_source` regressions
remain the behavioral acceptance tests; the exact-head mypy/CI run is the
static regression gate. Await new-head CI results and continue real-source
review, longitudinal measurement verification, migration reconciliation with
1.1 and installed Windows GUI acceptance. **1.2 NOT RELEASE-READY; 1.3 not
started.**


## Saved Workflow Builder connected-branch proposal (2026-10-28; development only)

The read-only saved-skeleton branch-preview API is also exposed as the executable
`ecology_connected_branch_preview` Workflow Builder node. Its typed project
input and `connected_branch_preview` output require a saved analysis ID,
explicit edit ID and integer source-image pixel path. Execution reuses the
standalone preview's latest-revision, checksum, topology, attachment and
image-bound checks. It refuses foreign-project source images and unsupported
parameters. The persisted artifact includes project ID, source analysis ID,
source result SHA-256, exact proposed node/edge geometry, pixel-only lengths,
`proposal_unverified`, `scientist_review_required` and explicit false
flags for persistence and physical-length calculation. It cannot feed
verified-dataset ports. Saved-workflow acceptance exercises API parity,
read-only behavior, foreign-project refusal and forged verification claims.
This is **not** a reviewed or persisted biological branch measurement.
Calibrated per-segment identity, explicit acceptance, scientific source review,
and representative installed-Windows validation remain outstanding.

The same iteration corrects two exact Ruff E501 line-length errors in the
ecological identity schema observed in the previous CI backend jobs.
New-head CI is required; source changes and committed tests are not test passes.


## 2026-10-28 Track B — connected-branch source graph continuity and typing

**Pre-edit audit:** `main` remained at `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`;
1.2 draft PR #74 was open at `a69378a277b622be5456883b1adb2818159b92e3`.
All 19 prior-head Actions completed: 16 successful and three backend failures.
CI, Pose Workflow Validation and ReefVision 1.0 Acceptance each failed strict
mypy on exactly two errors in `services/connected_branch_editing.py`:
a `Sequence` passed to a list/tuple-only length helper and a nullable root
assigned to a variable inferred as non-null from the initial-graph path.
The fix materializes a tuple for the length helper and gives initial-graph
nodes distinct local names; no graph measurements or verification status change.

**Scientific integrity:** The existing read-only branch-preview kernel now
rejects a source graph edge whose stored pixel path contains a nonadjacent
step or whose first/last pixel is not in the claimed source/target node.
Previously, a forged but internally length-consistent edge could conceal a
missing skeleton pixel or misattribute graph attachment, compromising connected
branch and total-length interpretation. Two focused regressions construct
length-consistent forged source edges and require fail-closed behavior.
Valid initial, endpoint, junction, and interior-attachment previews retain
existing behavior. The standalone saved-skeleton API and executable persisted
`ecology_connected_branch_preview` Workflow Builder node share the same
service and source-bound provenance, remain `proposal_unverified`, and require
scientist review. Existing API/saved-workflow acceptance tests are the
integration regression gate; no separate duplicate workflow node is added.

**Validation boundary:** The code and regression tests were committed to the
isolated 1.2 branch. Full local checkout, mypy, Ruff and runtime pytest were
not available in the execution environment; exact-head GitHub Actions must
confirm the fixes. No source-backed calibrated per-branch measurement, approved
biological identity, verified experimental design, or real longitudinal growth
claim follows from these previews. Migration reconciliation with 1.1 and
installed Windows GUI/MSI scientific acceptance remain required.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Source graph path uniqueness and cycle consistency (2026-10-28)

Connected coral branch previews now reject source segments that revisit an
interior pixel, even when their stored length matches the inflated walk.
The source graph also rejects a cycle flag that disagrees with its endpoint
node identities. Legitimate closed cycles may repeat their start pixel exactly
at the end; the non-destructive preview and source-length preservation remain
supported. These checks run in the shared standalone API and executable,
persisted `ecology_connected_branch_preview` Workflow Builder path, without
promoting unreviewed geometry into verified measurements. Focused regression
tests cover forged lengths, false cycle flags and valid closed loops.

This increment also corrects the previous exact-head Ruff E501 failure at
`connected_branch_editing.py:122`. The prior head `4ae68de8` had 16/19
successful Actions workflows; the other three failed at Ruff. New-head CI,
reviewed calibrated measurements, 1.1 migration reconciliation, and native
Windows installer/GUI acceptance remain release gates.


## Source graph pixel-step uniqueness (2026-10-28)

The standalone connected-branch preview and the existing executable, persisted
`ecology_connected_branch_preview` Workflow Builder node share a fail-closed
source-graph check: two segments may meet at a node pixel, but cannot traverse
the same undirected skeleton pixel step. Duplicate forward or reversed steps
would otherwise inflate total branch length despite individually valid segment
checksums. The check is limited to source-graph QC; it does not establish
biological branch identity, calibrated physical length or verified observations.
Regression tests cover both segment orientations, and existing saved-workflow
parity/review-gate tests remain applicable. Exact-head CI and Windows scientific
acceptance are still required; this is not a release-ready declaration.

## CI regression recovery — signed evidence and report contracts (2026-10-28)

The exact-head 1.2 backend suite exposed stale tests after the 0021 candidate
fingerprint, b12_identity_0005 migration, and fail-closed signed-evidence checks.
The regression fixtures now sign report algorithm identifiers, use authentic
empty-identity digests, preserve historical unverified artifacts only when
modern history-dependent audit claims are absent, and expect early rejection
of contradictory sampling levels or altered source hashes. These are test
contract repairs, **not** relaxation of scientific validation or proof of
Windows/biological acceptance. CI and saved-workflow parity must be checked
again on the resulting commit before advancing release readiness.

## Source-graph pixel provenance and CI recovery (2026-10-28)

The existing connected-branch preview now fails closed on negative or otherwise
non-integer source node/segment pixels, missing node pixel provenance, and
ambiguous duplicate pixel ownership across graph nodes. These safeguards run
through the same shared service used by standalone previews and the executable,
persisted `ecology_connected_branch_preview` Workflow Builder node; they do not
change verified datasets, calibration or accepted measurements. Focused tests
cover negative source pixels and duplicate node ownership, alongside existing
saved-workflow parity/review-gate acceptance. The preceding exact-head CI
completed 16/19 workflows; all three failures were the same Ruff RUF043
regex-literal diagnostic in a test, now corrected without weakening its
assertion. Latest-head CI, scientist review and Windows GUI acceptance remain
required; this increment is not release-ready.

## Population CSV parent-lineage review and CI regression (2026-10-28)

The exact-head 1.2 CI at `c2c1b55a` completed 17/19 workflows
successfully; both backend failures were one test expecting a missing-parent
roster mutation to be rejected even though the supplied value already matched
the fixture's true `["tank-A"]` disclosure. The regression now forges
actually different missing-parent rosters, preserves a positive control for
real missing-parent evidence, and requires the existing recomputation guard
to reject re-signed contradictory population summaries. The population CSV
writer additionally rejects malformed or duplicated independent-unit rosters,
missing-parent unit IDs outside the declared roster, and missing/independence
review-blocker inconsistencies at the serialization boundary. Focused tests
cover these defenses; standalone and persisted saved-workflow export use the
same renderer. All outputs remain `linked_unverified` with scientist review
required; neither true independence nor verified parentage is claimed.

This is a bounded scientific-integrity and CI-recovery change. New-head CI,
reviewed longitudinal calibration/identity, 1.1 migration reconciliation,
and physical Windows installer/GUI acceptance remain required. Version 1.2
is **not release-ready**; version 1.3 has not started.

## Declared-unit CSV serialization safeguards (2026-10-28)

The existing standalone ecological population CSV and executable saved
`ecology_population_csv_export` Workflow Builder node now independently
validate the serialized **declared-unit** roster and eligibility gate, in
addition to source-level recomputation. A candidate row must retain exactly
one identified declared unit, at least one contributing organism and an
absolute-change value. An excluded row cannot carry contributing organisms,
unit votes or endpoint means. Unit identifiers in JSON must match the
spreadsheet-safe identifier column, and the explicit
`independence_not_authenticated` review blocker cannot be removed or
replaced. Seven parametrized serializer-corruption cases cover these
failure modes, while existing standalone/API and persisted saved-workflow
parity tests protect legitimate candidate and excluded rows.

This is a serialization integrity check, **not** independent authentication
of tank/colony assignment, reviewed identity or calibration. Evidence remains
`linked_unverified`, inference is forbidden, and scientist review is required.
CI, longitudinal source authentication, migration reconciliation and physical
Windows acceptance remain release blockers.

## Population CSV parent-colony disclosure integrity (2026-10-28)

The standalone ecological population CSV renderer and executable, persisted
`ecology_population_csv_export` Workflow Builder node now reject a forged
parent-colony roster at the final serialization boundary. Parent identifiers
must be unique, nonblank strings; shared-parent identifiers must be unique
members of the disclosed parent roster. Duplicate, blank or non-string
scientific-review blockers are also rejected. Six parametrized regression
cases cover malformed/duplicated parent IDs, an undisclosed shared parent,
duplicate shared-parent IDs and duplicate review warnings. The existing
standalone/API and saved-workflow parity acceptance remains applicable.

This run also applies the exact Ruff formatting change reported by the
preceding 1.2 head `4162f739` (16/19 successful Actions; three backend
format failures). The new commits have not passed exact-head CI at the
time of implementation. These are serialization integrity checks, **not**
authenticated parentage, independent experimental replicates, reviewed
calibrated growth or release acceptance. The 1.1 migration divergence,
scientist review, real-data acceptance and physical Windows GUI/MSI checks
remain blockers. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Population CSV shared-parent and dispersion integrity (2026-10-28)

Exact-head CI at `de12122e` passed 17 of 19 workflows; both
backend failures were the same test expectation mismatch. A forged candidate
unit count of zero correctly triggers the earlier declared-unit denominator
validation, rather than the later candidate-specific check. The regression now
expects that fail-closed error; production denominator checks are unchanged.

The existing standalone population CSV renderer and executable, persisted
`ecology_population_csv_export` Workflow Builder node now also independently
reject a shared-parent roster without its required pseudoreplication review
blocker (or a spurious blocker without shared parents). A shared parent cannot
be reported across fewer than two declared units. Sample standard deviations
must remain absent for one unit and finite, nonnegative values for two or more
units; a CSV serializer cannot invent a variance estimate for one tank or hide
an expected estimate for multiple tanks. Six parametrized corruption cases
cover these guards, alongside the existing standalone/API and saved-workflow
parity tests. This is a final-serialization defense, not independent validation
of parentage, organism identity, calibration, or statistical inference.

New-head CI, real scientist-reviewed longitudinal evidence, migration
reconciliation with 1.1 and installed Windows GUI/MSI acceptance remain
outstanding. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Population CSV stratum identity and dimensions (2026-10-28)

The shared standalone and executable, persisted Workflow Builder population
CSV renderer now independently rejects population rows that masquerade as a
candidate unit, acquire a single-unit ID, or serialize missing/multiple/blank
physical units or UTC sampling-window labels. Eligible population strata
retain exactly one physical unit and one sampling-window label. This is an
export-boundary integrity check in addition to the existing source-fingerprint,
source-recomputation and experimental-unit review gates; it does **not**
authenticate biological independence, convert candidates to verified data,
or imply inference. Eight parametrized corruption cases and saved-workflow
CSV assertions cover the contract. The preceding exact-head Ruff format
failure at `ecology_population_export.py:207` was also corrected.

Validation of this new commit remains pending until exact-head CI completes;
no local Ruff/pytest or physical Windows installed-GUI acceptance was run.


## Paired-count biological denominator and image-weighting audit (2026-10-28)

The existing standalone paired human–model comparison and executable, saved
`ecology_paired_count_comparison` Workflow Builder node now expose the number
of **distinct caller-declared organisms** separately from the number of paired
images. A deterministic per-organism pair-frequency roster, number of pairs
beyond each organism's first, and unequal-frequency QC flags are available at
the overall and declared-unit levels. These diagnostics reveal when repeated
images could dominate a pair-weighted mean; existing nested organism/unit
balanced means remain unchanged. A repeat pair is not assumed to be a new
biological replicate or a confirmed technical replicate: acquisition times,
identity and true experimental independence remain unauthenticated.

The output/provenance contract advances to `ecology-paired-count-0004`;
older persisted artifacts retain their original algorithm and remain readable
through additive defaulted fields. Focused domain, standalone API and saved
Workflow Builder tests cover unequal and equal image frequencies, biological
sample denominators, deterministic provenance, and persisted artifact parity.
Full exact-head CI, authenticated sources, real-data scientific acceptance,
1.1 migration reconciliation and installed Windows GUI/MSI acceptance remain
outstanding. No inferential sample-size or model-agreement validity is claimed.

## Paired-count CI recovery checkpoint (2026-10-28)

The prior paired-count denominator audit at `c4601804` completed 15 of 19
GitHub Actions workflows successfully, with one workflow still running at
inspection. The three failed backend workflows (CI, Pose Workflow Validation,
and ReefVision 1.0 Acceptance) all stopped at Ruff formatting before pytest.
This checkpoint applies the five exact Ruff 0.17.3 formatter replacements
reported by CI in the existing domain, scientific regression and saved-workflow
test files; it does not alter biological calculations, source-review boundaries,
or experimental-unit weighting. Full latest-head CI, authenticated calibration
and longitudinal identities, migration reconciliation and installed Windows
GUI/MSI acceptance are still required. **1.2 NOT RELEASE-READY.**

## Paired-count exact-head CI regression and shared-parent workflow parity (2026-10-28)

The exact-head GitHub Actions CI and ReefVision 1.0 Acceptance backend jobs at
`2d4e677e` each completed 2,005 passing tests, 32 skips and **one failed
assertion**: a legacy standalone parent-lineage test still expected
`ecology-paired-count-0003` after the biological-denominator contract had
intentionally advanced to `ecology-paired-count-0004`. Ruff check and format
passed before pytest. The assertion now checks the current provenance contract,
and the positive case explicitly verifies disclosure of a parent colony shared
between two separately declared tank experimental units.

A new executable saved-Workflow-Builder regression checks the same
shared-parent/two-tank design from plan through persisted typed artifact. It
requires the shared-parent disclosure, two distinct declared tank units,
one organism per unit, mandatory unverified evidence and source-review gate,
and parity with the standalone API for provenance and nested summaries.
These checks do not establish true tank independence or verify parent identity.
They do not change the production statistical algorithm.

The new head awaits its own CI verification; local full-repository checkout is
blocked by GitHub DNS resolution. Real authenticated calibrated longitudinal
measurements, 1.1 migration reconciliation, scientist review, and physical
Windows GUI/MSI acceptance remain outstanding. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Cross-tank organism identity saved-workflow regression (2026-10-28)

Exact-head Actions for `905e5b8b` completed **16 of 19 workflows successfully**.
The three failed backend workflows (CI, Pose Workflow Validation, ReefVision
1.0 Acceptance) stopped at the same Ruff formatter error: an extra blank line
before `test_saved_workflow_discloses_shared_parent_across_tanks` in
`test_ecology_lineage_workflow_1_2.py:107`. The formatter issue is corrected.

A new negative executable saved-workflow regression uses two paired images of
the **same organism** but falsely assigns them to different tank experimental
units. Both standalone API and saved Workflow Builder execution must reject
this pseudoreplicate, the workflow run must fail, and no
`paired_count_comparison` artifact may persist. The positive saved-workflow
case additionally checks distinct tank IDs, organism denominator, paired-image
denominator and absence of repeat-image inflation while disclosing a shared
parent colony. No verified parentage or independence is inferred.

The source file was read back after the correction; no full local pytest/Ruff
run was possible because the environment cannot clone GitHub and Ruff is not
installed. New-head CI is required before crediting passing tests. Authenticated
calibrated longitudinal source review, 1.1 migration reconciliation and
physical Windows installer/GUI acceptance remain outstanding.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Directional human–model percentage bias (2026-10-29)

The existing paired-count standalone API and executable saved Workflow Builder
node now report **signed percentage bias** (100 × [model − human] / human)
alongside the existing absolute percentage deviation. Positive values mean
model overcount and negative values mean undercount; zero human-reference
counts are excluded from *both* percentage denominators, never from signed
count bias or absolute error. Pair-weighted, declared-unit-weighted, and
organism-then-unit-weighted signed percentages are reported separately.
Repeated images cannot silently masquerade as independent organisms or tanks.
All values remain `caller_supplied_unverified`, with explicit source-review
gates and no inferential significance or verified reference consensus.
The provenance algorithm advances to `ecology-paired-count-0005`; new
response fields are optional when reading older persisted comparison artifacts.
Domain, standalone API, and saved Workflow Builder tests assert direction,
zero-reference handling, nested weighting and provenance parity. Full CI and
Windows/scientific acceptance remain required.

## Paired human–model direction-frequency audit and Ruff recovery (2026-10-29)

The previous exact-head `e790bf2b` passed 16 of 19 Actions workflows.
The three backend failures all stopped at Ruff formatting before pytest;
CI identified two files: `model_agreement.py` and
`test_model_agreement_1_2.py`. This increment applies the exact reported
formatter corrections without changing signed percentage arithmetic.

The standalone paired-count endpoint and executable, saved
`ecology_paired_count_comparison` Workflow Builder node now persist
**overcount, undercount and exact-match paired-image frequencies**, both
across the entire comparison and within each declared experimental unit.
Zero-reference observations still contribute to these signed-count categories
and absolute error, but not to percentage-bias denominators. Repeated images
are counted as pairs, **never** as independent biological replicates; the
existing distinct-organism, unit and repeated-image denominators remain
separate. No confidence intervals, ICC, p-values or verified reference claims
are introduced. New fields default to zero when parsing older saved artifacts;
new analyses use provenance algorithm `ecology-paired-count-0006`.

Focused scientific regression cases cover all three directions, zero-human
reference, repeated organisms and per-tank counts. Standalone API and saved
Workflow Builder acceptance check persistence and output parity. All sources
remain `caller_supplied_unverified` with mandatory researcher review.
Exact new-head CI, authenticated calibrated longitudinal source records,
1.1 migration reconciliation, real-data scientific review and installed
Windows GUI/MSI acceptance remain required. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Paired-count exact-head CI provenance regression (2026-10-29)

Pre-edit exact-head `14e63d7e` Actions completed **17/19** successfully.
The CI and ReefVision 1.0 Acceptance backend jobs each completed their test
suites except for the same stale lineage acceptance assertion at
`test_ecology_lineage_workflow_1_2.py:128`: the test expected the historical
`ecology-paired-count-0004` identifier, but the implemented and independently
regressed directional-frequency algorithm correctly emits `0006`. Ruff,
strict typing, the frontend job and the separate Pose Workflow Validation
workflow passed at that head. The lineage regression now expects `0006` and
checks that two tank units sharing a declared parent preserve two biological
units, opposite signed count directions, both nonzero-reference percentage
contributors, zero balanced signed-percent bias and standalone/persisted
Workflow Builder artifact parity. This is a regression/acceptance repair,
not a change to production statistics or source verification.

No full local checkout was possible (GitHub DNS resolution failed); no new-head
pytest, Ruff, mypy, migration, Windows installed-GUI or MSI/CAB acceptance
passes are claimed before their actual execution. Reviewed source-backed
longitudinal calibration, organism identity, study-design independence and
1.1 Alembic-head reconciliation remain release blockers.
**1.2 NOT RELEASE-READY; 1.3 not started.**


## Paired-count organism-direction QC (2026-10-29)

The existing standalone human–model comparison and executable, persisted
`ecology_paired_count_comparison` Workflow Builder node now report overcount,
undercount and zero-mean direction **per caller-declared organism** in addition
to existing per-image directional frequencies. Each organism receives one vote
from the arithmetic mean of its signed paired-image differences; repeated
images cannot inflate the number of organism votes. A zero-mean organism may
contain cancelling over- and undercounts, and is deliberately named
`balanced_organism_count`, not an exact-match organism. Per-tank organism
votes and global organism votes are descriptive, not verified independent
experimental replicates. All outputs remain caller-supplied/unverified and
cannot flow into verified datasets through Workflow Builder.

The additive typed fields default to zero when older persisted artifacts are
read. New computations use provenance `ecology-paired-count-0007`; older
artifacts retain their historical algorithm identifiers. Domain regression
tests exercise cancelling errors, repeated-image denominators, nested tank
votes and legacy decoding. Standalone API and saved executable workflow tests
check persisted typed artifacts and parity. Prior head `739953939` passed
19/19 GitHub Actions workflows; the new head requires its own CI validation.
Scientist-reviewed calibrated longitudinal evidence, 1.1 migration
reconciliation, representative real-data review and physical Windows
installer/GUI acceptance remain outstanding. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Paired-count exact-head CI recovery and persisted directional denominators (2026-10-29)

The prior `75048416` head completed 17/19 Actions workflows successfully.
Both failed backend suites executed 2,009 passing tests, 32 skips and two
assertion failures: older test expectations still required algorithm `0006`
although the organism-direction implementation intentionally emits `0007`.
The two assertions now expect the current provenance contract.

The versioned typed paired-count result schema now rejects a forged
`0007` artifact if overcount/undercount/exact image counts do not add up to
the paired-image denominator, if organism-direction votes do not add up to
distinct caller-declared organisms, or if per-unit directional and biological
denominators disagree with the overall record. This protects saved Workflow
Builder artifacts against inflated image/organism sample sizes without
mistaking balanced mean organism error for exact image matches. Older
algorithm artifacts retain their additive-default decoding compatibility.

Four parametrized schema-integrity regression cases cover corrupted global
and per-unit counts. The saved executable workflow acceptance now includes
one organism with opposing errors that cancel, demonstrating that a balanced
organism is not an exact-match image. Shared-parent/two-tank saved-workflow
acceptance checks the current algorithm and organism-vote parity. No new
inference, authenticated parentage, or independent-replicate claim is made.

Latest-head CI must pass before counting these changes as validated; local
full-repository pytest/Ruff remain blocked by GitHub DNS resolution. Reviewed
calibrated longitudinal measurements, the 1.1 migration divergence and
physical Windows GUI/MSI acceptance remain blockers. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Persisted paired-count row-integrity and CI recovery (2026-10-29)

Pre-edit exact-head `c6d5ffe61e` completed **16 of 19** GitHub Actions
workflows successfully. CI, Pose Workflow Validation and ReefVision 1.0
Acceptance backend jobs failed at Ruff 0.17.3 formatting, before pytest.
The formatter required two condensed pair-count expressions in
`schemas/model_agreement.py` and a one-line parametrized test signature in
`tests/test_model_agreement_1_2.py`; these were corrected without changing
the descriptive paired-count algorithm.

The version `ecology-paired-count-0007` typed result now additionally
reconciles saved image-direction frequencies with actual signed paired rows,
organism frequency/duplicate-image denominators with those rows, and zero
versus nonzero human-reference denominators with those rows. Merely making
over/under/exact counts add up is insufficient: an altered direction label
must fail validation. Four parametrized regression cases cover swapped
direction counts, fabricated organism frequencies, forged percentage
eligibility and dropped paired rows. The preexisting standalone API and
executable saved Workflow Builder use this same typed result; their existing
source-review gates, persisted-artifact tests, and unverified provenance
remain unchanged. No new verified scientific observations or experimental
replicates are inferred. Older algorithm artifacts retain compatibility.

Full exact-new-head CI, authenticated longitudinal calibration/organism
identity, independent-unit verification, 1.1 migration reconciliation,
representative scientific review, and physical Windows installed GUI/MSI
acceptance remain required. This iteration could not execute local
repository pytest/Ruff because the environment cannot resolve GitHub
for checkout and has no installed Ruff. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Paired-count saved-artifact arithmetic and unit-roster integrity (2026-10-29)

Previous exact-head `87c35f67` CI completed **16/19** workflows
successfully. CI, Pose Workflow Validation and ReefVision 1.0 Acceptance
backend jobs all failed before pytest at the same Ruff 0.17.3 formatting
location in `schemas/model_agreement.py`; the exact formatter-required
expression is corrected.

The existing version `ecology-paired-count-0007` typed response now
fails closed when persisted paired rows contradict raw human/model counts,
absolute error, signed/absolute percentage, or zero-reference eligibility.
For declared experimental units it also rejects duplicate unit IDs,
organisms counted across multiple units, fabricated within-unit image
frequencies/repeats/imbalance, and inconsistent nested percentage-eligible
denominators. These are internal consistency checks, **not** evidence
authentication or cryptographic verification. Historical pre-0007 artifacts
retain their previous decoding path. The existing standalone API and
executable saved Workflow Builder share the result schema and mandatory
`caller_supplied_unverified` / source-review gate.

Fourteen parametrized negative scientific regressions and an executable
saved-workflow artifact-tampering/parity check were added. Full new-head
CI, authenticated calibrated longitudinal sources, experimental-design
review, 1.1 migration reconciliation and physical Windows installer/GUI
acceptance remain mandatory. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Saved paired-count aggregate integrity (2026-10-29)

The current `ecology-paired-count-0007` typed result contract now recomputes
pair-weighted signed bias, absolute error and percentage means directly from
persisted paired differences. It also reconciles unit-balanced and nested
organism/unit means with the persisted unit summaries. Missing eligible
reference counts must remain null, not an invented zero percentage, and
nonzero-reference rows must retain signed percentage deviation. Fourteen
focused scientific tamper cases and saved executable Workflow Builder artifact
acceptance cover these checks; the standalone API shares the same result
schema. These consistency checks **do not** authenticate source records,
registered units, biological identity or human consensus. Previous algorithm
versions remain readable. CI and Windows scientific/GUI acceptance remain
required before release.

## Per-tank paired-count evidence reconciliation (2026-10-29)

Pre-edit exact head `5dbe713c51f55f16dee269f68d867643852f9457`
completed 16/19 GitHub Actions workflows successfully. All three backend
failures stopped at the same Ruff formatting discrepancy (a missing blank
line at `schemas/model_agreement.py:335`), before running pytest. The
formatting issue was corrected.

For current `ecology-paired-count-0007` persisted results, the existing
typed comparison contract now independently reconstructs each declared
tank's paired-image directions, organism-mean directional votes, eight
pair/organism-balanced signed/absolute statistics, and percentage-eligible
denominators from the organisms assigned to that tank. It also verifies
global organism-direction votes and unequal repeated-image flags against
the underlying paired rows. Altering a tank mean and its grand mean
together, or swapping two tanks' directional labels while preserving
global totals, must fail validation. The existing standalone endpoint
and saved executable `ecology_paired_count_comparison` Workflow Builder
share this typed contract, and a saved-workflow tampering regression
exercises it. Twelve new focused negative regression variants cover
unit means, directional vote swaps, ungrouped organism votes and repeated
image imbalance.

These are **internal arithmetic and roster consistency checks only**:
caller-declared organism IDs, tank IDs, human reference counts and
calibration are still unverified. No inferential independence, validated
parentage, new statistical significance or verified biological evidence
is claimed. Older algorithm artifacts retain their previous decoding
contract. Full exact-head CI, authenticated longitudinal measurement
review, migration reconciliation with 1.1, real-data scientific review
and physical Windows GUI/MSI acceptance remain required.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Exact JSON count precision and CI recovery (2026-10-29)

The prior exact-head `529271eabeaa5f3303d2319a534449bc88472f86`
completed 16/19 GitHub Actions workflows successfully. All three failed
backend workflows stopped at Ruff formatting before pytest; this increment
applies the exact formatter-reported changes to the paired-count schema and
scientific regression test, without changing the comparison arithmetic.

The paired-count input schema additionally rejects **JSON integer** human/model
counts above the IEEE-754 safe-integer maximum (2^53 - 1). The schema stores
counts as floating-point values; an integer such as 2^53 + 1 otherwise rounds
to 2^53 before whole-number validation, silently altering a scientific source
count. This narrowly protects exact JSON integer input and does **not** claim
that arbitrary floating-point counts are exact or authenticated. The existing
standalone endpoint and typed executable Workflow Builder share this contract.
Focused tests cover both reference/model inputs, the largest safe integer,
standalone HTTP 422, and failed saved-workflow execution without a successful
comparison artifact. All evidence remains `caller_supplied_unverified`, with
researcher review required and no changes to model weights, migrations or
experimental-unit definitions.

Exact new-head CI, authenticated calibrated longitudinal observations,
1.1 migration reconciliation, real-dataset scientific review and installed
Windows MSI/GUI acceptance remain outstanding. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Persisted paired-source identity and whole-count integrity (2026-10-29)

The current `ecology-paired-count-0007` typed result now rechecks that saved
paired observation IDs, human-reference source IDs, and model source IDs are
individually unique and that reference/model source sets do not overlap.
It also rejects fractional raw organism counts in reloaded result rows, even
when paired differences, percentages, direction counts, and summary means
have been adjusted to remain internally consistent. These are result
read-back checks, complementary to existing standalone request validation;
older versioned artifacts retain their prior compatibility policy.

Scientific regression cases cover repeated image/source IDs, cross-role source
reuse and fractional exact-match pairs. Executable saved Workflow Builder
acceptance rejects a source-ID-tampered persisted artifact without changing
typed ports, provenance, or the `caller_supplied_unverified` review gate.
The prior exact-head CI identified a Ruff formatter discrepancy in the
strict-input regression test, which is corrected here. No evidence is
promoted to verified status; authenticated source linkage, registered
experimental designs, calibration review, migration reconciliation, and
native Windows acceptance remain required.

## Float-count precision guard and saved-result integrity (2026-10-29)

Exploratory paired human/model counts now reject **both JSON integers and
integral JSON floats** above the IEEE-754 safe-integer maximum (2^53 - 1).
The prior integer-only guard allowed an integral-looking float above that
limit, where consecutive organism counts cannot be reliably distinguished.
Current-version persisted `ecology-paired-count-0007` artifacts enforce the
same raw-count limit on read-back, including typed Workflow Builder results.
The largest safe integer remains permitted as an integer or integral float.
Standalone API, saved-workflow failure/no-successful-artifact, and persisted
artifact tamper regressions cover the boundary. Historical versioned
artifacts retain their existing compatibility path. This numerical safeguard
does not authenticate biological counts, calibration, experimental units or
source reviews; evidence remains `caller_supplied_unverified`. Full CI,
scientific dataset review and Windows installed-GUI acceptance are pending.

## Reproducible paired human–model CSV and executable export (2026-10-29)

A new standalone POST `/api/v1/ecology/paired-count-comparison/report.csv`
and typed executable Workflow Builder `ecology_paired_count_csv_export`
consume the same descriptive comparison contract. The workflow node accepts
`paired_count_comparison` and persists `paired_count_comparison_csv` with
CSV SHA-256, canonical input fingerprint, source IDs, project binding and
explicit unverified evidence/review restrictions. Both export paired-image
rows, declared-unit summaries and one overall descriptive summary, without
turning repeated photographs into independent biological samples. Null
zero-reference percentages remain blank; identifiers are spreadsheet-formula
escaped. Saved artifacts are revalidated against their source-row arithmetic
and provenance source roster before CSV creation. Historical result contracts
are not silently promoted to the current export contract.

Standalone API and saved-workflow acceptance tests cover deterministic
input-order parity, CSV denominators, formula safety, project binding,
provenance, persisted output and refusal of verified-dataset port wiring.
The prior head `cd5d1924` passed 16/19 workflows; three backend jobs
stopped at a Ruff blank-line formatting error, corrected in this increment.
This export remains **caller-supplied/unverified** and is not a substitute
for authenticated annotations, calibrated longitudinal evidence, registered
independent experimental units, ICC/Bland–Altman, or scientist review.
Exact-head CI, migration reconciliation with 1.1, representative data and
native Windows GUI/MSI acceptance remain required. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Per-organism descriptive CSV rows and formatter recovery (2026-10-29)

The prior exact-head `51cb56ea53a8b9f2c2609a3df340fc7fbfacc8ff`
completed 15/19 GitHub Actions workflows successfully. CI, Pose Workflow
Validation, ReefVision 1.0 Acceptance and Milestone 10 Acceptance stopped at
Ruff formatting before executing their backend scientific tests. Applied the
formatter's exact four-file corrections.

Paired human–model CSV export `ecology-paired-count-csv-0002` now adds one
**organism_descriptive** row per distinct organism, with within-organism
signed bias, absolute error, eligible percent-deviation denominators, repeated
image counts and stable source-observation identifiers. Pair-level, declared
experimental-unit and overall rows remain, and deterministic ordering is
preserved. Each CSV row explicitly states `independent_inference_allowed=false`:
repeated photographs and caller-declared organisms/tanks are **not** verified
independent replicates. The standalone endpoint and existing typed, executable
saved Workflow Builder CSV node use the same renderer and provenance/review
restrictions. Regression coverage includes repeated images, zero-reference
percent exclusion, spreadsheet formula safety, standalone/workflow parity,
and the unverified-inference warning. No source is promoted to verified.

Full exact-new-head CI, authenticated longitudinal calibration/identity,
1.1 migration reconciliation, real-data scientific review and physical
Windows GUI/MSI acceptance remain outstanding. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Workflow Builder CSV type-contract recovery (2026-10-29)

Pre-edit exact head `a100d79558d24c5a7ae3e718051009cab737700c`
completed **15/19** GitHub Actions workflows successfully. Three backend
workflows stopped at a Ruff 0.17.3 CSV list-comprehension formatting error.
Milestone 10 Acceptance additionally reported **22 failed, 21 passed**:
`ecology_paired_count_csv_export` advertised
`paired_count_comparison_csv`, but `WorkflowDataType` omitted that literal,
causing Pydantic validation to fail during node-registry construction and
breaking unrelated saved workflow tests.

The typed workflow data-type union now explicitly includes the unverified
paired-count CSV artifact. The exporter follows the exact CI-reported Ruff
formatting requirement. A focused regression asserts the CSV type is declared
and can be constructed as a Pydantic workflow port; existing standalone API,
saved executable graph, persistence, CSV parity and verified-dataset port
rejection tests remain the full integration acceptance contract. The new
port is **not** a verified annotation/dataset type, and its existing
`caller_supplied_unverified` provenance and review restrictions remain.

An isolated Pydantic literal-port smoke test passed, **not** a full repository
pytest/Ruff run. Exact-head CI, authenticated longitudinal calibration and
organism identity, experimental-design review, 1.1 migration reconciliation,
representative biological data and installed Windows GUI/MSI acceptance are
still required. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Paired-count CSV explicit biological weighting (2026-10-29)

The exact predecessor `d1dbc8c4a4935792d5d4913c74390531e85fbab5`
passed **16/19** GitHub Actions workflows, including Milestone 10
Acceptance and Windows desktop build. Three backend checks failed solely
at Ruff import sorting in `test_ecology_paired_count_csv_1_2.py`; the
CI-reported import ordering is corrected here.

Export contract `ecology-paired-count-csv-0003` now exposes the
existing organism-balanced, declared-unit-balanced and nested
organism-within-unit-balanced signed bias, absolute error and percentage
deviation as **separate named CSV columns**. It also exposes eligible
organism/unit percentage denominators. A unit row reports organism-balanced
statistics; the overall row reports unit-balanced and nested statistics.
Pair-weighted descriptive means remain labeled separately. Missing
experimental-unit registration yields blank unit-balanced estimates,
never an invented independent sample size. These are descriptive estimates,
not ICC, hypothesis tests, authenticated replication or verified measurements.

Standalone CSV and the typed executable saved Workflow Builder CSV artifact
share the same renderer and updated schema version. A new unequal-image
fixture demonstrates that pair-, unit- and nested-balanced means diverge,
checks denominator integrity, and verifies the unregistered-unit case.
Existing saved-workflow CSV SHA-256, provenance, unverified review gate,
source-identity protection and standalone parity tests remain in force.

Integrated exact-head CI, migration reconciliation with 1.1, source-authenticated
calibrated longitudinal measurements, biological review and physical Windows
GUI/MSI acceptance are still required. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Explicit directional votes in descriptive paired-count CSV (2026-10-29)

Export contract `ecology-paired-count-csv-0004` now exposes distinct
**paired-image** overcount/undercount/exact-match frequencies and
**organism-mean** overcount/undercount/balanced frequencies in separate
CSV columns. Organism, declared-unit and overall rows disclose their
appropriate counts; unit/overall rows also expose repeated photographs
beyond the first per organism. An organism with opposing image errors
can have a balanced mean without any exact-match image, and the export
now makes that distinction directly inspectable without parsing nested
JSON. All directional values come from the existing validated typed
comparison result, not new inference or invented independent sample sizes.

A focused API regression exercises a balanced organism with opposite
signed image errors, a second undercounted organism, one declared tank,
and repeated photographs. The existing standalone and saved executable
Workflow Builder exporters share this renderer and retain the same
source fingerprint, typed ports, persisted SHA-256, unverified evidence
and researcher-review gate. The prior exact head `6c1b2b9c` completed
16/19 workflows successfully; three backend workflows failed Ruff
formatting before pytest. This increment also applies the two exact
CI-reported formatter corrections. Latest-head CI, authenticated
organism/calibration records, migration reconciliation, representative
scientific acceptance and installed Windows GUI/MSI checks remain pending.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Persisted paired-count provenance and denominator integrity (2026-10-29)

The existing `ecology-paired-count-0007` typed result validator now
reconciles its sorted human/model `analysis_provenance.source_record_ids`
with the actual persisted paired rows. A missing, fabricated or reordered
source roster fails read-back even when the numerical means and directional
votes remain unchanged. Comparisons with no declared independent units also
reject invented unit counts and percentage-eligible organism/unit denominators
instead of silently accepting biological replication that was never registered.
The same validator is used for standalone analysis results and saved executable
Workflow Builder comparison artifacts; no new node, migration or verification
claim is introduced. The paired-count source schema, `caller_supplied_unverified`
evidence level, review restrictions, and existing CSV export remain unchanged.

Regression coverage includes six malformed persisted-artifact scenarios and a
saved-workflow provenance tamper case. Corrected a shadowed `values` local
in the validator that caused **six mypy errors** on prior head
`452d68007c44021b24e9227c1c5bbd82598105a6` (16/19 Actions passed;
three backend workflows failed at type checking). These new changes require
exact-head CI confirmation; local full pytest/mypy/Ruff and physical Windows
installer/GUI acceptance are not yet verified. **1.2 remains NOT RELEASE-READY.**

## Persisted raw-count JSON type integrity and CI recovery (2026-10-29)

Pre-edit exact HEAD `a9229cec01b3d36276c286873eb6b057b8fa741b`
completed **16/19** GitHub Actions workflows. All three backend workflows
failed at the same Ruff 0.17.3 blank-line formatting requirement in
`test_model_agreement_1_2.py`, before scientific pytest ran; the formatter
location is corrected. A stale scientific test expecting `1e308` organism
counts conflicted with the existing IEEE-754 safe-integer contract; it now
checks the largest precisely representable permitted count instead.

For current `ecology-paired-count-0007` persisted results, raw human and
model counts must remain JSON numeric values at deserialization. A saved
Boolean or numeric string can otherwise be coerced by Pydantic to a float,
evading raw-evidence type integrity while preserving valid arithmetic and
unit-balanced summaries. The new pre-validation guard rejects that
coercion, with focused positive/historical compatibility, negative
scientific and saved executable Workflow Builder artifact regressions.
Older algorithm-version artifacts retain their existing read-back policy.
The standalone input schema already rejects these coerced types; no
new node, migration, model download or verified-dataset promotion is added.

These checks **do not authenticate** sources, biological identities,
calibration, independent units or human consensus. Exact-new-head CI,
1.1 migration reconciliation, representative verified longitudinal data,
scientist review and physical Windows installer/GUI acceptance remain
mandatory. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Canonical persisted paired-row identity and backend CI recovery (2026-10-29)

The previous exact HEAD `c81242e79b86413ba5af20495dc6227236237ab3`
completed 16/19 GitHub Actions workflows successfully. All three failed
backend workflows stopped at one Ruff 0.17.3 formatting discrepancy in
`test_workflow_model_agreement_1_2.py`; the exact formatter-requested
one-line list comprehension is applied.

The existing `ecology-paired-count-0007` result reader now requires
persisted paired rows to retain the producer's sorted observation order and
canonical nonblank, whitespace-trimmed observation, organism and human/model
source identifiers. Reordering rows can otherwise change reproducible CSV
output without changing summary arithmetic or the input SHA-256 fingerprint;
padding an observation ID can silently change its biological source identity.
The producer already sorts and trims these fields, so valid generated reports
retain their existing contract. Older algorithm-version artifacts retain
their prior read-back compatibility.

Focused scientific regression cases cover reordered rows and altered IDs,
and executable saved Workflow Builder artifact acceptance rejects a reordered
result. The unverified-evidence review gate, source-provenance checks,
experimental-unit safeguards and existing typed ports remain unchanged.
Full exact-head CI, verified longitudinal calibration/identity, registered
experimental designs, migration reconciliation, representative scientific
acceptance and physical Windows GUI/MSI tests remain required.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Exact-head backend CI recovery: executable CSV planner and schema parity (2026-10-29)

Pre-edit 1.2 HEAD `122f7d6a5833270b75e1db8bb54776690aae8f59`
completed 17/19 Actions workflows successfully. The two failing backend
workflows executed the full pytest suite (2,094 passed, 32 skipped) and
identified three regressions: a missing `ecology_paired_count_csv_export`
planner action, a stale test expecting the detailed source-roster message
instead of the deliberately generic integrity error, and a stale test
expecting `finite` rather than the current IEEE-754 safe-integer validation
message. The CSV workflow adapter also persisted schema `0003` while the
standalone CSV renderer and saved-workflow acceptance expected `0004`.

The planner now advertises the existing executable CSV node action. Both
standalone CSV rows and persisted workflow artifacts share one version
constant, `PAIRED_COUNT_CSV_SCHEMA_VERSION`, preventing future schema drift.
The two test assertions now reflect the actual fail-closed validation and
non-disclosing public error contract. The existing saved executable workflow
regression exercises typed ports, plan, persisted output, exact CSV parity,
source SHA-256 and rejection by verified-dataset ports. No new biological
claims, identity verification, calibration, model weights, migration or
cross-version changes are introduced.

These edits require **new-head CI** confirmation; repository pytest/Ruff
cannot run locally in this environment because GitHub DNS blocks checkout.
Authenticated longitudinal measurement, real study-design review, migration
reconciliation and physical installed Windows GUI/MSI acceptance remain
outstanding. **1.2 NOT RELEASE-READY; 1.3 not started.**


## Exact-head planner/adapter contract recovery (2026-10-29)

The preceding head `e39cdceb370a62f16ee6d2d8314a28dab89c649f`
completed 15/19 GitHub Actions workflows successfully. The four failing
workflows (CI, Pose Workflow Validation, ReefVision 1.0 Acceptance and
Milestone 10 Acceptance) all stopped on one Ruff formatting requirement
in the newly registered paired-count CSV Workflow Builder planner action.
The exact CI-reported formatting correction was applied.

The ecology planner regression is now **registry-driven** rather than
checking only the two original analysis nodes: every executable
`ecology_*` node must have a nonblank planner action, a runtime adapter,
typed input/output ports supported by `WorkflowDataType`, and a matching
registered definition. A second regression rejects orphaned ecology planner
actions or runtime adapters. This protects saved scientific workflows from
future registry/planner drift without adding duplicate 1.1 context features
or changing the existing source-unverified evidence and review gates.

This is a bounded integration repair, **not** authenticated calibrated
longitudinal measurement or validated independent replication. The new
head's backend/Workflow Builder CI results, 1.1 migration reconciliation,
representative biological review and physical Windows installer/GUI tests
must still be checked. **1.2 NOT RELEASE-READY; 1.3 not started.**


## Source-level measurement export: explicit four-layer lineage (2026-10-29)

Exact predecessor `01d6c1f69531cd81a9c6bb440c09a8584245049a`
completed **19/19 GitHub Actions workflows successfully** (including backend
CI, Milestone 10 and Windows desktop build). This is automated build evidence,
not installed Windows GUI or ecological scientist acceptance.

The existing standalone `/measurements.csv` endpoint and executable saved
`ecology_measurement_csv_export` Workflow Builder node now share
`MEASUREMENT_CSV_SCHEMA_VERSION` (`ecology-measurement-export-0002`). Each
projected measurement CSV row explicitly carries the registry-history,
source-image, reviewed-annotation and calibration-evidence SHA-256 fingerprints,
alongside the existing aggregate input/report digests and individual source IDs.
The saved typed workflow artifact also exposes the four lineage digests and
fingerprint contract. Both export surfaces explicitly set
`independent_unit_inference_allowed=false`; they do not upgrade
`linked_unverified` observations into verified growth or independent replicates.

Existing full source fingerprint/QC recomputation is reused, including rejection
of altered source values. Updated API and saved-workflow acceptance checks assert
all four lineage digests, schema parity, byte-identical CSV and review restrictions.
No migration, cloud access, model download or cross-version branch integration.
Exact-new-head CI, authenticated biological identity/calibration approval,
1.1 migration reconciliation, real scientific review and installed Windows
MSI/GUI tests remain release gates. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Four-layer source-digest disclosure in calibrated measurement exports (2026-10-30)

The existing standalone projected-measurement CSV and the executable, persisted
`ecology_measurement_csv_export` Workflow Builder node now expose
`four_layer_source_digests_present`. This flag is true only when the source
artifact has a fingerprint contract and all four registry-history, image,
annotation and calibration SHA-256 fields have valid hexadecimal shape.
It is **not** an assertion that any of those hashes match the current project
database, that a scientist verified organism identity or geometry, or that
measurements establish growth. The separate `source_fingerprint_rechecked`
flag still describes internal artifact fingerprint recomputation, not
external attestation. Legacy artifacts with missing lineage fields remain
exportable with the new flag false, and all rows retain
`independent_unit_inference_allowed=false` and scientist review gates.

CSV contract `ecology-measurement-export-0003` is shared by the standalone
endpoint and saved typed Workflow Builder output. Focused tests cover current
four-digest sources, malformed/missing digests, historical partial lineage,
CSV parity, and the persisted artifact flag. The preceding exact head
`c22d8a9d` passed 16/19 Actions workflows; three backend workflows stopped
at one Ruff formatting discrepancy in the measurement CSV test, which this
increment also corrects. Exact-new-head CI, authenticated longitudinal
identity/calibration review, 1.1 migration reconciliation, real ecological
acceptance, and installed Windows GUI/MSI tests remain mandatory.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Population CSV saved-workflow contract alignment (2026-10-30)

The existing `ecology_population_csv_export` executable Workflow Builder node
now persists the same `ecology-population-export-0004` schema version used by
the standalone CSV renderer. Previously its artifact metadata incorrectly
advertised `0001` while the CSV rows used `0004`. A single shared version
constant prevents future drift. Persisted workflow artifacts additionally
include the SHA-256 digest of their UTF-8 CSV bytes, the source fingerprint
contract, source candidate and declared-unit denominators, and an explicit
`independent_unit_inference_allowed=false` review boundary. Saved-workflow
acceptance checks compare exact standalone CSV bytes, schema metadata, digest,
and denominators; the existing typed ports and verified-dataset promotion block
remain in place. Historical saved artifacts are not rewritten. This is
provenance/contract integrity, not verified ecological independence, organism
identity, or calibrated growth acceptance.


## Source geometry dimensional integrity (2026-10-30)

Source-linked calibrated candidates now fail closed when a box width/height is
mislabeled as a mask area, a linear box unit is replaced by a squared unit,
or a projected mask area lacks a squared unit. Persisted JSON validation
rejects incompatible candidates during saved Workflow Builder replay. The
shared series-QC renderer also checks in-memory candidates created through
`model_copy(update=...)`, which bypasses Pydantic validators, before any
standalone measurement, population or series CSV can export re-signed source
evidence. Regressions cover valid and invalid geometry/unit combinations,
saved-workflow tampering and re-signed CSV tampering. Existing typed ports,
source digests, researcher-review gates and unverified dataset boundaries
are preserved. This is dimensional-integrity validation, **not** verified
calibration, biological growth or experimental-unit independence.

Exact-head CI, scientist-reviewed longitudinal data, experimental-design
approval, 1.1 migration reconciliation, representative ecological acceptance
and installed Windows GUI/MSI tests remain required.
**1.2 NOT RELEASE-READY; 1.3 not started.**


## Projected geometry unit syntax integrity (2026-10-30)

The existing source-linked calibrated-measurement candidate schema now rejects
dimension-encoded linear units even when written with Unicode superscripts,
trailing digits, or higher exponents (for example `mm²`, `mm2`, `mm^3`,
`mm⁴`). Mask projected areas still require a single `^2` suffix on a
linear base unit. This closes a relabeling gap in persisted standalone and
executable saved Workflow Builder artifacts and in re-signed source-series CSV
exports. Tests cover valid `mm`/`µm` and `mm^2`/`µm^2`, invalid
dimensions, saved-workflow tampering, and re-signed CSV tampering.

This is a **unit-syntax consistency check**, not a verified physical unit
registry, calibration attestation, identity verification, or biological growth
claim. Unreviewed evidence remains gated; experimental-unit independence and
installed Windows/scientific acceptance are not established.


## Full candidate-schema revalidation at scientific CSV boundary (2026-10-30)

The existing source-linked series-QC CSV exporter now revalidates the entire
`EcologyMeasurementCandidate` schema before accepting even an in-memory,
re-signed artifact. Pydantic's `model_copy(update=...)` bypasses validators:
checking only the decorated geometry method missed forged negative/Boolean
values, invalid SHA-256 source evidence, impossible identity revisions and
contradictory capture-time status. Calling the decorated validator directly
also failed strict mypy in three exact-head backend workflows at `eeb88060`.
The exporter now uses `model_validate(model_dump(mode="python"))` to check
all candidate fields and dimensional constraints with the ordinary Pydantic
validation path, converting failures to a domain validation error.

Five re-signed tampering regressions extend the existing geometry, standalone
CSV and saved-workflow tests. This is a defensive internal-consistency gate,
not source ownership attestation, scientist approval, calibration verification,
or experimental-unit independence. Typed Workflow Builder results, historical
artifact compatibility and review restrictions remain unchanged. Latest-head
CI and installed Windows/scientific acceptance are required before release.

## Shared physical-unit eligibility at source and artifact boundaries (2026-10-30)

Source-linked ecological measurements now use one physical-length unit policy
for the frozen calibration registry and the persisted measurement-candidate
schema. Previously the registry rejected pixels, seconds and arbitrary unit
labels, but the candidate schema only checked that a label *looked* linear:
a re-signed saved artifact could therefore export `pixels`, `seconds` or
`unknown` as if they were calibrated physical lengths, and `px^2` as
a projected physical area. The schema now accepts the same recognized
physical-length labels as the source registry; mask projected areas must use
the corresponding `^2` suffix. Existing accepted micro-sign/Greek-mu
spellings and metric/imperial units remain supported.

Focused standalone Pydantic regressions cover accepted units and rejected
nonphysical labels; saved executable Workflow Builder replay and re-signed
source CSV regression cases must fail closed on altered units. The common
helper does **not** convert units, validate the physical scale, authenticate
calibration/identity or establish independent biological replicates.
Historical artifacts with invalid nonphysical units must fail scientific
revalidation rather than being silently promoted. All outputs remain
`linked_unverified` with scientist review required. Exact-head CI,
registered design, real longitudinal review, migration reconciliation and
installed Windows GUI/MSI acceptance remain release gates.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Current source-lineage digest completeness gate (2026-10-30)

The current `ecology-measurement-candidates-0021` contract now requires all
four source-lineage SHA-256 digests (identity history, source images,
annotation evidence, calibration evidence) to be present and well-formed.
The typed API/saved Workflow Builder artifact rejects incomplete current
records at deserialization. Both standalone scientific CSV export paths also
fail closed on unchecked in-memory `model_copy` changes. Older persisted
contracts retain their explicitly disclosed partial-lineage compatibility
and remain unverified. Focused tests cover current API output, saved
Workflow Builder parity, all four missing/malformed digest fields, and
exporter bypass attempts. This is **digest metadata completeness only**:
it does not verify digest correspondence to live project records,
scientist approval, biological identity, calibration accuracy, or
experimental-unit independence. Migration reconciliation with 1.1,
representative ecological acceptance and physical Windows GUI testing
remain required before release.

## Per-revision experimental-design corrections in identity CSV (2026-10-30)

The existing standalone `identity-registry/history.csv` export now includes
`design_revision_change_json` on the exact append-only revision that
changed an organism's kind, parent colony, experimental-unit level or unit ID.
The field carries the complete typed before/after audit event and changed
field list; unchanged/reason-only revisions retain a blank value. The
existing signed history digest, latest-snapshot digest, design-audit
reconciliation, CSV formula escaping and review restrictions are preserved.

Regression coverage checks tank reassignment and reversion, exact revision
alignment, deterministic standalone CSV equality with the persisted
`ecology_identity_registry_source` Workflow Builder artifact, and blank
change details on legacy artifacts whose design audit is unavailable. This
closes a reporting gap where a CSV disclosed only the number of design
corrections, not their actual assignment changes. It does **not** establish
that a correction is a biological movement, a verified study-design
registration, or independent replication.

1.2 remains **NOT RELEASE-READY** pending exact-head CI, authenticated
scientist-reviewed longitudinal measurements and design approval, migration
reconciliation with unmerged 1.1, representative biological acceptance and
installed Windows MSI/GUI testing. 1.3 remains unstarted.


## Per-revision source-evidence traceability for design corrections (2026-10-30)

The existing project-owned identity-history CSV now enumerates the exact
image-evidence, reviewed-annotation-evidence and frozen-calibration-evidence
link IDs attached to **each identity revision**. Three source-collection
SHA-256 digests are included for reproducibility. A design-correction row
separately lists all earlier-revision image-evidence link IDs for that organism,
so a tank/colony reassignment or identity correction exposes earlier evidence
that requires a scientist to reconsider. A missing link is represented as an
empty JSON array; unchanged revisions leave the prior-evidence warning blank.
The exporter revalidates typed source-link provenance to reject in-memory
tampering before writing these new columns.

The same existing executable `ecology_identity_registry_source` Workflow
Builder node persists the typed registry used by the standalone CSV endpoint;
regression coverage exercises a real image -> human annotation -> calibration
link chain, a later study-design correction, saved-workflow parity, and
tampered image/annotation/calibration links. No parallel node or migration is
introduced. These are **linked but unverified source claims**, not scientist
approval of organism identity, true experimental-unit independence, or
verified longitudinal measurements. The review gate remains
`scientist_review_required`. Real-data acceptance, 1.1 migration-lineage
reconciliation, full exact-head CI and installed Windows GUI testing remain
required.


## Strict typing repair for identity-history evidence export (2026-10-30)

At branch head `08c6ca30`, 16 of 19 PR-triggered Actions workflows passed;
three backend workflows failed on four strict mypy errors in
`ecology_identity_history_export.py`. The three linked source-evidence
collections (image, reviewed annotation, frozen calibration) contain distinct
typed row models, but their sequential loops reused the same variable
`link`. Mypy retained the image-link type for subsequent loops, rejecting
the annotation and calibration field access.

The exporter now uses type-specific `image_link`, `annotation_link` and
`calibration_link` names. Source mapping, CSV schema, validation and review
semantics are unchanged. The existing integration regression
`test_history_csv_traces_revision_sources_and_prior_design_change_evidence`
checks all three link types, the earlier-revision design-correction warning,
tampering rejection and exact standalone/saved Workflow Builder parity.
This repair introduces no migration or parallel scientific implementation.

A source-level inspection is not a substitute for strict mypy/pytest or
physical Windows acceptance. Check the **new commit's exact-head** Actions
results before claiming the typing gate is resolved. Version 1.2 remains
**NOT RELEASE-READY**; 1.3 has not begun.


## Prior derived-evidence review queues on identity-design corrections (2026-10-30)

The existing identity-history CSV now exposes two additional per-revision
review queues: `design_change_prior_annotation_evidence_ids_json` and
`design_change_prior_calibration_evidence_ids_json`. When an organism's
registered biological kind, parent colony or experimental-unit assignment
changes, these deterministic arrays identify earlier-revision reviewed
annotation links and frozen calibration links, in addition to the existing
prior-image evidence queue. A correction with no prior derived links records
`[]`; unchanged revisions record blank fields. Earlier evidence is flagged
for scientist reassessment, never silently reassigned or promoted to verified
longitudinal measurements. The same project-owned typed registry is persisted
by the executable `ecology_identity_registry_source` Workflow Builder node;
standalone CSV and saved-workflow parity tests cover a real image/annotation/
calibration chain and a correction without derived evidence. The pre-existing
collection digests, source integrity revalidation, review gate and
pseudoreplication restrictions remain in effect. This iteration also fixes
the Ruff formatting failure at prior head `42bb87b1` in the same exporter.

This is provenance/reporting integrity, not authenticated biological review,
independent experimental-unit approval, or verified growth. Exact-head CI,
1.1 migration reconciliation, representative ecological acceptance and
installed Windows MSI/GUI tests remain release gates. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Identity-revision image metadata QC in history exports (2026-10-30)

The existing identity-history CSV now reports the image-metadata evidence state
for each append-only identity revision. `revision_image_metadata_qc_status`
distinguishes `no_image_evidence`, `frozen_metadata_linked_unverified`, and
`legacy_unfrozen_requires_review`; the companion
`revision_legacy_unfrozen_image_evidence_ids_json` lists the exact legacy
source links needing follow-up. A frozen metadata fingerprint is only a
reproducibility check, **not** an authenticated scientist-reviewed specimen,
image, annotation, calibration or growth measurement. Historical links remain
visible and unverified rather than silently appearing fully frozen.

The existing executable `ecology_identity_registry_source` Workflow Builder
node continues to persist the same typed source registry; standalone CSV and
saved-workflow parity regressions cover current frozen links, revisions with
no image links, and pre-migration legacy-unfrozen links. This iteration also
corrects the exact Ruff formatting failure at previous head `b964a1c1`
in the history exporter (three backend workflows failed). No new database
migration, 1.1 environmental-context duplication or verified-dataset
promotion is introduced. Exact-new-head CI, migration reconciliation,
independent biological review and physical Windows GUI/MSI acceptance remain
required. **1.2 NOT RELEASE-READY; 1.3 not started.**


## Legacy source review across identity-design corrections (2026-10-30)

The existing identity-history CSV now includes
`design_change_prior_legacy_unfrozen_image_evidence_ids_json`. On a recorded
change of biological identity, parent colony or experimental-unit assignment,
this deterministic list identifies **earlier-revision image links without a
frozen source-metadata fingerprint**. It is a subset of the existing prior-image
review queue, not a count of independent biological observations. Revisions
without a design correction leave the field blank; a correction without earlier
legacy links records `[]`. No source link is reassigned, upgraded to verified,
or omitted from the history.

The existing typed `ecology_identity_registry_source` Workflow Builder node
and standalone CSV endpoint reuse the same source registry and provenance
checks. Regression coverage exercises a real legacy image link, a subsequent
tank-assignment correction, empty/blank cases, and exact persisted saved-workflow
CSV parity. This increment also repairs the Ruff format failures at previous
head `25f4cf9c`. No migration or new environmental-context implementation.
Latest-head CI and representative biological/Windows acceptance are still
required; **1.2 NOT RELEASE-READY; 1.3 not started**.


## Persisted identity design consistency gate (2026-10-30)

A project-owned identity revision previously checked independent-unit labels
when received through the standalone API, but its persisted
`EcologyIdentityRow` schema did not repeat those checks when reading saved
Workflow Builder artifacts or ecological source evidence. The row schema now
rejects technical units (images/frames/cameras), half-declared unit type/ID
pairs, blank unit IDs, and parent-colony references on non-fragments. This
is applied to the same typed history consumed by standalone CSV and saved
`ecology_identity_registry_source` artifacts; it does not introduce a
parallel analysis node, database migration or 1.1 environmental feature.
Acceptance coverage uses an executed saved workflow plus invalid standalone
registration requests. This iteration also applies the exact Ruff formatter
correction diagnosed from prior-head CI for the legacy-source regression.

This is **structural design QC only**: it does not authenticate the study's
experimental-unit registry, certify biological independence, review growth
measurements, or promote data to a verified dataset. Full exact-head CI,
representative scientific review, 1.1 migration reconciliation and installed
Windows GUI/MSI acceptance remain mandatory. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Evidence revalidation precedence: regression alignment (2026-10-30)

Exact-head CI on `6a5799f7` found four backend tests failing solely because
copied, tampered typed identity-registry objects now fail the earlier full
Pydantic evidence-integrity revalidation before reaching derived design-change,
shared-parent and historical-parent audit checks. The error is
`Ecological identity source evidence integrity check failed`, not the later
specific audit error expected by older tests. Both paths reject tampering;
no integrity gate is weakened. Updated the ten existing tamper assertions
across the two affected test modules to expect the earlier fail-closed check,
and documented this validation order in test comments. No API, database,
workflow contract, production behavior or scientific dataset was changed.

Previous exact-head backend CI: 2,144 passed, 4 failed, 32 skipped (the four
failures were stale error-message assertions). This test-only repair still
requires fresh exact-head CI before claiming a pass. Authenticated biological
review, longitudinal measurement acceptance, 1.1 migration reconciliation
and installed Windows MSI/GUI testing remain outstanding. **1.2 NOT
RELEASE-READY; 1.3 not started.**

## Legacy audit-field replay and tamper integrity (2026-10-30)

Exact-head CI at `a7733650` reported 17 successful workflows and two
failed backend workflows. The backend suite reached 2,147 passes, 32 skips,
and one failure: a previously saved registry without the later-added
`cross_unit_parent_details` field was rejected during CSV revalidation.
Pydantic's default `model_dump()` made the omitted legacy field appear
explicitly present as `[]`, which incorrectly asserted a modern audit.

The existing identity-history exporter now preserves the absent-field
semantics for only the two optional derived parent-audit detail lists, and
only while their default values remain empty. Explicitly supplied modern
lists and in-place modifications to previously absent lists remain subject
to full schema revalidation and fail-closed provenance checks. Regression
coverage exercises current API/workflow CSV parity, historical saved
artifacts, and in-place tampering of both legacy parent-audit lists.
This does not change stored identity evidence, migrate records, or promote
any unverified observation. Fresh exact-head CI, authenticated biological
measurement review, migration reconciliation and Windows GUI/MSI acceptance
remain required. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Persisted projected endpoint replay arithmetic (2026-10-30)

The existing typed `EcologyProjectedEndpointChange` now revalidates the
arithmetic and source-date ordering of projected endpoints when decoding
saved Workflow Builder artifacts, as well as when created by the standalone
source-linked analysis. Baseline/final timestamps must be timezone-aware,
represent different ordered **UTC** sampling dates, and refer to distinct
image IDs. The stored elapsed days, absolute/percent changes, and optional
per-day rates must agree (within numerical tolerance) with the baseline,
final value, and actual UTC elapsed time. Earlier persisted artifacts
without the optional slope fields remain readable. Replayed artifacts with
altered derived values or timestamp/source identity fail closed.

The focused regression exercises an existing project-owned source chain,
compares standalone candidate output to a **persisted executed**
`ecology_identity_registry_source` Workflow Builder artifact, then tests
valid typed endpoint replay, legacy missing rates, equivalent UTC offsets,
and eight independent tampering cases through both endpoint and persisted
candidate-response deserialization. The tampering fixture adds a synthetic
endpoint to the real typed source response; it does **not** represent an
authenticated, independently reviewed biological observation or prove
source-to-endpoint linkage. No migration, new node, new pretrained weights,
or 1.1 environmental-context feature is introduced.

The prior branch head `0b83bee5` passed all 19 PR-triggered GitHub
Actions workflows (including backend CI and Windows build), but that is
**pre-change** evidence. Exact-new-head CI, authenticated scientist-reviewed
longitudinal measurement promotion, independent study-design verification,
1.1 migration reconciliation, representative biological data, and installed
Windows GUI/MSI acceptance remain open. **1.2 NOT RELEASE-READY; 1.3
not started.**

## Endpoint source-ID integrity and exact-head CI repair (2026-10-30)

The previous head `b319b314` completed 16 of 19 PR-triggered Actions
workflows successfully. Backend CI, Pose Workflow Validation, and ReefVision
1.0 Acceptance failed at Ruff formatting, before backend scientific tests.
The CI logs identified two unformatted files: the endpoint replay schema
and its focused regression module. Applied the exact Ruff-requested layouts.

A persisted projected endpoint now rejects empty or whitespace-only image,
annotation-evidence, and calibration-evidence identifiers for either timepoint.
This guards against saved scientific evidence losing its source links; it does
not establish that a nonblank identifier belongs to an authenticated source.
The existing standalone/project-source and saved-workflow parity test now
also checks those missing-ID tampering cases, and rejects differing local dates
that resolve to the **same UTC sampling date**. The already-executable typed
Workflow Builder contract and scientist-review gate are unchanged.

This increment does not authenticate growth, establish independent replication,
add migrations, or duplicate 1.1 environmental context. Fresh exact-head CI
must pass before treating this change as validated end-to-end. Real reviewed
longitudinal measurements, migration reconciliation, representative biological
acceptance, and installed Windows MSI/GUI acceptance remain mandatory.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Current-contract saved ecological payload fingerprint replay (2026-10-30)

The v0021 ecological measurement response now recomputes its canonical
source-input SHA-256 from the **actual persisted** candidates, sampling-date
QC, projected visit coverage, projected endpoint changes, unit and population
summaries, exclusions, project ID and four lineage digests. A mismatched saved
Workflow Builder payload fails closed even when its individual projected
endpoint arithmetic is internally consistent. It also rejects a current
candidate count that differs from its source rows. This closes a gap where
saved typed responses previously checked the *shape* of lineage digests but
did not recompute the source-input digest after replay.

The check runs before newer optional Pydantic row defaults are injected, so
older v0021 snapshots with legitimately omitted optional fields can retain
their original fingerprint. The focused regression also replays such a
legacy-omission case without silently upgrading its review status.

The existing standalone project endpoint and executed
`ecology_identity_registry_source` Workflow Builder node share this response
contract; the focused acceptance test checks both payloads, rejects edited
candidate values, counts, QC and digests, and confirms a synthetic endpoint
cannot be appended while retaining the old fingerprint. Earlier v0018–v0020
fingerprint contracts remain readable without asserting they follow the
v0021 canonical algorithm. The test's synthetic two-date endpoint is
**unverified projected geometry**, not a scientist-approved growth observation.
A SHA-256 integrity check is not authentication or biological verification:
a party able to rewrite the entire payload and its digest could still forge
the artifact. Immutable source records and independent scientist review
remain required.

Pre-change head `276e254a` passed all **19** associated GitHub Actions
workflows, including backend CI and Windows Desktop Build. That evidence
does not validate this new commit. No new migration, environmental context,
model-weight download or parallel Workflow Builder node was introduced.
Release gates remain authenticated reviewed longitudinal measurements,
registered experimental-unit independence, migration reconciliation with
unmerged 1.1, representative ecological datasets, exact-head CI, and
physical Windows MSI/GUI acceptance. **1.2 NOT RELEASE-READY; 1.3 not
started.**

## Exact-head CI lint repair (2026-10-30)

At head `180795b65e9a04c1fc015b35a69f47132104b24d`, 16 of 19
GitHub Actions workflows passed, including Windows Desktop Build. Backend CI,
Pose Workflow Validation and ReefVision 1.0 Acceptance failed before tests
because Ruff found one unsorted import and two non-raw `pytest.raises(match=)`
regular-expression literals in
`test_ecology_endpoint_replay_integrity_1_2.py` (I001, RUF043).
The dedicated 1.2 branch corrects only these test-source lint violations;
no measurement calculations, source fingerprints, review gates, migrations,
Workflow Builder ports or verified-dataset semantics changed. The exact
post-fix head must pass all applicable CI workflows before this is considered
validated. Local Ruff/pytest remain unavailable without repository checkout
and dependencies; Windows installed-GUI and independent ecological review
remain required for release readiness.


## Ecological candidate-report replay integrity (2026-10-30)

The source-linked `ecology-candidate-report-0001` previously carried a
`report_sha256` but did not verify that digest when loading persisted
Workflow Builder report artifacts. The parent
`EcologyMeasurementCandidatesResponse` also did not cross-check a report
against the source candidate rows. A modified QC count, declared experimental
unit count, or other descriptive figure could therefore be accepted with an
unchanged source-input fingerprint.

The existing report schema now recomputes the canonical report SHA-256 on
deserialization. When a report is attached to a source-candidate response,
the typed response additionally checks project/source lineage, candidate
count, distinct source images and organisms, declared-unit count, sampling-date
QC totals, exclusions and QC-status frequencies against its source rows.
For historical declared-unit labels, either the earlier literal-label count
or the canonical biological-unit alias count is admissible; neither is
treated as proof of experimental independence. Historical candidate artifacts
without the optional report remain readable. No new workflow node or
migration was introduced.

The focused API + saved executable Workflow Builder regression exercises
standalone report deserialization, persisted `ecology_candidate_report`
artifacts, tampered counts without updated digests, and forged counts
with recomputed report digests. It also retains the legacy absent-report
acceptance case. This is a reproducibility/integrity guard, **not**
authenticated scientist review or independently verified growth.

Pre-change exact-head `d8982fe1` completed 16/19 GitHub Actions workflows
successfully, including Windows Desktop Build. Three backend workflows
failed Ruff formatting checks in the source-candidate schema and endpoint
replay test. This iteration applies the exact formatter-requested layout
alongside the report integrity improvement. Fresh exact-head CI, full
scientific acceptance, migration reconciliation with 1.1 and physical
Windows MSI/GUI acceptance remain required. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Standalone and persisted Workflow Builder ecological QC histogram integrity (2026-10-30)

A source-linked ecological report previously validated its SHA-256 and, when
embedded in a full measurement-candidate response, checked counts against the
source rows. The **separately persisted typed** `ecology_candidate_report`
Workflow Builder output still accepted a recomputed fingerprint over impossible
QC status histograms (unknown categories, negative/boolean/coerced counts,
inconsistent series totals, or falsely claimed date-series passes).

The existing report schema now requires explicit nonnegative integer
frequencies for the nine supported sampling QC categories; category totals
must equal pass-plus-excluded series, and the `date_series_candidate` count
must equal the declared pass count. The checks apply to the standalone report
type, API response, and saved executable Workflow Builder report artifact
without adding a duplicate node, migration, or environmental-context feature.
Focused regression exercises the real API/workflow report and eight altered
artifacts with **recomputed** report fingerprints. This is consistency QC,
**not** authenticated scientist review or proof of biological independence.

The preceding exact head `c5568f23` completed 16/19 GitHub Actions
workflows successfully (including Windows Desktop Build); three backend
workflows failed Ruff format checks. This iteration also applies the three
exact formatting corrections identified in CI logs. New-head integrated CI,
reviewed longitudinal measurements, independent study-design registration,
1.1 Alembic reconciliation, representative ecological acceptance, and installed
Windows GUI/MSI acceptance remain required. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Current-source replay and backend acceptance repair (2026-10-30)

Previous head `ef3a9bfb` passed 17/19 Actions workflows, including Windows
Desktop Build, but both full-backend jobs failed nine regressions (2,142 passed,
32 skipped on Linux). The current v0021 source SHA-256 guard now intentionally
rejects modified saved candidates and lineage digests *before* older semantic
assertions. The report QC-arithmetic guard similarly precedes its digest check.
Tests now exercise both early saved-artifact rejection and independent candidate
and lineage validation, preserving the scientific checks.

Current-source deserialization now converts Python-mode `datetime` objects
to canonical JSON timestamps before fingerprint comparison. This repairs a
real `TypeError` without accepting stale or altered source evidence. Focused
regressions cover signed Python-mode replay, re-signed contradictory capture
metadata, and legacy undated artifacts under their historical contract.
Existing Workflow Builder typed ports, provenance, persisted artifacts,
`linked_unverified` evidence and scientist-review gates are unchanged.

**Release HOLD:** exact-head backend, Ruff/mypy, frontend and Windows CI;
project-owned verified longitudinal observations, registered study design,
representative scientific validation, 1.1 migration reconciliation and native
Windows MSI/GUI acceptance. No 1.3 branch or release is implied.

## Backend Ruff format repair after Python datetime replay (2026-10-30)

The preceding head `660a97f6d1e24d113f7726c2d102ec8bc5969c23`
completed 16/19 PR-triggered GitHub Actions workflows successfully,
including Windows Desktop Build and frontend checks. Backend CI, Pose
Workflow Validation, and ReefVision 1.0 Acceptance failed before pytest:
Ruff 0.17.3 requested four one-line expression layouts across three
existing ecological regression modules. This change applies those exact
formatter-requested layouts without changing test assertions, biological
calculations, provenance, experimental-unit logic, migrations, or Workflow
Builder behavior. Fresh exact-head Ruff, full backend and frontend CI,
scientist-reviewed longitudinal measurements, migration reconciliation,
representative biological validation, and installed Windows MSI/GUI
acceptance remain required. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Current-contract projected endpoint source-row replay (2026-10-30)

The prior exact head `9964ea55bbfaf408e5ba64838abd4142f29ead30`
completed **19/19 GitHub Actions workflows successfully**, including full
backend CI, Pose Workflow Validation, ReefVision 1.0 Acceptance and Windows
Desktop Build. That is pre-change evidence, not validation of this increment.

The existing `ecology-measurement-candidates-0021` typed response now
cross-checks every persisted projected endpoint against its actual source
candidate series **after** canonical SHA-256 verification. An endpoint must
have one unambiguous passing UTC sampling-date QC series, the correct
observed timepoint count, source-ordered first and last observations,
matching image/annotation/calibration evidence IDs, timestamps, geometry
values, unit, organism identity revision, parent colony and declared
experimental unit. Duplicate endpoints for the same organism/metric fail
closed. A recomputed payload and report digest cannot promote a fabricated
endpoint or count repeated images as new independent observations.

Focused tests use the existing API and executed, persisted Workflow Builder
artifact, plus source-linked synthetic two-date evidence to exercise six
rehashed lineage mismatches, a self-consistent but fabricated final
measurement, duplicate endpoint rejection, and historical v0020 replay.
The tests do not claim authenticated scientific review: source-linked
projected geometry remains `linked_unverified` and
`scientist_review_required`. No new workflow node, migration, pretrained
weights, environmental context or cross-track merge is introduced.

**Release HOLD:** fresh exact-head CI, authenticated reviewed longitudinal
observations, registered experimental-unit independence, representative
ecological validation, 1.1 migration reconciliation, and installed Windows
GUI/MSI acceptance. **1.2 NOT RELEASE-READY; 1.3 not started.**

## Exact-head endpoint replay Ruff formatting repair (2026-10-31)

At prior head `be4e693e4ef638a723791fb82d5379b734cc81e2`, 16 of 19
PR-triggered GitHub Actions workflows succeeded, including Windows Desktop
Build. Backend CI, Pose Workflow Validation, and ReefVision 1.0 Acceptance
failed at Ruff 0.17.3 `format --check` before running backend tests.
All three jobs reported the same nine formatting adjustments in
`test_ecology_endpoint_source_replay_1_2.py`: compacting one API call,
one `model_copy`, two projected endpoint validation calls, three response
validation calls, and two `pytest.raises` contexts. Applied the exact
CI-reported formatting without altering any test assertions, scientific
calculations, source-linked provenance, persisted Workflow Builder behavior,
review gates, experimental units, migrations, or verified datasets.

This is a test-gate repair, not new ecological functionality. The new head
requires fresh backend/full CI validation. Authenticated scientist-reviewed
longitudinal measurements, registered independent experimental units,
representative coral data, reconciliation with 1.1 migrations, and physical
installed Windows GUI/MSI acceptance remain required. **1.2 NOT
RELEASE-READY; 1.3 not started.**


## Current-contract UTC sampling QC source replay (2026-10-31)

After the preceding head `81f1e66cb0a36275fa83b7c465db20e849c52979`
passed **19/19 GitHub Actions workflows**, including backend, pose workflow,
ReefVision 1.0 Acceptance and Windows Desktop Build, the v0021 typed
`EcologyMeasurementCandidatesResponse` now **recomputes the full per-organism
UTC sampling-date QC from the actual persisted source candidate rows** when
deserializing standalone API and saved executable Workflow Builder artifacts.
This check runs in addition to canonical SHA-256 verification, so an attacker
or accidental edit cannot simply recompute a digest to fabricate sampling
dates, omit a failed series, invent extra source images, hide same-day
technical replicates, or change source-conflict flags.

The regression `test_ecology_sampling_qc_source_replay_1_2.py` exercises real
standalone API and executed saved-workflow parity, rehashed forged QC metadata
and counts, missing/duplicated series, and v0020 historical compatibility.
The existing typed `ecology_identity_registry_source` node, review gate,
provenance, persistence and offline workflow remain unchanged. Older source
fingerprint contracts remain readable without retroactively claiming their
historical QC was authenticated. **The source rows are still
`linked_unverified` projected geometry; SHA-256 and deterministic QC are
not scientist review, verified growth or proof of independent experimental
units.**

**Release HOLD:** exact-new-head CI, authenticated scientist-reviewed
longitudinal measurements, registered experimental-unit independence,
representative ecological/human-model validation, 1.1 Alembic reconciliation
and physical installed Windows GUI/MSI acceptance. **1.2 NOT RELEASE-READY;
1.3 not started.**


## Calibration-link source uniqueness and CI repair (2026-10-31)

Pre-change head `ab787f079f1b6b93b405d1142130673fd7677dff` completed
**16/19 PR-triggered Actions successfully**, including Windows Desktop Build.
Backend CI, Pose Workflow Validation and 1.0 Acceptance failed before backend
pytest because Ruff 0.17.3 requested two formatting changes in
`test_ecology_sampling_qc_source_replay_1_2.py`. Applied the exact CI
formatting changes without altering the QC assertions.

A separate scientific replay gap remained: a saved current-contract
(`ecology-measurement-candidates-0021`) artifact could include the same
calibration evidence and metric twice, or reuse one calibration evidence ID
for a different image/annotation/organism lineage. Even if its source SHA-256
was recomputed, such a record could inflate sampling effort or disguise
contradictory evidence. The typed response now rejects duplicate
`(calibration_evidence_id, metric)` rows and requires every metric sharing
a calibration evidence ID to retain identical source image, annotation,
identity, biological unit, acquisition time and evidence digests. A box's
width and height legitimately share one calibration ID and remain allowed.

Focused regression covers the actual standalone API and executed, persisted
Workflow Builder candidate artifact, re-signed duplicate rows, conflicting
cross-metric lineage, and older v0020 records with no report. Existing typed
ports, offline operation, immutable verified-dataset semantics and scientist
review gates are unchanged. This is source-link *consistency*, not
authentication of the calibration, independence of tanks/colonies or
scientist-verified growth. No migration or 1.1 environmental context was added.

**Release HOLD:** exact-new-head backend/frontend/E2E/Windows CI, authenticated
scientist-reviewed longitudinal measurements, registered independent study
units, human-model comparison on representative biological data, migration
reconciliation with unmerged 1.1 and installed Windows GUI/MSI acceptance.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Replayed observed-visit and experimental-unit summary integrity (2026-10-31)

Current `ecology-measurement-candidates-0021` source-linked artifacts now
recompute observed UTC-date visit coverage, projected organism/metric endpoints,
one-row-per-declared-unit summaries, and equal-unit-weighted population
summaries from their original candidate measurements. Persisted Workflow Builder
results and standalone API responses use the same typed Pydantic contract.
Even if an altered payload and its candidate-report SHA-256 are recomputed,
fabricated/missing/duplicated visit rows, inflated independent-unit
denominators, reassigned tanks, altered unit means, or removed
independence-review blockers must fail deserialization. Older v0018–v0020
source-fingerprint contracts retain historical readability and remain
`linked_unverified`.

The focused regression includes live standalone API versus executed saved
Workflow Builder payload parity, a tampered saved-workflow visit, nine altered
derived-field cases, six missing/duplicate summary-row cases, and historical
decoding. This is **source-to-derived replay consistency**, not authentication
of source images, parentage, calibration, biological independence, or
scientist-approved growth. It does not introduce another environmental
context provider, migration, model checkpoint, or workflow node. Full exact-head
CI, authenticated review, independent ecological acceptance, cross-version
migration reconciliation, and installed Windows GUI/MSI checks remain required.
**1.2 NOT RELEASE-READY; 1.3 not started.**

## Derived ecological summary replay — Ruff gate repair (2026-10-31)

At preceding exact head `40da75ebcd17bf0075b5a96e0f5f10215f0cd018`,
16/19 PR-triggered GitHub Actions workflows passed, including Windows Desktop
Build. Backend CI, Pose Workflow Validation, and ReefVision 1.0 Acceptance
failed at Ruff 0.17.3 `format --check` before scientific pytest execution.
Both failing Ruff hunks were in
`test_ecology_derived_summary_source_replay_1_2.py`: the calibrated-candidate
API call and historical-contract `model_copy` expression. Applied the exact
formatter-requested compact expressions without changing assertions, source
replay, biological calculations, typed Workflow Builder artifacts, scientific
review gates, provenance, or experimental-unit handling. This is a test-gate
repair, not a new feature; full exact-head CI must complete before declaring
the regression resolved.

**Release HOLD:** authenticated scientist-reviewed longitudinal observations,
registered independent experimental units, representative biological and
human/model acceptance, 1.1 migration reconciliation, and physical installed
Windows MSI/GUI acceptance remain outstanding. **1.2 NOT RELEASE-READY;
1.3 not started.**

## Saved-workflow fabricated-visit acceptance repair (2026-10-31)

At exact head `222ebfbab0bd607c5f88bd90589fbc8b93c41caa`, 17 of 19
PR-triggered GitHub Actions workflows succeeded, including the Windows
Desktop Build, Pose Workflow Validation, frontend and E2E. Backend CI and
ReefVision 1.0 Acceptance each reported **2,194 passed, one failed, and
32 skipped**. The single failing case was
`test_saved_workflow_rejects_rehashed_fabricated_visit`: after running an
actual saved Workflow Builder graph, the test created a second project using
a shared fixed annotation UUID. The annotations API correctly rejected that
cross-image reuse with HTTP 400, before the intended forged-visit replay
assertion could execute. This is a test-fixture collision, not evidence of a
production ecological replay failure.

The regression now synthesizes a timezone-aware, biologically unit-labeled
visit **in memory** from the already persisted source candidate. It signs the
modified saved artifact without changing the original undated source rows,
then requires current-contract deserialization to reject the fabricated
visit as inconsistent with its source. No additional project, image or
annotation is created. The test retains real API and executed saved-workflow
coverage, typed artifact provenance, `linked_unverified` evidence and the
scientist-review gate. No production code, migration, environmental context,
model weights or unreviewed version branch is changed.

**Release HOLD:** new exact-head backend/frontend/E2E/Windows CI, independent
scientist-reviewed longitudinal observations, registered experimental-unit
independence, representative biological/human-model acceptance, 1.1 migration
reconciliation and installed Windows MSI/GUI checks. **1.2 NOT
RELEASE-READY; 1.3 not started.**
