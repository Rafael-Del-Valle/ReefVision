# Pose visualization

ReefVision pose visualization is derived from the persisted canonical pose state. It does not
reinterpret model tensors as biological measurements.

## Visualization definitions

- **Keypoint confidence heatmap**: mean persisted landmark confidence for included observations
  in each source-pixel grid cell. This is not a native neural-network confidence map.
- **Occupancy heatmap**: fraction of sampled canonical pose frames with at least one included
  landmark in each cell.
- **Activity / speed heatmap**: mean source-pixel speed of resolved persistent-landmark
  movement segments, assigned by segment midpoint.
- **Trajectory overlay**: consecutive points sharing a resolved `landmark_track_id`. Explicit
  identity breaks are never bridged.

Occlusion-predicted coordinates are excluded by default. When enabled, they remain labeled as
predicted and are counted separately from observed coordinates.

## Provider capability

The current ReefVision adapters persist canonical keypoint coordinates and, when supplied,
keypoint scores. They do not persist native model confidence-map tensors or raw
part-affinity-field (PAF) tensors. ReefVision therefore does not synthesize or label a derived
field as a native PAF.

If raw provider tensors are added later, the capability contract must report them as persisted
before the UI may render them as native confidence maps or PAFs.

## Reproducible exports

The visualization endpoint supports numeric exports using the same filters as the rendered view:

- JSON: complete visualization response plus the exact request and provenance.
- Cell CSV: heatmap cell statistics plus source revision and visualization parameters.
- Trajectory CSV: resolved persistent-landmark points and trajectory summaries.

Trajectory CSV is blocked when temporal identity state is missing or stale. JSON remains the
recommended audit export because it preserves capability state and all visualization metadata.
