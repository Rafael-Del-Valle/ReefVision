# ReefVision 1.6 — local desktop publication staging integrity

## Existing-scope audit
The 1.0–1.5 local desktop backend, 1.6 class visibility/QC, dense editor,
onboarding, installer/start/update support and typed, executable, persisted QC
Workflow Builder already exist. This change is **not** another scientific
workflow node: it addresses the packaged desktop sidecar's local filesystem
handshake. Existing graph inputs, outputs, units, saved runs, provenance,
retries and explicit researcher approvals are unchanged.

## Failure and correction
Both the GUI-ready port file and packaged self-test result previously used the
predictable staging suffix `.tmp`. A previous crashed process or another
local process could leave that path occupied. In particular, opening a
preplanted symbolic link with `Path.write_text` follows the link and can
truncate an unrelated biological observation or researcher-controlled artifact
before `os.replace` publishes the intended output.

Both writers now use an exclusive, unpredictable file created with
`tempfile.mkstemp` in the destination directory. The handle closes before
atomic replacement (including on Windows), and failed publication removes
its staging file. An old fixed-suffix `.tmp` is deliberately **not** removed
or overwritten: it may be someone else's file. Only the requested publication
target is replaced. No model downloads, original-image changes, migrations
or scientific data repairs occur.

## Regression and release boundary
Backend tests cover normal port publication, occupied legacy staging file
preservation, a Swiftia observation behind a planted staging symlink,
preservation of a prior ready signal and cleanup on simulated Windows lock,
and self-test JSON publication with preserved old evidence. The symlink test
skips only where the host cannot create disposable symlinks. An independent
local Python probe passed the symlink and failed-replace scenarios; this
is not full repository pytest.

**RELEASE HOLD** until exact-head Ruff/mypy/pytest, frontend format/type/unit/
E2E/build, native Windows preservation, representative standalone and saved
typed-QC workflow replay, independent 1.1/1.6 Alembic-0038 reconciliation,
real MSI/CAB clean install/upgrade/rollback and installed GUI checks, and
researcher approval. 1.7/revised 1.8 remain isolated. Do not merge, release
or modify research assets.
