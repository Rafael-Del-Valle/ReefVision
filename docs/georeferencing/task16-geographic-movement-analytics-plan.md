# Task 16 — Geographic Movement Analytics

## Goal

Add scientifically explicit movement analytics for persisted georeferenced video observations.

Task 16 builds on:

- Task 10 canonical `GeoReferencedObservation`
- Task 12 persistence
- Task 13 georeferenced observation API
- Task 14 geographic map UI
- Task 15 bidirectional video/map synchronization

The analytics layer must use persisted geographic coordinates and timestamps as authoritative inputs.

The frontend must not independently recalculate geographic distance, speed, or trajectory metrics.

---

## 1. Scope

Task 16 should provide:

- segment distance
- elapsed time
- segment speed
- cumulative track distance
- net displacement
- total elapsed track time
- mean movement speed
- maximum valid segment speed
- movement observations in temporal order
- track-level movement summary
- frame/time references for linking analytics back to video and map

Task 16 should NOT yet provide:

- uncertainty propagation
- uncertainty-radius visualization
- behavioral classification
- smoothing of trajectories
- interpolated geographic positions
- inferred positions for missing frames
- GeoJSON/CSV export
- recalculation/version history

Those remain separate roadmap items.

---

## 2. Unit of Analysis

The primary analytics unit is a persisted `track_id`.

Only observations belonging to the same track are joined into movement segments.

Observations with:

`track_id = null`

remain valid geographic observations, but they do not form a tracked movement trajectory unless a later workflow explicitly assigns them to a track.

A track requires at least two valid geographic observations to calculate movement distance or speed.

---

## 3. Observation Ordering

For each track:

1. Load persisted georeferenced observations.
2. Sort primarily by `frame_index`.
3. Preserve `frame_time_s`.
4. Do not reorder based on latitude, longitude, or spatial proximity.
5. Never infer missing frames.
6. Never interpolate missing positions.

Expected order:

Observation 1
-> Observation 2
-> Observation 3
-> ...

Each adjacent pair forms one movement segment.

---

## 4. Geographic Coordinate Policy

The stored geographic coordinates are authoritative.

Task 16 must use:

- latitude from the persisted georeferenced observation
- longitude from the persisted georeferenced observation
- CRS from the persisted observation

The analytics service must not:

- rerun georeferencing
- reinterpret representative pixels
- recalculate coordinates from telemetry
- change camera calibration
- modify geographic observations

Task 16 analyzes already-persisted geographic positions.

---

## 5. CRS Policy

Initial implementation should explicitly support the geographic CRS produced by the current ReefVision georeferencing pipeline.

Expected current CRS:

`EPSG:4326`

If an unsupported CRS is encountered:

- do not silently treat it as WGS84
- do not fabricate movement metrics
- return an explicit unsupported-CRS condition

A future extension may transform additional CRS values before analytics.

---

## 6. Segment Model

For consecutive observations A and B, create a movement segment containing:

- start observation ID
- end observation ID
- track ID
- start frame index
- end frame index
- start frame time
- end frame time
- start latitude
- start longitude
- end latitude
- end longitude
- elapsed time seconds
- distance meters
- speed meters per second
- cumulative distance meters
- optional bearing/departure direction if included in the first implementation

Suggested schema concept:

`GeographicMovementSegment`

Fields:

- `track_id`
- `start_observation_id`
- `end_observation_id`
- `start_frame_index`
- `end_frame_index`
- `start_frame_time_s`
- `end_frame_time_s`
- `elapsed_time_s`
- `distance_m`
- `speed_m_s`
- `cumulative_distance_m`

---

## 7. Distance Calculation

Distance should be calculated geographically rather than as Euclidean differences in latitude/longitude degrees.

Preferred implementation:

- one centralized backend geographic-distance function
- WGS84-aware distance calculation
- output in meters

Do not calculate:

`sqrt(delta_lat^2 + delta_lon^2)`

because latitude/longitude degrees are not linear metric coordinates.

Before selecting the implementation library, inspect existing ReefVision backend dependencies.

Prefer an already-installed geodesic implementation if one exists.

If a new dependency is required, add it deliberately and test it.

---

## 8. Time Calculation

For each segment:

`elapsed_time_s = end.frame_time_s - start.frame_time_s`

The original persisted `frame_time_s` values are authoritative.

Do not recompute segment time from:

`frame_index / fps`

when persisted frame timestamps already exist.

Frame indices remain useful identity and synchronization references, but movement timing should use persisted observation time.

---

## 9. Speed Calculation

For a valid segment:

`speed_m_s = distance_m / elapsed_time_s`

A segment is valid for speed calculation only when:

`elapsed_time_s > 0`

If elapsed time is zero or negative:

- preserve the segment identity
- do not divide by zero
- do not fabricate speed
- return `speed_m_s = null`
- expose a validity/reason field if needed

Suggested reason:

`non_positive_elapsed_time`

This allows bad or duplicate timestamp data to remain inspectable.

---

## 10. Track Summary

Suggested track-level schema:

`GeographicTrackAnalytics`

Fields:

