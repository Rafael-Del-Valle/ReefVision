# Phase 6 — Video and Fish Tracking

## Scope

Phase 6 adds managed project videos, frame review, editable sparse tracks, detector-plus-tracker inference, and trajectory summaries while retaining original source-video pixel coordinates.

## Implemented vertical slice

- managed video upload into project storage
- SHA-256 duplicate detection
- OpenCV metadata inspection
- original-video content streaming
- background frame extraction with a configurable stride
- persisted extraction status, frame directory, job reference, and revision
- exact extracted-frame content endpoint
- revisioned sparse bounding-box tracks
- human and machine-generated track provenance
- detector and instance-segmenter support for automated tracking
- provider-neutral video tracking interface
- Ultralytics detection plus ByteTrack or another supported tracker YAML
- model-label to project-class mapping
- minimum-track-length filtering
- linear and hold interpolation
- editable track identity, class, status, and keyframes
- soft deletion
- path length, displacement, duration, mean speed, maximum speed, mean footprint, and 3×3 occupancy summaries
- project Video Tracking workspace

## Coordinate contract

All keyframes use the original source-video dimensions and the bounding-box form:

```text
[x, y, width, height]
```

where `x` and `y` are the upper-left source pixel coordinates. Interpolated boxes and trajectory summaries are computed from this immutable coordinate contract.

## Machine-tracking contract

A tracking run requires a registered detector or instance-segmentation model. Provider class names must map to ReefVision project classes through the registered model class map. Unmapped labels are reported in the job result and are not silently assigned.

Machine tracks remain editable and start with status `machine_generated`. A human may change the class, adjust keyframes, and mark the track verified.

## Deferred validation

The branch remains unvalidated until a later validation day confirms:

1. migration upgrade through `0021` and downgrade to `0020`
2. Ruff formatting and lint
3. strict mypy
4. synthetic-video and fake-provider Phase 6 tests
5. all Phase 4 and Phase 5 focused tests
6. complete backend regression suite
7. Prettier and TypeScript
8. frontend unit and browser tests
9. production build and Windows MSI
10. import and playback of a real fish video
11. frame extraction and still-frame access
12. real detector plus ByteTrack inference
13. manual track corrections and restart persistence
14. comparison of trajectory summaries against a manually checked track

## Known limitations

- tracks currently use bounding boxes only
- automatic identity reconciliation across separate tracking runs is not implemented
- occlusion-specific quality flags are not yet exposed
- trajectory values are in pixels and pixels per second; physical calibration for video is future work
- frame extraction stores JPEG review frames and may require substantial disk space for long videos
- automated tracking uses the full video and does not yet support time-range selection
- no social-interaction or schooling metrics are included in this slice
