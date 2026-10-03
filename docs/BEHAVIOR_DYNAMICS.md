# Behavior dynamics

Phase 7 behavior dynamics uses a canonical annotation layer that is independent of any one
classifier backend.

## Ethograms

Ethograms are project-scoped, immutable revisions. A new revision is created rather than editing
an existing definition in place, and no-op revisions are rejected. Each revision stores a SHA-256
hash of its complete state definition. States have a stable code, a human-readable label, and a channel.

Channels allow simultaneous behavioral dimensions. For example, a locomotion channel can contain
`rest` and `swim` while a feeding channel independently contains `feed` and `not_feed`.
Bouts may overlap across channels, but they cannot overlap within one channel.

## Behavior bouts

Behavior bouts use inclusive source-video frame intervals and are attached to one persisted video
track. Time boundaries use the start of the first frame and the end boundary immediately after the
last included frame, so a two-frame bout at 10 fps has a duration of 0.2 seconds. Each revision stores the video-track revision that was current when the bout was created.
If the track later changes, ReefVision reports the bout and any derived dynamics as stale instead
of silently assuming identity continuity.

Manual bouts are human-verified ground truth and do not carry model confidence. Imported bouts may
carry confidence and remain unreviewed until a later review workflow. Behavior dynamics use
verified bouts only by default. Including unreviewed bouts requires an explicit request and the
response records that annotation policy.

## Dynamics

Behavior dynamics are calculated independently for each channel:

- dwell frames and dwell seconds per state;
- fraction of the evaluated interval and fraction of labeled time;
- bout count, mean bout duration, and maximum bout duration;
- channel coverage and unlabeled time;
- directed transition counts and transition probabilities.

Transitions are counted only when two labeled bouts in the same channel are directly adjacent in
source frames. ReefVision does not infer a transition across an unlabeled gap.

The initial P7A schema is designed so model-assisted behavior predictions can be added later without
changing the scientific meaning of manual ground-truth bouts.


## P7B behavior feature vectors

ReefVision derives model-ready scalar behavior features from the current canonical track and pose
state without persisting another derived database copy. Each response records the source track
revision, frame window, feature-set version, extraction-parameter SHA-256 hash, sampling policies,
and pose-identity status.

The feature set has three provenance groups:

- **Track kinematics** use configured track interpolation and include center path/displacement,
  speed, bounding-box area variability, and an explicit bounding-box-diagonal normalization.
- **Pose geometry** uses persisted canonical pose keyframes and includes pose-frame coverage,
  landmark count/confidence, RMS pose spread, pairwise landmark distances, and bbox-diagonal
  normalized geometry.
- **Pose identity** uses the continuity-safe persistent landmark segments from pose visualization
  and includes resolved-identity coverage, aggregate landmark path/speed, and continuity segment
  count.

Raw pixels remain the primary coordinate unit. Bbox-diagonal normalization is labeled as a
dimensionless image-space normalization; it must not be interpreted as anatomical body length.

Occlusion-predicted coordinates are excluded by default. When explicitly included, their fraction
is reported. If temporal pose identity is missing or stale, identity-dependent features are
returned as unavailable with `value=null` and a reason rather than as numeric zero. Geometry
features that do not require persistent identity remain available when the current pose keyframes
support them.


## P7C model-assisted behavior review

Behavior models use the transparent `standardized_nearest_centroid` algorithm over versioned
P7B scalar features. The default training corpus includes only verified **manual** bouts attached
to the current video-track revision. Accepted model predictions are deliberately excluded from
future training truth unless a scientist later recreates them as manual ground truth.

Three feature presets are available: track-only, track plus pose geometry, and track plus current
persistent-pose identity. Model records store the feature names, scaler, state centroids, class
counts, training tracks/bouts, ethogram revision, and a SHA-256 training-manifest hash.

Inference creates reviewable behavior predictions only. The displayed score is a normalized
inverse-distance score used to rank the nearest state centroid; it is **not** a calibrated
probability. Predictions retain the complete per-state distance/score map and raw feature vector.

A scientist may accept, edit-and-accept, or reject a pending prediction. Acceptance is blocked if
the prediction is stale against the current track revision or would overlap an existing canonical
bout in the same ethogram channel. Accepted predictions create new verified canonical bouts with
back-references to the behavior model and prediction.

JSON, canonical-bout CSV, and prediction CSV exports preserve track/ethogram/model provenance.
