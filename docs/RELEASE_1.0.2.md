# ReefVision 1.0.2 pre-release acceptance and handoff

**Status:** HOLD — implementation and exact-head validation are in progress.

**Implementation base:** `70da46deceebe56ecc1c58240e950c08ae581360`  
**Development branch:** `feat/reefvision-1.0.2-annotation-usability`  
**Publication policy:** Do not merge, tag, publish, replace installer assets, or install on the maintainer's computer without explicit approval. PR #44 remains draft and unchanged.

## Acceptance evidence

Evidence will be added only after it is produced from the final implementation commit.

| Gate | Status | Evidence |
|---|---|---|
| Version consistency | In progress | 1.0.2 source contract introduced |
| Frontend format, type, unit, build | Pending | — |
| Playwright workflows | Pending | — |
| Backend format, Ruff, mypy, pytest | Pending | — |
| Alembic up/down/up | Pending | — |
| Scientific regression checks | Pending | — |
| Exact-head Windows MSI/CAB build | Pending | — |
| Noninstalling package inspection | Pending | — |
| Clean install, launch, persistence, uninstall | Pending isolated environment | — |
| Physical high-resolution interaction QA | Outstanding unless performed | — |

## Release gate

The final report will list implemented features, exact test counts and skips, installer files and hashes, scientific-integrity evidence, remaining blockers, and either **READY FOR MAINTAINER REVIEW** or **HOLD**. Passing evidence from an older commit will not be used as proof for 1.0.2.
