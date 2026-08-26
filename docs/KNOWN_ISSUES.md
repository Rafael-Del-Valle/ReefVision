# ReefVision 1.0 Known Issues

This document records issues and validation gaps observed during the 2026-08-26
Prompt 8 release-candidate pass. It is not a substitute for the release checklist.

| Severity | Area | Description | Workaround | Release blocking |
| --- | --- | --- | --- | --- |
| BLOCKER | Clean-machine acceptance | The current `1.0.0` MSI/CAB set has not been installed, launched, restarted, uninstalled, and reinstalled on a disposable clean Windows machine. | Run `scripts/acceptance-windows-clean-install.ps1` from an elevated disposable machine and retain its report. | Yes |
| HIGH | Source provenance | The validated package was built from a working tree containing the integrated but uncommitted Prompt 1–8 changes. | Review the complete diff, create one intentional RC commit, rerun abbreviated gates, and rebuild from that exact commit. | Yes for final release provenance |
| HIGH | Package size/build time | The staged backend contains about 19,467 files and 4.16 GiB before compression. WiX requires nine external CABs and takes tens of minutes to link. | Distribute the MSI with every `rv*.cab`; investigate narrower PyInstaller collection after 1.0 unless package delivery becomes impractical. | No, provided all CABs remain together and verification passes |
| MEDIUM | Frontend bundle | Vite reports a JavaScript chunk of about 667 kB after minification. | None required for correctness; consider route-level code splitting after 1.0. | No |
| MEDIUM | Provider/scientific hardware evidence | Real biological classification, segmentation, tracking benchmarks, physical calibration, and the final real VDA scientific-3D smoke are not all current-head validated. | Run the prepared acceptance harnesses with suitable data/hardware and report results as scientific validation, not software-unit evidence. | No for core software; required before making corresponding scientific-performance claims |
| LOW | Test dependency warning | Backend tests emit a Starlette/httpx deprecation warning; one frontend measurement test emits a non-failing React Query undefined-data warning. | Update the dependency/test fixture in a post-freeze maintenance pass. | No |

