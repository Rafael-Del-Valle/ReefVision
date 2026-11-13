# Scientific and environmental context (1.1 development)

This development milestone adds project scientific records and a first
environmental provider. It is not the complete 1.1 release.

## Local researcher data

The Environmental Context workspace accepts a JSON file containing a
`records` array. This synthetic example illustrates the format; replace all
values, times and source descriptions with your own measurements:

```json
{
  "records": [
    {
      "variable": "water_temperature",
      "value": 20.0,
      "unit": "degC",
      "observed_at": "2026-04-03T13:00:00Z",
      "source_kind": "observed",
      "location": {
        "crs": "EPSG:4326",
        "latitude": 32.75,
        "longitude": -79.93
      },
      "depth_m": 5,
      "depth_reference": "sea_surface",
      "uncertainty": { "value": 0.2, "kind": "standard_deviation" },
      "qc": "unassessed",
      "provenance": {
        "source": "Replace with sensor and deployment identity",
        "dataset_id": "Replace with researcher dataset identity",
        "acquired_at": "2026-04-03T13:01:00Z",
        "processing_parameters": {},
        "source_metadata": {}
      }
    }
  ]
}
```

Each import is transactional, limited to 5,000 records, and creates immutable
records. Reimporting a local file creates another set of records; local-file
deduplication is not implemented. GET lists are paginated. A record may link
to `subject.image_id`, or `subject.video_id` with `frame_index`/`track_id`;
image objects may also name `annotation_id`, `mask_id` or `prediction_id`.
`model_run_id` references a supported inference/depth/tracking job in the
existing project job table, with matching input media. When a canonical
prediction, annotation, mask or track is named, its recorded source run must
match. Human objects without a source run cannot be attributed to a model job.
All IDs must belong to the same project and media; a reference never verifies
an annotation. Training, export and other operational jobs are not model
output identities in this API.

Pixel positions use `pixel: {frame: "image_pixels", x: 10, y: 20}` or
`video_pixels`, in original source pixels. Geographic positions are WGS84
latitude/longitude. Other CRS transformations are not yet supported. Times
require explicit offsets and are serialized as UTC. Depth is positive down
and requires its reference; omitted depth is unknown, not the sea surface.

Supported unit spellings: `m`, `cm`, `mm`, `km`, `m2`, `cm2`, `mm2`, `s`,
`min`, `h`, `m/s`, `cm/s`, `kn`, `degC`, `degF`, `K`, `PSU`, `g/kg`,
`count`, `1`, `degree`, `px`, `px2`. Original values/units remain in the
record alongside normalized values. Temperature uncertainty uses scale only,
without the absolute-temperature offset. Practical salinity and mass salinity
are separate dimensions; no PSU-to-g/kg conversion is assumed.

`source_kind` is required: `observed`, `remotely_sensed`, `modeled`, or
`derived`. Unknown uncertainty is null. Records with image calibration retain
the calibration snapshot and checksum; changing the canonical calibration
marks that snapshot as no longer current without rewriting the saved value.

## NOAA and offline reuse

POST `/api/v1/projects/{project_id}/environment/noaa` with:

```json
{ "station_id": "8665530", "day": "2026-10-16", "offline": false }
```

The initial adapter supports CO-OPS water temperature, one UTC day per request.
It stores the raw provider response, source URL, dataset identity, QC flags,
acquisition time and checksums. Missing values are skipped and counted;
nonfinite/malformed data and provider errors are rejected. Provider flags
remain visible; nonzero flags produce `suspect`, never automatic acceptance.
Sensor depth and uncertainty remain unknown when the response omits them.

The project cache is reused for 24 hours. A later online request refreshes it;
there is no unattended daily scheduler yet. Identical refresh payloads reuse
record IDs. Changed responses append a new acquisition snapshot. The record
API retains the immutable history and reports `environmental_snapshot_current`;
the workspace labels superseded provider snapshots. Normal environmental
lookup uses only the current snapshot, including when a correction removes a
sample or changes its QC to suspect. This avoids reusing an obsolete value
after a provider correction. Offline mode never makes a
network request; it returns a matching cache with `fresh` or `stale_offline`
status, or a missing-cache error. A failed online refresh leaves the prior
cache intact. No authentication is required for this NOAA endpoint. Copernicus
credentials, currents, salinity grids and local CSV import remain future work.

