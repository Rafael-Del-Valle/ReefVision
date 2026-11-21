# ReefVision 1.6 — invocation-bound Windows acceptance evidence

The **Track D 1.6** `scripts/phase11c-acceptance.ps1 -TrackD16` wrapper now generates a random 12-character lowercase hexadecimal acceptance token and passes it to the existing disposable clean-install harness with `-EvidenceToken`. The child writes its report only under `.artifacts/windows-clean-acceptance-<token>/report.json` and refuses an already-existing evidence or run directory. Its report also records `evidence_run_token`. The wrapper requires the exact token, the actual disposable acceptance root supplied to the child, and the canonical full `<acceptance-root>/reefvision-clean-<token>/data` path before independent installed-science verification. A matching last-directory name at a different root is not accepted.

This removes a false-attribution race: two simultaneous clean-install jobs may each produce a valid new report, but only the report tied to the *current* parent invocation can be evaluated. A missing, stale or mismatched report fails closed. An unrelated concurrent run does not spuriously cause rejection. Historical Phase 11C mode retains its prior unique-new-directory selector, and direct clean-install runs without `-EvidenceToken` retain their generated-token behavior. `-PlanOnly` remains a non-installing dry run and does not imply a release-ready installed-GUI result.

**Regressions:** `scripts/test-phase11c-report-selection.ps1` exercises native Windows PowerShell token shape, canonical case/path normalization, rejection of different-root and same-basename substituted data paths, legacy report selection and exact-head checks. `apps/api/reefvision/tests/test_phase11c_acceptance_contract.py` checks wrapper/child token handoff and fail-closed report binding. CI runs the native PowerShell script in the Windows research-preservation job. The existing installed-science validator still requires class visibility, QC review and executable persisted/replayed typed Workflow Builder evidence with scientific provenance and explicit researcher review.

**Release status: HOLD.** This is an evidence-attribution improvement, **not** a genuine installed Windows MSI/CAB acceptance result. Independent 1.1/1.6 Alembic-0038 reconciliation, complete exact-head backend/frontend/E2E/Windows CI, representative biological saved-workflow checks, real MSI clean installation/upgrade/rollback, installed GUI and explicit researcher approval remain outstanding. No 1.7/revised-1.8 changes, merge, tag, release, hosting, model-weight download or research-asset deletion are authorized.

## Fully qualified local-drive evidence paths (2026-11-21)

The 1.6 wrapper now refuses Windows drive-relative (`C:folder`),
current-drive-rooted (`\\folder`), UNC and extended-device evidence roots
**before** calling `GetFullPath`. On Windows, `Path.IsPathRooted` can return
true for a path that is not fully qualified; expanding it against the
process's working directory could otherwise make an incomplete report path
appear to match the invocation's disposable root. The expected root supplied
to the child, returned acceptance root and returned isolated data root all
require ordinary fully qualified local-drive paths. Case differences and
forward-slash separators remain supported.

Native PowerShell regressions reject five unsafe path forms independently
at all three validation positions and accept a standard forward-slash path.
The independent Python verifier remains the final installed-science gate.
No user data, schema, model, or Workflow Builder node is changed.

## Independent installed-science token binding (2026-11-21)

The standalone Python installed-Windows verifier now checks the report
`evidence_run_token` against its exact `reefvision-clean-<token>/data`
directory, even when called without the PowerShell wrapper. For Track D 1.6,
the wrapper supplies `--expected-evidence-token`, binding the independent
class-visibility, QC and saved executable Workflow Builder PASS decision to
the invocation that actually launched the disposable MSI test. Missing,
malformed, replayed and substituted tokens fail closed. Historical direct
install reports with no invocation token remain supported without this
explicit option.

Python regression cases cover matching, missing, invalid/case-changed and
different-run tokens plus the parent-to-verifier CLI contract. This is an
evidence integrity improvement, not proof of a completed MSI installation;
full exact-head CI, cross-track 0038 reconciliation, representative biology,
installed-GUI upgrade/rollback, and researcher approval remain outstanding.

## Installed QC project-lineage causal gate (2026-11-21)

Audited the already implemented 1.6 class-management, visibility, review,
saved executable QC Workflow Builder, native Windows acceptance harness and
1.0–1.5 overlap. The installed harness records successful post-restart
`project_persistence` **before** `qc_review_coordination`, but its independent
Python verifier previously allowed the reverse while both gates individually
reported PASS inside the test window. This could attribute QC results to
an image/annotation whose survival across restart had not yet been verified.

The independent verifier now requires project persistence before QC
coordination. Regression tests reject the inverted chronology and accept the
restored native-harness sequence, without altering scientific data, installation
artifacts, typed graph execution, provenance, approvals, or migrations. Also
corrected the exact backend Ruff E501 test line reported by CI
[#44904743983](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44904743983).

**RELEASE HOLD:** new exact-head CI, full tests, 1.1/1.6 Alembic-0038
reconciliation, representative biological persisted-workflow acceptance,
genuine Windows MSI/CAB clean install/upgrade/rollback and installed-GUI
checks, plus explicit researcher approval. No unrelated version changes.

## Exact-head CI formatting unblock (2026-11-21)

A fresh read of exact-head [Actions #44909736559](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44909736559) identified two independently blocking format gates: backend Ruff format in the Phase 11C token-binding contract test, and frontend Prettier in the class-reassignment panel and its regression tests. The native Windows research-preservation check passed. Applied only the formatter's exact reported source changes in these three files; **no** scientific operation, reference/category inventory, human approval, Workflow Builder execution, MSI behavior or database migration semantics changed. These isolated formatting corrections are needed before the existing backend pytest and frontend TypeScript/unit/E2E/build gates can execute. Source-level substitutions and branch readback are not a replacement for those tests; require a new exact-commit CI pass before making a release claim.

Status: **RELEASE HOLD** pending CI, 1.1/1.6 Alembic-0038 reconciliation, native Windows MSI/CAB installed GUI/upgrade/rollback, representative biological saved-workflow validation and researcher sign-off.

## Class-reassignment blocking-inventory regression (2026-11-21)

After the 1.6 preview safety checks began enforcing the backend's exact
scientific reference categories, [CI #44914871500](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44914871500)
completed backend and native-Windows preservation successfully but failed
**two frontend tests**. Their synthetic `blocking_records` used the unsupported
key `archived_annotation`; the UI correctly classified that as incomplete
scientific evidence rather than displaying a complete blocked preview.

Updated those two fixture variants to the supported
`review_queue_items_workflow` category so they test the intended valid,
**blocked** preview with a nonempty inventory, while preserving disabled
execution and zero mutation requests. Added separate reassignment and
reassign-and-delete regressions for an unknown blocking category: these must
show *incomplete evidence*, refuse execution, and issue no mutation requests.
This intentionally changes no production behavior or backend scientific
contract; full category validation and researcher review gates remain intact.

The updated tests require exact-head CI confirmation; no local full repository
checkout is possible here while github.com DNS remains unavailable. This is
**not** Windows installed-MSI/GUI acceptance. Version 1.6 remains on release
HOLD for full CI/scientific acceptance, 1.1/1.6 Alembic-0038 reconciliation,
representative biological saved workflows, real installed MSI/CAB validation,
and researcher approval.
