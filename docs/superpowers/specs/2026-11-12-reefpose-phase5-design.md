# ReefPose Phase 5 Biological Movement Design

Date: 2026-11-12  
Branch: `feature/reefpose-core`  
Starting commit: `1d75641d92cc5510c10573bbd56a62ecdeba81f2`

## Intent

Phase 5 turns source-coordinate anatomical landmark trajectories into reproducible
measurements, deterministic movement-cycle events, scientist-reviewed event revisions,
and provenance-preserving exports. Researchers should be able to complete routine
movement analysis inside ReefVision without maintaining separate scripts, while retaining
the distinction between model observations, derived measurements, automated candidate
events, and scientist-confirmed biological observations.

The first acceptance example is a synthetic fish-gape analysis: select two stable landmark
IDs, compute their distance over time, detect complete opening-and-closing cycles, correct
one event through the GUI, reload it, and export the reviewed result. The same engine must
also support angles, axes, curvature, velocity, extension, amplitude, and frequency through
configuration rather than species-specific code.

## Goals

- Implement deterministic 2D anatomical measurements for single- and multi-animal
  identity trajectories.
- Preserve source frames, timestamps, identity IDs, landmark IDs, coordinate space,
  schema revision, calibration, quality flags, and input/output hashes.
- Detect temporal cycles with hysteresis, amplitude/duration/separation/refractory rules,
  confidence gates, smoothing, missing-data handling, and partial-cycle reporting.
- Persist automated events separately from append-only scientist revisions.
- Provide executable jobs, Workflow Builder nodes, GUI charts and frame navigation, and
  JSON/CSV scientific exports.
- Reject or mark stale results when source video, identity revision, schema, calibration,
  or measurement/event configuration no longer matches.
- Preserve CPU compatibility and all Phase 1–4 behavior.

## Non-goals

- No learned behavior classifier or learned re-identification model.
- No claim that a 2D projected measurement is a true 3D biological distance.
- No automatic interpolation through extended occlusion, rejected landmarks, or uncertain
  identity assignments.
- No hard-coded fish species, landmark names, or biological interpretations.
- No replacement for existing mask measurements, video activity, behavior ethograms,
  pose schemas, identity tracking, or calibration services.
- No automatic download of models or installation of optional dependencies.

## Anti-goals

The implementation is unacceptable if it counts a sustained state as repeated cycles,
silently converts pixels without valid calibration, mutates pose predictions, mixes
different animals in one signal, treats automated candidates as scientist-verified events,
or authorizes an old analysis after its source revision has changed.

## Existing systems to reuse

- Phase 4 `PoseIdentityAssociationRun`, `PoseAnimalIdentity`, and current
  `PoseIdentityObservation` revisions are the canonical multi-animal pose input.
  They are also the canonical single-animal input: one compatible pose track passes
  through the existing association service to produce one stable identity. Phase 5 does
  not add a polymorphic direct-`VideoTrack` source or duplicate single-animal pipeline.
- Phase 2C stable landmark IDs and schema revisions define anatomy. Display names remain
  mutable presentation; measurement definitions bind stable IDs.
- `VideoScienceService` owns scalar video spatial calibration (`mm`, `cm`, or `m`) and
  video calibration revisions. Phase 5 hashes the selected calibration snapshot rather
  than introducing another calibration store.
- `BehaviorDynamicsService` supplies useful append-only review conventions, but behavior
  bouts are not reused as measurement-derived events because they represent manually
  labeled state intervals and do not carry measurement-run provenance.
- Existing jobs, workflow child-job execution, cancellation, review gates, managed
  artifacts, and Video Tracking Workspace patterns remain canonical.
- Existing SVG chart and source-frame navigation patterns are reused; no chart dependency
  is added.

## Approaches considered

### 1. Dedicated measurement and event runs — selected

Add Phase 5 records bound to an identity-run revision. This cleanly separates raw pose,
numeric observations, automated events, and scientist revisions; supports stale-input
checks; and gives Workflow Builder durable typed artifacts. It requires a reversible
migration and new services, but meets the scientific provenance requirements directly.

### 2. Store detected events as existing behavior bouts

This reduces schema work but conflates a scientist-authored behavioral state with a
measurement-derived cycle, loses explicit signal/configuration lineage, and makes an
automated candidate look more authoritative than it is. Rejected.

### 3. Compute on demand without persistence

This is adequate for exploratory plots but cannot support reproducible workflow replay,
append-only correction history, stale-artifact rejection, or verified export. Rejected.

## Domain model

### Measurement definitions

A measurement definition is immutable JSON within a measurement run and has a stable
definition ID, display name, type, ordered landmark IDs, formula version, parameters, and
declared output dimension. Supported types are:

