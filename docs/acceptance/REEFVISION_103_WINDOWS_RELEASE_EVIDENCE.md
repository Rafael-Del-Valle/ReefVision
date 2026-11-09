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

## Camera JPEG acceptance: reproducible original-file manifest

Before importing any camera files, create an immutable source manifest in PowerShell (run in a directory containing **copies** of original camera media, never in the only source directory):

```powershell
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath '.').Path
$files = @(Get-ChildItem -LiteralPath $root -File -Recurse |
  Where-Object { $_.Extension -match '^(?i:\.(jpg|jpeg|jpe|jfif))$' } |
  Sort-Object FullName)
if ($files.Count -eq 0) { throw 'No original JPEG camera samples found' }
$manifest = @($files | ForEach-Object {
  [pscustomobject]@{
    RelativePath = [IO.Path]::GetRelativePath($root, $_.FullName)
    Extension = $_.Extension
    Bytes = $_.Length
    SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
  }
})
$manifest | Export-Csv -LiteralPath (Join-Path $root 'jpeg-source-manifest.csv') -NoTypeInformation -Encoding UTF8
$manifest | Format-Table -AutoSize
```

Use separate physical camera originals for `.jpg`, `.JPG`, `.jpeg`, and `.JPEG` when available. For `.jpe` and `.jfif`, record whether the sample is genuinely camera-generated or an explicitly labeled **alias copy**; renaming a file only exercises extension routing and does **not** validate decoder compatibility. Record EXIF orientation, ICC profile (including CMYK if present), dimensions, and camera model from a trusted metadata reader; never infer them from the extension. Test import, thumbnail, first-image viewport, full-resolution image, navigation, annotation overlay, and reopen for every sample. Unsupported color profiles or aliases must produce a clear recoverable error rather than a blank viewport.

After import, rerun `Get-FileHash` against the source paths and compare to the manifest. Record the exact application commit, Windows/WebView2 version, per-file observed result, screenshots and any decode error. Treat missing real-camera samples as **BLOCKED**, not PASS. The manifest script records file identity only; it does not test the application, and its CSV is an output artifact that must not be imported as an image.

## Read-only external training console: process-continuity acceptance

The console is a **viewer**, not a training launcher or controller. Test with an actual locally trained run whose ID is obtained from ReefVision's job UI/API, not a fabricated ID. Record the run ID, exact commit, training process PID, model architecture, local dataset provenance, and the timestamped source of each reported loss. `box`, `cls`, and `dfl` are only required for training architectures that actually emit those components; mark each unavailable component **NOT EMITTED** with the reason, never manufacture zeroes.

Before opening the external PowerShell window, record a baseline using the real training PID (substitute the observed numeric PID, never an untrusted string):

```powershell
$ErrorActionPreference = 'Stop'
$trainingPid = 12345 # replace with the actual numeric PID observed for this run
if ($trainingPid -le 0 -or $trainingPid -eq $PID) { throw 'Invalid training PID' }
$before = Get-CimInstance Win32_Process -Filter "ProcessId=$trainingPid"
if (-not $before) { throw 'Training process not running before monitor test' }
$beforeIdentity = [pscustomobject]@{
  ProcessId = $before.ProcessId
  CreationDate = $before.CreationDate
  ExecutablePath = $before.ExecutablePath
}
$beforeIdentity | Format-List
```

While training is running, launch the application's documented **read-only** monitor command in a separate PowerShell process. Capture its command line with credentials/tokens redacted, exit code, and timestamped stdout/stderr. Confirm the monitor displays real run status and advancing epoch/step, logs and loss values backed by the same persisted job. Close the monitor **without** sending Ctrl+C to the training terminal. Verify a new checkpoint/log entry or advancing step after monitor exit, then recheck process identity:

```powershell
$after = Get-CimInstance Win32_Process -Filter "ProcessId=$trainingPid"
if (-not $after) { throw 'Training process exited during monitor test' }
if ($after.CreationDate -ne $beforeIdentity.CreationDate) {
  throw 'PID was reused: training process restarted or was replaced'
}
'PASS: original training process remains alive (checkpoint/step progress still needs independent verification)'
```

Also exercise a nonexistent run ID, path traversal characters, PowerShell metacharacters, unauthorized access, unavailable backend, and log contents containing terminal escape sequences. Confirm that the monitor neither executes log text nor exposes credentials, write endpoints, shell control, or arbitrary filesystem reads. Document actual outputs and access-denial behavior. The PID continuity check alone cannot prove training progressed or that the console is secure; retain independent checkpoint/epoch evidence and code-level command allowlist/argument-escaping review. If no real training run or external monitor is available, record **BLOCKED**, not PASS.
