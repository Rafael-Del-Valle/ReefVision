# ReefVision 1.6 — fail-closed desktop API ready-port handshake

## Milestone and existing-scope audit (2026-11-22)

The 1.0–1.5 desktop foundation already starts a bundled local Uvicorn sidecar,
publishes its selected loopback port through an atomic context file, and
exposes a control-channel shutdown. The isolated 1.6 branch already has
per-project and per-user class visibility, QC assignment/comment/bulk review,
dense editor, onboarding, startup commands, Windows packaging safeguards and
an executable **typed and persisted** QC Workflow Builder with provenance,
retry policy, dimensionless priority values and explicit researcher approval.
Do not duplicate any of those capabilities.

The remaining handshake gap was the failure path: when the API listener
started but its port could not be read or written to the desktop context file
(e.g., invalid parent path or filesystem permission failure),
`publish_runtime_port_when_ready` raised in a background task while the
main coroutine awaited `uvicorn.Server.serve()`. The sidecar could remain
running without a GUI-connected port even though publication was impossible.
That is both an onboarding failure and unnecessary exposure of the local
write-capable scientific API.

## Implemented contract

- On a readiness/port-file publication exception, signal the existing
  Uvicorn server's shutdown **before** propagating the original error.
- Preserve the atomic context-file write, actual bound-port discovery, and
  successful startup path. Do not publish a requested ephemeral port of zero.
- The existing server coroutine observes `should_exit`, completes its
  shutdown, and then awaits the publisher's original failure so packaged
  startup returns a nonzero exit status.
- Do not mutate source images, annotations, masks, dataset versions,
  researcher review decisions, local models or saved workflow evidence.
  No migration or additional Workflow Builder node is warranted: this is a
  local desktop transport handshake, not a scientific data transformation.

## Regression and acceptance

`test_desktop_port_readiness_16.py` exercises actual publication of a bound
ephemeral-port mock, an unavailable socket (no fabricated ready signal), and
a ready-context path whose parent is a file. The last test uses a live async
sidecar simulation that remains active until signaled to shut down. It asserts
the publisher's original filesystem failure, server termination request,
researcher-controlled file preservation and absence of a false ready signal.

The GitHub commit and remote source read-back confirm **authored code and
tests**, not execution. A complete exact-head Ruff/typing/pytest, frontend
format/type/unit/E2E/build, scientific standalone + saved typed QC graph
regression, migration-lineage compatibility and native Windows CI matrix
must still pass. Validate the real Windows installer/CAB with a clean install,
prior-version upgrade, rollback, installed-GUI normal startup, and a
deliberately unwriteable ready-context path in a **disposable test directory**.
Do not damage user profiles or research data to test this.

## Release boundary

**RELEASE HOLD:** independent 1.1/1.6 Alembic-0038 history reconciliation,
full head-specific CI, representative biological and persisted-workflow
acceptance, Windows MSI/CAB installed-GUI validation and explicit researcher
approval remain required. Version 1.7 and the **revised**, nonduplicative
1.8 research scope are untouched. No merge, tag, release, deployment, paid
hosting, unapproved pretrained-model download or user-asset deletion.
