# Stabilization failure triage

The first executable Windows release-validation run established the following
repair order. Do not start new feature work while any earlier tier remains red.

## Tier 0 — application startup and test collection

- Keep the experimental SAM 2 sidecar isolated from supported API startup.
- Repair its stale prediction-result contract in a later focused provider slice.
- Require the coral journey and full pytest suite to collect before interpreting
  individual test failures.

## Tier 1 — deterministic repository hygiene

- Run Ruff safe fixes and Ruff formatting across `apps/api` and `scripts`.
- Review every non-format semantic change before commit.
- Run Prettier over the 16 reported frontend files.
- Keep `git diff --check` clean.

## Tier 2 — static correctness

- Reduce strict mypy errors by domain rather than adding broad ignores.
- Start with shared schemas and provider contracts because they fan out into the
  largest number of services.
- Do not weaken strict mypy globally to make the gate green.

## Tier 3 — executable regressions

- Run the coral import-to-export journey.
- Run focused tests for any corrected backend domain.
- Run full pytest and Vitest only after collection and formatting are clean.

## Tier 4 — release environment

- Correct bootstrap native-stderr handling so successful npm installs with
  deprecation warnings do not fail the gate.
- Re-run packaging only after the non-packaging gate is green.

## Local commands for the next pass

```powershell
# Update the focused stabilization branch.
git pull

# Confirm API startup and the contained sidecar boundary.
.\.venv\Scripts\python.exe -m pytest `
  apps/api/reefvision/tests/test_sam2_sidecar_route_stabilization.py `
  apps/api/reefvision/tests/test_stabilization_coral_journey.py -q

# Re-run the full non-packaging gate without reinstalling dependencies.
.\scripts\run-release-validation.ps1 -SkipBootstrap -SkipPackaging
```

Upload the newest `release-validation-failure-bundle.zip`; older failure bundles
must not be mixed into subsequent triage.
