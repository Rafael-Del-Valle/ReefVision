# Scientific and environmental context (1.1 development)

This development milestone adds project scientific records and a first
environmental provider. It is not the complete 1.1 release.

## Local researcher data

The Environmental Context workspace accepts a JSON file containing a
`records` array. This synthetic example illustrates the format; replace all
values, times and source descriptions with your own measurements:

```json
{
  "records": [{
    "variable": "water_temperature",
    "value": 20.0,
    "unit": "degC",
    "observed_at": "2026-04-03T13:00:00Z",
    "source_kind": "observed",
    "location": {"crs": "EPSG:4326", "latitude": 32.75, "longitude": -79.93},
    "depth_m": 5,
    "depth_reference": "sea_surface",
    "uncertainty": {"value": 0.2, "kind": "standard_deviation"},
    "qc": "unassessed",
    "provenance": {
      "source": "Replace with sensor and deployment identity",
      "dataset_id": "Replace with researcher dataset identity",
      "acquired_at": "2026-04-03T13:01:00Z",
      "processing_parameters": {},
      "source_metadata": {}
    }
  }]
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
{"station_id": "8665530", "day": "2026-10-16", "offline": false}
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