Protocol references:

- https://api.tidesandcurrents.noaa.gov/api/prod/
- https://api.tidesandcurrents.noaa.gov/api/prod/responseHelp.html

## Lookup and scientific limits

POST `/api/v1/projects/{project_id}/environment/lookup` with `variable`,
`location`, offset-aware `observed_at`, `max_distance_m`, and
`max_time_delta_s`. Optional depth filtering requires `depth_m`,
`depth_reference`, and `max_depth_delta_m`. Optional `source_kinds` restricts
the acquisition categories. Results report distance/time/depth offsets and
the original records; they are observations within bounds, not interpolated
estimates at an organism. Rejected/suspect records are excluded. A depth
criterion excludes records whose depth or reference is unknown/different.

WGS84 movement analytics now excludes stale or unknown-freshness coordinates.
`initial_bearing_deg` is the geodesic initial azimuth clockwise from true
north for each sampled movement segment. It is null for coincident positions;
it does not estimate organism body orientation. Projection uncertainty and
field-reference validation are still required before scientific acceptance.

## Compatibility and verification

Migration 0038 adds tables without rewriting existing image, calibration,
annotation or tracking data. Existing 1.0.x projects open through the normal
desktop migration path. Full database backups capture these records. Exchange
format 1.0 cannot preserve them: enriched projects refuse exchange export
until the format is extended. Legacy projects still export normally.

Synthetic tests cover migration upgrade/downgrade, units/UTC, invalid bounds,
identity ownership and matching source runs, transactional import, corruption,
calibration changes, provider corrections, cache freshness/offline, full backup
snapshot reuse and lookup exclusions. Live smoke
acceptance on 2026-10-18 acquired 240 Charleston station 8665530 observations
for 2026-10-16 and reopened all 240 from a disposable database offline with
unchanged IDs. This verifies acquisition/persistence, not sensor accuracy or
installed Windows behavior. No Windows/GPU/physical field acceptance is claimed.

## Project exchange in 1.1

Project exchange format `1.1` includes scientific records, environmental cache
entries, computed metric definitions/results and immutable environmental-event
definitions. This includes superseded environmental snapshots, original units, QC,
uncertainty, calibration snapshots, CRS, formula/algorithm versions, input snapshots,
workflow run/node linkage and definition/result checksums. Projects without any of
this enriched scientific state retain format `1.0`. Both versions can be imported;
other versions fail inspection explicitly.

An import creates a new project and fresh internal identifiers. Scientific subject
links and cache record links are remapped, checksums are recomputed, and the source
archive plus the identifier map remain import provenance. Literal source metadata,
raw provider responses and calibration snapshots retain their original values.
Import validates ownership, references and scientific integrity and commits once,
after media and artifact restoration. A failure rolls back all imported rows and
removes only the new import directory. Existing projects are never overwritten.

Computed results are accepted only when their archived definition, input record IDs,
input snapshots, timestamps, units, values, uncertainty and provenance hashes reproduce
the stored result under the recorded safe formula-engine version. Import remaps declared
project/scientific/workflow identifiers, rebuilds each input snapshot from the remapped
scientific records and recomputes the result checksum. Literal dataset IDs, provider
metadata and source URLs remain evidence and are not rewritten merely because their text
matches an internal UUID. The untouched source archive and its original identifiers stay
available as import provenance.

Environmental-event definitions retain their immutable typed threshold query and checksum;
saved workflow references are remapped through the existing workflow exchange inventory.
This portability slice does not add event aggregation, inferred onset/duration, tidal/lunar
context or causal interpretation.

## Reviewed annotation aggregate metrics