- `track_id`
- `video_asset_id`
- `observation_count`
- `segment_count`
- `first_frame_index`
- `last_frame_index`
- `first_frame_time_s`
- `last_frame_time_s`
- `elapsed_time_s`
- `total_distance_m`
- `net_displacement_m`
- `mean_speed_m_s`
- `max_segment_speed_m_s`
- `start_location`
- `end_location`
- `segments`

Definitions:

### Total distance

Sum of valid consecutive segment distances.

### Net displacement

Geographic distance between the first and last valid observation.

### Elapsed track time

`last.frame_time_s - first.frame_time_s`

### Mean movement speed

Preferred initial definition:

`total_distance_m / elapsed_time_s`

when elapsed time is positive.

This should be explicitly documented as track-average movement speed, rather than the arithmetic mean of segment speeds.

### Maximum segment speed

Maximum non-null `speed_m_s` among valid segments.

---

## 11. Missing and Invalid Data

Task 16 should behave explicitly when data are incomplete.

### Zero observations

Return an empty/no-analytics response.

### One observation

Return:

- observation count = 1
- segment count = 0
- total distance = 0
- net displacement = 0
- no valid movement speed

### Null track ID

Do not construct a track trajectory.

### Duplicate frame index

Do not silently remove records.

Preserve deterministic ordering and flag ambiguity if necessary.

### Duplicate timestamp

Distance can still exist.

Speed must be null because elapsed time is zero.

### Negative time delta

Speed must be null.

### Unsupported CRS

Return an explicit unsupported-CRS result/error.

### Invalid geographic coordinate

Reject at schema/service boundary rather than calculating invalid movement.

---

## 12. Backend Service

Recommended file:

`apps/api/reefvision/services/geographic_movement_analytics.py`

Suggested responsibilities:

- retrieve observations for a track
- validate CRS compatibility
- sort observations
- compute segments
- compute track summary
- centralize distance calculation
- preserve observation IDs and frame identities

Suggested public method:

`analyze_track(track_id)`

Potential lower-level pure functions:

- `geographic_distance_m(...)`
- `movement_segment(...)`
- `summarize_track_movement(...)`

Keep the mathematical functions pure where practical so they are easy to test.

---

## 13. Backend Schemas

Recommended file:

`apps/api/reefvision/schemas/geographic_movement_analytics.py`

Suggested models:

- `GeographicMovementSegment`
- `GeographicTrackAnalytics`
- `GeographicTrackAnalyticsSummary`

Use explicit units in field names.

Prefer:

- `distance_m`
- `speed_m_s`
- `elapsed_time_s`

instead of ambiguous names such as:

- `distance`
- `speed`
- `duration`

---

## 14. API

Recommended first endpoint:

`GET /api/v1/video-tracks/{track_id}/geographic-analytics`

Response:

- track identity
- summary metrics
- ordered movement segments

Potential later video-level endpoint:

`GET /api/v1/videos/{video_id}/geographic-analytics`

The video-level endpoint could return lightweight summaries for all tracks.

The first implementation should prioritize the single-track endpoint because:

- movement is defined per track
- it has clear ownership semantics
- it avoids unnecessarily large responses
- it can directly support the selected/active track UI

---

## 15. API Validation

The endpoint should verify:

- track exists
- parent video exists
- observations belong to the requested track
- geographic observations are available
- CRS is supported

Expected behavior:

### Missing track

HTTP 404

### Track exists but no georeferenced observations

Return a valid empty analytics payload rather than inventing values.

### Unsupported CRS

Use an explicit client-visible error.

Do not silently calculate using the wrong coordinate system.

---

## 16. Frontend API Client

Recommended extension:

`apps/web/src/features/video/videoGeographicAnalyticsApi.ts`

Responsibilities:

- fetch track geographic analytics
- preserve backend numeric values
- avoid duplicating backend calculations
- expose typed summary and segment models

The frontend should not calculate distance or speed from coordinates.

---

## 17. Frontend Analytics Panel

Recommended component:

`GeographicMovementPanel.tsx`

Initial UI should show:

- selected track
- observation count
- total distance
- net displacement
- elapsed time
- mean speed
- maximum segment speed

Segment table:

- start frame
- end frame
- start time
- end time
- distance
- elapsed time
- speed

Selecting a segment should expose its frame references for integration with the existing Task 15 synchronization layer.

---

## 18. Map Integration

Task 16 should reuse Task 15 active track state.

When a tracked observation is active or selected:

- identify its `track_id`
- request analytics for that track
- display the track summary
- allow segment inspection

The map remains responsible for geographic visualization.

The analytics service remains responsible for scientific movement calculations.

No distance/speed calculations should be embedded inside `GeoreferencedMapPanel`.

---

## 19. Video Integration

Segment records should preserve:

- `start_frame_index`
- `end_frame_index`
- `start_frame_time_s`
- `end_frame_time_s`

This allows later UI behavior such as:

- jump to segment start
- jump to segment end
- inspect movement while video plays

Task 16 can expose these callbacks without introducing a second synchronization system.

Reuse the Task 15 video/map synchronization state.

---

## 20. Active Track Analytics

