# Phase 6: Video and fish tracking

## Status

The Phase 6 core workflow is code-complete in this branch and has deterministic
software-acceptance coverage. It is not yet validated for scientific tracking quality on
representative fish videos, long-video performance, codec coverage on packaged Windows builds, or
packaged-desktop operation. Synthetic trajectories and mocked detector/tracker output validate
software contracts only; they are not evidence of biological or tracker accuracy.

Persistence hardening is introduced by Alembic revision
`0030_phase6_tracking_hardening`. Applied migrations remain unchanged.

## End-to-end workflow

The implemented local-first path is:

1. import a video into project-managed storage;
2. inspect persisted metadata, stream the source, and request exact source frames;
3. select a compatible registered detection model and ByteTrack or BoT-SORT;
4. run tracking asynchronously through the existing job worker;
5. review persisted tracks and correct observations or identities with optimistic revisions;
6. save scalar calibration and rectangular analysis zones;
7. persist deterministic trajectory, behavior, heatmap, and schooling summaries;
8. evaluate candidate tracking against explicitly selected verified ground-truth tracks; and
9. create restart-safe data or rendered-video artifacts with provenance and checksums.

Original source videos and frames are never modified.

## Managed video storage and playback

Imports support MP4, MOV, AVI, MKV, and M4V containers. The storage layer:

- streams uploads to a temporary project-local file while computing SHA-256;
- rejects unsafe names, missing sources, unsupported media, and unreadable containers;
- probes width, height, frame count, FPS, duration, and codec with OpenCV;
- atomically publishes a managed project-relative source path;
- deduplicates imports by project and source checksum;
- cleans temporary files after success or failure; and
- resolves managed paths beneath the configured data root before reads or deletes.

The API exposes inline source playback and exact zero-based frame access. Frame-extraction jobs use
atomic publication, progress and heartbeat updates, cancellation checks, and failure cleanup.

## Tracking-job lifecycle

Tracking requests select a managed video, a compatible registered detection model, ByteTrack or
BoT-SORT, confidence and IoU thresholds, a frame stride, tracker-specific options, and `auto`, `cpu`,
or `cuda` device resolution.

The ML adapter owns Ultralytics-specific model and tracker integration. The worker validates project
ownership, detector task compatibility, managed model paths, and checksums before inference. It
records:

- source-video ID and checksum;
- detector model ID, checksum, provider, and provider version;
- tracker name and complete resolved configuration;
- confidence and IoU thresholds, frame stride, and resolved device;
- per-observation class, confidence, box, centroid, frame, and timestamp; and
- the originating job ID.

The worker accumulates results before committing tracks, observations, audit events, and final job
state in one database transaction. Cancellation and failures roll back track state and remove
temporary tracker configuration. A canonical request fingerprint and originating-job constraint make
completed retries idempotent instead of creating duplicate tracks. Progress, cancellation, clean
structured errors, and restart-safe terminal job state use the existing job system.

BoT-SORT appearance ReID is not enabled because Phase 6 does not download or silently select an
external ReID checkpoint. Its supported local configuration and motion-association path are still
separate from ByteTrack and covered by acceptance tests.

## Track persistence, correction, and provenance

Tracks have public UUIDs, stable video-local track numbers, optional project classes and names,
source type, soft-deletion state, an integer revision, and detector/tracker origin metadata.
Observations have stable UUIDs and preserve frame number, timestamp, source-pixel box, optional
centroid, confidence, class, deletion state, and manual-edit metadata.

Correction endpoints support:

- adding, moving, resizing, deleting, and restoring observations;
- changing a class or track label;
- soft-deleting and restoring a track;
- splitting a track at a selected frame;
- merging two tracks;
- correcting an identity switch from a selected frame; and
- reassigning selected observations between tracks.

Every correction checks the expected revision, and repeated operation UUIDs replay the prior result.
Validation rejects cross-video assignments, duplicate active observations at a frame, invalid frame
numbers, boxes outside the source frame, negative geometry, and zero-area boxes. Multi-track
operations are transactional. Corrections append a `VideoTrackEvent` audit record containing before
and after state; the original automated snapshot and detector/tracker provenance are retained rather
than rewritten as human ground truth.

## Calibration, trajectories, zones, and behavior

Calibration is an optional positive scalar distance-per-pixel plus a user-supplied physical unit.
Without valid calibration, results are explicitly pixel-based and every physical distance, speed,
acceleration, centroid, spread, and wall-distance field is `null`. A calibration does not imply lens
correction, perspective correction, or a planar homography.

Track samples retain both frame number and time in seconds. A persisted observation timestamp is used
when present; otherwise time is derived from frame number and positive video FPS. For consecutive
valid samples with elapsed time `dt`:

- step distance is Euclidean centroid distance;
- speed is `distance / dt`;
- acceleration magnitude is `abs(speed[i] - speed[i-1]) / dt`;
- turning angle is the unsigned angle between adjacent non-zero displacement vectors;
- angular-velocity magnitude is `turning angle / dt`;
- total path length is the sum of valid step distances;
- net displacement is the first-to-last centroid distance; and
- tortuosity is path length divided by non-zero net displacement.

