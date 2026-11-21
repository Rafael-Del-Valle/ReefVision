# ReefVision 1.6 Phase 11C: isolate installed-acceptance evidence

Status: **release HOLD**. Branch: `develop/reefvision-1.6`; draft PR #77.

## Gap and remedy

The Phase 11C wrapper launched a disposable Windows clean-install harness, then
chose the newest report directory not present at startup. When another
concurrent isolated acceptance run created a report in the same repository,
the wrapper could select that run's later-modified evidence and misattribute
its PASS outcome to this invocation.

The wrapper now requires **exactly one distinct new** report directory after
the child process exits successfully. Zero or multiple candidates fail closed.
It does not delete, rename, overwrite, or inspect existing user assets, and it
does not change the independent installed scientific report validator. Report
selection never uses modification time to arbitrate concurrent evidence.

The native Windows regression checks an ordinary run, the first run, duplicate
listings, Windows case-folded paths, missing evidence, and multiple concurrent
reports. It also checks the existing 1.6 branch and exact-build-commit gates.
CI executes the PowerShell regression on `windows-latest`. A Python source
contract keeps the parent wrapper wired to the tested helper.

This is installation-evidence integrity, not a scientific computation; it
does not duplicate a Workflow Builder node. Existing typed saved QC graph
execution, provenance, human review, retry/replay and units are unaffected.

## Acceptance limits

The native helper regression is not a real installed MSI/CAB acceptance.
Genuine disposable Windows MSI clean-install, populated-database upgrade and
rollback, interactive class visibility/QC/Workflow Builder GUI, representative
biology, and the independent 1.1/1.6 Alembic-0038 reconciliation still require
verification and explicit researcher approval. No merge or release is authorized.
