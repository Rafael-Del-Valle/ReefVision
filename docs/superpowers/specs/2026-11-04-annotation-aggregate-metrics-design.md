# Annotation Aggregate Metrics Design

## Intent

ReefVision 1.1 needs a first saved, executable annotation-derived measurement that is
scientifically honest about what was counted and what constitutes an independent unit. A
researcher must be able to define, preview, calculate, reopen, export, rerun through Workflow
Builder, and project-exchange a verified annotation or verified mask count without treating
unreviewed predictions or individual organisms as biological replicates.

This slice extends the existing computed-metric persistence and workspace. It does not create a
parallel statistics subsystem and does not reinterpret the existing scalar expression engine.

## Goals

- Persist immutable aggregate definitions and results in the existing
  `computed_metric_definitions` and `computed_metric_results` tables.
- Count either canonical saved bounding-box annotations or verified mask annotations from images
  whose annotation status is `reviewed`.
- Optionally filter by an explicit set of project label classes.
- Require explicit image IDs for every preview/calculation; do not search an implicit changing
  project population.
- Group by either source image or `ImageAsset.group_key`, with the selected grouping level also
  serving as the declared independent experimental-unit level for this slice.
- Report observation count, image/sample count, independent-unit count, group totals, the mean
  observations per independent unit, eligible/excluded inventories, and immutable source
  snapshots/checksums.
- Keep accepted model outputs eligible only after they have become canonical annotations or
  verified masks. Pending/rejected proposals remain excluded and separately reported.
- Use the same service for standalone API and Workflow Builder execution.
- Preserve and explicitly remap aggregate relationships through project exchange 1.1.
- Export aggregate values, grouping fields, source identities, sample sizes, workflow lineage, and
  checksums as CSV.

## Non-goals

- Mask union area, summed mask area as coverage, calibrated physical area, density, ROI
  denominators, or unit conversion. Those require exact raster union and calibration semantics and
  must not be approximated by the existing summed-area summary.
- A generic subject hierarchy, treatment-design editor, parent/child specimen schema, or full
  inferential statistics system.
- Automatic inference that `group_key` means tank, colony, treatment, or biological replicate.
- Aggregating video frames, tracks, predictions that have not been accepted, or scientific records.
- Editing migrations `0038`, `0039`, or `0040`, releasing 1.1, or reconciling the independent 1.6
  migration identifier.

## Constraints

- Original source images and annotations remain unchanged.
- Existing scalar definition/result API behavior, hashes, formula engine, workflow nodes, CSV, and
  exchange behavior remain backward compatible.
- A new additive `0041` migration follows `0040`; published migrations are never rewritten.
- Definitions and results are immutable and project scoped.
- Missing `group_key` values reject group-key calculations; they never become a shared empty group.
- Duplicate image IDs reject the request rather than silently changing its sample inventory.
- Empty selections and zero eligible observations return an explicit preview but calculation is
  rejected; a persisted scientific zero must come from at least one reviewed, eligible image.
- Each result is one aggregate snapshot. `observation_count` means annotations or verified masks,
  `image_count` means eligible reviewed images, and `independent_unit_count` means image IDs or
  explicit nonempty group keys according to the definition.
- Group means are descriptive only. No standard error, confidence interval, hypothesis test, or
  claim of treatment replication is produced.

## Approaches considered

### 1. New standalone aggregate tables

This is structurally simple, but it duplicates computed definition/result persistence, pagination,
CSV, workflow lineage, and exchange integrity. It would create the parallel system the brief asks
the implementation to avoid.

### 2. Encode aggregate configuration inside scalar expressions

This avoids a migration but overloads the safe arithmetic language with non-scalar query syntax,
misstates annotation inventories as formula symbols, and makes validation and UI behavior obscure.
It would weaken rather than extend the existing computed contract.

### 3. Discriminated aggregate rows in the existing computed tables (selected)

Add a `definition_kind` plus optional `configuration_json` to definitions and a `result_kind` to
results. Existing rows are backfilled/defaulted to `scalar`; scalar payloads and hashes stay
unchanged. Aggregate rows use their own typed schemas, hashes, calculation service, preview API,
workflow adapter, CSV serializer, and exchange validator/remapper while sharing project scope,
immutability, workflow foreign keys, pagination conventions, and project-exchange sections.

This is the smallest clean extension point for later aggregate operations such as exact mask union
coverage. It costs one additive migration and discriminated response handling, but avoids corrupting
the scalar expression model.

## Data contract

### Aggregate definition

`definition_kind = "annotation_aggregate"`,
`formula_version = "reefvision.annotation-aggregate.v1"`, and `configuration_json` contains:

- `schema_version = "annotation-aggregate-definition-0001"`
- `source_kind`: `verified_annotations` or `verified_masks`
- `grouping_level`: `image` or `image_group_key`
- `label_class_ids`: sorted unique project UUIDs, possibly empty for all classes
- `required_image_status = "reviewed"`
- `operation = "count"`
- `independent_unit_contract`: `image_is_independent_unit` or
  `group_key_is_independent_unit`

The existing scalar columns remain populated with a readable operation token and output unit
`count`, but scalar compilation is never invoked for aggregate definitions. The definition checksum
hashes name, kind, engine version, and canonical configuration.

### Preview and result

