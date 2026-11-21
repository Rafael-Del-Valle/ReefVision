#![cfg(windows)]

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = env::temp_dir().join(format!(
            "reefvision-cli-test-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let profile = Self(root);
        fs::create_dir(profile.0.join("automation")).unwrap();
        fs::create_dir_all(profile.0.join("backend/reefvision-api")).unwrap();
        fs::create_dir(profile.0.join("scratch")).unwrap();
        fs::copy(env!("CARGO_BIN_EXE_reefvision"), profile.launcher()).unwrap();
        profile
    }

    fn launcher(&self) -> PathBuf {
        self.0.join("automation/reefvision.exe")
    }

    fn backend(&self) -> PathBuf {
        self.0.join("backend/reefvision-api/reefvision-api.exe")
    }

    fn run(&self, args: &[&str]) -> Output {
        let scratch = self.0.join("scratch");
        let witness = self.0.join("reply-path.txt");
        let output = Command::new(self.launcher())
            .args(args)
            .env("PATH", "")
            .env("TEMP", &scratch)
            .env("TMP", &scratch)
            .env("REEFVISION_TEST_REPLY_WITNESS", &witness)
            .output()
            .unwrap();
        assert!(fs::read_dir(scratch).unwrap().next().is_none());
        if witness.is_file() {
            let reply = PathBuf::from(fs::read_to_string(witness).unwrap());
            assert!(!reply.parent().unwrap().exists());
        }
        output
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn installed_launcher_forwards_original_args_and_streams_without_a_developer_path() {
    let fixture = Fixture::new();
    let compiler = env::var_os("RUSTC").unwrap_or_else(|| "rustc".into());
    assert!(Command::new(compiler)
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/backend.rs"))
        .arg("-o")
        .arg(fixture.backend())
        .status()
        .unwrap()
        .success());

    for (args, code, stdout, stderr) in [
        (&[][..], 0, "no-argument help\n", ""),
        (&["--help"][..], 0, "help for reefvision\n", ""),
        (
            &["review", "résumé fish 🐟\" tail\\", "", "--"][..],
            3,
            "review pending 🐟\n",
            "",
        ),
        (&["--failure"][..], 7, "", "invalid input\n"),
    ] {
        let result = fixture.run(args);
        assert_eq!(result.status.code(), Some(code));
        assert_eq!(result.stdout, stdout.as_bytes());
        assert_eq!(result.stderr, stderr.as_bytes());
    }
}

#[test]
fn reports_a_missing_installed_backend_without_leaking_private_scratch() {
    let fixture = Fixture::new();
    let result = fixture.run(&["--help"]);
    assert_eq!(result.status.code(), Some(1));
    assert!(result.stdout.is_empty());
    assert!(String::from_utf8(result.stderr)
        .unwrap()
        .contains("installed backend"));
}