- `landmark_distance`: Euclidean distance between two visible landmarks.
- `landmark_displacement`: per-landmark displacement from the prior valid sample.
- `landmark_velocity`: displacement divided by the actual positive time delta.
- `movement_direction`: `atan2(dy, dx)` in source-image axes, explicitly documented as
  image-coordinate direction.
- `joint_angle`: angle at a middle landmark from three ordered landmarks, in degrees.
- `angular_velocity`: unwrapped angle delta divided by actual time delta.
- `body_axis_orientation`: orientation of an ordered two-landmark axis.
- `chain_curvature`: total absolute turning angle divided by chain arc length for at least
  three ordered landmarks; zero-length chains are invalid.
- `relative_landmark_movement`: change in the vector or distance between two landmarks,
  according to the definition parameter.
- `anatomical_extension`: per-frame span across an ordered landmark set, plus run-level
  minimum and maximum extension.
- `movement_amplitude`: peak-to-trough signal amplitude over a configured interval or
  detected event.
- `movement_frequency`: complete reviewed-or-automated cycle count divided by evaluated
  valid duration, never a frame-count proxy.

The first nine types produce per-frame measurement series. `movement_amplitude` and
`movement_frequency` are post-detection derived summaries bound to an event run, avoiding
a circular dependency in the first-stage measurement job. Run-level minimum and maximum
extension are likewise summaries over valid extension samples.

Fish gape, jaw angle, gill pumping, fin movement, tail beat, dolphin fluke motion,
appendage motion, and polyp expansion are configuration presets composed from these
generic definitions. Presets provide suggested names and cycle definitions only; they do
not assert biological observability or validity.

### Measurement samples and quality

Each sample belongs to one measurement series and one stable animal identity. It stores
frame index, time seconds, pixel value where meaningful, calibrated value where available,
unit, confidence, and quality flags. Missing or invalid samples are persisted with a null
value and explicit flags rather than omitted. Required flags include missing landmark,
occluded, out of frame, rejected identity, low confidence, nonpositive time delta,
gap exceeds configured maximum, degenerate geometry, calibration unavailable, and
projected 2D.

No interpolation occurs in the measurement engine. A derivative uses only adjacent valid
samples whose gap is within the configured frame and time limits. Identity boundaries are
absolute: values from different `PoseAnimalIdentity` records are never joined.

Sample confidence is the conservative minimum of the required visible landmark
confidences and the Phase 4 association confidence when present. The individual
components are retained in quality/provenance data. Event confidence is the minimum valid
sample confidence across its observed start-to-end samples; configuration may raise the
acceptance threshold but may not replace this value with a product or opaque score.

### Timebase

Use a finite, nonnegative `PoseIdentityObservation.time_s` when present. Otherwise derive
time as `frame_index / video.fps` and record `video_fps_derived` in provenance. Timestamps
must strictly increase within an identity series. Irregular deltas are used directly.
Dropped frames therefore increase the derivative denominator rather than being silently
treated as consecutive samples. A run is rejected when neither valid observation times nor
positive video FPS can provide a timebase.

### Calibration and dimensions

All geometry starts in `source_pixels`. Distance-like pixel outputs are always retained.
Any input observation whose coordinate space is not `source_pixels`, or whose coordinates
fall outside an incompatible source-frame geometry, is rejected instead of transformed
implicitly.
When a current, valid `VideoSpatialCalibrationResponse` exists, distance and velocity also
receive physical values using `pixels_per_unit`. Angle and orientation are not rescaled.
Chain curvature retains radians-per-pixel and additionally reports radians-per-physical-unit
when calibrated. Unsupported, nonfinite, zero, or negative calibration values are rejected.
The calibration snapshot, video revision, and SHA-256 are stored.

Physical values are labeled `projected_2d_<unit>` or `projected_2d_<unit>_per_second`.
They must never be called 3D distance. Changing or clearing calibration makes an existing
run stale but does not rewrite it. Lack of calibration is valid and produces pixel-only
results.

## Event and cycle detector

An event-detection run consumes exactly one persisted scalar measurement series per
identity and an immutable documented cycle definition. The definition includes signal
meaning, increasing/opening direction, lower and upper hysteresis thresholds, minimum
amplitude, minimum complete duration, maximum allowed duration if any, minimum separation,
refractory seconds, minimum confidence, maximum missing gap, smoothing method/window, and
whether boundary partial cycles should be retained.

The detector is a deterministic state machine:

1. Begin `below` only after a valid sample is at or below the lower threshold.
2. Enter `rising` after leaving the lower band; track the maximum valid sample as peak.
3. Cross the upper threshold to qualify the opening half-cycle.
4. Enter `falling` after the peak and require a return to or below the lower threshold.
5. Emit one complete event only when amplitude, duration, confidence, separation, and
   refractory rules pass. A sustained signal above the upper threshold remains one
   in-progress event.
