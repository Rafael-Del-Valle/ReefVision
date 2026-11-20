# Third-party SLEAP distribution audit

Audit date: 2026-11-15
Decision: [0010](decisions/0010-sleap-supported-build-retirement.md)

## Component inventory

| Component | Version / state | ReefVision distribution state | License evidence | Decision |
| --- | --- | --- | --- | --- |
| `sleap-nn` | Adapter expected `0.3.3`; package is absent from ReefVision dependencies, requirements, bootstrap, MSI build, and CI install commands | Not packaged | [v0.3.3 LICENSE is GPLv3](https://raw.githubusercontent.com/talmolab/sleap-nn/v0.3.3/LICENSE); [v0.3.3 package metadata declares BSD-3-Clause](https://raw.githubusercontent.com/talmolab/sleap-nn/v0.3.3/pyproject.toml) | Material upstream inconsistency; active provider retired fail-closed |
| `sleap-io` | Exactly `0.9.2` in optional `interoperability` extra | Optional development/neutral-interchange dependency; not installed by normal bootstrap or desktop sidecar build | [v0.9.2 LICENSE is BSD-3-Clause](https://raw.githubusercontent.com/talmolab/sleap-io/v0.9.2/LICENSE); [v0.9.2 package metadata](https://raw.githubusercontent.com/talmolab/sleap-io/v0.9.2/pyproject.toml) | Allowed only behind neutral checksum-bound NWB interchange |
| Original `sleap` application | No version pinned or installed by ReefVision | Not distributed | No application artifact is consumed by the supported build | Outside the supported build; no license conclusion is needed for distribution |
| SLEAP-NN model weights/bundles | User-provided historical `.zip` source assets only | Preserved, never executed or newly registered | Weight terms are artifact-specific and were not established by ReefVision | Provider unavailable; preserve hashes/metadata and offer neutral guidance |
| SLP files | Historical source artifacts only | No active import/export menu or supported API literal | Container semantics formerly came from `sleap-io` | Preserve source bytes where already managed; conversion is external |

## `sleap-io==0.9.2` declared dependencies

The installed 0.9.2 metadata declares: `numpy`, `attrs`, `h5py>=3.8.0`,
`pynwb`, `ndx-pose>=0.2.1`, `ndx-multisubjects>=0.1.1`, `pandas`,
`simplejson`, `imageio`, `imageio-ffmpeg>=0.5.0`, `tifffile`, `tqdm`,
`pyyaml`, `rich_click`, `shapely>=2.0`, `lazy-loader>=0.4`,
`skia-python>=87.0`, `colorcet>=3.0`, `fsspec>=2024.10.0`, and
`aiohttp>=3.13.5`. Its optional extras add OpenCV, PyAV, MATLAB/scipy,
Polars/Arrow, or cloud filesystem packages. ReefVision requests no such
`sleap-io` extra.

These dependencies belong to the optional interoperability environment. The
desktop bootstrap installs `.[dev]`, and the PyInstaller sidecar builds from
that environment; therefore the supported MSI does not intentionally include
`sleap-io`, `sleap-nn`, SLP fixtures, SLEAP weights, or SLEAP executables.
Exact installer contents must still be rechecked for every release artifact.

The November 19 integration closed dispatch paths that previously accepted
historical SLEAP-NN model IDs for pose comparison, image inference and video
tracking. The API and saved Pose Inference graphs now reject new work with
the retirement reason. An old queued image-inference job reaches a terminal
failure before opening its checkpoint. The model registration and completed
results remain available for historical inspection.

COCO, DeepLabCut CSV and Ultralytics pose exchange use ReefVision's native
readers and writers. All three exported and imported with the optional codec
unavailable. The pinned 0.9.2 codec ran the neutral NWB round trip. Earlier
standalone NWB archives need the original project for an audited re-export
or independent verification of the pose frame mapping during neutral
conversion. Existing checksum-bound NWB files continue to open.
[Compatibility decision](decisions/0010-sleap-supported-build-retirement.md).

## Supported-build verification boundary

An archive audit of Windows checkpoint `2194f2e96` verified the MSI, six
external cabinets and provenance by SHA-256. Its 19,133 installed paths and
11,977 nested Python module entries contained the application-owned historical
descriptor. The auditor found zero targeted SLEAP vendor runtimes, command-line
entries, SLP samples or SLEAP model bundles. The MSI SHA-256 was
`ff3c21d5be96552e4ab0ca876f517def36f6e5d3f5e4b10f18bb7be1d8c0d08d`.
Each later candidate requires an audit of its own bits.
[Windows package build](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44667026842).

- Provider catalog: historical descriptor only; `registerable=false`, no
  execution runtimes, no CPU/GPU/tracking capabilities.
- Provider factories: explicit structured domain failure before inspecting or
  importing a bundle.
- Video workspace: old registrations remain visible with an unavailable
  message; execution is disabled.
- Interchange: API and TypeScript format unions omit `slp`; normal controls omit
  SLP links/options/file extensions. NWB, COCO, DeepLabCut, and Ultralytics pose
  remain visible.
- Data compatibility: model/run/provider strings and canonical pose records are
  not rewritten or deleted.
- CI: ordinary suites may install the optional neutral NWB codec, but no
  supported job opts into SLP or SLEAP-NN execution.

## Re-enable gate

Do not re-enable active support from package metadata alone. Require an
authoritative resolution covering the exact source and wheel/sdist, a complete
license and transitive review, checkpoint/weight terms, installer payload
inspection, historical-project migration tests, and installed Windows/GPU
acceptance approved by the owner.
