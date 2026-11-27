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

Use the repository's read-only JPEG inventory as the primary pre/post evidence
instead of a separate in-tree CSV. It detects filesystem links, Windows path
collisions, duplicate bytes, malformed JPEG markers, decode failures, EXIF geometry
and ICC payload fingerprints. Work only with owner-approved copies of original
camera files in a dedicated non-linked directory; keep all reports outside it.

### Separate physical-camera and alias-routing cohorts

The inventory deliberately rejects identical SHA-256 hashes, even if filenames
or extensions differ. Do not put a capture and its renamed alias copies in the
same accepted inventory. Use independent fixture roots and evidence records:

| Cohort | Preparation | What a passing run demonstrates |
| --- | --- | --- |
| Physical-camera originals | Distinct unmodified Sony/Canon or other available camera captures; preserve native names and extensions. | Representative original-camera decoding and installed-app rendering for the tested files only. |
| Extension routing | One approved byte-for-byte copy per original digest in each separate fixture root; exercise JPG/JPEG and JPE/JFIF/JFI/JIF, including mixed case. | Extension routing for the tested copies; not additional independent captures or additional camera models. |
| Duplicate negative control | A separate disposable fixture root with two byte-identical copies under different names/extensions. | Inventory must exit nonzero and report duplicate source bytes; this root must never be counted as passing physical-camera evidence. |

For each alias root, record the original source digest, original filename,
alias filename and tested extension in a separate operator record. An alias
copy must never be counted as a new biological observation or experimental
unit. Distinct source hashes are necessary for this fixture inventory, but
are not sufficient to establish scientific independence.

For every physical or alias file, test import, thumbnail, first-image viewport,
full-resolution image, navigation, annotation overlay and reopen. Record camera
make/model as declared by metadata (not authenticated camera origin), native
and display dimensions, EXIF orientation, ICC profile fingerprint and any
recoverable decode/display error. Include CMYK JPEG when available. Synthetic
samples cannot substitute for actual original-camera acceptance.

The scanner enforces a saved **pre-import source inventory** directly.
Run the following independently for each positive cohort. Use a dedicated evidence
directory **outside** the approved camera fixture tree, preserve its SHA-256
separately, and keep the same absolute fixture path between runs:

```powershell
$ErrorActionPreference = 'Stop'
$cameraRoot = 'C:\camera-test-copies'
$evidenceRoot = 'C:\camera-evidence'
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
# Use a fresh evidence directory per cohort/candidate; do not overwrite earlier QC.
$before = Join-Path $evidenceRoot 'jpeg-before.json'
$after = Join-Path $evidenceRoot 'jpeg-after.json'
if ((Test-Path -LiteralPath $before) -or (Test-Path -LiteralPath $after)) {
  throw 'Choose a fresh evidence directory; do not overwrite prior reports.'
}
python scripts/verify_camera_jpeg_fixtures.py $cameraRoot --verify-decode > $before
if ($LASTEXITCODE -ne 0) { throw 'Camera pre-import inventory failed.' }
$beforeSha256 = (Get-FileHash -LiteralPath $before -Algorithm SHA256).Hash
# Record $beforeSha256 independently NOW. Do not recalculate it from the
# baseline file when validating the post-import camera evidence.
# Perform approved installed-app import/reopen; never modify camera originals.
python scripts/verify_camera_jpeg_fixtures.py $cameraRoot --verify-decode --compare-manifest $before --expected-manifest-sha256 $beforeSha256 > $after
if ($LASTEXITCODE -ne 0) { throw 'Camera originals changed, disappeared, or were added after import.' }
"PASS: verified pre/post JPEG names, byte counts and SHA-256; saved baseline hash $beforeSha256"
```

The baseline must be a well-formed, error-free scanner JSON inventory.
The scanner refuses baseline files **inside** the approved camera fixture tree
and refuses baseline paths traversing symbolic links or Windows junctions.
Keep the JSON evidence in an independent, non-linked directory as shown above;
these checks protect provenance boundaries but do not authenticate the operator.
Comparison rejects a different source root, duplicate/unsafe manifest paths,
duplicate source hashes, malformed decoded geometry, changed source hashes even when file size is unchanged, missing files and new JPEG files.
The optional `--expected-manifest-sha256` flag also rejects a baseline whose
JSON bytes differ from the separately recorded pre-import digest, including
when altered JPEGs and baseline hashes have been co-edited. A baseline created
with `--verify-decode` also requires `--verify-decode` during the post-import
comparison: the scanner now rejects missing pixel-decode evidence and checks
that emitted native/display dimensions, EXIF orientation/exposure provenance,
and ICC payload fingerprint still agree. Matching JPEG SHA-256 alone cannot
establish stable decoder interpretation across application or library versions.
A baseline created without pixel decoding only verifies source-byte integrity;
it cannot establish camera-codec compatibility. Preserve that digest
in an independent experiment record; hashing an already altered baseline at
comparison time cannot establish authenticity. This is still source-integrity
evidence only, not proof of physical camera compatibility, GUI rendering or
scientific validity.

**Limitations:** The pinned SHA-256 proves consistency with a separately retained digest, not who originally acquired or authorized the capture. Use a dedicated staging directory. Reject filesystem reparse points/symlinks in the staging tree: lexical path checks do not prove physical containment. Preserve the manifest and its SHA-256 separately. This verifies original-file integrity, **not** decoding or GUI compatibility. Record application commit, Windows/WebView2 version, per-file results and decode errors; missing real-camera samples are **BLOCKED**, not PASS.

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