6. At a boundary or disqualifying missing gap, optionally emit one `partial` candidate with
   a reason; never count it as a complete cycle.

A missing interval at or below `maximum_missing_gap` preserves the current detector state
without inventing samples or smoothing across the gap. Its elapsed time remains part of
event duration and its absence lowers data quality. A longer gap terminates the in-progress
candidate as partial (when retained) and resets the state machine.

Smoothing supports `none`, centered moving mean, and centered moving median with a window
expressed in seconds and applied only within contiguous valid segments. It never bridges a
missing gap. The detector stores raw and smoothed peak values, start/peak/end frames and
times, amplitude, duration, confidence, status, and rejection reasons. Frequency summaries
use complete, non-rejected events and valid evaluated duration.

Synthetic validation covers one cycle, multiple cycles, sustained high state, boundary
partials, noise, missing landmarks, short and extended occlusions, identity separation,
irregular timestamps, and confidence rejection.

## Persistence and provenance

Reversible migration `0042` adds focused tables:

- `pose_measurement_runs`: job/status, project/video, source identity run and revision,
  schema binding, source manifest hash, video SHA/revision, optional calibration snapshot
  and hash, timebase, definitions/configuration, environment/runtime provenance, output
  hash, timestamps, and error/progress data.
- `pose_measurement_series`: run, identity, definition ID/type, landmark IDs, units,
  formula/version, summary statistics, and series hash.
- `pose_measurement_samples`: series, frame/time, raw pixel and calibrated values,
  confidence, validity, quality flags, and source observation IDs/revisions.
- `pose_event_detection_runs`: measurement run, configuration/cycle definition and hashes,
  status/progress, output hash, and provenance.
- `pose_biological_event_revisions`: stable event-series ID, append-only revision,
  supersedes ID, current flag, identity/measurement series, start/peak/end frames and
  times, amplitude/duration/confidence, complete/partial state, automated/scientist source,
  review state, reason, actor, and before/after integrity.

Deletion uses existing project/video cascade policy for owned runs while source identity,
schema, and calibration references use restrictive or snapshot semantics so historical
meaning remains inspectable. Existing tables and annotations are not rewritten.

The input manifest hashes the video bytes/revision, identity-run ID/revision, every current
observation ID/revision/content, stable identity IDs, schema ID/revision/hash, calibration
snapshot, timebase policy, and definitions. Submission and worker execution both validate
it. Event runs similarly bind the measurement output hash. GUI/API reads report stale
status by comparing current source state; stale results remain readable but cannot be
approved, replayed as current, or exported as current scientific output.

The run also copies upstream pose model/checkpoint registration, tracking job, and any
selected identity-evaluation references into provenance when available. Missing optional
evaluation evidence is reported, never fabricated.

## Services, jobs, and API

Pure domain modules calculate measurement samples and cycle candidates without database or
UI dependencies. Persistence services validate source state, construct immutable outputs,
provide summaries/exports, and append scientist revisions.

Two cancellable job types are used:

- `pose_anatomical_measurement` calculates all requested definitions for selected or all
  identities, reporting identity/frame progress and committing output atomically.
- `pose_biological_event_detection` evaluates selected series, reporting series/sample
  progress and committing candidate events atomically.

Queued manifests are revalidated immediately before computation. Cancellation reads and
progress writes use short transactions so SQLite cancellation remains observable while
scientific outputs stay atomic. Failed/cancelled jobs leave no completed run or current
candidate set.

REST endpoints submit/list/get/cancel runs, retrieve series and samples, submit event
detection, list candidates, append corrections (`accept`, `reject`, `adjust_boundaries`,
`add_manual`, `remove_manual`), inspect history, and export JSON/CSV. Boundary adjustments
must remain ordered and within the measurement series. Manual additions require an
explicit cycle definition and scientist reason.

Direct API/GUI measurement may run on a completed but unreviewed identity run for
exploratory use; every output then carries `automated_unreviewed_identity` and cannot be
presented as verified. The scientific workflow consumes the reviewed Phase 4 artifact by
default. In both paths, stale identity revisions are rejected.

Scientists edit event start/peak/end boundaries and disposition, not amplitude, duration,
frequency, or confidence. Every adjustment and manual addition deterministically
recomputes those derived fields from the bound samples. A manual event with no valid peak
sample is rejected.

## Scientist review and GUI

Add a `BiologicalMovementPanel` to the existing Video Tracking Workspace, using the
selected completed identity run. It provides:

- individual and measurement-definition selectors;
- stable landmark selectors sourced from the bound schema;
- distance/angle and event-configuration controls for the vertical slice;
- run status/progress/cancellation and stale-state messages;
- an accessible SVG time-series chart with raw/derived values, invalid-gap segments,
  confidence styling, thresholds, and event start/peak/end markers;
