# WiX MSI relink recovery

When Tauri successfully compiles `reefvision-desktop.exe` and generates the WiX object files but `light.exe` fails during the final MSI link, do not repeat model staging, PyInstaller, or Rust compilation immediately.

Run:

```powershell
.\scripts\relink-tauri-msi.ps1
```

The recovery script:

- reuses the generated `.wixobj` files under the Tauri release directory;
- preserves the 512 MB WiX cabinet split settings;
- runs `light.exe` with verbose output;
- suppresses only MSI Internal Consistency Evaluator validation during the link (`-sval`);
- writes the complete linker log under `.artifacts\wix-relink-<timestamp>`;
- copies the resulting MSI to the normal Tauri MSI bundle directory; and
- administratively extracts and verifies the installer with `verify-windows-msi.ps1`.

A failure caused by missing inputs, cabinet creation, payload size, source paths, or another non-validation linker error still fails and remains visible in `light-sval.log`.

Suppressing link-time ICE validation is a recovery for machines where the Windows Installer validation custom actions cannot execute correctly. It is not a replacement for extracting, installing, launching, and smoke-testing the generated MSI.
