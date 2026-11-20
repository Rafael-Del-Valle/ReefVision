# ReefVision 1.5.0 Report

## Current release state

The 1.5.0 engineering candidate builds on the validated 1.4.0 installer at `fb2276c87`. Draft #95 integrates the local provider catalog from #88 with the six project workflows below. Source and desktop results use generated research fixtures. Representative studies and release approval remain open. [Candidate and current Windows checks](https://github.com/Rafael-Del-Valle/ReefVision/pull/95)

## Implemented provider foundation

- Strict discovery of direct `.json` files in `<data_dir>/provider-manifests`.
- Bounded file reads and a closed manifest schema with stable identity, version, capability, and availability fields.
- Failure isolation: invalid UTF-8, JSON, schemas, duplicates, symlinks, directories, built-in ID conflicts, and oversized files remain visible as unavailable records without preventing other manifests from loading.
- No imports, entry-point resolution, package installation, command execution, or model loading.
- Provider-catalog API metadata for source kind, schema version, capabilities, availability, source file and digest, and discovery errors.
- An explicit blocked preflight for local manifests; local records are not accepted by execution routes.
- A tested project path at **Home → open project → Models & AI → Providers**. The workspace exposes discovery evidence and keeps local execution controls disabled.
- A metadata-only `provider_manifest_snapshot` Workflow Builder node. It records manifest metadata and the source digest, can preserve invalid records as unavailable evidence, and refuses a changed digest when one was pinned.

## Safety boundary

The 1.5 foundation is an inspection and provenance layer, not a runtime extension system. A manifest cannot grant code execution authority. Executable plugin loading, lifecycle controls, permissions, compatibility negotiation, and a stable SDK remain tracked separately for 2.0.

## Verification state

The provider-foundation inventory entry is verified at source SHA `6d054d532b3faad9eb1b6a377e26ea54d92c6046`. Source tests, the normal browser path, and Workflow Builder snapshot coverage passed. The exact-head Windows clean-install and published-1.0.3 upgrade runs seeded a declarative manifest in the isolated application data directory, verified its packaged-API source digest, and confirmed that installed preflight remained inspect-only and blocked. No representative scientific dataset or physical GPU is required for this metadata-only foundation.

## Research workflows

| Project entry | Verified fixture outcome |
| --- | --- |
| Research → Study design | A prospective declaration retained the independent units, two visits, treatment allocation, exclusions and analysis choice. Two successive project imports preserved the original signed report and allowed a new declaration to bind later evidence. |
| Review → Reviewer lab | Two blinded reviewers agreed on one of two images, giving 50% agreement and Cohen’s kappa of zero. Adjudication retained both decisions. Fresh locally scoped credentials continued an unfinished imported round. |
| Data & annotation → Field capture | Offline PNG and MP4 records retained original digests, known or unknown clocks, notes, reconciliation and reviewed conflicts. A shared field and project image occupied a single native archive member and retained both identities after restore. |
| Models & AI → Model Hub | Local scratch-trained detectors ran directly and twice through saved graphs. All nine CPU and ten CUDA detections matched their corresponding direct class, box and confidence values to six decimal places. A replaced checkpoint stopped queued execution and replay. |
| Models & AI → Model comparison | Two locally trained detectors compared three held-out originals in two groups. The user reopened a disagreement and exported JSON and CSV. Four playable synthetic videos also went through the real validation workers. From two independently scored models, a pose disagreement opened frame 2 in one recording. An event disagreement opened the other recording at 0.2 seconds and resolved to frame 2. Browser decoding and both source hashes were verified. Backend tests also verify segmentation masks and tracking identities. |
| Research → Export reproducibility package | A 64,711-byte ZIP bound the design, sealed review, comparison, methods, exclusions and environment. Inspection of all 112 nested members found neither omitted checkpoint digest. Two original workflow runs and a third in the reopened project returned the same proof payload, `fdfcb169edd1a8e6c67aaddcbb979e01470286afd53a07e2b8901bca62e9d84a`. |

All six Research journeys passed from a fresh disposable profile, including new local CPU training. The playable pose and event browser checks used the same frozen reference `0b3c5fe93e7e0ce58b4ddf06fc0f1c6509059ca0a4469513cb6e7dd912677b8a`. [Six-journey acceptance](https://github.com/Rafael-Del-Valle/ReefVision/commit/74645f2dff3e369f9d05152e0b7841e0afc65f8d)

## Upgrades and historical evidence

The application and installer identify version 1.5.0. The four additive research migration branches join at `b15_integrated_0001`. Its successor `b15_integrated_0002` recovers the source-ID map missing from an earlier applied 1.5 model table. A real generated early profile reopened twice with its original receipt UUID, JSON, UTC timestamp and checkpoint digest. Forty-seven migration, backup and restoration checks passed. An older review that omitted class bindings stays readable and requires a fresh review before execution. [Migration](https://github.com/Rafael-Del-Valle/ReefVision/commit/ebce490b1e153fcdaf84c0b4c7c13721b12b7b6f)

A detector comparison created with the earlier `8155cc78a` application survived two imports and four saved graph replays with its original score digest. A research package requires the original evaluation outputs. Missing or ambiguous output records leave the historic comparison available with guidance to recover or repeat the evaluation. [Comparison and package verification](https://github.com/Rafael-Del-Valle/ReefVision/commit/b8e754ffe464c4dc708d37b4871800f2f57adb69)

Native Project Exchange also honors the weight selection when generated artifacts are included. On a project with two locally trained detectors, the exported ZIP contained zero matching checkpoint members with weights off and seven with weights on. Both training CSVs survived each export. [Checkpoint omission and Results Package coverage](https://github.com/Rafael-Del-Valle/ReefVision/commit/e5ef7535286efd14a96d3772d570fc6752795c0f)

The preliminary `eed04eeec` MSI and six cabinets passed hash and MSI Media verification. The administratively extracted native app opened a marked profile under a standard Windows user, connected its WebView2 to the packaged sidecar and detected the physical RTX 3090. Its distribution audit inspected 19,138 payload paths and 12,023 frozen Python entries with zero retired-runtime findings. The new installed Research, CUDA and direct 1.4-to-1.5 upgrade journeys have their own checks on the integrated candidate. [Preliminary Windows build](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44713484982)

## Outstanding scientific acceptance

Study design requires a prespecified study with independent tank, site or colony units, repeated calibrated visits, treatment allocations, observation effort, exclusions and a separate statistical reference. Reviewer agreement requires a fixed representative sample, independent reviewers and adjudicator, and a prespecified threshold. Model comparison requires independent reference labels on frozen groups with compatible checkpoints and prespecified task-specific scoring margins. The canonical inventory tracks each input and its corresponding workflow. [Feature inventory](roadmap/REEFVISION_2_0_FEATURE_INVENTORY.md)
