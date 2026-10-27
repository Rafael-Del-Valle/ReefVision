use std::{env, path::Path};

fn main() {
    let profile = env::var("PROFILE").unwrap_or_default();
    if profile == "release" {
        let executable_name = if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
            "reefvision-api.exe"
        } else {
            "reefvision-api"
        };
        // The MSI bundles the complete PyInstaller onedir backend as a Tauri
        // resource. It is NOT a Tauri sidecar under src-tauri/binaries.
        // Keep this check aligned with tauri.conf.json's backend/ mapping.
        let release_backend = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../.desktop/release-1.0.3/backend/reefvision-api");
        let packaged_backend = release_backend.join(executable_name);
        let model_catalog = release_backend.join("_internal/config/model_catalog.json");
        if !packaged_backend.is_file() || !model_catalog.is_file() {
            panic!(
                "The staged ReefVision backend is incomplete. Expected executable {} and model catalog {}. Run scripts/build-desktop-backend.ps1 before desktop packaging.",
                packaged_backend.display(),
                model_catalog.display(),
            );
        }
        println!("cargo:rerun-if-changed={}", packaged_backend.display());
        println!("cargo:rerun-if-changed={}", model_catalog.display());
    }

    tauri_build::build()
}