Missing frames retain their actual elapsed interval. Duplicate or non-increasing timestamps are
skipped with a warning and do not become false zero-speed samples. Results are ordered
deterministically, include their analysis configuration, calibration revision, source-track
revisions, and a canonical result checksum, and may be stored as immutable `VideoAnalysisRun`
records.

Saved rectangular zones support revisioned create, update, list, and delete operations. Analysis
reports deterministic entry/exit events and residence time. It also reports source-coordinate
trajectories, occupancy heatmaps, distance to the rectangular frame boundary, pairwise distance,
nearest-neighbor distance, school centroid, RMS school spread, and polarization from available
non-zero movement directions.

## Tracking evaluation

Persisted evaluation requires the user to identify which active tracks are verified ground truth and
which tracking job is the candidate. If no verified ground truth exists, the API returns a clear
non-evaluable result and warning rather than inventing a score.

For a configured IoU threshold, evaluation reports:

- localization IoU over matched boxes;
- observation-level detection precision and recall;
- false-positive and false-negative observations and tracks;
- per-frame matches and counts;
- per-ground-truth-track coverage, continuity, and fragmentation;
- identity switches;
- mostly-tracked and mostly-lost counts; and
- aggregate per-track summaries.

Stored results preserve candidate tracker, job, detector, thresholds, source revisions, configuration,
and checksum. Listing stored evaluations enables ByteTrack/BoT-SORT and confidence-threshold
comparisons, but synthetic comparisons are software acceptance only.

## Exports

Quick endpoint exports remain available for CSV, MOTChallenge text, and ReefVision JSON. Managed data
exports atomically publish a ZIP artifact containing:

- video metadata and calibration;
- tracks and observations with IDs, frames, timestamps, boxes, centroids, classes, confidence,
  manual-edit state, and provenance;
- trajectory, zone-event, behavior, and evaluation JSON when requested;
- CSV, ReefVision JSON, MOTChallenge, and NumPy formats as selected; and
- a manifest with schema version, source revisions, provenance, per-file SHA-256 checksums, and the
  complete artifact checksum.

Rendered-video jobs write to a temporary path and atomically publish only after encoding succeeds.
Both data and rendered exports create normal `ArtifactRecord` rows with project-relative managed
paths. A database-finalization failure removes an already-published file so corrupt or orphaned
partial exports are not presented as complete. Artifacts remain readable after ReefVision restarts.

## Desktop workflow

The Video dashboard provides:

- upload, video selection, persisted metadata, playback, seek, and exact-frame access;
- detector/tracker/device/threshold/stride/tracker-option controls;
- job progress, cancellation, terminal errors, and completion refresh;
- source-coordinate track, trajectory, and zone overlays;
- track selection, metadata editing, observation add/update/delete/restore, merge, split, identity
  correction, and observation reassignment;
- calibration and saved-zone editing;
- movement, schooling, behavior, heatmap, and evaluation views; and
- managed data exports, rendered-video exports, and quick tabular downloads.

Pending mutations disable repeat submission. Video switches clear selected tracks, active-job state,
and video-scoped mutation results so stale overlays are not reused. React Query invalidation refreshes
video, track, analysis, evaluation, zone, job, and export state after successful operations. Automatic
and manually edited observations use distinct overlay styling.

## Automated software acceptance

Deterministic backend tests cover import/storage/restart behavior, exact frame indexing, ByteTrack and
BoT-SORT request paths, multi-object and multi-class persistence, empty detections, detector
validation, device resolution, cancellation, failure rollback, retry idempotency, artifact cleanup,
track corrections and conflicts, calibrated and uncalibrated behavior formulas, missing timing data,
evaluation edge cases, managed export contents/checksums, rendered export publication, and literal
application restart reads.

Frontend tests cover video selection, stale-state clearing, tracker options, job pending/completion/
failure/cancellation states, overlays, observation and identity editing controls, calibration, zones,
behavior, evaluation, and export submission. Existing application tests retain non-video navigation
coverage.

The tiny synthetic observations and mocked detector/tracker outputs used by these tests validate
indexing, transactions, identity bookkeeping, metrics, and serialization only.

## Remaining validation and limitations

- Tracking and identity-switch quality must be measured on representative, manually verified fish
  videos before scientific use.
- Long-video memory, throughput, cancellation latency, and export size have not been characterized.
- Codec/container behavior requires representative Windows and packaged-desktop testing.
- Packaged-desktop installation and smoke testing are outside this implementation pass.
- BoT-SORT appearance ReID needs an explicitly managed compatible local checkpoint before it can be
  enabled safely.
- Zones are axis-aligned source-frame rectangles; polygonal arenas are not implemented.
- Calibration is a scalar conversion and cannot correct camera perspective or optical distortion.
- No synthetic acceptance result should be cited as tracker performance on real fish.
