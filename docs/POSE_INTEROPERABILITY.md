# Phase 5 pose interoperability

ReefVision remains the canonical pose store. Install the optional interoperability
runtime from this checkout with `python -m pip install -e ".[interoperability]"`
(installed distribution: `python -m pip install "reefvision[interoperability]"`).
The extra pins **sleap-io==0.9.2**; normal installation does not install it.
`GET /api/v1/pose-interoperability/runtime` reports importability, required and
installed versions, and the installation command. A missing, incompatible, or
broken runtime produces a domain error without preventing normal application use.

## Artifact contracts

| Format | Native data and transformations | Media and supplementary information |
| --- | --- | --- |
| SLP | Zero-based source frame indices, unique node names, instances, track names, finite occluded coordinates and visibility. Point coordinates/confidence use float64; instance scores use float32 and can round. Unknown confidence remains unknown. | Annotated frames embedded losslessly as PNG; RGB decoding is explicit. Complete encoded source video is not included. Repeated-label mapping and native evidence live in SLP provenance. |
| NWB | Real ndx-pose series contain pixel coordinates, confidence and timestamps in seconds using measured video FPS. The adapter corrects SLEAP-IO 0.9.2's sparse-frame/unknown-confidence writer behavior. | Standard NWB ImageSeries embeds annotated decoded frames. Checksum-bound scratch metadata preserves source frame indices, visibility, track names, instance scores and native evidence. Independent SLEAP-IO reads numeric pose data; its bare reader loses some semantics. ReefVision restores these only after checksum validation. |
| Ultralytics pose ZIP | Per-class labels, normalized coordinates and keypoints with visibility 0/1/2; normalization can incur floating-point roundoff. Training boxes are derived from present points with half-pixel padding, not the original ReefVision boxes. | Includes exact decoded source pixels in PNGs, YAML class/keypoint/skeleton metadata, labels and digest-bound provenance. Filenames are derived artifact names mapped to original video SHA-256 and frame indices. The dataset checker resolves an extracted YAML from any working directory. |
| COCO keypoints JSON | Standard images/categories/annotations, pixel coordinates, 0/1/2 visibility, keypoint counts, derived boxes/areas and one-based skeleton edges. | Referenced-image workflow. Logical image references are explicitly marked unavailable, never represented as existing local files. Source SHA/frame mapping and native evidence are embedded in the ReefVision extension. Images are not copied or fabricated. |
| DeepLabCut ZIP | Standard four-level CSV headers: scorer, individuals, bodyparts, coords; x/y and likelihood retain numeric observations, including finite occluded coordinates. | CSV plus digest-bound metadata sidecar; images are references explicitly reported unavailable. The sidecar supplies source dimensions/frame mapping, visibility and repeated-label semantics. Raw CSV alone is rejected with an actionable metadata-required error. |

The Ultralytics exchange package aliases train/val to the exchange images to allow
dataset inspection. **It is not an independent evaluation split.** Create
leakage-safe training/validation splits before training or reporting metrics.

## Scientific preservation and limitations

Exactly retained where the format supports them: semantic node order, instances,
finite x/y values (subject to the numeric encodings above), known versus unknown
confidence, visible versus occluded state, and source association. Repeated
landmark groups become unique external names (`tentacle__1`, `tentacle__2`) with
an explicit semantic-label/occurrence mapping; suffixes are never guessed on import.

The native external fields cannot encode ReefVision observation IDs, `uncertain`
versus visible, `out_of_frame` versus absent, correction-source labels, temporal
association confidence, identity breaks, or immutable human correction history.
Canonical keyframes, track metadata, and available temporal audit records remain
as supplementary evidence. They are persisted with the imported provenance, not
replayed as historical database changes. Native imports use new observation IDs,
derive pose boxes, and enter `imported_review_required`; the scientist's selected
target class applies to imported tracks. Original classes and boxes remain in
provenance. Consequently all export responses retain the lossy header.

Unsupported external fields are not claimed to survive: arbitrary SLP model/
identity embeddings, suggestions and external correction history; arbitrary NWB
acquisitions/processing data beyond this pose contract; COCO segmentation/crowd
and tracking extensions; DLC scorer history; YOLO split/training configuration.
The complete external upload is not archived by this endpoint. Preserve it
separately when those fields are scientifically relevant.

Plain external SLP and standard COCO can be imported with explicit source-frame
confirmation when ReefVision provenance is absent. COCO dimensions are required;
no fallback dimensions or file locations are invented. Generic external NWB is
rejected without verified frame-mapping metadata because SLEAP-IO 0.9.2 reindexes
its frames. DLC and YOLO imports require the ReefVision metadata package. These
are deliberate restrictions relative to the previous permissive readers, which
could discard observations or misassign frames. Use a verified SLP conversion or
a compatible ReefVision export when the required metadata is missing.

Changed text artifacts or NWB datasets whose digests no longer match their
metadata are rejected. Re-export updated observations; stale sidecars never
overwrite externally edited coordinates. Digests detect inconsistencies, not
authorship or authenticity. Source video bytes and decoded dimensions are checked
against the managed record before export. Original imagery is never modified.

## Failure and transaction behavior

Parsing, skeleton/occurrence validation, source checksum mapping, frame bounds,
coordinate bounds and instance relationships are checked before creating tracks.
Schema revisions and all imported tracks commit together. Validation and database
failures roll back; errors identify the file/format, state that nothing was
imported and the operation was atomic, and suggest correction/retry. Importing
over a still-live ReefVision source track is rejected as duplicate scientific data.

## Reproducible validation

Use the existing `integration` marker and explicit opt-in:

```powershell
python -m pytest apps/api/reefvision/tests/test_pose_interoperability.py apps/api/reefvision/tests/test_pose_interoperability_validation.py apps/api/reefvision/tests/test_pose_interoperability_runtime.py apps/api/reefvision/tests/test_pose_exchange_text.py apps/api/reefvision/tests/test_pose_nwb_runtime.py --pose-interop-integration
```

Ordinary pytest runs skip real-runtime tests. Opt-in runs require the exact pin
and fail if it is missing. All assets are synthetic and temporary; tests require
no datasets, user paths, downloads or network access. Tests include real SLEAP-IO
SLP/NWB reads, pynwb validation, independent JSON Schema/semantic COCO validation,
pandas DLC parsing, and installed Ultralytics label/dataset checks.

NWB compatibility narrowly filters the exact deprecated upstream constructor
arguments during the 0.9.2 writer call. It does not globally suppress warnings
or patch installed libraries. See the Phase 5 validation report for actual local
dependency versions, counts, warnings and acceptance results.
