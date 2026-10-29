# ReefVision 1.4 — first project-scoped 3D source persistence slice

The local-only `POST /api/v1/projects/{project_id}/spatial/assets` accepts
multipart OBJ, PLY, or GLB originals (8 MiB maximum). Exact source bytes
are stored under the managed project directory with an immutable SHA-256
digest, byte count, filename, format, and timestamp in SQLite. Identical
bytes of the same format deduplicate within one project. List, detail,
and byte-content retrieval are project-scoped. Content reads recheck the
stored byte length and SHA-256 and reject missing or modified originals.
The managed filesystem path is never exposed by the API.

PLY is `mesh_or_point_cloud` because the extension alone does not establish
topology. Raw imports are **unreviewed**, not parsed, calibrated, registered,
or biologically identified. No delete or remote publishing operation exists.

This is a first persistence slice, **not yet** a finished asset workspace.
Standalone mesh/point-cloud previews and typed persisted Workflow Builder
nodes still consume bounded inline geometry. A subsequent 1.4 slice must
bind project-owned asset IDs to both execution paths with digest checks,
saved-graph replay tests, and an interactive asset picker. Installed-Windows
GUI, large-file streaming, and full scientific release gates remain open.
