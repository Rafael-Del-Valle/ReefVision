# ReefVision 1.6 — offline desktop loopback security

## Prior-scope audit

Versions 1.0–1.5 already provide the local FastAPI desktop sidecar, annotation
stores, model workflows and the installer framework. Version 1.6 already has
persistent class visibility, QC event/assignment/bulk review, the dense editor,
and an executable saved QC Workflow Builder. Do not duplicate these systems.

The desktop CLI previously accepted `--host 0.0.0.0`, `--host ::` and remote IP
addresses, and the resulting Settings value was passed to Uvicorn. CORS is not
API authentication or a defense against direct non-browser requests, so
an unintentionally exposed local desktop API could provide network access to
private projects and biological records.

## Change and behavior

- Restrict desktop sidecar binding to loopback IP literals (including the IPv4
  loopback range and IPv6 `::1`) or the conventional `localhost` hostname.
- Refuse non-loopback IPs, wildcard listeners and arbitrary DNS hostnames
  with an explicit error. The CLI fails before creating the research data
  directory or running database migrations.
- Validate in argument parsing, Settings construction and the async server
  entrypoint. Programmatic callers cannot bypass the final bind check by
  passing a nonlocal Settings instance.
- Keep normal ephemeral-port startup, packaged self-test, offline inference,
  installed commands, scientific data, original image pixels and every
  approval/revision unchanged. This does not authorize remote hosting.

## Regression and acceptance

`apps/api/reefvision/tests/test_desktop.py` tests rejection through CLI,
programmatic Settings construction and direct async server startup, and
acceptance of `127.0.0.1`, another valid 127/8 loopback IP, `::1` and
`localhost`. All invalid-address tests must have **no published port** or
new data directory. Run backend Ruff, mypy, pytest, full frontend and E2E,
migration compatibility and native-Windows preservation CI on the exact SHA.
Also test actual installed Windows MSI/CAB clean install, upgrade, rollback,
loopback startup and local GUI before release. Source-only tests are not proof
of an installed application's behavior.

## Workflow Builder boundary and release hold

The bind-address check is an application security boundary, **not** a biological
workflow transformation. Existing typed QC Workflow Builder ports, units,
saved graphs and runs, provenance, retries and mandatory researcher review are
unchanged. No new node, migration, online service or pretrained model is needed.

**RELEASE HOLD:** independently reconcile incompatible 1.1/1.6 Alembic-0038
histories, obtain complete exact-head CI and representative real biological
saved-workflow acceptance, run installed Windows packaging/GUI tests and
obtain explicit researcher approval. Do not merge unaccepted branches,
tag/release, deploy, download unapproved weights or delete user assets.
