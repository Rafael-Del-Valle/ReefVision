# ReefVision depth, Auto Mask, and Ultralytics reporting

## Ultralytics class metrics and reports

Completed Ultralytics detection and segmentation runs now perform an explicit validation pass after training. ReefVision stores a version-tolerant validation contract rather than relying only on Ultralytics console text.

The validation artifacts include:

- aggregate validation metrics;
- per-class precision;
- per-class recall;
- per-class F1;
- per-class mAP50;
- per-class mAP75;
- per-class mAP50–95;
- box and mask scopes for segmentation models;
- count and normalized confusion-matrix summaries when supplied by Ultralytics;
- inference-speed metadata;
- the standard Ultralytics PNG plots produced by validation;
- JSON and CSV files suitable for independent statistical analysis.

The desktop Training Reports workspace presents the class-wise table in a CoralNet-Toolbox-like layout and can generate a self-contained HTML report. Users can choose the font family and independently adjust body, heading, table, and figure-label sizes.

Training reports can include:

- run and dataset provenance;
- epoch-by-epoch training curves;
- class-wise precision, recall, F1, and mAP;
- confusion matrices;
- Ultralytics PR, P, R, F1, confusion, label-distribution, and results plots when available;
- hyperparameter trial ranking;
- fitness-by-trial plots;
- parameter-versus-fitness plots;
- best parameters and best fitness;
- package, model, dataset, and checkpoint provenance.

Hyperparameter tuning uses the Ultralytics tuning interface and preserves a ReefVision-owned trial summary so the report layout remains stable across Ultralytics versions.

## Lightroom-style Auto Mask

The raster editor includes an optional Auto Mask toggle. When enabled, each paint or erase stroke samples the image beneath the stroke and limits the edit to pixels with similar color and luminance while respecting image edges.

Controls include:

- color tolerance;
- luminance tolerance;
- edge sensitivity;
- seed-sampling radius;
- contiguous-region selection;
- paint and erase modes.

Auto Mask does not replace the original image or overwrite an old mask file. Every edit creates a normal immutable raster-mask revision with complete settings stored in provenance and a dedicated audit event.

Auto Mask is a classical edge-aware local-selection method. It is useful when the target has visually distinct boundaries. SAM-family Prompt Assist remains the stronger option for complex semantic selections.

## Prompt Assist acceptance outputs

Prompt Assist candidates remain temporary proposals while the user adds or removes points and
reviews the preview. Accepting a candidate is an explicit action that selects an annotation class
and calls:

```text
POST /api/v1/assist-sessions/{session_id}/accept
```

`AssistAcceptRequest.output_kind` supports:

- `raster_mask`, the default and faithful representation of the reviewed candidate; or
- `polygon`, an editable source-coordinate contour derived at acceptance time.

Polygon acceptance is intentionally narrow. ReefVision requires a source-aligned candidate with
one simple contour and rejects masks with holes, multiple components, non-faithful simplification,
or excessive contour complexity. A rejected polygon conversion does not accept or modify the
candidate; the user can keep reviewing it or accept the raster representation instead. This is not
a general raster-to-polygon or polygon-to-raster conversion workspace.

Neither the preview nor its prompts are verified annotations. Only a successful, explicit user
acceptance creates the linked verified mask and bounding-box records with model, prompt, output,
and source-prediction provenance.

## Depth maps and object measurements

ReefVision can persist depth maps aligned to project images. A map may contain either:

- **relative monocular depth**, where values describe near/far ordering but not real units; or
- **metric depth**, where values are calibrated distances such as metres or millimetres.

Depth maps can be generated through a configured provider or imported as aligned numeric arrays. Each map records its provider, model, checksum, depth type, units, dimensions, statistics, preview image, and metadata.

For an annotated polygon or raster mask, ReefVision can report:

- minimum, maximum, mean, and median depth;
- 5th and 95th percentile depth;
- valid-depth pixel count;
- a relative depth-weighted area index;
- 3D centroid estimates;
- projected metric width and height;
- projected metric area when metric depth and camera intrinsics are available.

The current projected-area method uses a pinhole-camera, locally fronto-parallel approximation. It is more realistic than assuming every object lies on the same flat image plane, but it is not a substitute for calibrated stereo, structured light, photogrammetry, or multi-view surface reconstruction when true curved surface area is required.

### Provider readiness and preview revalidation

The Depth workspace reports local runtime readiness before a Depth Anything request is queued.
Real providers require the optional PyTorch/Transformers runtime plus an explicitly registered,
verified local checkpoint folder. Provider inference is always local-only and never downloads
weights. The luminance provider bypasses model readiness solely as a deterministic workflow
fixture and remains non-scientific.

Depth Anything V2 output is persisted as raw relative-depth values. The preview uses a separate
per-image display normalization and does not overwrite the numeric array. Relative output has no
centimeter or meter unit and cannot be interpreted as physical coral height without independent
metric calibration.

Frontend readiness is advisory; the backend still validates the provider, requested device,
checkpoint policy, and image when it handles the queued job and returns a structured failure when
the request cannot run.

Depth preview PNGs are served inline with private, short-lived caching and revalidation. Retrying a
failed preview uses a cache-busting revision URL; it does not regenerate the depth map, change its
numeric array, or alter its provenance.

## Is depth used during model training?

Normal Ultralytics RGB models do not use depth. They receive three input channels: red, green, and blue.

ReefVision now includes RGB-D foundations that can create a four-channel input composed of RGB plus aligned depth. A three-channel PyTorch first convolution can be adapted to four channels by copying its RGB weights and initializing the depth channel from the mean RGB kernel. The resulting model must then be fine-tuned on aligned RGB-depth training pairs.

Depth can be used in three distinct ways:

1. **Input feature during training**
   - Generate or capture a depth map for every training image.
   - Align it pixel-for-pixel with RGB.
   - Normalize depth consistently.
   - Train an RGB-D architecture with four input channels or a separate depth encoder.

2. **Post-detection measurement**
   - Train a normal RGB detector.
   - Sample depth inside each detection or mask afterward.
   - Use median depth and camera calibration to estimate size or 3D position.

3. **Tracking association feature**
   - Sample a representative depth value for every fish detection.
   - Maintain a depth history for each track.
   - Combine depth difference with motion and appearance costs.
   - Reject candidate matches whose normalized depth gap is implausibly large.

The third method is particularly useful for fish moving through the water column. Two fish whose boxes overlap in the 2D image may still be separable because their estimated depths differ.

## Important limitations

Monocular relative depth cannot determine an animal's absolute size by itself. Absolute measurements require at least one of:

- metric depth from a calibrated sensor;
- stereo-camera calibration;
- known camera intrinsics plus metric distance;
- a reference object at a known depth;
- multi-view photogrammetry;
- another experimentally validated scale model.

Underwater imagery also introduces refraction, turbidity, color attenuation, moving caustics, and housing-port effects. Accurate metric work should use underwater camera calibration rather than air calibration values.
