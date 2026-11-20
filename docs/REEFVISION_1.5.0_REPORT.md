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

## Verified precursor and spatial correction

On source `c2ab5d330`, all six Research journeys and all ten preserved desktop journeys passed with zero skips or retries. Two scratch-trained segmentation models compared six untouched originals in two independent groups. They returned 12 and 46 evaluation-only polygons, mean IoU 0.04745 and 0.05002, and no matched reference instances at the declared threshold. Both saved runs retained the direct report SHA-256 `8371bf9d6c52416b034a9c79b97da97f50ccbb26c1e5d8060cafe71a8343b10a`. Three separate source tests on the NVIDIA RTX 3090 exercised native ReefPose evaluation, two-model comparison and training through registration and inference. [1.5 Research candidate](https://github.com/Rafael-Del-Valle/ReefVision/pull/95)

The installed 1.4 sidecar created a backup of a disposable profile containing two projects, local trained weights and completed box and mask reviews. The 1.5 source migrator preserved all seven managed files, both registered checkpoints, fourteen checked domain tables and both project snapshots. The restored database matched the backup byte for byte. The 1.4 app reopened the restored profile and accepted an edit.

PR #79 advanced after the Research candidate was pushed. Its new tetrahedron regression reproduced a numeric error at `c2ab5d330`. The exact signed volume for one winding is `-390625/105553116266496` in source units cubed. The previous calculation returned zero. The reviewed merge recovers the representable value of about `-3.7007434154171883e-09` and the opposite sign after reversing the faces. An exactly planar control returns zero in either orientation. The standalone preview and two saved workflow runs use the same geometry calculation and preserve its provisional status. [Reviewed upstream merge](https://github.com/Rafael-Del-Valle/ReefVision/commit/e118e997675df90dbaef8a1121d45209b96adf7a)

## Installed Windows evidence

The corrected 1.5.0 MSI came from commit `3c8e2d0707aa8f8de669a5d4bbe2798b4d2a02fc`. Its SHA-256 is `c6e92040617eb055c4ee62afcca86af709ebe73d02602165d474e1259582e05e`. The installer and six external cabinets total 2,972,344,879 bytes. Their source, MSI Media table and hashes matched the original build provenance, SHA-256 `c5686b4aa34b322a597bfa15b0d9b5db5a726ee8b9b87d3115698625029d8c62`. The distribution audit inspected 19,139 installed files and 12,031 frozen Python entries and found zero retired-runtime components. [Official installer build and artifacts](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136242363814)

| Researcher action | Observed result on the exact build |
| --- | --- |
| Install and use a clean Windows profile | All six Research and ten preserved ordinary, coral and spatial WebView2 journeys passed with zero skips, failures or retries. The installed executable and both WebView2 listeners ran under the standard-user account. Uninstall retained the project. [Clean installation](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916) |
| Upgrade or recover an existing project | All five prior-version scenarios passed, including published 1.0.3, validated 1.4 and 1.3, and both numeric draft schemas. The 1.3 reader refused the upgraded database and reopened its own verified backup. On a physical host the two-project 1.4 backup preserved both checkpoint identities and seven managed files. The 1.4 executable reopened both projects and accepted a write on the restored copy. [Installation scenarios](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547) |
| Review offline field records, use a registered model, export and reopen a Research package | All six Research journeys passed under a standard user in the MSI-extracted desktop on the physical Windows host. In a separate RTX 3090 profile, three pinned CUDA jobs succeeded. Direct inference and two saved runs matched all nine proposals. Both saved payloads had SHA-256 `4428cc1865bc9b57380597ea920b021630cd0640dbca579c5db107d58b31e812`. [Draft and runtime identities](https://github.com/Rafael-Del-Valle/ReefVision/pull/96) |
| Import a calibrated closed mesh and rerun the saved measurement | The forward and reversed OBJ and a double-precision PLY produced `3.7007434154171883e-9 m³` at fixture scale. The planar control withheld volume. The reopened workflow reproduced all four result hashes. Physical WebView2 receipt SHA-256 `91cc3210fe28a508a20cea48fb60ffdb988648389071357938184997870c54b7`. [Spatial integration and acceptance](https://github.com/Rafael-Del-Valle/ReefVision/pull/96) |

The exact Windows backend suite passed 5,419 of 5,431 cases. The twelve skips comprised five symlink-permission cases, three external WhaleDrone data cases, the opt-in live SAM provider check and three opt-in ReefPose GPU cases. All three ReefPose tests ran separately on the physical RTX 3090, including training, registration, inference and a queued comparison. The hosted frontend passed 737 unit tests and 15 Playwright tests. [CI](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744526) · [Additional scientific, provider and desktop acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744722)

The hosted Linux suite with opt-in pose interchange passed 5,421 tests, with ten skips. The separate scientific acceptance job passed 5,414 tests, with 17 skips, followed by all 126 focused scientific regressions. [Linux CI](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744526/job/136242365630) · [Scientific acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744722/job/136242363843)

The #96 native Temporal workspace also ran a 24-frame causal refinement on the RTX 3090 with zero future frames. The packaged sidecar trained and registered the frame and temporal checkpoints. Five independent generated recording groups supplied 120 held-out frames, 240 landmark coordinates and seven reference events. Both models covered all 240 coordinates. Mean error was 5.575 px for frame-only and 4.006 px for temporal refinement. Frame-only missed seven events and added fifteen. The refined output missed four and added eighteen. The frozen evaluation manifest SHA-256 was `9081f6dc7e5da3d09100b83b29e98541c52100f31b585ecf2b95463bc693cd74`. Physical receipt SHA-256 was `9539c37a38e7c3a486bfd3503c5d2c1647783869a0ce8ae74059ad61cbd4f637`. [Exact candidate and engineering evidence](https://github.com/Rafael-Del-Valle/ReefVision/pull/96)

## Outstanding scientific acceptance

Study design requires a prespecified study with independent tank, site or colony units, repeated calibrated visits, treatment allocations, observation effort, exclusions and a separate statistical reference. Reviewer agreement requires a fixed representative sample, independent reviewers and adjudicator, and a prespecified threshold. Model comparison requires independent reference labels on frozen groups with compatible checkpoints and prespecified task-specific scoring margins. The canonical inventory tracks each input and its corresponding workflow. [Feature inventory](roadmap/REEFVISION_2_0_FEATURE_INVENTORY.md)

Field acceptance requires an authorized acquisition batch and an independent field log documenting the clock basis, source identities, duplicate transfer and conflict decision. Historical-user acceptance requires an authorized prior profile and its verified pre-upgrade backup. The physical Windows 11 test machine reported Smart App Control off, and the exact MSI, application and sidecar were unsigned. Verification under enforcing policy still requires a suitable device. Merge, tagging and publication require separate owner approval.