ReefVision can persist count definitions over either canonical bounding-box annotations or
verified masks. The sources remain separate. Only explicitly selected images whose annotation
status is `reviewed` are eligible; draft masks and model proposals are excluded. Accepted model
proposals count only after they have become canonical annotations or verified masks, with their
source provenance retained. A preview may show zero observations, but ReefVision refuses to save
that result because the current schema cannot distinguish a true observed zero from missing
annotation work.

Every definition declares one of two independence contracts. `image` treats each selected image
as one independent unit. `image_group_key` combines images with the same nonblank, researcher-
declared `group_key`; missing keys fail validation. ReefVision does not infer biological
replicates, subjects, colonies, treatments or time points. Results report observation count,
image count and independent-unit count separately, plus literal group totals, per-class totals
and the mean count per independent unit. The UI deliberately does not relabel annotation count
as a statistical sample size.

Saved results contain deterministic image, annotation/mask, label, proposal-exclusion and group
snapshots with definition, evidence and result SHA-256 values. The currentness endpoint rebuilds
the source inventory and reports explicit changes such as deletion, reclassification, mask
status/revision, image review status, group key or missing media. CSV emits an overall row and
one row per independent unit while retaining source IDs, sample-size fields, class counts,
workflow lineage and checksums. The executable `annotation_aggregate` Workflow Builder node uses
the same calculation service. Project exchange validates the archived totals against canonical
evidence, explicitly remaps project-owned IDs, preserves literal group keys, re-canonicalizes
ordering after UUID replacement and requires the imported result to validate as current before
commit.

This slice does **not** calculate mask union area, fractional coverage, calibrated physical area,
density, ROI summaries, generic subject hierarchies, treatment/timepoint models or inferential
statistics. Summing mask areas would double-count overlaps and is therefore not presented as
coverage. These remain follow-on scientific contracts rather than implicit behavior.

**Full application backup** copies the database and managed files for exact
restoration, preserving identifiers. **Project exchange** transfers a selected
project into a new independent project. Optional media/artifact inclusion still
applies to exchange; scientific cache payloads are included as scientific data,
not as model weights. Neither workflow includes provider credentials.

### Saved polygon regions and reference-plane coverage

In **Computed Metrics → Open verified mask coverage**, supply one source-image
polygon per selected image. The JSON list accepts objects with an `image_id` and
ordered `points` as `[[x, y], ...]`. An immutable coverage definition saves the
geometry independently of annotation classes. Simple concave polygons are
supported. Each polygon is tied to a project image and checked against its source
dimensions. Self-intersections, missing regions and foreign images fail
validation. The same source-pixel fill convention applies to ROI polygons and
verified polygon masks.