Preview accepts 1–500 unique explicit image IDs and returns the calculation that would be saved,
including eligible/excluded images and reasons. Calculation accepts the same request and persists a
single `ComputedMetricResult` with `result_kind = "annotation_aggregate"`.

The aggregate payload includes:

- Definition snapshot and checksum
- Project ID and calculation timestamp
- Source kind, operation, filters, grouping/independence contract, and units
- Sorted image IDs and image snapshots: image SHA-256, dimensions, annotation revision/status,
  capture timestamp, group key, and metadata checksum
- Sorted annotation or mask snapshots with IDs, revisions, class, source/status, and content hash
- Label-class snapshots plus per-class counts for the whole result
- Group rows with group key, image IDs, observation IDs, observation count, per-class counts,
  image count, and independent-unit count `1`
- Overall observation count, image count, independent-unit count, and mean observations per
  independent unit
- Excluded image/proposal inventories with explicit reason/status counts
- Workflow run/node IDs in scalar columns and result response
- Content SHA-256 over the complete aggregate payload

Listing a result also reports whether the current source inventory reproduces its saved source
snapshot. A changed/deleted annotation, mask, image revision, group key, review state, or class
assignment marks the result stale without rewriting it.

## Eligibility and grouping rules

- Bounding-box source includes non-deleted canonical `Annotation` rows only. `source_type` remains
  in each snapshot, so human/imported/accepted-prediction observations remain distinguishable.
- Mask source includes non-deleted `MaskAnnotation` rows with `status == "verified"` only.
- Every eligible source image must have `annotation_status == "reviewed"`.
- Label filters are project scoped and must resolve before preview/calculation. Results always
  retain per-class counts for the eligible inventory; verified masks without a class remain an
  explicit `Unclassified` category rather than disappearing.
- Prediction proposals never enter observation counts. The preview reports proposal status counts
  so exclusions are visible.
- `image` grouping creates one independent unit per eligible image.
- `image_group_key` grouping requires every eligible image to carry a nonblank `group_key`; images
  with the same value form one independent unit. The result never claims that the key represents a
  tank, colony, treatment, or biological replicate beyond the researcher's explicit selection.
- Zero observations across reviewed eligible images are previewable but not persisted. This avoids
  conflating a true observed zero with missing/unreviewed annotation work.

## API and UI

New aggregate endpoints live under the existing computed-metric project routes:

- create/list aggregate definitions
- preview a definition over explicit image IDs
- calculate and persist a result
- list aggregate results
- export aggregate results CSV
- validate a saved result against current source inputs

The Computed Metrics workspace gains an “Annotation aggregates” section. It exposes source kind,
class filters, grouping/independence level, explicit image IDs, preview counts/exclusions, calculate,
saved definition/result cards, stale/current state, provenance, and aggregate CSV. Existing scalar
forms and result cards stay unchanged.

## Workflow Builder

Add executable `annotation_aggregate` analysis node:

- Input: `project_reference`
- Required parameters: `definition_id`, `image_ids`
- Output: `computed_metric_result`

Execution calls the same calculation method as the standalone API, stores workflow run/node IDs,
and emits result ID, definition checksum, observation/image/independent-unit counts, mean, unit, and
content checksum. Replaying a node run is idempotent through the existing unique result/node
contract; a conflicting definition or image inventory is rejected.

## Project exchange

No new exchange sections are introduced. Existing computed definition/result sections contain the
new discriminator/configuration columns. Aggregate validation runs before import and checks every
definition, source snapshot, observation inventory, group total, summary value, workflow link, and
content checksum.

Remapping rewrites only declared project relationships: project, definition, image, annotation,
mask, label-class, workflow-run, and workflow-node IDs. Group-key strings, original filenames,
source types, capture timestamps, and arbitrary image metadata remain literal evidence. Import
rebuilds snapshots from remapped source rows and marks irreproducible or missing source inventory as
an atomic failure.

## Testing and acceptance

- API tests cover empty preview, true-zero refusal, single/multiple sources, mixed classes,
  verified-mask filtering, pending proposal exclusion, duplicate image rejection, multiple images,
  missing group assignments, and group-key pseudoreplication prevention.
- Mutation tests cover deleted/modified sources and stale result reporting.
- Workflow tests prove standalone/workflow equality, persisted lineage, idempotence, and atomic
  failure.
- Migration tests exercise `0040 -> 0041 -> 0040 -> 0041` while preserving scalar rows.
- Exchange tests prove ID remapping, literal group-key preservation, replay after import, tamper
  rejection, and atomic rollback.
- Frontend tests prove preview, visible exclusions/sample sizes, calculation, saved provenance,
  stale state, and CSV link behavior.
- Existing scalar, scientific exchange, event, annotation, workflow, backend, and frontend gates
  remain green.

## Scientific interpretation and remaining work

This slice produces descriptive counts only. Annotation/mask count is not density, abundance,
coverage, biomass, or a claim of independent organisms. `n` is the declared image or group-key unit
count, never the number of annotations. Group-key semantics remain the researcher's responsibility
and are recorded verbatim.

Exact mask union coverage, calibrated physical area, count per calibrated area, ROI denominators,
parent/child subjects, treatment/timepoint configuration, repeated-measures summaries, and broader
group statistics remain follow-on work. Those features must extend this discriminator/configuration
contract rather than bypass it.