- per-individual amplitude, event-count, and frequency summaries;
- event selection that calls the workspace's existing frame navigation;
- accept/reject, boundary adjustment, manual add/remove, correction reason, and history;
- JSON/CSV export links and explicit `automated candidate` versus `scientist confirmed`
  labels.

The chart does not connect across invalid samples. Individual changes update the series,
events, summaries, and overlay consistently. Reload obtains current event revisions from
the API; no review state is kept only in React memory.

## Workflow Builder

Extend the existing pose workflow registry and runtime with typed executable nodes:

`reviewed_pose_identity_tracks → anatomical_measurement → biological_event_detection → biological_event_review_gate → biological_movement_export`

Artifacts are respectively `pose_anatomical_measurements`,
`pose_biological_events`, `reviewed_pose_biological_events`, and
`pose_biological_movement_package`. The measurement node persists definitions and submits
the real measurement job. Event detection submits the real detector job. The review gate
pauses until all retained current complete and partial candidates are accepted or rejected
and records scientist approval.
Export refuses stale or unreviewed artifacts. Workflow child jobs carry workflow and node
run IDs for cancellation and replay provenance.

Saved replay revalidates hashes and produces new immutable runs; it does not silently reuse
outputs whose source revisions changed.

## Scientific exports

JSON contains the complete measurement/event/review document. CSV export is a deterministic
ZIP or managed package containing at least `measurements.csv`, `events.csv`,
`individual_summaries.csv`, `review_history.csv`, and `manifest.json`. Rows include IDs,
frames, timestamps, pixel/physical units, quality flags, configuration hashes, source
revisions, and verification state. The manifest records file hashes and the package hash.

Automated events are labeled `automated_unreviewed`; accepted or manually added current
revisions are `scientist_confirmed`; rejected/removed revisions remain in history but are
excluded from confirmed counts. Exports never describe synthetic engineering fixtures as
biological validation.

Retained partial candidates are included in export audit history with their disposition
but never enter complete-cycle counts or frequency. Candidates rejected automatically by
confidence/duration/amplitude rules remain diagnostic records and do not require scientist
review unless explicitly promoted into the review queue.

## Resolved design calls

These implementation choices close builder-review ambiguities without expanding the
approved architecture:

- One-identity Phase 4 association is the single-animal adapter; no second source type.
- Completed unreviewed identities are allowed only for clearly labeled exploratory runs;
  the default scientific workflow uses reviewed identities.
- Amplitude and frequency are event-run summaries, not first-stage scalar series.
- Short missing gaps preserve detector state without interpolation; long gaps create a
  partial/reset.
- Scientist boundary edits recompute all derived event values.
- Confidence uses the conservative minimum while retaining its source components.
- Every retained complete or partial candidate needs disposition before review approval;
  partials remain excluded from complete-cycle counts.

## Validation and acceptance

Domain tests use hand-calculated geometry and time series for every measurement family,
calibration conversion, irregular time deltas, missing-data propagation, and deterministic
hashing. Event tests cover every required synthetic case and explicitly prove a sustained
open state produces one event, not one event per frame.

Persistence/API tests cover migration reversibility, immutable source observations,
manifest revalidation, stale revisions, cancellation rollback, event correction history,
multi-animal isolation, export integrity, and no incomplete registration. Workflow tests
exercise real child jobs, pause/resume, cancellation, saved replay, stale rejection, and
managed packages. Frontend tests cover selectors, chart gaps/markers, identity switching,
navigation, correction persistence, cancellation, validation, and compatibility with the
existing Phase 4 panel.

Live Chromium acceptance uses a synthetic source-coordinate fish-gape fixture against the
real API, worker, migration, and Vite UI. It calculates a distance series, detects repeated
cycles, adjusts one event, reloads, exports, and verifies hashes. CPU is the authoritative
execution path. GPU is not required because measurement and event analysis are deterministic
scalar computation; existing ReefPose CUDA evidence remains upstream evidence only.

Completion reports four distinct evidence levels: computational correctness, automated
workflow correctness, agreement with manually reviewed events, and biological validity.
Only the first two may be claimed from synthetic fixtures. Real agreement and biological
validity remain explicitly unvalidated until independent research data exist.

## Delivery order

1. Pure measurement engine and synthetic geometry/timebase tests.
2. Deterministic event state machine and synthetic cycle tests.
3. Migration, persistence, jobs, API, stale checks, corrections, and exports.
4. Workflow nodes and saved replay.
5. GUI workspace and live vertical-slice acceptance.
6. Full regression, migration, CPU, frontend, static, build, and final review evidence.

Each stage is locally committed. No push, merge, tag, publish, model download, optional
dependency install, or unrelated branch modification is authorized.

