# Behavior dynamics

Phase 7 behavior dynamics uses a canonical annotation layer that is independent of any one
classifier backend.

## Ethograms

Ethograms are project-scoped, immutable revisions. Each revision stores a SHA-256 hash of its
complete state definition. States have a stable code, a human-readable label, and a channel.

Channels allow simultaneous behavioral dimensions. For example, a locomotion channel can contain
`rest` and `swim` while a feeding channel independently contains `feed` and `not_feed`.
Bouts may overlap across channels, but they cannot overlap within one channel.

## Behavior bouts

Behavior bouts use inclusive source-video frame intervals and are attached to one persisted video
track. Each revision stores the video-track revision that was current when the bout was created.
If the track later changes, ReefVision reports the bout and any derived dynamics as stale instead
of silently assuming identity continuity.

Manual bouts are human-verified ground truth and do not carry model confidence. Imported bouts may
carry confidence and remain unreviewed until a later review workflow.

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
