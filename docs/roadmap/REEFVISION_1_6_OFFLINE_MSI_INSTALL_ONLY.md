# ReefVision 1.6 — offline pinned-MSI install-only contract

**Status:** development only; no release acceptance or user-data migration authorization.

## Scope and overlap audit

The existing 1.6 Windows command installer, `update-reefvision.ps1`, MSI
provenance verifier, pinned MSI digest, local-source-commit verification,
Windows installer rollback ownership, and command preflight already exist.
This change does **not** add a second installer, change model providers, or
duplicate the earlier class/QC/Workflow Builder implementations.

Previously, `update-reefvision --install-only` still evaluated the ordinary
dependency-setup decision and could invoke `bootstrap.ps1` before installing
a previously built and SHA-256-pinned MSI. This could unexpectedly require
network access or modify Python/Node development dependencies even though
the user requested only installation of a cached MSI.

## Contract

- `--install-only` never executes the dependency bootstrap, regardless of
  changed dependency signatures or missing `.venv`/`node_modules`.
- `--install-only --setup` is explicitly rejected rather than silently
  ignoring the user's contradictory request.
- Normal build/update paths still bootstrap when the dependency signature
  changes or development environments are missing, unless `--skip-setup`
  is explicitly selected. `--setup` still forces setup for build/update.
- `--dry-run --install-only` reports `setup_needed: false`.
- The provenance validator uses only Python's standard library. If the
  repository's .venv is absent, an **already installed** Python 3.11+ on PATH
  is permitted, running with -I -S -B (isolated, no site packages, no bytecode
  writes). No interpreter or packages are downloaded. If neither interpreter
  exists, installation fails closed **before** the running desktop is stopped.
  If the .venv interpreter is broken or older than 3.11, the resolver
  checks other already-installed Python executables on PATH in order, never
  launching Windows Store App Execution Aliases. An unusable candidate does
  not trigger package installation or desktop shutdown. This is not a
  Python-free installer; native MSI/GUI acceptance remains required.
- Installation still requires a pinned MSI, matching SHA-256, verified
  embedded source commit/version, safe local MSI/log paths, and successful
  Windows Installer execution. No automatic pretrained model downloads,
  repository updates, user-asset deletions, or scientific approval are added.

## Regression and acceptance

`scripts/test-reefvision-msi-update.ps1` now parses the **actual** updater
PowerShell AST, evaluates the setup decision in an isolated disposable
fixture, and checks five cases: install-only with and without skip-setup,
normal dependency mismatch, explicit skip-setup, and explicit setup.
It also checks for the conflicting-option guard. The Windows preflight
now exercises the actual Python resolver against a disposable repository
without .venv, verifies selection of an existing Python executable, checks
recovery from a corrupt local .venv executable, and confirms a missing
validator still fails before installation. The Windows build workflow
provisions a known Python 3.12 interpreter before this preflight (without
installing ReefVision dependencies), rather than relying on the runner's
ambient PATH. The existing `.github/workflows/build-desktop.yml` Windows
preflight invokes the test before building an MSI.

This check does not execute `msiexec`, perform an actual upgrade/rollback,
or verify an installed GUI. Native Windows test results, MSI upgrade and
rollback, installed GUI, cross-version 1.1/1.6 Alembic revision-0038
reconciliation, saved executable Workflow Builder regressions, and
representative biological-data validation remain release HOLD gates.

No cross-version branches were merged, and no user files were modified.

## Unattended downgrade preflight (2026-10-30)

A cached MSI can have valid provenance and a correct digest while still being
**older than the installed desktop**. The updater now calls
`Assert-ReefVisionMsiNoDowngrade` after verifying the MSI payload and before
stopping ReefVision. It compares numeric three-part MSI versions with three-
or four-part installed executable FileVersions, including the fourth build
component. A known newer installed build is never silently replaced by an
older pinned MSI. Unknown nonempty installed version strings fail closed,
rather than being treated as an empty/uninstalled machine. A missing installed
version (clean install) and an equal version (MSI-managed repair) remain
permitted. No version changes, migrations, model downloads or user-data
operations are performed by this preflight.

