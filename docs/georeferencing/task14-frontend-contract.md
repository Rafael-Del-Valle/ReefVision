# Task 14 — Georeferenced Map Frontend Contract

Status: Draft frontend contract
Depends on: Tasks 9–13
Next dependency: Task 15 video/map synchronization

## Purpose

Task 14 adds the frontend contract for displaying persisted georeferenced observations on a map.

The frontend must:

1. Load lightweight persisted geographic observations for a video.
2. Render geographic observation points without loading the complete scientific provenance payload for every point.
3. Load the complete canonical Task 10 GeoReferencedObservation only when a point is selected.
4. Keep map collection state separate from selected-point detail state.
5. Preserve frame_index and frame_time_s so Task 15 can synchronize the map with video playback.
6. Never recalculate latitude or longitude in the frontend.

The API response is authoritative for geographic coordinates.

---

## 1. API Calls

### Primary video observation collection

GET /api/v1/videos/{video_id}/georeferenced-observations

This is the primary Task 14 map endpoint.

Optional query parameters:

- track_id
- frame_index

Examples:

GET /api/v1/videos/{video_id}/georeferenced-observations?frame_index=123

GET /api/v1/videos/{video_id}/georeferenced-observations?track_id={track_id}

GET /api/v1/videos/{video_id}/georeferenced-observations?track_id={track_id}&frame_index=123

### Track-specific collection

GET /api/v1/video-tracks/{track_id}/georeferenced-observations

Use when the map is intentionally scoped to one track.

### Frame-specific collection

GET /api/v1/videos/{video_id}/frames/{frame_index}/georeferenced-observations

Use when the UI needs observations for one exact video frame.

### Observation detail

GET /api/v1/georeferenced-observations/{observation_id}

Use only when a specific geographic observation is selected.

Rule:

Collection endpoints feed the map.

The detail endpoint feeds the observation inspector.

Do not fetch full Task 10 provenance for every map point during initial map loading.

---

## 2. Lightweight Observation Fields

Each collection item contains:

### Identity

- id
- project_id
- video_asset_id
- track_id
- detection_id

### Video position

- frame_index
- frame_width_px
- frame_height_px
- frame_time_s

### Source image geometry

- bbox.x_min
- bbox.y_min
- bbox.x_max
- bbox.y_max

### Representative pixel

- representative_pixel.x
- representative_pixel.y
- representative_pixel.method

Representative pixel method may include:

- explicit
- bbox_center

The frontend must display the method returned by the API and must not silently substitute another method.

### Geographic position

- location.latitude_deg
- location.longitude_deg
- location.crs

The geographic position returned by the API is authoritative.

The frontend must not derive new latitude or longitude values from:

- bounding boxes
- representative pixels
- telemetry
- calibration
- video dimensions

### Georeferencing metadata

- uncertainty_available
- method_version
- created_at

---

## 3. Minimum Map Point State

A rendered geographic map point needs:

- observation ID
- track ID or null
- frame index
- frame time in seconds
- latitude
- longitude
- uncertainty availability

The map point does not initially require:

- full telemetry provenance
- full calibration provenance
- complete platform pose
- complete camera pose
- complete uncertainty record
- complete method record

Those fields are loaded on selection.

---

## 4. Initial Map Loading Flow

Expected flow:

Video selected

-> request lightweight observations

-> GET /api/v1/videos/{video_id}/georeferenced-observations

-> receive observation collection

-> store observation summaries

-> convert summaries into renderable map points

-> render map points

The frontend must not display an empty-state message while the initial request is still loading.

---

## 5. Point Click Flow

When a user clicks a map point:

1. Record the selected observation ID immediately.
2. Visually highlight the selected point immediately.
3. Open the observation inspector immediately.
4. Put the detail inspector into a loading state.
5. Request:

GET /api/v1/georeferenced-observations/{observation_id}

6. On success:
   - store the full observation detail
   - change detail state to success
   - populate the inspector

7. On failure:
   - keep the selected point visible
   - keep the map collection intact
   - change only the detail state to error
   - provide a retry action

A detail-loading failure must never remove the map.

---

## 6. Full Observation Detail

The selected observation detail uses the complete canonical Task 10 GeoReferencedObservation payload.

