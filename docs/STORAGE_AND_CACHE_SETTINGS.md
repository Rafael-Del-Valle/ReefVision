# ReefVision storage and cache settings

ReefVision exposes a global **Storage settings** control in the desktop interface. It is available without opening a project.

## Configurable directories

- **Application data root** — database, projects, imported media, annotations, trained and imported models, exports, logs, and backups.
- **Model and download cache** — downloadable catalog checkpoints, provider packs, Hugging Face/Transformers caches, Torch caches, and temporary model downloads.
- **Temporary workspace** — temporary files created during imports, exports, model processing, and other local operations.

Each path must be absolute, creatable, and writable. ReefVision reports the available free space before saving it.

Saved changes take effect after ReefVision restarts. The preferences file is stored at `%LOCALAPPDATA%\ReefVision\config\storage.json` on Windows unless `REEFVISION_STORAGE_SETTINGS_FILE` overrides it.

Deployment environment variables take precedence and lock the corresponding field in the interface:

- `REEFVISION_DATA_DIR`
- `REEFVISION_MODEL_CACHE_DIR`
- `REEFVISION_TEMP_DIR`

The packaged Tauri launcher also supplies a first-launch data directory so the local API always has a safe fallback. That internal desktop fallback is not treated as an administrator lock: after a user saves a different application data root, the persisted value takes effect on the next restart. Explicit environment overrides used outside the packaged desktop launcher remain authoritative.

## Moving existing application data

Changing the application data root does not copy the current database or projects automatically. Before switching it:

1. Create a backup or copy the complete active data root while ReefVision is closed.
2. Copy or restore that data into the new directory.
3. Start ReefVision, open **Storage settings**, and save the new application data root.
4. Restart ReefVision.
5. Verify projects and managed files before deleting the old copy.

Exports stay under the application data root so project records and generated outputs remain portable together.

Changing only the model cache does not move trained or imported models. Downloadable model checkpoints and provider packs may need to be restored or installed again in the new cache.

## Cache cleanup

Run the safe cleanup from the repository root:

```powershell
.\scripts\clear-reefvision-caches.ps1
```

It removes rebuildable packaging output, Rust/Tauri build output, web build output, test output, and Python source caches. It preserves databases, projects, annotations, trained/imported models, exports, backups, completed packaged Transformer snapshots, and user model caches.

Include old validation artifacts:

```powershell
.\scripts\clear-reefvision-caches.ps1 -IncludeValidationArtifacts
```

Also remove `node_modules`:

```powershell
.\scripts\clear-reefvision-caches.ps1 -IncludeValidationArtifacts -IncludeNodeModules
```

Remove downloadable user model caches as well:

```powershell
.\scripts\clear-reefvision-caches.ps1 -IncludeValidationArtifacts -IncludeUserModelCaches
```

The last command removes downloadable catalog checkpoints, provider packs, Hugging Face/Transformers caches, Torch caches, and incomplete model downloads. Those assets must be restored or downloaded again.

Avoid `-IncludeCompletedTransformerSnapshots` unless disk recovery is more important than preserving the six verified offline packaging snapshots. Removing them forces the packaging workflow to download them again.

Additional shared package-manager caches can be cleared separately:

```powershell
.\.venv\Scripts\python.exe -m pip cache purge
conda clean --all -y
npm cache clean --force
```

These commands do not remove the ReefVision virtual environment or Conda environments, but future installs may need to download packages again.
