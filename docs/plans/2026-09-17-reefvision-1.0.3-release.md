# ReefVision 1.0.3 Release Consolidation

**Branch:** `release/reefvision-1.0.3-final-20260917`

## Included release-critical work

- Annotation-editor smoke fixes and trained-model deployment from PR #31.
- Current-image model deployment for trained/imported project models such as `best.pt`.
- Gallery batch deployment for selected images.
- Polygon Delete/Backspace event-routing fix and regression coverage from PR #32.
- Backend mypy/package compatibility updates.
- Version metadata synchronized to 1.0.3 across Python, npm, Tauri/Rust, command tooling, onboarding, and version-consistency tests.

## Required release evidence

1. Hosted backend/frontend CI passes.
2. ReefVision 1.0 acceptance workflow passes.
3. Windows MSI workflow produces the 1.0.3 installer artifact.
4. Packaged project persistence and restart lifecycle acceptance passes.
5. Installer hashes/manifests are recorded from the exact validated commit.

Do not publish the installer while GitHub Actions jobs are blocked before runner startup.