## Windows MSI/CAB candidate integrity and clean-install evidence

Run the following **after** a successful Windows installer build, from a dedicated staging directory containing only artifacts from the candidate build. This is an integrity and provenance collector, **not** a substitute for installing and launching the application. Record the exact source commit and build workflow URL separately; artifact filenames do not prove which commit produced them.

```powershell
$ErrorActionPreference = 'Stop'
$staging = (Resolve-Path -LiteralPath '.').Path
$artifacts = @(Get-ChildItem -LiteralPath $staging -File -Recurse |
  Where-Object { $_.Extension -match '^(?i:\.(msi|cab))$' } |
  Sort-Object FullName)
if (-not ($artifacts | Where-Object { $_.Extension -ieq '.msi' })) {
  throw 'BLOCKED: no MSI found; do not report installer acceptance'
}
$records = @($artifacts | ForEach-Object {
  $signature = Get-AuthenticodeSignature -LiteralPath $_.FullName
  [pscustomobject]@{
    RelativePath = [IO.Path]::GetRelativePath($staging, $_.FullName)
    Bytes = $_.Length
    SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    SignatureStatus = [string]$signature.Status
    Signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '' }
  }
})
$records | Export-Csv -LiteralPath (Join-Path $staging 'installer-artifact-manifest.csv') -NoTypeInformation -Encoding UTF8
$records | Format-Table -AutoSize
```

For a split-cabinet ReefVision 1.0.3 build, the read-only collector can verify **all five or six CABs** against the same `build-provenance.json` alongside the MSI (not just one CAB):

```powershell
$repoRoot = 'C:\path\to\ReefVision' # replace with the exact-SHA source checkout
$collector = Join-Path $repoRoot 'scripts/windows/collect-103-acceptance-evidence.ps1'
$msi = Join-Path $staging 'ReefVision_1.0.3_x64_en-US.msi'
$cabs = @(Get-ChildItem -LiteralPath $staging -Filter 'rv*.cab' -File | Sort-Object Name | ForEach-Object FullName)
& $collector -CandidateSha '<exact 40-character source commit>' `
  -MsiPath $msi -CabPath $cabs -ProvenancePath (Join-Path $staging 'build-provenance.json')
```

Require `provenance.status = matched_complete` and the expected individual MSI/CAB hashes before progressing; `matched_subset` means at least one declared artifact was not supplied. Compare the MSI **Media** table with the complete CAB set separately, because an unsigned manifest cannot establish which CABs the installer actually needs. This procedure never launches `msiexec`.

If the build embeds CAB data inside the MSI, a separate CAB may not exist; record that packaging fact instead of inventing a CAB artifact. An unsigned development MSI must be labeled **unsigned**; a signature status alone is not proof of a trusted publisher or successful installation. Preserve the manifest alongside the exact build logs and immutable artifact copies.

On a clean Windows account or VM snapshot, record Windows build, architecture, WebView2 runtime, installation command and exit code, installer log, application startup, first image rendering, gallery scrolling, JPG/JPEG import, and read-only training monitor launch. For an interactive MSI install with verbose logging, an operator may use `msiexec.exe /i "<absolute MSI path>" /L*V "<absolute log path>"`; do **not** invoke this automatically from CI on a shared machine. Record installed product/version, WebView2 initialization errors, and any missing runtime dependencies. Reboot only if explicitly required and record it.

Repeat on a supported upgrade target containing a backed-up project and verify that original media SHA-256 hashes, annotation counts, dataset identity, migrations, and provenance are unchanged after upgrade and reopen. Uninstall and verify that user-owned project data remains intact. A successful build, a zero `msiexec` exit code, and a working first launch are **separate** gates; report each independently as PASS / FAIL / NOT RUN / BLOCKED with UTC timestamps and evidence paths.


## Exact-head CI failure triage — 2026-11-09 UTC

At commit `ae39787ba9d358c305f26e91f8003e9c98943583`, push workflow [42565146980](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42565146980) completed **FAILURE**. The backend and Windows acceptance-collector jobs succeeded; frontend job [128989942475](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42565146980/job/128989942475) failed at `npm run format:check` (`prettier --check .`, exit 1). This is **not** a passing frontend test run: subsequent frontend gates were not reached. The job also reported 2 moderate and 2 high npm audit vulnerabilities, which require independent dependency triage rather than automatic unreviewed upgrades.

Prettier reported exactly these ten files (paths relative to `apps/web`):

```text
src/App.test.tsx
src/features/annotation-editor/ImageViewport.test.tsx
src/features/annotation-editor/ImageViewport.tsx
src/features/gallery/Gallery.test.tsx
src/features/gallery/Gallery.tsx
src/features/gallery/galleryNavigation.test.ts
src/features/gallery/galleryNavigation.ts
src/features/training/TrainingRunDetail.test.tsx
src/features/training/TrainingRunDetail.tsx
tests/e2e/gallery-viewport-103.spec.ts
```

Remediation on this branch: run `npm ci` in `apps/web`, run `npx prettier --write` **only** on the ten listed files, review the diff to ensure formatting-only changes, then run `npm run format:check`, frontend typecheck/unit/E2E gates, and exact-new-HEAD Actions. Do not use `--ignore-path`, weaken `format:check`, or call older SHA checks green. This entry is a **diagnostic record**, not evidence that the formatting failure has been resolved. Windows installer, physical camera, WebView2, and GPU acceptance remain separate BLOCKED/NOT RUN gates until independently evidenced.
