# Milestone 5 Report

## Summary

This pass adds the ReefVision 1.3.0 backend foundation for local model registration, queued detector inference, persisted prediction proposals, proposal review, SAM-style assist-session APIs, and annotation provenance. It also exposes project-level model registration, gallery-side detector job launch controls, and annotation-editor prediction review UI.

## Implemented

- Registered project-scoped model checkpoints with SHA-256 checksums, framework/task/provider metadata, notes, and stored class maps.
- Queued inference jobs backed by the existing `jobs` table and worker loop.
- Persisted prediction proposals with pending/accepted/rejected/edited-and-accepted review state.
- Acceptance of proposals into normal ReefVision annotations while preserving provenance.
- In-memory SAM-style assist-session runtime with prepared-image caching and backend acceptance into box annotations.
- Project UI for model registration and gallery UI for launching inference jobs.
- Annotation-editor prediction overlay, filtering, single accept/reject, and bulk visible review.

## Verification

Backend:

- `.\.venv\Scripts\python.exe -m pytest --basetemp='..\test_runtime_tmp\pytest_m5_backend_all_post_fix' apps\api\reefvision\tests -q`
- `.\.venv\Scripts\python.exe -m ruff check apps\api`
- `.\.venv\Scripts\python.exe -m mypy`

Frontend:

- `cmd /c npm.cmd run typecheck`
- `cmd /c npm.cmd test`

## Known limitations

- The Smart Mask and SAM Box backend session APIs are implemented, but the existing React editor only exposes prediction-review UI in this pass; a dedicated brush-driven Smart Mask canvas workflow is still pending.
- Real Ultralytics/SAM execution depends on optional local ML dependencies that are not installed in the repository `.venv`.
- Desktop packaging, NSIS installer verification, and production checkpoint-shipping decisions were not revalidated in this sandbox.

## Security and trust boundary

- Checkpoints are treated as trusted local `.pt`/`.pth` files only.
- The repo documents and enforces a provider boundary instead of claiming arbitrary model formats are safe.
- No model download, cloud inference, active learning, or training workflow was added.
