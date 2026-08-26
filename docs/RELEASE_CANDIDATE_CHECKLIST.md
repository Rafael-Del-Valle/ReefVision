# ReefVision 1.0 Release-Candidate Checklist

Passing the automated release-candidate script is **not a release authorization**.
A public release requires completion of the manual acceptance section and an explicit release decision.

## Automated release-candidate gate

Run from the repository root:

```powershell
.\scripts\release-candidate.ps1
```

For the final Windows package:

```powershell
.\scripts\release-candidate.ps1 -BuildInstaller
```

The automated gate covers Ruff, mypy, focused Items 11-18 acceptance,
full backend pytest regression, frontend TypeScript, full Vitest regression,
frontend production build, and optional Tauri MSI packaging.

## Roadmap implementation state

- 11 Classification — automated implementation/acceptance gate
- 12 Active Learning — automated implementation/acceptance gate
- 13 Video & Tracking — automated implementation/acceptance gate
- 14 Workflow Builder — automated implementation/acceptance gate
- 15 UI/UX cleanup — release-facing terminology and regression gate
- 16 Full Regression — release-candidate script
- 17 Windows Installer — built only with `-BuildInstaller`
- 18 ReefVision 1.0 Release — pending manual acceptance

## Manual acceptance

### Annotation and prediction review
- Create/select classes
- Box, rotated box, polygon, brush, erase, fill
- Move/resize/rotate/edit
- Undo/redo
- Save/reopen
- Grounding DINO proposal review
- SAM 2 raster proposal review
- Accept/reject prediction proposals

### Models and AI
- Model Hub install
- Verify feedback
- Remove/reinstall
- Restart persistence
- Advanced Provider readiness after restart
- SmolVLM Ask ReefVision image interpretation
- TrOCR Scale Assistant OCR

### Scientific measurement and calibration
- Manual scale
- Ruler detection
- Scale-bar detection
- OCR-assisted evidence
- ArUco
- ChArUco
- Camera/profile reuse confirmation
- TLE
- projected area
- perimeter
- surface-area models
- polyp density
- export provenance

### Classification
- Add/edit image-level labels
- Materialize classification dataset
- Queue/train classifier
- Run inference
- Review prediction
- Verify accepted label state

### Active Learning
- Create acquisition round
- Inspect ranking/explanation
- Open Review Queue
- Complete reviewed items
- Freeze feedback dataset snapshot

### Video & Tracking
- Import video
- Create/edit manual track
- Run detector + tracker
- Inspect interpolation and analytics
- Run benchmark against verified ground truth
- Export/copy science reports

### Workflow Builder
- Load template
- Edit nodes and typed connections
- Validate/plan
- Execute
- Pause at review gate
- Resume after review
- Inspect persisted lineage
- Cancel a run

### Installer / clean-machine acceptance
- Build final MSI
- Keep MSI and required CAB files together
- Install on a clean Windows machine
- Launch ReefVision
- Run packaged backend self-test
- Confirm bundled model assets
- Confirm optional Model Hub downloads
- Create/open a project
- Restart application
- Uninstall/reinstall
- Confirm expected data retention
- Review remaining WiX ICE warnings

## Final release decision

- Release candidate date:
- Commit / source revision:
- MSI filename:
- MSI checksum:
- Manual acceptance completed by:
- Known non-blocking warnings:
- Release approved: YES / NO