Select **Use reference-plane homography for physical values** only for a calibrated
planar scene. ReefVision takes the union in source-pixel space and maps each
disjoint pixel run as a rectangle onto the reference plane. It reports the
projected union, sampling area, ROI intersection and coverage. Pixel coverage is
retained when the transform is unavailable or invalid. Uncertainty information
supplied with the calibration remains in the snapshot. The area calculation does
not estimate a homography covariance or validate the calibration against surveyed
field controls. See [OpenCV's planar homography reference](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html).

Saved polygon and reference-plane definitions use `reefvision.mask-coverage.v2`.
Existing definitions retain their original calculation and hashes. The same
service runs standalone and through the saved `mask_coverage` Workflow Builder
node. CSV includes polygon coordinates, calibration method and the physical
coverage columns. Project exchange remaps project image IDs, preserves the polygon
coordinates and recalculates the result hashes. The calculation uses the existing
definition and result tables.

### Calibrated image heatmaps and saved workflows

Enable **Show scalar-calibrated density** to divide each layer's centroid count
by the calibrated cell area. The grid remains aligned to the source image. Its
legend and JSON report the physical area unit, density values, calibration
snapshot and hash. Missing or unsupported calibration keeps the source-pixel
counts available. This calculation assumes a uniform image scale and does not
estimate measurement uncertainty or physical density for a projective scene.

The **Scientific Heatmap** Workflow Builder node accepts a project and explicit
image ID plus grid, class and calibration options. It saves the same report as a
typed artifact with the evidence snapshot, content hash and calculation version.
Project exchange preserves the original evidence snapshot and binds a new result
hash to remapped project and image IDs.

### Sampling effort in environmental joins

Choose **Retain unmatched observations** to keep a row when a bounded environmental
match is unavailable. Matched and unmatched rows retain the observation ID and UTC
time, lag and target time. The saved result reports the requested, matched and
unmatched totals. Lagged analysis applies the same policy independently at each
lag. Omitting the option retains the original strict matching behavior.

An optional study assignment list identifies every selected observation by
`observation_record_id` and supplies `subject_id`, `experimental_unit_id`,
`experimental_unit_kind`, `treatment` and `timepoint`. Multiple fragments or
observations may share a declared tank. Counts describe sampling and reuse.
ReefVision does not estimate independence, significance or causality from these
associations. The evidence is available in standalone analysis, saved workflows,
the existing CSV export and project exchange.

### Migration-lineage coordination

This 1.1 branch owns `0038_scientific_data.py`, followed by
`0039_computed_metrics.py`, `0040_environmental_event_definitions.py` and the additive
`0041_computed_annotation_aggregates.py`. The last migration adds metric-kind discriminators and
aggregate configuration without rewriting scalar rows or hashes. Independent 1.6
work also published a different migration identified as `0038`. Neither published
migration may be renamed, combined or rewritten in its source branch. Eventual cross-version
integration must first preserve both branch histories, then add an explicit reconciliation
migration with a new unique revision ID and cross-version upgrade/downgrade tests.

## Subject-specific environmental inspection

The image annotation inspector and the video/frame/track workspace include
**Inspect environmental context**. Project scientific cards for geographic
position references expose the same inspector. The lookup is local and works
offline. Researchers set maximum spatial, temporal and depth separation, inspect
original source/QC/uncertainty and see provider-cache age explicitly.

A subject requires a `geographic_position` scientific record with WGS84 location
and an explicit UTC capture timestamp. The inspector can append this documented
reference; imported JSON can supply it too (`value: 1`, `unit: "1"` marks presence,
not a physical measurement). The subject identifiers must match exactly, including
frame, track and model run when provided. Multiple references require explicit
selection. Missing/suspect references and changed calibration produce unavailable
context. Station locations on environmental records are never subject locations.

Existing drone georeferencing supplies relative video time; it does not yet
establish UTC capture time. This milestone therefore does not automatically join
those outputs to ocean models. Supply a documented subject position/time reference;
no camera GPS coordinate is silently substituted for an organism's ground position.

## Copernicus Marine modeled data and ocean-current map

Open **Environmental Context → Open ocean current map**. Choose a cached dataset,
UTC time and depth. Direction arrows point toward the current's direction clockwise
from true north; speed is `hypot(eastward, northward)` in m/s. A stationary vector
has no direction. Components must share source kind, provider, dataset/version,
location, time and depth; duplicates, rejected/suspect values and superseded cache
snapshots are excluded. No spatial interpolation or particle/advection model is
applied. Arrow length is symbolic. Map extent and layer controls use the existing
Leaflet map. Basemap tiles are opt-in; cached vectors work offline without tiles.
WGS84 object overlays exclude stale georeferencing and are labeled spatial-only
until explicit UTC synchronization exists. The Web Mercator map excludes polar
vectors above 85° latitude; their exact values remain in the measurement list.

An east/north pair must also share the provider acquisition timestamp: observations
captured together must not be combined across different dataset refreshes. The
velocity table and map tooltip retain each component's **original uncertainty
kind** (standard deviation, standard error or bound) while displaying its
normalized numeric uncertainty in m/s. Unknown or invalid component uncertainty
stays explicitly unknown; a known zero remains zero. No vector-speed, bearing or
position uncertainty is inferred without the necessary covariance/position
evidence. A non-finite derived speed is not displayed, even when both individual
velocity components are finite.

**Acquire Copernicus modeled data** accepts an exact `cmems_mod_…` dataset/version,
variables `uo`, `vo`, `thetao`, `so`, WGS84 bounds, UTC interval and sea-surface depth.
Limits are 5° per horizontal axis, seven days, 5,000 scalar values and 90 seconds.
Split antimeridian requests. Only regular geographic time/depth grids are supported;
grid-relative velocities are rejected. `thetao` is stored as
`water_potential_temperature`, never mislabeled as in-situ temperature. Salinity
requires explicit `sea_water_practical_salinity` semantics and PSU/`1e-3` units;
ambiguous generic salinity fields require a dataset-specific scientific adapter.
Missing values are counted and skipped, never replaced. QC remains unassessed and
uncertainty remains unknown when the provider does not supply validated estimates.

The optional official [Copernicus Toolbox Python API](https://toolbox-docs.marine.copernicus.eu/en/stable/python-interface.html)
is used in an isolated local worker process. For a researcher-managed Python
runtime, the optional dependency is `reefvision[environmental]`. Configure the
backend environment (never project JSON, Git or an exchange archive):

- `REEFVISION_COPERNICUS_USERNAME` and `REEFVISION_COPERNICUS_PASSWORD`.
- `REEFVISION_COPERNICUS_PYTHON_EXECUTABLE`: absolute path to the Python executable
  containing the Toolbox. Required for a packaged desktop build; a source checkout
  defaults to its running interpreter.

ReefVision does not install that runtime or store those credentials. Secrets are
excluded from serialized settings and passed only through the worker environment.
Errors are sanitized. The small worker script is included in desktop packaging;
the optional Toolbox/xarray stack is not added to the default installer. Previously
cached subsets reopen without that runtime or credentials.

The cache refreshes after 24 hours on acquisition requests; explicit refresh and
cache-only controls are available. Unchanged payloads retain scientific record IDs;
changed datasets retain immutable historical observations. Dataset identity,
version, source URL, acquisition time, original CF unit/name, Toolbox version,
request bounds and available coordinate resolutions are preserved. Credentials,
provider live-data acceptance and packaged-runtime execution have not been claimed.
Synthetic xarray fixtures validate the worker, numerical interpretation, caching
and exchange independently of Copernicus access.

## Descriptive current-slice metrics (development)

The ocean-current workspace reports the number of paired records, unweighted
arithmetic mean speed, maximum speed, and magnitude/direction of the mean
velocity vector for a selected UTC time and depth datum. **Mean speed** and
**vector-mean speed** are different: opposing currents can have positive mean
speed but zero vector-mean flow, in which case direction is undefined. The
summary is suppressed when source, model version, acquisition, time, or depth
reference differs across records. These are descriptive statistics of eligible
records, not independent experimental replicates. No spatial weighting,
uncertainty propagation, confidence interval, organism transport, or advection
is inferred. Original immutable component records remain authoritative.

## Bounded environmental threshold samples (1.1 development)

POST `/api/v1/projects/{project_id}/environment/events/threshold` accepts the
same required location, UTC timestamp, distance/time bounds, optional depth
bounds and source-kind filters as `/environment/lookup`, plus
`threshold_value`, explicit `threshold_unit`, and `direction` (`above` or
`below`). For example, a threshold of 68 `degF` for `water_temperature`
is normalized to 20 `degC` before comparison. Incompatible physical units
are rejected; comparisons are strict, so equality is not an exceedance.

The response contains the original immutable scientific records, their
provenance and QC, and the space/time/depth offsets. Suspect, rejected,
calibration-stale and superseded-provider observations are excluded by the
bounded lookup. The method label is
`observed_sample_threshold_no_interpolation`: results identify **individual
samples**, not inferred onset/cessation times, durations, independent events,
or causal environmental effects. Sample uncertainty remains attached to its
source record; the threshold comparison does not claim statistical certainty.
This endpoint is read-only and does not persist new event artifacts. Event
aggregation, persisted event definitions and typed Workflow Builder execution
remain future work before 1.1 release acceptance.