The Windows MSI preflight covers clean install, same-version repair,
three/four-part version comparisons, known downgrades, unknown installed
versions, invalid target numeric limits, and the **verification -> downgrade
guard -> desktop shutdown** ordering. These are source-level and helper tests,
not proof of a real Windows upgrade/rollback. Native installed-GUI acceptance,
representative biological data, cross-version Alembic 0038 reconciliation,
and complete exact-head CI remain release HOLD gates.


## Build source-provenance gate (2026-10-30)

The updater already recorded the Git HEAD as MSI provenance, but did not
reject a dirty working tree or a source change during compilation. An MSI
could therefore claim a clean source commit while containing uncommitted or
untracked local changes. The 1.6 updater now calls
`Assert-ReefVisionSourceTreeClean` immediately before and after the desktop
build. It requires the same full 40-character Git SHA and no tracked or
untracked source changes. If either condition fails, the updater refuses to
select or cache the newly built installer; it does not stop the installed
application. Ignored build outputs remain permitted. This is a fail-closed
source-integrity guard, not a claim that Git commits are cryptographically
signed or that the MSI is reproducible byte-for-byte.

The disposable Windows Git fixture exercises a clean source, mismatched HEAD,
dirty tracked file, untracked file, and clean recovery. The preflight also
asserts both call sites in the actual updater. The guard is deliberately not
run for `--install-only`, which relies on its previously pinned digest and
independent MSI/CAB provenance checks. No migrations or scientific Workflow
Builder nodes are introduced by this packaging-only change. A native Windows
MSI installation, rollback and installed-GUI acceptance are still required.

## Pinned build identity survives a later checkout (2026-10-30)

A previously verified MSI can remain cached after a researcher checks out a
newer ReefVision commit or version. Previously, `--install-only` verified the
old MSI against the **current** checkout's version and HEAD, causing a valid
pinned build to fail provenance verification. A subsequent checkout must not
silently redefine the cached installer's identity.

The command configuration now persists `last_installer_version` and
`last_installer_source_commit` alongside the existing exact local MSI path
and SHA-256 **only after a successful build/provenance check**. During
`--install-only`, the updater reads this pinned identity rather than invoking
Git or taking the current checkout's version. It still verifies the cached
MSI hash, MSI/CAB manifest and embedded source provenance, and still rejects
installing a version older than the currently installed desktop **before**
stopping the application. The repository and validator must remain locally
available; no network or package bootstrap is introduced.

Legacy cached MSI configurations lacking either pinned identity field now
fail closed with instructions to rerun `--build-only`; the updater never
infers identity from an untrusted filename or changed checkout. The Windows
preflight covers valid pinned identity, missing version/commit, invalid SHA,
invalid MSI numeric limits and the actual updater's pinned-identity wiring.
Native MSI upgrade/rollback and installed-GUI acceptance remain outstanding.

## Unreadable installed-version fail-closed preflight (2026-10-30)

An installed executable with missing/corrupt version metadata previously yielded
`$null` from `Get-ReefVisionExecutableVersion`. The downgrade check interpreted
that value as a clean installation, even when a ReefVision executable existed.
A stale per-user installation registration could produce the same ambiguity.

The updater now distinguishes an absent, unregistered installation from an
existing executable with unreadable version metadata or a registered install
whose version cannot be verified. Either ambiguous existing-install case
fails closed **after verifying the pinned MSI and before stopping ReefVision**.
A genuinely clean install, or an existing executable with a known version,
continues through the existing numeric downgrade guard. Disposable Windows
preflight regressions cover both failures, both valid cases and call ordering.
This is not a claim of native installed-GUI or MSI rollback acceptance.

## Per-machine MSI registration safeguard (2026-10-30)

The WiX MSI declares `InstallScope="perMachine"`; Windows normally registers
it under a GUID-named uninstall entry in HKLM rather than the historical HKCU
ReefVision key. The updater now checks the HKCU and both native/WOW6432Node HKLM
uninstall views for an **exact** ReefVision DisplayName, in addition to the
legacy keys. If an installation is registered but its executable version is
unreadable, the existing fail-closed version guard stops **before** desktop
shutdown. Registry inspection is read-only. Disposable HKCU test entries
exercise absent, unrelated, similarly named, and exact product registrations
without modifying actual installation keys. Native Windows CI must pass before
this is accepted; this does not substitute for a real MSI upgrade/rollback or
installed-GUI validation.
