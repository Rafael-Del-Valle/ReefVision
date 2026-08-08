# Phase 4: Coral Measurements

## Status

Implementation is present on `feat/coral-measurements-phase4`. Automated validation and installed-app acceptance are intentionally deferred.

This branch is stacked on `feat/semantic-segmentation-nnunet`. It does not merge, replace, or mark the Phase 3/3E branches ready.

## Scientific boundary

ReefVision keeps source-image pixel geometry as the exact measurement record. Physical-unit and three-dimensional values are derived estimates that are only returned when the image has an explicit calibration and, where required, a documented surface-model assumption.

The Phase 4 slice supports verified polygon and raster masks.

## Implemented measurements

Per mask:

- source-pixel area
- source-pixel perimeter
- centroid and bounding extent
- contained bounding-box count
- density per 1,000 mask pixels
- density filtered by project class, scientific name, and state
- physical area and perimeter after calibration
- density per square physical unit
- editable source-coordinate centerline
- total linear extension in pixels and physical units
- optional surface-area estimates

## Calibration

Calibration is stored in the source image metadata under `measurement_calibration` and includes:

- distance per pixel
- physical unit
- source or method
- optional reference length and measured pixel length
- optional default depth or thickness
- notes

Images without calibration continue to return the original pixel measurements and explicitly report that physical measurements are unavailable.

## Revisioned measurement profile

Migration `0019` adds `measurement_json` to each mask annotation. The profile stores:

- centerline points
- selected surface model
- optional depth override
- optional diameter override
- notes

Profile updates require the current mask revision. A successful update:

- increments the mask revision
- increments the image annotation revision
- writes a `measurement_updated` mask audit event
- invalidates stale measurement results in the editor

## Centerline and total linear extension

The mask workspace adds a **Centerline** tool for one selected persisted mask. Points are stored in original source-image coordinates.

Editing behavior:

- click empty canvas space to add a point
- drag a point to reposition it
- double-click a point to remove it
- clear, cancel, or save the draft
- reject one-point and consecutive-duplicate centerlines
- reject points outside the source image

Total linear extension is the sum of Euclidean distances between consecutive points. ReefVision does not automatically infer biological branch topology in this slice.

## Surface-area models

### None

No three-dimensional estimate is reported.

### Closed planar extrusion

The mask is treated as a planar footprint extruded through a depth:

```text
surface area = 2 × projected area + perimeter × depth
```

Depth comes from the mask profile or the image calibration default.

### Equivalent centerline cylinder

The centerline is treated as the axis of an equivalent cylinder:

```text
surface area = π × diameter × total linear extension
```

A diameter can be supplied explicitly. When omitted, ReefVision estimates an equivalent diameter as projected area divided by total linear extension. Every response includes the assumptions used.

These models are geometric approximations and are not substitutes for photogrammetry, depth reconstruction, or direct surface scanning.

## Density filters

Contained boxes are counted using their center points. Users can restrict counts by:

- label-class ID
- scientific name
- state name

Filters use the existing project label-class metadata, including coral species and open/closed state definitions.

## Exports

Project measurement exports are available as:

- UTF-8 CSV
- NumPy bundle ZIP

The NumPy bundle contains:

```text
measurements.npy
columns.json
rows.json
```

`measurements.npy` is a float64 matrix. Missing physical values are represented as `NaN`; row identifiers and nonnumeric metadata remain in `rows.json`.

## API surface

```text
GET    /api/v1/images/{image_id}/measurement-calibration
PUT    /api/v1/images/{image_id}/measurement-calibration
DELETE /api/v1/images/{image_id}/measurement-calibration

GET /api/v1/mask-annotations/{mask_id}/measurement-profile
PUT /api/v1/mask-annotations/{mask_id}/measurement-profile
GET /api/v1/mask-annotations/{mask_id}/measurements

GET /api/v1/projects/{project_id}/measurement-export?format=csv
GET /api/v1/projects/{project_id}/measurement-export?format=numpy
```

## Deferred validation gates

Before Phase 4 is considered usable:

1. Run Ruff lint and formatting.
2. Run strict mypy.
3. Run all backend tests, including migration `0019`, calibration, centerline, filter, surface-model, CSV, and NumPy tests.
4. Run Alembic upgrade and downgrade.
5. Run Prettier, TypeScript, Vitest, and Playwright.
6. Build the backend sidecar, Tauri executable, and MSI.
7. Run `scripts/phase4-acceptance.ps1` against the tested commit.
8. Confirm existing box, mask, detection, instance-segmentation, and semantic-segmentation workflows are unchanged.

## Known limitations

- Calibration is currently entered numerically; an interactive scale-bar drawing tool is not included yet.
- Centerlines are single ordered polylines, not branching graphs.
- Centerlines are not automatically constrained to remain inside a mask.
- Surface-area models are explicit approximations rather than depth-derived reconstructions.
- Batch filters are exposed through measurement requests; a dedicated project analytics dashboard remains future work.
- Project JSON interoperability for calibration and measurement profiles needs a later Phase 9 schema update.
- Scientific agreement against manual TLE or physical surface measurements remains unvalidated.
