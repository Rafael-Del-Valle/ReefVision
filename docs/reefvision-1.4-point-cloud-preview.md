# ReefVision 1.4 — provisional XYZ point-cloud preview

The standalone `POST /api/v1/projects/{project_id}/spatial/point-cloud-preview` endpoint and executable persisted `point_cloud_preview` Workflow Builder node share one bounded measurement engine.

Inputs are **either** up to 2,000 XYZ points **or** a vertex-only ASCII PLY 1.0 file with three floating-point XYZ properties. Binary PLY, color properties, polygon meshes, normals, and other attributes are deliberately unsupported in this first preview. The original PLY is passed as text; **no persistent 3D asset is created**.

Outputs include point count, duplicate-point QC, calibrated global-axis extents and diagonal, arithmetic centroid in the source coordinate frame, and scale-only uncertainties when supplied. The axis-aligned bounding-box **envelope** volume (m³) is the product of the three extents, **not** coral tissue volume or reconstructed occupied volume. Its scale-uncertainty interval applies the lower and upper scale factors cubically. Coplanar or collinear points have zero envelope volume, regardless of actual organism thickness. Surface area and branch length are **null**, not estimated from a point cloud. Scale evidence and exact geometry fingerprint are recorded, but calibration and coordinate registration are **not verified**. Dimensions are not anatomical branch measurements, and geometry fingerprints are not organism identities.

Both standalone API and saved-workflow artifacts remain `caller_supplied_unverified`. Do not promote to a verified scientific observation without human review and registration/calibration QC. Future work includes persistent 3D assets, large/binary clouds, interactive viewer, registration and longitudinal comparisons.
