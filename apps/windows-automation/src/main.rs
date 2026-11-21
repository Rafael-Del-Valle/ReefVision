#[cfg(windows)]
mod windows_console {
    use std::env;
    use std::ffi::OsStr;
    use std::fs::{self, File};
    use std::io::{self, ErrorKind, Write};
    use std::os::windows::{ffi::OsStrExt, process::CommandExt};
    use std::path::{Path, PathBuf};
    use std::process::{Command, Stdio};
    use std::ptr;
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::{
            Authorization::{
                ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
            },
            Cryptography::{BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG},
            SECURITY_ATTRIBUTES,
        },
        Storage::FileSystem::CreateDirectoryW,
        System::Threading::CREATE_NO_WINDOW,
    };

    struct ReplyDirectory(PathBuf);

    impl ReplyDirectory {
        fn new() -> io::Result<Self> {
            let mut bytes = [0u8; 16];
            // The system RNG owns no handle in system-preferred mode and fills this live buffer.
            let status = unsafe {
                BCryptGenRandom(
                    ptr::null_mut(),
                    bytes.as_mut_ptr(),
                    bytes.len() as u32,
                    BCRYPT_USE_SYSTEM_PREFERRED_RNG,
                )
            };
            if status < 0 {
                return Err(io::Error::other(
                    "Windows could not create a private reply name",
                ));
            }
            let temp = env::temp_dir();
            if !temp.is_absolute() {
                return Err(io::Error::new(
                    ErrorKind::InvalidInput,
                    "Windows temporary directory is not absolute",
                ));
            }
            let path = temp.canonicalize()?.join(format!(
                "reefvision-cli-{:032x}",
                u128::from_le_bytes(bytes)
            ));
            create_private_directory(&path)?;
            Ok(Self(path))
        }
    }

    fn create_private_directory(path: &Path) -> io::Result<()> {
        // This directory and newly inherited reply files grant access to the owner and SYSTEM.
        let permissions: Vec<_> = OsStr::new("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)")
            .encode_wide()
            .chain(Some(0))
            .collect();
        let path: Vec<_> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        let mut descriptor = ptr::null_mut();
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                permissions.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor,
            bInheritHandle: 0,
        };
        let created = unsafe { CreateDirectoryW(path.as_ptr(), &attributes) };
        let result = if created == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        };
        unsafe { LocalFree(descriptor) };
        result
    }

    impl Drop for ReplyDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    pub fn run() -> io::Result<i32> {
        let executable = env::current_exe()?;
        let installation = executable.parent().and_then(Path::parent).ok_or_else(|| {
            io::Error::new(
                ErrorKind::NotFound,
                "could not locate the installed backend",
            )
        })?;
        let backend = installation.join("backend/reefvision-api/reefvision-api.exe");
        if !backend.is_file() {
            return Err(io::Error::new(
                ErrorKind::NotFound,
                "could not locate the installed backend",
            ));
        }

        let scratch = ReplyDirectory::new()?;
        let reply_path = scratch.0.join("reply.json");
        let outcome = Command::new(backend)
            .arg("--automation-cli-output")
            .arg(&reply_path)
            .arg("--")
            .args(env::args_os().skip(1))
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()?;
        let code = outcome.code().unwrap_or(1);
        let mut reply = match File::open(reply_path) {
            Ok(reply) => reply,
            Err(_) => {
                writeln!(io::stderr().lock(), "The installed backend exited with code {code} before producing an automation reply.")?;
                return Ok(if matches!(code, 0 | 3) { 1 } else { code });
            }
        };
        if matches!(code, 0 | 3) {
            let mut stdout = io::stdout().lock();
            io::copy(&mut reply, &mut stdout)?;
            stdout.flush()?;
        } else {
            let mut stderr = io::stderr().lock();
            io::copy(&mut reply, &mut stderr)?;
            stderr.flush()?;
        }
        Ok(code)
    }
}

#[cfg(windows)]
fn main() {
    let code = windows_console::run().unwrap_or_else(|error| {
        eprintln!("ReefVision automation could not start: {error}");
        1
    });
    std::process::exit(code);
}

#[cfg(not(windows))]
fn main() {
    eprintln!("This ReefVision automation launcher is for Windows installations.");
    std::process::exit(1);
}
