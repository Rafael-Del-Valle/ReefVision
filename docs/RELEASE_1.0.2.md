# ReefVision 1.0.2 pre-release acceptance and handoff

**Status: HOLD — remaining release evidence and explicit maintainer authorization required.**

**Implementation base:** `70da46deceebe56ecc1c58240e950c08ae581360` (1.0.1 PR #44)  
**Feature branch:** `feat/reefvision-1.0.2-annotation-usability`  
**Draft PR:** [#50](https://github.com/Rafael-Del-Valle/ReefVision/pull/50)  
**Publication policy:** Do not merge, tag, publish, replace installer assets or install on the maintainer's personal device without approval. PR #44 is still draft/unmerged; PR #50 targets it, not older `main`.

## Automated evidence — verified earlier candidate

Commit `88ae9cf00ad0f96c9b6d0e7112f5005e737b139e` completed **26/26 GitHub checks successfully**. This is a historical validated checkpoint, **not a blanket claim that later documentation/benchmark commits are already validated**.

| Gate | Observed result | Evidence |
| --- | --- | --- |
| Version consistency | 1.0.2 MSI name and ProductVersion checked | [Windows workflow](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147093) |
| Frontend format/type/unit/build | PASS, 421 Vitest tests across 92 files | [Full acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147180) |
| Playwright | 11 passed, 1 configured skip | Same full acceptance workflow |
| Backend lint, mypy, pytest | PASS, 1,043 passed, 32 skipped; strict mypy checked 388 source files | Same full acceptance workflow |
| Focused scientific regression | 117 passed | Same full acceptance workflow |
| Database migrations | Canonical upgrade/downgrade/upgrade PASS | Same full acceptance workflow |
| SAM 2.1 Windows CPU and live checkpoint inference | PASS | Same full acceptance workflow |
| Exact-head Windows MSI/CAB build | PASS: `ReefVision_1.0.2_x64_en-US.msi`, five CABs | [Independent release build](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147180) |
| Clean Windows install/launch/persistence/uninstall | PASS, including real packaged SAM 2.1 Tiny CPU inference | [Disposable Windows acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38259147093) |

The source workflow artifact was named `reefvision-1.0-windows-msi` despite containing the 1.0.2 MSI. A separate `ReefVision-Windows-Installer` artifact and `ReefVision-1.0.2-Windows-Clean-Install-Evidence` were produced by the build/clean-install workflow. Use a single build's MSI and associated CABs together.

## Additional acceptance work after the green checkpoint

1. **Reproducible performance metrics.** `reefvision-1.0-acceptance.yml` now uploads per-head frontend/raster benchmarks. See [recorded kernel benchmark baseline](validation/REEFVISION_1_0_2_RESPONSIVENESS.md). New post-checkpoint workflow execution/results must be reviewed before recording new measurements.
2. **Interactive operator proof.** Follow [installed-GUI acceptance checklist](validation/REEFVISION_1_0_2_INSTALLED_GUI_ACCEPTANCE.md) in a disposable Windows environment. None of its interactive cases is marked PASS solely from process-launch or browser Vitest evidence.
3. **GPU proof.** Real NVIDIA SAM/training inference remains outstanding unless separately exercised and recorded; CPU inference is not equivalent.
4. **Final exact-head status.** Reconfirm all required checks (including new benchmark artifact steps) against the newest PR SHA, and retain the matched run IDs and installer hashes.

## Release decision

**HOLD**, despite the earlier 26/26 green automated checkpoint, until the latest head passes, installed-GUI acceptance and GPU/performance evidence are completed or explicitly dispositioned, dependency on PR #44 is resolved, and the maintainer expressly approves merge/publication. Do not portray installation on the maintainer's workstation as already completed.
