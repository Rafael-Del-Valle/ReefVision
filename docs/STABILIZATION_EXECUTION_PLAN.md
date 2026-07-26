# ReefVision stabilization execution plan

This plan converts the current all-phases branch into a release candidate without adding product features.

## Immediate freeze

- Keep `.reefvision-feature-freeze.json` active.
- Reject new production modules and migrations.
- Allow only defect fixes, deletion, tests, release evidence, packaging repairs, documentation corrections, and simplification of existing workflows.
- Do not merge encoded or generated source payloads. Implementation source must be readable in the PR.

## Review decomposition

Use `RELEASE_REVIEW_DOMAINS.md` as the mandatory file and journey boundary. Prepare focused follow-up PRs in this order:

1. core projects and annotation;
2. datasets, training, inference, and evaluation;
3. coral measurements and scientific validation;
4. classification;
5. video and tracking;
6. providers, Prompt Assist, depth, and active learning;
7. interchange and workflow composition;
8. desktop, storage, recovery, and release.

Each domain PR must list:

- included paths;
- removed or consolidated abstractions;
- exact user journey tested;
- automated results;
- real-data or installed-app evidence;
- deferred capabilities;
- known defects.

## Code-reduction rule

During each domain review:

1. identify routes, schemas, services, jobs, UI panels, scripts, and tests that represent the same concept;
2. choose one canonical implementation and naming contract;
3. remove unused wrappers, duplicate compatibility rules, dead feature flags, temporary adapters, and unreachable UI;
4. preserve migrations and stored-data compatibility unless a reviewed migration is explicitly approved after the freeze;
5. rerun the domain journey after every deletion or consolidation;
6. update the demonstrated-journey ledger with evidence.

A file is not justified merely because a test imports it. It must participate in a supported journey, provide a necessary safety boundary, or be removed.

## Validation sequence

Run from the Windows repository root:

```powershell
.\scripts\run-all-phases-acceptance.ps1
.\scripts\run-release-validation.ps1
.\scripts\run-complete-release-validation.ps1 -PerformMachineInstall
```

Then complete the real journeys recorded in `DEMONSTRATED_USER_JOURNEYS.md` using representative coral images, trained checkpoints, fish videos, external consumers, and a clean installed desktop environment.

## Decision rule

For every capability, choose exactly one outcome before release:

- **supported:** automated and real/installed evidence passes;
- **experimental:** clearly labeled, isolated from the primary journey, and unable to corrupt trusted data;
- **unavailable:** visible readiness state with no misleading controls;
- **removed:** code and UI deleted from the release candidate.

No capability may remain implicitly supported solely because implementation-shaped code exists in the repository.
