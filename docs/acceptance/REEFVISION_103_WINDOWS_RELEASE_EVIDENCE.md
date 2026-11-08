# ReefVision 1.0.3 — Windows release evidence gate (unreleased)

This is an **evidence collection protocol**, not a record of successful acceptance. Run it against the exact candidate commit and preserve the resulting logs, machine details, artifact SHA-256 hashes, and any failures. Never reuse a green check from an older SHA.

## Candidate identity and prerequisites

Record commit SHA, GitHub Actions run URLs and conclusions, Windows build/version, WebView2 runtime version, Node/npm/Python/Rust versions, GPU model/driver/CUDA/PyTorch versions, and whether the test machine is clean or an upgrade target. Use offline, locally trained weights and test datasets with documented origin; do not download pretrained models.

## Acceptance matrix

| Gate | Reproducible action | Required evidence / pass condition |
| --- | --- | --- |
| Frontend | Run repository lockfile, Prettier, lint, typecheck, unit tests and production build from the candidate SHA. | Complete logs; zero errors, including formatting errors. |
| Backend / science | Run backend lint/typecheck, tests, migrations and scientific geometry/provenance regressions. | Logs and test counts; no unexpected schema/data changes; uncertainty, QC and experimental-unit semantics retained. |
| Rust / Workflow Builder | Run Rust/Tauri checks and saved-graph typed execution tests on the same SHA. | Logs for command permissions, graph reload and execution, including failure paths. |
| First image / gallery | On a real Windows WebView2 install, open a fresh project, a single-image project, a large multi-page project, and a project with a saved selection. Scroll the image and thumbnail gallery; navigate first/last/previous/next and reopen. | Screen recording and test-project manifest; initial image visible without manual refresh, scroll/selection stable, no blank viewport or redundant page fetch. |
| Camera formats | Import original, unmodified camera files including uppercase/lowercase JPG/JPEG, JPE/JFIF aliases, and representative CMYK JPEG. Include Canon/Sony originals if available. | Source file SHA-256, camera metadata, import result, decoded display, and original-byte preservation. Synthetic files do not replace real-camera acceptance. |
| Training monitor | Start an actual CPU and, where available, GPU local training job; open external read-only PowerShell monitor while it runs, then close the monitor. Try malformed run IDs and denied API access. | Timestamped monitor output from the same job showing real status, epoch, box/cls/dfl losses where emitted, and logs; training PID/checkpoints continue unchanged after monitor closes; no command injection or mutation. |
| Installer | Build Windows MSI/CAB at the candidate SHA; collect hashes, sizes, signing state and build logs. Install on a clean Windows user/machine and separately test supported upgrade. | Actual installer files, SHA-256, install/uninstall logs, startup, project open, WebView2 availability, and no unexpected data loss. A hash-only collector test is not an installer test. |
| GPU and offline | Run local inference/training on the supported GPU; disconnect network and repeat supported local operations. | GPU memory/device logs, inference/training results, no mandatory network fetch, provenance and immutable dataset checks. |

## Evidence record

For every gate, record **PASS / FAIL / NOT RUN / BLOCKED**, exact commit SHA, UTC timestamp, machine, command or GUI steps, output artifact path/hash, and reviewer. A gate is **NOT RUN** until executed; a prior-SHA pass is historical evidence only. Keep original scientific images and datasets immutable, record calibration and geographic coordinate frames, and report uncertainties rather than silently substituting values.

## Release decision

Keep **HOLD** until all required gates above and the versioned roadmap are complete with reproducible evidence. A CI green status alone is insufficient for physical-camera, clean-install, WebView2, or GPU acceptance. No merge, tag, publication, release, or installer deployment is authorized by this document.