Recommended frontend behavior:

Playback frame
-> active geographic observation
-> active track ID
-> analytics query for active track
-> movement summary displayed

Changing active frames within the same track should not repeatedly refetch the same analytics.

Use React Query caching keyed by:

`["geographic-track-analytics", trackId]`

Changing to another track may request that track's analytics.

---

## 21. Race Safety

If playback changes tracks quickly:

1. Query for Track A may begin.
2. Playback changes to Track B.
3. Query for Track B begins.
4. A late Track A response must not replace Track B's visible analytics.

React Query keys and current active track identity should prevent stale data from becoming the current panel.

The rendered panel must always verify that returned analytics correspond to the currently requested track.

---

## 22. Precision and Presentation

Backend calculations should retain useful numeric precision.

Frontend display can round values for readability.

Example display:

- distance: meters
- speed: m/s
- elapsed time: seconds

Do not round values before calculations.

Do not convert persisted coordinates before analytics unless required by a documented CRS transformation.

---

## 23. Tests — Geographic Mathematics

Create backend tests for:

- zero-distance segment
- known short-distance geographic pair
- increasing latitude
- increasing longitude
- diagonal displacement
- identical coordinates at different times
- positive distance with positive time
- zero time delta
- negative time delta
- cumulative distance
- net displacement
- summary mean speed
- maximum segment speed

Use deterministic coordinate fixtures with known expected tolerances.

---

## 24. Tests — Track Semantics

Test:

- observations sorted by frame
- track identity preserved
- observation identity preserved
- frame identity preserved
- null-track observations excluded from track analytics
- no interpolation over missing frames
- duplicate timestamps do not produce infinite speed
- unsupported CRS is explicit
- one-observation track behaves correctly
- empty track behaves correctly

---

## 25. Tests — API

Test:

- successful track analytics
- missing track
- empty georeferenced track
- correct ownership
- ordered segments
- correct units
- invalid timing handling
- unsupported CRS behavior

---

## 26. Tests — Frontend

Focused tests should verify:

- analytics panel loads for active track
- no analytics request for untracked observation
- track summary renders
- segment rows render in chronological order
- loading state
- empty state
- API error state
- retry
- changing tracks changes analytics
- stale prior-track response does not replace active track
- repeated playback inside same track does not unnecessarily refetch
- displayed values are backend values rather than recomputed map values

---

## 27. Acceptance Criteria

Task 16 is complete when ReefVision can:

1. Load persisted observations for one track.
2. Order them deterministically.
3. Calculate WGS84-aware geographic segment distance.
4. Calculate elapsed segment time from persisted frame timestamps.
5. Calculate valid segment speed.
6. Avoid speed calculation when elapsed time is non-positive.
7. Calculate cumulative distance.
8. Calculate net displacement.
9. Calculate total elapsed time.
10. Calculate track-average movement speed.
11. Calculate maximum valid segment speed.
12. Preserve observation IDs.
13. Preserve track ID.
14. Preserve frame indices.
15. Preserve persisted frame times.
16. Reject or explicitly report unsupported CRS.
17. Expose analytics through a typed API endpoint.
18. Display analytics for the active/selected track.
19. Avoid analytics for null-track observations.
20. Avoid frontend geographic recalculation.
21. Avoid trajectory interpolation.
22. Avoid fabricated uncertainty.
23. Avoid stale-track UI races.
24. Pass focused backend tests.
25. Pass focused frontend tests.
26. Pass full regression.
27. Pass production build.

---

## 28. Suggested Implementation Sequence

### Task 16A — Scientific contract

Finalize:

- metric definitions
- CRS policy
- timing policy
- invalid-segment policy
- units
- acceptance tests

### Task 16B — Backend schemas and pure calculations

Implement:

- movement segment schema
- track summary schema
- geographic distance function
- segment calculations
- track summary calculations

### Task 16C — Analytics service

Implement:

- database retrieval
- track validation
- ordered observation preparation
- analytics orchestration

### Task 16D — API

Implement:

`GET /api/v1/video-tracks/{track_id}/geographic-analytics`

Add endpoint tests.

### Task 16E — Frontend API/state

Implement:

- typed API client
- React Query integration
- active-track analytics loading

### Task 16F — Analytics UI

Implement:

- summary
- segment table
- loading
- empty
- error
- retry

### Task 16G — Task 15 integration

Connect:

video playback
-> active observation
-> active track
-> geographic analytics

Do not introduce a competing playback synchronization mechanism.

### Task 16H — Validation

Run:

- backend focused tests
- frontend focused tests
- backend regression
- frontend regression
- typecheck
- production build
- git diff --check

---

## 29. Recommended First Coding Slice

Begin with Task 16A/16B only.

Create:

`apps/api/reefvision/schemas/geographic_movement_analytics.py`

`apps/api/reefvision/services/geographic_movement_analytics.py`

`apps/api/reefvision/tests/test_geographic_movement_analytics.py`

Do not touch the frontend until the scientific definitions and backend calculations are locked by tests.

This keeps geographic science logic centralized and makes the later UI a presentation layer rather than an independent analytics implementation.