The frontend must retain all returned provenance.

Expected detail categories include:

### Identity

- id
- project_id
- video_asset_id
- detection_id
- track_id

### Frame geometry

- frame_index
- frame_width_px
- frame_height_px
- bbox
- representative_pixel

### Timing

- timestamp.frame_time_s
- timestamp.utc
- timestamp.source
- timestamp.fps

### Platform pose

- latitude
- longitude
- altitude
- height above surface
- yaw
- pitch
- roll
- heading reference

### Camera pose

- yaw
- pitch
- roll
- orientation source

### Calibration

- calibration ID
- calibration version
- checksum
- camera model
- image dimensions
- focal lengths
- principal point
- distortion model
- zoom state

### Telemetry

- source ID
- source type
- telemetry sample index
- synchronization method
- telemetry time
- signed time delta
- absolute time error
- synchronization tolerance
- field provenance

### Geographic result

- latitude
- longitude
- CRS

### Uncertainty

- available
- method
- unavailable reason where applicable
- future uncertainty values when Task 17 adds them

### Georeferencing method

- method name
- method version
- surface model
- representative pixel policy version
- synchronization version
- pose convention version

### Record metadata

- schema version
- created_at

---

## 7. Default Observation Inspector

The default non-expanded inspector should prioritize:

- latitude
- longitude
- frame index
- video time
- track ID
- representative point method
- uncertainty availability

An expandable Georeferencing Details section should contain:

- CRS
- method and version
- calibration ID
- calibration version
- telemetry source
- telemetry sample
- synchronization delta
- camera pose
- platform pose
- source bounding box
- representative pixel
- created timestamp

The purpose is to keep the normal UI readable while retaining complete scientific provenance.

---

## 8. Collection State

Collection state must support:

- idle
- loading
- success
- error

Collection state must independently retain:

- observations
- error message

The detail request has a separate state machine.

---

## 9. Detail State

Detail state must support:

- idle
- loading
- success
- error

Detail state must independently retain:

- selected observation ID
- selected full observation
- detail error message

A collection failure and a detail failure are not the same condition.

---

## 10. Initial Loading State

During initial collection loading:

- keep the map panel mounted
- show a loading indicator
- show a message such as:

Loading georeferenced observations...

Do not show:

No georeferenced observations

until the collection request has successfully returned an empty result.

---

## 11. Successful Empty State

A successful response with:

count = 0

and:

items = []

is not an error.

Display:

No georeferenced observations

This video does not currently have any persisted geographic observations.

Task 14 does not need to infer why observations are absent.

Georeferencing readiness remains a separate backend concept.

---

## 12. Initial Collection Error

If the first collection request fails:

- keep the map container mounted
- show an error state
- provide Retry

Recommended text:

Unable to load georeferenced observations.

Do not convert:

- 404
- network errors
- server errors
- invalid responses

into a valid empty collection.

---

## 13. Refresh Error With Existing Data

If geographic points were already loaded and a later refresh fails:

- retain existing observations
- retain existing rendered markers
- show a non-destructive refresh warning
- allow retry

Recommended text:

Could not refresh geographic observations.

Do not erase existing points solely because a refresh failed.

---

## 14. Detail Loading State

Point selection should feel immediate.

When the user selects a point:

- select the marker immediately
- open the inspector immediately
- display the known summary values immediately where possible
- show:

Loading observation details...

for fields that require the detail endpoint

Do not wait for the detail request to finish before highlighting the point.

---

## 15. Detail Error State

If observation detail loading fails:

- preserve the selected observation ID
- preserve the selected map point
- preserve all map observations
- display a detail-specific error

Recommended text:

Unable to load observation details.

Provide:

Retry

The collection request does not need to run again.

---

## 16. Rapid Selection / Request Race Protection

The frontend must protect against stale detail requests.

Example:

User selects point A.

Detail request A begins.

User selects point B.

Detail request B begins.

Request A completes after B was selected.

Request A must not overwrite point B's inspector.

Implementation must use one or both of:

- cancellation of the old request
- observation-ID verification before applying a completed response

The selected observation ID is authoritative for determining whether a detail response remains relevant.

---

## 17. Detail Cache

Full observation detail may be cached in memory for the lifetime of the active frontend session.

