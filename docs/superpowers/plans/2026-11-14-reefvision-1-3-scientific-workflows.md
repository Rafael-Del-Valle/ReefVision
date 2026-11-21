# ReefVision 1.2 acceptance and 1.3 scientific workflows

The reviewed 1.3 base is `ff19386e557a0b354d693ccf3aebe8fd92ef7bf5` on `codex/reefvision-1.2-reefpose`. Draft PR #85 keeps acceptance changes. The separate `codex/reefvision-1.3-scientific-workflows` branch will use a stacked draft PR.

## 1.2 acceptance

- In the existing validation job, export and UI paths, verify old interrupted protocols against the original input digest and held-out lock. Preserve the failed job and provide recovery or original-project guidance. Cover exact replay and rejection of changed inputs.
- Exercise the pinned Ultralytics Windows stack with a disposable profile and local synthetic checkpoint. Keep production compatibility checks active. Inventory permitted real references and provide a review protocol for unavailable independently reviewed datasets.
- For a changed head, verify the Windows MSI and its media payload on disposable runners. Use existing migration and backup fixtures for rollback and unknown-head rejection. Keep representative measurement and installed scientific workflow evidence separate.

## 1.3 worktree

- Extend ReefPose validation with project-scoped comparison of frozen held-out reports. Use the existing scored event windows and matched measurements. Report descriptive error, zero denominators, individual-weighted summaries, agreement limits under explicit assumptions, and paired uncertainty at declared independent sampling units.
- Reuse ecology identity and experimental unit declarations. Add reviewed study assignment metadata and retained snapshots where the current registry lacks site, treatment, tank, and sampling semantics. Use existing longitudinal summaries for independent-unit weighting and preserve explicit missingness.
- Create event-summary contracts, services and API routes, plus a panel inside Organisms & ecology and an executable Workflow Builder node. Select current reviewed pose links and one detector definition per recording span. Count confirmed complete events pinned by those links. Compute valid seconds from consecutive measured frames and exclude intervals with missing frames. Use elapsed time between observed frames. Aggregate durations and counts per organism, and only display grouped unit estimates when every included organism has a compatible declared unit.
- Persist report configuration and evidence, export JSON/CSV and vector figures, and make reports depend on immutable analysis snapshots. Reuse completed scientific job and Workflow Builder artifacts where they represent the lifecycle. Use a forward `b13_scientific_0001` migration if study data requires schema changes.
- Extend the current QC dashboard, job API, rules and Workflow Builder adapter with acquisition checks and explicit thresholds. Preserve warning-only results and original media.
- Extend the integrated archive validator and import mappings for every new persisted type. Verify old format and migration compatibility, atomic bad archives, stale inputs, standalone/workflow replay, and new-project re-export.

## Verification

Run `python -m ruff check apps/api`, `python -m ruff format --check apps/api`, `python -m mypy -p reefvision`, and `python -m pytest apps/api/reefvision/tests --pose-interop-integration` using short isolated Windows temporary paths. Run web formatting, types, full Vitest, Playwright and production build. Exercise real GPU paths when their exact provider stack is available. Preserve data from other worktrees and primary profiles.
