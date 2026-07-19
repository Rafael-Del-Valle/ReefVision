# Phase 4: Coral measurement validation

## Status

The Phase 4 measurement workflow is feature-complete in code. Representative manual-reference validation and packaged-Windows acceptance remain release gates.

## Existing measurements retained

ReefVision measures verified polygon and raster masks without modifying annotation geometry:

- pixel area and perimeter;
- centroid and bounds;
- calibrated physical area and perimeter;
- contained polyp-box count and density;
- class, scientific-name, and state filters;
- revisioned centerline profiles and total linear extension;
- extruded and cylindrical-centerline surface-area models;
- project summaries;
- CSV and NumPy exports;
- immutable dataset snapshots of measurement profiles.

## Manual-reference validation

`POST /api/v1/projects/{project_id}/measurement-validation` accepts one or more mask IDs and manually measured reference values.

Supported metrics include:

- `area_pixels`;
- `perimeter_pixels`;
- `area_physical`;
- `perimeter_physical`;
- `total_linear_extension_pixels`;
- `total_linear_extension_physical`;
- `surface_area_physical`;
- `contained_box_count`.

Each reference can specify a unit and tolerance percentage. A project-level default tolerance is used when a value-specific tolerance is omitted.

## Reported accuracy statistics

For each observation ReefVision reports:

- measured and reference values;
- signed error;
- absolute error;
- percent error when defined;
- tolerance;
- pass/fail.

For every metric/unit combination ReefVision reports:

- mean measured and reference values;
- mean signed bias;
- mean absolute error;
- root mean square error;
- mean absolute percentage error when defined;
- maximum absolute error;
- passed and failed counts.

Unavailable calibrated metrics and unit mismatches are skipped with explicit warnings rather than silently converted.

## Desktop workflow

The Measurements tab provides:

1. project-wide geometry, TLE, density, calibration, and surface summaries;
2. CSV and NumPy downloads;
3. a reference JSON editor;
4. validation execution;
5. metric-level bias, MAE, RMSE, MAPE, and tolerance results.

The comparison is read-only and never changes masks, profiles, calibration, boxes, or dataset versions.

## Validation included

- exact-match and tolerance-failure observations;
- calibrated physical values;
- metric summary calculations;
- unavailable physical-measurement warnings;
- unit-mismatch warnings;
- existing revision and immutable-snapshot behavior.

## Remaining release validation

- compare area, TLE, density, and surface estimates against representative manually measured coral fragments;
- define accepted error limits for each scientific output;
- run full Ruff, mypy, pytest, TypeScript, Vitest, Playwright, and production build;
- verify restart persistence;
- run the packaged-Windows acceptance workflow.
