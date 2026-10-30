# ReefVision 1.6 — class visibility save isolation

Development checkpoint (2026-10-30), Track D / issue #76 / draft PR #77.

## Existing scope audited

Per-user and project-default class visibility already persists through the local API,
with session overrides taking precedence. This change does not add a second
visibility store or duplicate the existing Workflow Builder, QC or class-manager
implementation.

## Failure mode and fix

A visibility PUT/DELETE can complete after a researcher switches projects in
the editor. Previously the mutation's completion handler used the editor's
currently selected project to select a React Query cache entry. An old
response could therefore be written into the new project's cached visibility
settings, incorrectly hiding or showing scientific annotation overlays.

Every save/reset request now carries its originating project ID through the
API call and response. The completion handler writes only that project's cache
entry and checks the cached bundle's project ID before changing any scope.
Messages from an old project do not replace the current project's status.
Neither persisted scientific records nor model predictions are modified.

## Evidence and release gates

- Pure regression: matching-project save changes only the requested scope and
  layer; mismatched-project responses preserve the cached bundle by identity.
- Editor regression: delay the first project's save, switch to another project,
  then resolve the old save; only the original project's cache may change.
- No migration or new Workflow Builder node is needed: visibility is an editor
  display preference, not a scientific computation or workflow artifact.
- Required before acceptance: exact-head frontend lint, typecheck, component
  tests and E2E; backend CI, Windows installed-GUI switch-project exercise,
  independent 1.1/1.6 migration reconciliation and biological-data validation.

Release HOLD. No cross-version merge, installer release, deployment,
pretrained-weight download or user-asset deletion.
