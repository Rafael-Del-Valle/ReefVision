$ErrorActionPreference = "Stop"

throw @"
Standalone browser mode has been retired. ReefVision is a desktop application.

Use:
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1

For low-level UI debugging only, the internal Vite server is still available through:
  npm.cmd --prefix apps/web run ui:dev

The internal UI server is not a supported ReefVision runtime and will not connect to a manually managed browser API.
"@
