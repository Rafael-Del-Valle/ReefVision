# Phase 6 — Video and Fish Tracking

## Scope

Phase 6 adds managed project videos, frame review, editable sparse tracks, detector-plus-tracker inference, calibrated trajectory and behavior summaries, schooling/occupancy analysis, and research-oriented track exports while retaining original source-video pixel coordinates.

## Implemented vertical slice

- managed video upload into project storage
- SHA-256 duplicate detection
- OpenCV metadata inspection
- original-video content streaming and desktop playback
- background frame extraction with a configurable stride
- persisted extraction status, frame directory, job reference, and revision
- exact extracted-frame content endpoint
- revisioned sparse bounding-box tracks
- human and machine-generated track provenance
- detector and instance-segmenter support for automated tracking
- provider-neutral video tracking interface
- Ultralytics detection plus ByteTrack or BoT-SORT
- model-label to project-class mapping
- minimum-track-length filtering
- linear and hold interpolation
- editable track identity, class, status, and keyframes
- soft deletion
- path length, displacement, duration, mean speed, maximum speed, mean footprint, and 3×3 occupancy summaries
- optional distance-per-pixel physical calibration stored with the managed video
- calibrated physical distance and speed conversion
- active/inactive time from a user-selected speed threshold
- rectangular-zone occupancy time
- configurable occupancy heatmaps
- frame-level active-fish count
- frame-level mean nearest-neighbor distance
- frame-level school spread
- CSV trajectory export
- MOTChallenge-compatible trajectory export
- ReefVision JSON export with source-video and track metadata plus interpolated frames
- project Video Tracking workspace with tracker selection, calibration, behavior analytics, and export controls

## Coordinate contract

All stored keyframes use the original source-video dimensions and the bounding-box form:

```text
[x, y, width, height]
```

where `x` and `y` are the upper-left source pixel coordinates. Interpolated boxes, trajectory summaries, occupancy, schooling calculations, and exports are computed from this immutable source-coordinate contract.

## Machine-tracking contract

A tracking run requires a registered detector or instance-segmentation model. Provider class names must map to ReefVision project classes through the registered model class map. Unmapped labels are reported in the job result and are not silently assigned.

The supported Ultralytics tracker configurations in this milestone are:

- `bytetrack.yaml`
- `botsort.yaml`

Machine tracks remain editable and start with status `machine_generated`. A human may change the class, adjust keyframes, and mark the track verified.

Each generated track preserves reproducibility metadata including provider/version, tracker configuration, confidence and IoU thresholds, device request, minimum-track rule, detector-model SHA-256, source-video SHA-256, and mean detection confidence. The source model and source job are retained as first-class references.

## Calibration and scientific interpretation

Pixel-space outputs are always available. Physical values are produced only when the user supplies a positive distance-per-pixel calibration and physical unit. The calibration is stored in managed video metadata and increments the video revision.

A single distance-per-pixel value assumes the image scale is sufficiently constant across the relevant movement plane. Perspective distortion, lens distortion, camera movement, water refraction, depth changes, and non-planar movement can make a single 2D scale biologically inappropriate. ReefVision therefore retains the raw pixel-space values alongside any physical conversion.

Activity is an operational measurement defined by the user-selected pixel-speed threshold. Schooling outputs in this milestone are geometric summaries—active track count, mean nearest-neighbor distance, and spread—not a biological classification of schooling behavior.

## Export contract

### CSV

Exports one row per interpolated frame/track observation with source frame, timestamp, track number, ReefVision class ID, center coordinates, bounding box, and confidence when the frame was directly observed.

### MOTChallenge

Exports one-based frame numbering and the conventional ten-column tracking representation. ReefVision track numbers are used as identity IDs. Fields without an applicable value are written using the conventional `-1` placeholders.

### ReefVision JSON

Uses format marker `reefvision_video_tracks_v1` and preserves managed video metadata, persisted track records/provenance, and interpolated frame geometry. This is the preferred loss-minimizing ReefVision-native research export.

## Automated acceptance gate

The permanent Milestone 6 workflow is required to verify:

1. Ruff lint and formatting for all Milestone 6 backend files
2. managed import and duplicate-safe video records
3. actual frame-extraction worker execution and extracted-frame retrieval
4. sparse-track interpolation and revision conflict handling
5. calibrated behavior analytics, activity, zones, schooling, and heatmap totals
6. CSV, MOT, and ReefVision JSON export generation
7. ByteTrack and BoT-SORT tracking-job contracts
8. generated-track provenance
9. migration upgrade through `0021`, downgrade to `0020`, and re-upgrade
10. frontend formatting, TypeScript, and focused Video Tracking workspace tests

As of August 8, 2026, GitHub-hosted jobs are blocked before checkout by the repository/account Actions billing or spending-limit state. The code must not be treated as CI-validated until GitHub can assign a runner and execute these steps.

## Required real-data and packaged-desktop validation

Automated tests do not replace the following release checks:

1. import and playback of representative real fish videos
2. correct metadata and extraction for those codecs/containers
3. real detector plus ByteTrack inference
4. real detector plus BoT-SORT inference
5. manual correction and restart persistence
6. comparison of trajectory, speed, activity, occupancy, and schooling outputs with manually checked footage
7. CSV/MOT/ReefVision JSON round-trip through representative consumers
8. packaged Windows application/MSI import, playback, extraction, tracking, analytics, and export acceptance
9. quantitative localization and identity-switch comparison against manually annotated fish trajectories
10. regression confirmation that earlier annotation, segmentation, measurement, and classification workflows still function

## Known limitations

- tracks currently use bounding boxes only
- automatic identity reconciliation across separate tracking runs is not implemented
- occlusion-specific quality flags are not yet exposed
- physical conversion uses a single user-supplied 2D distance-per-pixel scale and does not infer 3D movement
- activity depends on a user-selected speed threshold
- nearest-neighbor distance and school spread are descriptive geometric summaries rather than learned behavior labels
- frame extraction stores JPEG review frames and may require substantial disk space for long videos
- automated tracking uses the full video and does not yet support time-range selection
- real-world fish tracking accuracy and identity-switch performance remain scientific validation gates rather than assumed properties of the software
