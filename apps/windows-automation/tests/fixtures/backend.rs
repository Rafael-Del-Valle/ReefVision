use std::env;
use std::ffi::OsString;
use std::fs;
use std::path::PathBuf;

fn main() {
    let mut args = env::args_os().skip(1);
    assert_eq!(args.next(), Some(OsString::from("--automation-cli-output")));
    let reply = PathBuf::from(args.next().unwrap());
    assert_eq!(args.next(), Some(OsString::from("--")));
    assert!(reply.parent().unwrap().is_dir() && !reply.exists());
    assert!(env::var_os("PATH").unwrap().is_empty());
    fs::write(env::var_os("REEFVISION_TEST_REPLY_WITNESS").unwrap(), reply.to_str().unwrap())
        .unwrap();

    let args: Vec<_> = args.collect();
    let (status, text) = match args.first().and_then(|arg| arg.to_str()) {
        Some("review") => {
            assert_eq!(args[1], "résumé fish 🐟\" tail\\");
            assert!(args[2].is_empty());
            assert_eq!(args[3], "--");
            assert_eq!(args.len(), 4);
            (3, "review pending 🐟\n")
        }
        Some("--failure") => (7, "invalid input\n"),
        Some("--help") => (0, "help for reefvision\n"),
        None => (0, "no-argument help\n"),
        _ => panic!("unexpected forwarded arguments"),
    };
    fs::write(reply, text).unwrap();
    std::process::exit(status);
}
