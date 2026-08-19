# ReefVision Scale Assistant Validation

ReefVision 1.0 treats physical calibration as scientific evidence, not merely a UI feature. Unit tests and synthetic images can prove software behavior, but they do not establish measurement accuracy. Before release, run `scripts/acceptance_scale_assistant.py` with independently measured real images.

## Evidence classes

A useful validation set should include multiple examples of:

- a ruler photographed horizontally;
- a ruler photographed vertically;
- a ruler under less favorable contrast or lighting;
- an ArUco marker photographed close to the measurement plane;
- an ArUco marker at an oblique view with an independently measured planar probe;
- a ChArUco board at one or more oblique views;
- repeated images from a fixed camera/lens/focus/mount-distance setup for profile reuse; and
- at least one deliberate setup change evaluated independently rather than silently treated as the same profile.

The checked-in `docs/SCALE_ASSISTANT_VALIDATION_EXAMPLE.json` shows the supported manifest structure. Replace all placeholder paths and expected values with independently measured data.

## Ruler evidence

For each ruler case, record:

- the real image and optional SHA-256;
- ruler orientation or a manually selected ROI;
- the known physical length represented by one repeating detected interval;
- the independently expected distance-per-pixel value; and
- any optional known polygon/centerline probe geometry.

ReefVision's ruler detector may estimate only pixel spacing. It must return `unit_inferred=false` and `reference_length_required=true`. The researcher supplies the known physical interval and unit before calibration is applied.

Do not infer that one detected tick interval is 1 mm, 1 cm, or another unit from appearance alone.

## ArUco and ChArUco evidence

Marker cases use known printed geometry. Record the exact dictionary and printed dimensions used. For ChArUco, record board square counts, square length, and marker side length; the marker side must be smaller than the chessboard square side.

For perspective validation, include a polygon or centerline whose physical geometry was measured independently on the same planar surface as the marker or board. ReefVision then compares perspective-corrected physical area, perimeter, centroid, or TLE with the independent expected values.

A marker homography is valid only on its calibrated reference plane. It must not be interpreted as a general 3D calibration or applied to geometry that is materially displaced from that plane.

## Raster-mask boundary

The current 1.0 measurement contract does not resample raster masks through a projective warp. Raster-mask area, perimeter, centroid, and other physical values therefore remain on scalar `distance_per_pixel` calibration even when the image also has a marker homography. Polygon masks and centerlines can use the planar homography directly.

## Camera/setup profiles

A profile case reuses a previously accepted scalar calibration. The harness supplies the same explicit confirmation required by the application. Valid reuse requires the same:

- project;
- image resolution;
- camera;
- lens;
- focus;
- mount or working distance; and
- measurement plane.

ReefVision deliberately does not copy an image-specific perspective homography through a reusable profile. A new view requires new perspective evidence.

For repeatability evidence, compare multiple independently acquired images from the unchanged setup against the same external scale reference. A deliberate setup change should be independently measured and should not be presented as same-profile validation.

## Run

Use the ReefVision Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe .\scripts\acceptance_scale_assistant.py `
  --manifest C:\path\to\scale-assistant-validation.json `
  --output C:\path\to\scale-assistant-evidence
```

The output directory must not already exist. The harness creates an isolated ReefVision data root inside that output directory unless `--state` is supplied.

The resulting `report.json` records:

- source image paths and SHA-256 values;
- detector candidates and confidence;
- persisted calibration/provenance;
- scale error against independent expectations;
- optional physical polygon/centerline errors;
- whether perspective correction was expected and used; and
- restart persistence.

## PASS meaning

A harness `PASS` means every configured comparison stayed within the explicit manifest tolerance and every accepted calibration survived restart unchanged. It does not prove universal accuracy outside the tested cameras, markers, rulers, lighting, viewpoints, planes, or working distances.

Keep this evidence separate from provider execution evidence. SAM2/Depth Anything CUDA execution, for example, does not establish Scale Assistant physical accuracy, and relative monocular depth must never be used as metric calibration evidence.
