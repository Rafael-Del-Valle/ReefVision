# Phase 6: Video and fish tracking

## Status

Feature-complete first release in code. Real-detector tracking quality, identity-switch analysis, migration, restart, and packaged-Windows acceptance remain release gates.

## Managed video workflow

ReefVision imports MP4, MOV, AVI, MKV, and M4V files into the project-managed store. Import:

- streams the source to disk;
- computes SHA-256 while writing;
- detects duplicates within the project;
- reads width, height, frame count, FPS, and duration with OpenCV;
- never modifies the source frames;
- serves the managed source inline for desktop playback.

## Track creation and correction

Tracks use sparse bounding-box keyframes with stable track numbers. They support:

- human-created or generated tracks;
- optional project class assignment;
- linear or hold interpolation;
- editable keyframes, class, interpolation, and status;
- deletion and recreation;
- validation against video frame and image bounds.

Generated tracks remain editable, allowing identity and geometry correction after automated tracking.

## Automated tracking

A project detector can launch:

- **ByteTrack**;
- **BoT-SORT**.

The background job records:

- detector model ID and checksum;
- provider and provider version;
- tracker and tracker configuration;
- confidence and IoU thresholds;
- frame stride and device;
- source-video checksum;
- predicted label and resolved project class;
- per-frame confidence.

Generated tracks can replace prior generated tracks without deleting verified human tracks.

## Calibration and analytics

Video-level calibration converts pixels to a user-defined physical unit.

Per-track analytics include:

- first and last frame;
- observed/interpolated frame count;
- duration;
- trajectory distance;
- mean and maximum speed;
- active and inactive time using a configurable speed threshold;
- physical distance and speed when calibrated;
- time spent in user-defined rectangular zones.

School-level analytics include:

- active tracks per frame;
- mean nearest-neighbor distance;
- school spread around the frame centroid;
- physical versions when calibrated.

Occupancy heatmaps use configurable horizontal and vertical bin counts and report observation counts and occupancy seconds per cell.

## Research exports

- **CSV:** frame/time, track ID, class, center, box, confidence.
- **MOTChallenge:** standard frame, identity, box, confidence rows.
- **ReefVision JSON:** video metadata, sparse tracks, generated provenance, and fully interpolated keyframes.

## Desktop workflow

The Video tab provides:

1. managed video upload and selection;
2. inline playback and metadata;
3. physical calibration;
4. detector, ByteTrack/BoT-SORT, threshold, and stride selection;
5. automated tracking jobs;
6. manual track creation and generated-track correction;
7. zones, activity threshold, and heatmap settings;
8. movement, schooling, activity, and occupancy results;
9. CSV, MOT, and ReefVision JSON downloads.

## Validation included

- track creation and interpolation;
- calibration and physical conversion;
- distance, speed, activity, zone, school, and heatmap calculations;
- CSV, MOT, and JSON export structure;
- detector/tracker job configuration and provenance;
- track class and frame-bound validation.

## Remaining release validation

- Alembic upgrade/downgrade through revisions `0021` and `0022`;
- full Ruff, mypy, pytest, TypeScript, Vitest, Playwright, and production build;
- real detector runs with ByteTrack and BoT-SORT;
- manual reference comparison for track continuity, localization error, and identity switches;
- long-video memory and throughput testing;
- codec/container testing on Windows;
- restart persistence and packaged-Windows smoke testing.
