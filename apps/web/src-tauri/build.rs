use std::{env, path::Path};

fn main() {
    let profile = env::var("PROFILE").unwrap_or_default();
    if profile == "release" {
        let executable_name = if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
            "reefvision-api.exe"
        } else {
            "reefvision-api"
        };
        let packaged_backend = Path::new("binaries")
            .join("reefvision-api")
            .join(executable_name);
        if !packaged_backend.is_file() {
            panic!(
                "The packaged ReefVision backend bundle is missing at {}. Run scripts/build-desktop-backend.ps1 before desktop packaging.",
                packaged_backend.display()
            );
        }
    }

    tauri_build::build()
}