Cache key:

observation_id

Behavior:

If observation detail exists in the in-memory cache:

- display it immediately
- do not unnecessarily request it again

If it does not exist:

- request the detail endpoint
- cache the successful response

Task 14 should not require persistent browser storage.

---

## 18. Frame Synchronization Contract

Every map observation retains:

- frame_index
- frame_time_s

Point selection must make these values available to the parent video workspace.

Task 14 does not yet need to seek video playback.

Task 15 will connect:

map point selection

-> selected frame

-> video seek

and:

video playback position

-> active frame

-> map observation highlighting

Task 14 must therefore avoid discarding frame information.

---

## 19. Track-Aware Organization

Observations may be grouped by:

track_id

Within a track they must be ordered by:

frame_index

This supports future:

- track polylines
- trajectory visualization
- active-track highlighting
- movement analysis
- video/map synchronization

A null track_id is valid.

An observation without a track may still render as an independent geographic point.

---

## 20. API Client Responsibilities

The georeferencing frontend API client should provide equivalent operations for:

- list observations for video
- list observations for track
- list observations for frame
- retrieve one observation detail

The map component must not scatter raw API requests throughout unrelated UI components.

Network access should remain centralized in the frontend API layer.

---

## 21. Component Responsibility Boundary

Recommended responsibility structure:

Video Workspace

-> Georeferenced Map Panel

The map panel owns:

- map observation collection state
- map loading state
- map error state
- selected observation ID
- detail-loading state
- detail error state
- detail cache

The geographic map renderer owns:

- marker rendering
- selected-marker rendering
- point click events

The observation inspector owns:

- selected summary display
- detail loading indicator
- full provenance presentation
- detail retry action

The map renderer must not independently call the detail API.

---

## 22. Coordinate Rules

Task 14 frontend coordinate rules:

1. latitude_deg and longitude_deg come from the backend.
2. CRS must be preserved.
3. The frontend must not silently change CRS.
4. The frontend must not recalculate coordinates.
5. The frontend must not reinterpret representative pixels.
6. The frontend must not use bbox center unless the backend says representative_pixel.method is bbox_center.
7. Geographic provenance remains tied to the persisted observation ID.

---

## 23. Scientific Provenance Rules

The UI must not imply geographic precision that the backend has not established.

If uncertainty_available is false:

- do not fabricate an uncertainty radius
- do not display fake confidence circles
- show uncertainty as unavailable where relevant

Task 17 will expand uncertainty visualization.

The UI must preserve:

- method version
- calibration provenance
- telemetry provenance
- synchronization provenance
- representative point provenance

---

## 24. Task 14 Acceptance Criteria

Task 14 frontend contract is satisfied when the implementation can:

1. Open a video map view.
2. Request lightweight geographic observations.
3. Render the returned geographic points.
4. Preserve observation identity.
5. Preserve track identity.
6. Preserve frame_index.
7. Preserve frame_time_s.
8. Preserve latitude and longitude exactly as returned.
9. Display a loading state during the initial request.
10. Display a valid empty state after a successful empty response.
11. Display an initial-request error with Retry.
12. Retain existing points during a refresh failure.
13. Select a point immediately on click.
14. Load complete observation detail only after selection.
15. Display complete Task 10 provenance in the detail inspector.
16. Keep map state intact if detail loading fails.
17. Retry a failed detail request independently.
18. Prevent stale detail responses from replacing the current selection.
19. Cache successfully loaded observation detail in memory.
20. Group track-linked observations by track ID.
21. Order track observations by frame index.
22. Support observations where track_id is null.
23. Avoid frontend coordinate recalculation.
24. Avoid fabricated uncertainty.
25. Expose selected frame information for Task 15.

---

## 25. Task Boundary

Task 14 includes:

- observation collection loading
- geographic point rendering contract
- selection
- full observation detail loading
- loading states
- empty states
- error states
- detail caching
- request race protection
- frame-selection event contract

Task 14 does not yet include:

- automatic video seeking
- automatic map selection from video playback
- geographic distance analytics
- speed analytics
- uncertainty radius visualization
- GeoJSON export
- CSV export
- observation recalculation
- observation version history

Those remain Tasks 15–19.
