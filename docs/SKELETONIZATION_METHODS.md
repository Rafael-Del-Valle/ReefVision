# ReefVision coral skeletonization methods

## Scope

ReefVision skeletonization measures the two-dimensional projected branching
structure represented by one verified segmentation mask. It does not infer
hidden branches, bridge disconnected mask components, or reconstruct
three-dimensional colony architecture.

The canonical analysis schema is `skeleton-analysis-0001`. The thinning
algorithm is recorded as `zhang_suen`, algorithm version `0001`.

## Input acceptance

A mask must be verified and contain exactly one foreground component under
8-neighbor connectivity. Diagonal foreground contact therefore counts as
connected.

An empty mask or a mask with more than one component is blocked before
skeletonization. ReefVision does not silently connect components. A scientist
must resolve disconnected content by repairing a genuine segmentation gap,
deleting an artifact, or treating a component as a separate biological object.

Polygon masks are rasterized in source-image coordinates. Raster masks are
read in source-image dimensions. The binary mask content is hashed for
persistent-analysis provenance.

## Thinning and topology

The accepted binary mask is normalized to foreground/background values and
thinned with the Zhang-Suen iterative thinning algorithm. No automatic gap
bridging is applied.

After thinning, ReefVision requires the raw skeleton to remain one
8-connected component. Raw skeleton pixels are classified by 8-neighbor graph
degree:

- degree 0: isolated
- degree 1: endpoint
- degree 2: path
- degree 3 or greater: junction

Adjacent raw junction pixels are consolidated into deterministic junction
clusters before branch graph construction. Each consolidated junction records
its source-pixel cluster, centroid, representative pixel, and external
connections.

## Branch graph and length

Graph nodes represent endpoints, consolidated junctions, isolated points, or a
cycle anchor when needed. Branches are traced through degree-2 path pixels.

The primary branch length is node-to-node centerline length in source-image
pixels. A boundary-to-boundary pixel length is retained as a diagnostic but is
not the primary morphometric length.

Total linear extension (TLE) is defined as:

> the sum of node-to-node branch centerline lengths.

The longest path is the weighted graph diameter. Pairwise branch angles at a
junction are calculated from the consolidated junction centroid toward the
incident external branch directions.

These are projected two-dimensional quantities unless a calibration maps the
accepted image plane to physical coordinates.

## Terminal-spur pruning

Pruning is disabled by default with a threshold of 0 pixels.

When a positive threshold is explicitly supplied, only terminal
endpoint-to-junction branches whose node-to-node length is at or below the
threshold are eligible. Endpoint-to-endpoint trunks and cycles are not
automatically removed.

Pruning is iterative. After each accepted removal ReefVision reclassifies the
remaining skeleton and rebuilds the graph before evaluating another spur.
Junction-boundary shoulder pixels may be removed only when a trial removal
preserves a single 8-connected skeleton.

Every removed spur is retained in the analysis audit with its iteration,
branch, endpoint, junction, branch length, removed-pixel count, and
junction-boundary removal count.

Raw measurements are retained alongside auto-pruned measurements.

## Calibration

Without image calibration, lengths are reported in pixels.

With scalar calibration, physical branch lengths are calculated from
`distance_per_pixel` and the recorded physical unit.

When an accepted reference-plane homography exists, skeleton centerline
coordinates are transformed into that reference plane before physical lengths
and branch angles are calculated. ReefVision reports the calibration method,
source, confidence, angle coordinate space, and whether the measurement is
reference-plane-only.

A reference-plane measurement is not a three-dimensional reconstruction.
Branches displaced out of the calibration plane can have unmodeled projection
error.

## Human correction and review

The automatic raw skeleton and automatic-pruned skeleton are immutable
baselines. Human review edits only the final skeleton layer.

A manual correction is stored as a new analysis revision in the same revision
series. The previous revision is not overwritten. Correction provenance
includes the base analysis ID and hash, exact pixels added and removed, a
reason code, an optional note, and the actor/time recorded by the persisted
revision.

Corrected skeletons must remain non-empty, one 8-connected component, and
one-pixel-thin under the recorded Zhang-Suen algorithm. Corrections based on a
superseded revision are rejected.

Only the latest revision in a series may be reviewed or released as a
scientific export.

## Staleness and reproducibility

A persisted analysis records:

- input binary-mask SHA-256
- calibration SHA-256 when calibration exists
- analysis-parameter SHA-256
- result SHA-256
- mask revision and image identity
- algorithm and algorithm version
- pruning threshold
- review and correction provenance

Staleness is determined from the current binary mask content and calibration,
not merely from a generic annotation revision counter. This avoids invalidating
a skeleton when unrelated mask metadata changes while still detecting changes
to the analyzed geometry or physical calibration.

## Scientific export

Only an approved, latest, non-stale analysis may be exported.

The skeleton export includes the complete persisted analysis and provenance,
raw/auto-pruned/final skeleton pixel tables, raw/auto-pruned/final branch
tables, branch-angle tables, summary measurements, a manifest, checksums, and
a ZIP archive. The package is verified against its manifest before ReefVision
reports it as verified.

## Interpretation limits

ReefVision skeletonization describes the geometry encoded by the reviewed
segmentation. Measurement error can therefore arise from segmentation error,
image resolution, occlusion, projection, calibration error, pruning choices,
and human corrections.

Reported TLE is a 2D projected centerline metric. It should not be described as
true three-dimensional colony branch length unless an independent 3D method
supports that interpretation.
