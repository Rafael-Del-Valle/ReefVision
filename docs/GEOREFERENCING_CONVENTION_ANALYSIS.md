# ReefVision ↔ DVM projection convention analysis

Status: Task 2 diagnostic, 2026-09-23

Reference implementation inspected:
`SDU-UAS-Center/DVM@e56c85ce1073301eb4d6d0cbf649ccf967949d6b`,
especially `src/dvm/drone/fov.py`.

## Conclusion

The remaining ReefVision↔DVM coordinate disagreement is not explained by a
different yaw/pitch/roll rotation once coordinate axes are translated. The two
rotation formulations are algebraically equivalent.

Two deliberate projection conventions differ:

1. **Ray optical center**
   - ReefVision uses the calibrated OpenCV principal point `(cx, cy)` and focal
     lengths directly.
   - DVM first undistorts with `P=K`, then subtracts the image midpoint
     `(width/2, height/2)` and scales by FOV.
   - Because DVM derives FOV from the same camera matrix, this is equivalent to
     using the same normalized OpenCV ray plus a constant shift caused by
     `cx-width/2` and `cy-height/2`.

2. **Local-to-geographic mapping**
   - ReefVision treats the projected horizontal vector as true East/North and
     applies a WGS84 geodesic displacement.
   - DVM converts the drone GPS position to UTM, adds the projected x/y vector as
     UTM easting/northing, then converts back to latitude/longitude.
   - UTM grid north is not exactly true north away from the zone central meridian,
     so this can create an additional direction-dependent reference difference.

## WhaleDrone calibration consequence

The supplied DJI Mavic 3T RGB-wide calibration is 3840×2160 with:

- `fx=2969.4`
- `fy=2970.3`
- `cx=1968.5`
- `cy=1116.9`
- horizontal/vertical FOV 65.76° / 39.96°

The image midpoint is `(1920, 1080)`. Therefore the DVM midpoint convention is
offset from the calibrated principal point by:

- +48.5 px horizontally;
- +36.9 px vertically.

At a 90 m nadir camera height, the corresponding first-order footprint shift is
approximately:

- 1.47 m in the camera-right direction;
- 1.12 m in the camera-down/forward footprint direction.

Oblique projection can amplify these shifts. This is consistent in scale with the
roughly 2 m median DVM-coordinate disagreement seen in the two-clip AirData
validation, without implying that DVM or ReefVision is independently ground truth.

## Rotation equivalence

DVM represents a camera ray as right/forward/up and applies:

- roll about camera forward;
- pitch about camera right;
- negated yaw about world up.

ReefVision represents the OpenCV ray as right/down/forward, explicitly reorders it
to forward/right/down, and applies the equivalent roll, pitch, and clockwise
true-North yaw operations before converting NED to ENU.

`test_projection_conventions.py` translates the axis labels and verifies the two
rotation formulations agree numerically across multiple nontrivial rays and
attitudes.

## Implementation decision

Do **not** change ReefVision to DVM's image-midpoint ray convention merely to reduce
DVM-reference residuals. The calibrated OpenCV principal point is the optical-axis
parameter and is the appropriate production convention for a calibrated pinhole
model.

Do **not** replace ReefVision's true-East/North WGS84 displacement with UTM grid
addition merely to mimic DVM output. ReefVision's contract explicitly interprets
gimbal yaw in a true-North local frame.

DVM-coordinate agreement remains a compatibility/reference diagnostic. Absolute
geographic accuracy requires independent surveyed targets or another independent
ground-truth source.

## Task 2 acceptance

Task 2 is complete when:

- the new convention regression tests pass;
- existing synthetic georeferencing tests still pass;
- the two-clip WhaleDrone AirData integration still passes;
- Ruff, formatter, and mypy remain clean;
- this documented convention decision remains explicit before production track
  georeferencing is introduced.
