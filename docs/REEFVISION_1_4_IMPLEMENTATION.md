# ReefVision 1.4 implementation

Work in progress on isolated branch. Scientific 3D mesh measurement and Workflow Builder integration are the first planned vertical slice. This document does not imply release readiness.

## Local mesh file preview (in development)

The Workflow Builder workspace now offers a standalone, bounded OBJ/ASCII PLY/GLB
file picker. The local desktop UI reads a selected file and sends it to the
project-scoped local API mesh-preview endpoint, then renders the returned
bounded triangle sample using the existing interactive yaw/pitch/zoom viewer.

The current request contract limits OBJ and PLY files to 256,000 bytes and GLB
files to 262,500 bytes before base64 encoding. Backend geometry validation
still applies. The UI requests a positive meters-per-source-unit scale and
human-entered calibration evidence; optional relative scale uncertainty is
propagated into measurements. Calibration is **not** automatically verified.

Standalone preview results are transient. To persist a reproducible
measurement and provenance, users must configure and execute the typed
`mesh_surface_preview` node in a saved Workflow Builder graph. The full
mesh is used for scientific surface-area and dimension calculations; the
512-triangle visualization sample must never be treated as a biological
measurement or as evidence of specimen identity.

Outstanding: persistent asset ingestion and versioning, registered
coordinate frames, independent calibration review, direct point-cloud
visualization, validated anatomical branch lengths, longitudinal identity
linkage, and installed desktop/GPU/scientific acceptance.
