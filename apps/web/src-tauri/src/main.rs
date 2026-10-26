#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
#[cfg(test)]
use std::sync::Arc;
#[cfg(target_os = "windows")]
use std::{ffi::OsStr, os::windows::ffi::OsStrExt, ptr::null};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager, State, WindowEvent};
#[cfg(target_os = "windows")]
use windows_sys::Win32::{
    Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE},
    System::Threading::CreateMutexW,
    UI::WindowsAndMessaging::{FindWindowW, IsIconic, SetForegroundWindow, ShowWindow, SW_RESTORE},
};

const BACKEND_SHUTDOWN_REQUEST: &[u8] = b"shutdown\n";
const BACKEND_STARTUP_TIMEOUT: Duration = Duration::from_secs(180);
const BACKEND_GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(3);
const BACKEND_FORCE_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
const BACKEND_SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(100);
const DEV_DATA_DIR_ENV: &str = "REEFVISION_DESKTOP_DATA_DIR";
const ACCEPTANCE_MODE_ENV: &str = "REEFVISION_WINDOWS_ACCEPTANCE";
const ACCEPTANCE_DATA_DIR_ENV: &str = "REEFVISION_ACCEPTANCE_DATA_DIR";
const ACCEPTANCE_MARKER: &str = ".reefvision-clean-install-acceptance";

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopContext {
    api_base_url: String,
    data_dir: String,
    desktop_mode: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ShutdownOutcome {
    AlreadyStopped,
    Graceful,
    Forced,
}

trait ManagedProcess {
    fn request_graceful_shutdown(&mut self);
    fn has_stopped(&mut self) -> bool;
    fn force_terminate(&mut self);
}

struct ManagedBackend<P> {
    process: Mutex<Option<P>>,
    shutdown_started: AtomicBool,
}

impl<P> ManagedBackend<P> {
    fn new(process: P) -> Self {
        Self {
            process: Mutex::new(Some(process)),
            shutdown_started: AtomicBool::new(false),
        }
    }
}

impl<P: ManagedProcess> ManagedBackend<P> {
    fn shutdown_once(&self) -> Option<ShutdownOutcome> {
        if self.shutdown_started.swap(true, Ordering::AcqRel) {
            return None;
        }

        let mut process_slot = match self.process.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };

        process_slot.take().map(|mut process| {
            shutdown_process(
                &mut process,
                BACKEND_GRACEFUL_SHUTDOWN_TIMEOUT,
                BACKEND_FORCE_SHUTDOWN_TIMEOUT,
                BACKEND_SHUTDOWN_POLL_INTERVAL,
            )
        })
    }
}

struct BackendProcess {
    child: Child,
}

impl ManagedProcess for BackendProcess {
    fn request_graceful_shutdown(&mut self) {
        if let Some(stdin) = self.child.stdin.as_mut() {
            let _ = stdin.write_all(BACKEND_SHUTDOWN_REQUEST);
            let _ = stdin.flush();
        }
    }

    fn has_stopped(&mut self) -> bool {
        self.child
            .try_wait()
            .map(|status| status.is_some())
            .unwrap_or(false)
    }

    fn force_terminate(&mut self) {
        if self
            .child
            .try_wait()
            .map(|status| status.is_some())
            .unwrap_or(false)
        {
            return;
        }
        let _ = self.child.kill();
    }
}

struct DesktopState {
    backend: ManagedBackend<BackendProcess>,
    context: DesktopContext,
}

#[cfg(target_os = "windows")]
struct SingleInstanceGuard(HANDLE);

#[cfg(not(target_os = "windows"))]
struct SingleInstanceGuard;

#[cfg(target_os = "windows")]
impl Drop for SingleInstanceGuard {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}

#[tauri::command]
fn desktop_context(state: State<'_, DesktopState>) -> DesktopContext {
    state.context.clone()
}

// Only accept opaque run IDs. Never pass filesystem paths or arbitrary commands
// from the webview to the desktop shell.
fn valid_training_run_id(run_id: &str) -> bool {
    !run_id.is_empty()
        && run_id.len() <= 72
        && run_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

#[tauri::command]
fn open_training_console(state: State<'_, DesktopState>, run_id: String) -> Result<(), String> {
    if !valid_training_run_id(&run_id) {
        return Err("Invalid training run ID".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        // The source is the trusted loopback URL from desktop startup, not
        // frontend input. PowerShell performs read-only status queries.
        let url = format!("{}/training-runs/{}", state.context.api_base_url, run_id);
        let script = format!("$url = '{}'; ", url)
            + r#"
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# User-supplied run names, metric labels, and error messages are not
# terminal commands. Strip ANSI/C1 escape strings and invisible controls
# from displayed fields only; do not modify persisted run provenance.
function Format-SafeText {
  param([AllowNull()][object]$Value)
  if ($null -eq $Value) { return '' }
  $text = [string]$Value
  $text = [regex]::Replace($text, '\x1b[\]PX^_][\s\S]*?(?:\x07|\x1b\\|$)', '')
  $text = [regex]::Replace($text, '[\x90\x98\x9d\x9e\x9f][\s\S]*?(?:\x07|\x9c|\x1b\\|$)', '')
  $text = [regex]::Replace($text, '(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]', '')
  $text = [regex]::Replace($text, '\x1b[ -/]*[@-_]', '')
  $text = [regex]::Replace($text, '[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]', ' ')
  return $text
}
function Test-FiniteMetricValue {
  param([AllowNull()][object]$Value)
  if ($null -eq $Value -or $Value -is [bool] -or $Value -is [string] -or $Value -isnot [System.ValueType]) {
    return $false
  }
  try {
    $number = [Convert]::ToDouble($Value, [Globalization.CultureInfo]::InvariantCulture)
  } catch {
    return $false
  }
  return -not [double]::IsNaN($number) -and -not [double]::IsInfinity($number)
}
Write-Host 'ReefVision training monitor (read-only). Close this window to stop monitoring.'
while ($true) {
  try {
    $run = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 10
    Clear-Host
    Write-Host ('ReefVision - {0}' -f (Format-SafeText $run.run_name))
    Write-Host ('Status: {0} | Stage: {1}' -f (Format-SafeText $run.status), (Format-SafeText $run.stage))
    Write-Host ('Epoch: {0} / {1}' -f (Format-SafeText $run.progress_epoch), (Format-SafeText $run.progress_total_epochs))
    # Some training providers persist losses as epoch histories, while
    # others include the newest values in the summary metrics object.
    # Show both without inventing unavailable fields.
    # Summary metrics may lag behind the current epoch. Load them first;
    # where both sources have a value, the latest persisted epoch history
    # wins so box/cls/dfl losses reflect the actual training progression.
    $latestMetrics = @{}
    if ($null -ne $run.metrics) {
      foreach ($metric in $run.metrics.PSObject.Properties) {
        if (Test-FiniteMetricValue -Value $metric.Value) {
          $latestMetrics[$metric.Name] = $metric.Value
        }
      }
    }
    if ($null -ne $run.metrics_history) {
      foreach ($series in $run.metrics_history.PSObject.Properties) {
        $values = @($series.Value)
        for ($index = $values.Count - 1; $index -ge 0; $index -= 1) {
          if (Test-FiniteMetricValue -Value $values[$index]) {
            $latestMetrics[$series.Name] = $values[$index]
            break
          }
        }
      }
    }
    $trainingLosses = @('train/box_loss', 'train/cls_loss', 'train/dfl_loss', 'train/seg_loss', 'train/loss')
    $validationLosses = @('val/box_loss', 'val/cls_loss', 'val/dfl_loss', 'val/seg_loss', 'val/loss')
    if (@($trainingLosses | Where-Object { $latestMetrics.ContainsKey($_) }).Count -gt 0) {
      Write-Host ''
      Write-Host 'Training losses'
      foreach ($key in $trainingLosses) {
        if ($latestMetrics.ContainsKey($key)) { Write-Host ('  {0,-20} {1}' -f (Format-SafeText $key), (Format-SafeText $latestMetrics[$key])) }
      }
    }
    if (@($validationLosses | Where-Object { $latestMetrics.ContainsKey($_) }).Count -gt 0) {
      Write-Host ''
      Write-Host 'Validation losses'
      foreach ($key in $validationLosses) {
        if ($latestMetrics.ContainsKey($key)) { Write-Host ('  {0,-20} {1}' -f (Format-SafeText $key), (Format-SafeText $latestMetrics[$key])) }
      }
    }
    $otherMetrics = @($latestMetrics.Keys | Where-Object {
      $_ -notin ($trainingLosses + $validationLosses) -and $_ -ne 'epoch' -and $_ -ne 'time'
    } | Sort-Object)
    if ($otherMetrics.Count -gt 0) {
      Write-Host ''
      Write-Host 'Other model metrics'
      foreach ($key in $otherMetrics) {
        Write-Host ('  {0,-30} {1}' -f (Format-SafeText $key), (Format-SafeText $latestMetrics[$key]))
      }
    }
    # The API reads only the persisted run log, with path confinement and a
    # bounded tail. This console never opens a training process or writes logs.
    try {
      $tail = Invoke-RestMethod -Uri ($url + '/logs/tail') -Method Get -TimeoutSec 5
      if ($tail.available -and $tail.text) {
        Write-Host ''
        Write-Host 'Training job log (last 20 lines, read-only)'
        $logLines = @($tail.text -split '\r?\n' | Where-Object { $_ -ne '' })
        foreach ($line in ($logLines | Select-Object -Last 20)) {
          # Training logs are untrusted terminal text, just like run metadata.
          # Sanitize the displayed copy; never rewrite persisted log bytes.
          Write-Host (Format-SafeText $line)
        }
      } else {
        Write-Host 'No persisted training job log available yet.'
      }
    } catch {
      Write-Host 'Training job log unavailable (status/metrics remain live).'
    }
    if ($run.error_message) { Write-Host ('Error: {0}' -f (Format-SafeText $run.error_message)) }
    if ($run.status -in @('completed', 'failed', 'cancelled')) {
      Write-Host 'Run ended. This window can now be closed.'
      break
    }
  } catch {
    Write-Host ('Waiting for ReefVision training status: {0}' -f (Format-SafeText $_.Exception.Message))
  }
  Start-Sleep -Seconds 2
}
"#;
        Command::new("powershell.exe")
            .args(["-NoProfile", "-NoExit", "-Command", &script])
            .spawn()
            .map_err(|error| format!("Could not open PowerShell training monitor: {error}"))?;
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = state;
        Err("The external PowerShell training monitor is available on Windows only".to_string())
    }
}

#[cfg(target_os = "windows")]
fn focus_existing_instance_window() {
    let window_title: Vec<u16> = OsStr::new("ReefVision")
        .encode_wide()
        .chain(Some(0))
        .collect();
    let handle = unsafe { FindWindowW(null(), window_title.as_ptr()) };
    if handle.is_null() {
        return;
    }

    unsafe {
        if IsIconic(handle) != 0 {
            let _ = ShowWindow(handle, SW_RESTORE);
        }
        let _ = SetForegroundWindow(handle);
    }
}

#[cfg(not(target_os = "windows"))]
fn focus_existing_instance_window() {}

#[cfg(target_os = "windows")]
fn acquire_single_instance_guard() -> std::io::Result<Option<SingleInstanceGuard>> {
    let mutex_name: Vec<u16> = OsStr::new("Local\\ReefVisionDesktopInstance")
        .encode_wide()
        .chain(Some(0))
        .collect();
    let handle = unsafe { CreateMutexW(null(), 1, mutex_name.as_ptr()) };
    if handle.is_null() {
        return Err(std::io::Error::last_os_error());
    }

    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        unsafe {
            let _ = CloseHandle(handle);
        }
        return Ok(None);
    }

    Ok(Some(SingleInstanceGuard(handle)))
}

#[cfg(not(target_os = "windows"))]
fn acquire_single_instance_guard() -> std::io::Result<Option<SingleInstanceGuard>> {
    Ok(Some(SingleInstanceGuard))
}

fn workspace_root() -> std::io::Result<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.join("..").join("..").join("..").canonicalize()
}

fn ensure_directory(path: &Path) -> std::io::Result<()> {
    fs::create_dir_all(path)
}

fn desktop_dev_fallback_data_dir() -> std::io::Result<PathBuf> {
    Ok(workspace_root()?.join(".desktop").join("dev-data"))
}

fn acceptance_data_dir_from_environment() -> std::io::Result<Option<PathBuf>> {
    if std::env::var_os(ACCEPTANCE_MODE_ENV).as_deref() != Some(OsStr::new("1")) {
        return Ok(None);
    }

    let data_dir = std::env::var_os(ACCEPTANCE_DATA_DIR_ENV).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("{ACCEPTANCE_DATA_DIR_ENV} is required in acceptance mode"),
        )
    })?;
    let data_dir = PathBuf::from(data_dir);
    if !data_dir.is_absolute() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("{ACCEPTANCE_DATA_DIR_ENV} must be an absolute path"),
        ));
    }
    if !data_dir.join(ACCEPTANCE_MARKER).is_file() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("Acceptance data directory is missing the required {ACCEPTANCE_MARKER} marker"),
        ));
    }
    ensure_directory(&data_dir)?;
    Ok(Some(data_dir))
}

fn resolve_desktop_data_dir(app: &AppHandle) -> std::io::Result<PathBuf> {
    if let Some(data_dir) = acceptance_data_dir_from_environment()? {
        return Ok(data_dir);
    }

    if cfg!(debug_assertions) {
        if let Some(override_path) = std::env::var_os(DEV_DATA_DIR_ENV) {
            let override_path = PathBuf::from(override_path);
            ensure_directory(&override_path)?;
            return Ok(override_path);
        }
    }

    match app.path().app_data_dir() {
        Ok(data_dir) => match ensure_directory(&data_dir) {
            Ok(()) => Ok(data_dir),
            Err(error)
                if cfg!(debug_assertions)
                    && error.kind() == std::io::ErrorKind::PermissionDenied =>
            {
                let fallback = desktop_dev_fallback_data_dir()?;
                ensure_directory(&fallback)?;
                eprintln!(
                    "ReefVision desktop could not access {} ({}). Falling back to {} for development.",
                    data_dir.display(),
                    error,
                    fallback.display(),
                );
                Ok(fallback)
            }
            Err(error) => Err(error),
        },
        Err(error) if cfg!(debug_assertions) => {
            let fallback = desktop_dev_fallback_data_dir()?;
            ensure_directory(&fallback)?;
            eprintln!(
                "ReefVision desktop could not resolve the platform app-data directory ({}). Falling back to {} for development.",
                error,
                fallback.display(),
            );
            Ok(fallback)
        }
        Err(error) => Err(std::io::Error::other(error.to_string())),
    }
}

fn backend_log_path(data_dir: &Path) -> PathBuf {
    data_dir.join("logs").join("backend.log")
}

fn backend_port_path(data_dir: &Path) -> PathBuf {
    data_dir.join("runtime").join("backend-port.txt")
}

fn packaged_backend_executable_name() -> String {
    format!("reefvision-api{}", std::env::consts::EXE_SUFFIX)
}

fn packaged_backend_path_from_resource_dir(resource_dir: &Path) -> PathBuf {
    resource_dir
        .join("backend")
        .join("reefvision-api")
        .join(packaged_backend_executable_name())
}

fn packaged_model_catalog_path_from_resource_dir(resource_dir: &Path) -> PathBuf {
    resource_dir
        .join("backend")
        .join("reefvision-api")
        .join("_internal")
        .join("config")
        .join("model_catalog.json")
}

fn packaged_backend_executable(app: &AppHandle) -> std::io::Result<PathBuf> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| std::io::Error::other(error.to_string()))?;
    let executable = packaged_backend_path_from_resource_dir(&resource_dir);
    let model_catalog = packaged_model_catalog_path_from_resource_dir(&resource_dir);
    if executable.is_file() && model_catalog.is_file() {
        return Ok(executable);
    }

    Err(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        format!(
            "The ReefVision desktop backend bundle is incomplete. Expected executable {} and model catalog {}",
            executable.display(),
            model_catalog.display()
        ),
    ))
}

fn wait_for_backend_port(port_file: &Path, timeout: Duration) -> std::io::Result<u16> {
    let started = Instant::now();
    loop {
        if let Ok(contents) = fs::read_to_string(port_file) {
            if let Ok(port) = contents.trim().parse::<u16>() {
                return Ok(port);
            }
        }

        if started.elapsed() >= timeout {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "The ReefVision desktop backend did not publish its loopback port at {} within {} seconds.",
                    port_file.display(),
                    timeout.as_secs()
                ),
            ));
        }

        thread::sleep(Duration::from_millis(100));
    }
}

fn wait_for_process_shutdown<P: ManagedProcess>(
    process: &mut P,
    timeout: Duration,
    poll_interval: Duration,
) -> bool {
    let started = Instant::now();
    loop {
        if process.has_stopped() {
            return true;
        }

        if started.elapsed() >= timeout {
            return false;
        }

        thread::sleep(poll_interval);
    }
}

fn shutdown_process<P: ManagedProcess>(
    process: &mut P,
    graceful_timeout: Duration,
    force_timeout: Duration,
    poll_interval: Duration,
) -> ShutdownOutcome {
    if process.has_stopped() {
        return ShutdownOutcome::AlreadyStopped;
    }

    process.request_graceful_shutdown();
    if wait_for_process_shutdown(process, graceful_timeout, poll_interval) {
        return ShutdownOutcome::Graceful;
    }

    process.force_terminate();
    let _ = wait_for_process_shutdown(process, force_timeout, poll_interval);
    ShutdownOutcome::Forced
}

fn spawn_dev_backend(
    data_dir: &Path,
    log_file: &Path,
    port_file: &Path,
) -> std::io::Result<BackendProcess> {
    let workspace = workspace_root()?;
    let python = workspace.join(".venv").join("Scripts").join("python.exe");
    if !python.is_file() {
        return Err(std::io::Error::other(
            "ReefVision desktop mode requires .venv\\Scripts\\python.exe. Run scripts\\bootstrap.ps1 first.",
        ));
    }

    let child = Command::new(python)
        .arg("-m")
        .arg("reefvision.desktop")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--data-dir")
        .arg(data_dir)
        .arg("--log-file")
        .arg(log_file)
        .arg("--context-file")
        .arg(port_file)
        .current_dir(workspace)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;

    Ok(BackendProcess { child })
}

fn spawn_packaged_backend(
    app: &AppHandle,
    data_dir: &Path,
    log_file: &Path,
    port_file: &Path,
) -> std::io::Result<BackendProcess> {
    let executable = packaged_backend_executable(app)?;
    let working_directory = executable.parent().ok_or_else(|| {
        std::io::Error::other(
            "The packaged ReefVision backend executable is missing a parent directory",
        )
    })?;
    let data_dir_arg = data_dir.to_string_lossy().into_owned();
    let log_file_arg = log_file.to_string_lossy().into_owned();
    let port_file_arg = port_file.to_string_lossy().into_owned();
    let child = Command::new(&executable)
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--data-dir")
        .arg(data_dir_arg)
        .arg("--log-file")
        .arg(log_file_arg)
        .arg("--context-file")
        .arg(port_file_arg)
        .current_dir(working_directory)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| std::io::Error::other(error.to_string()))?;

    Ok(BackendProcess { child })
}

fn spawn_backend(
    app: &AppHandle,
    data_dir: &Path,
    port_file: &Path,
) -> std::io::Result<BackendProcess> {
    let log_file = backend_log_path(data_dir);
    if let Some(parent) = log_file.parent() {
        ensure_directory(parent)?;
    }
    if let Some(parent) = port_file.parent() {
        ensure_directory(parent)?;
    }
    if port_file.exists() {
        fs::remove_file(port_file)?;
    }

    if cfg!(debug_assertions) {
        spawn_dev_backend(data_dir, &log_file, port_file)
    } else {
        spawn_packaged_backend(app, data_dir, &log_file, port_file)
    }
}

fn install_panic_shutdown_hook(app_handle: AppHandle) {
    let previous_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |panic_info| {
        if let Some(state) = app_handle.try_state::<DesktopState>() {
            let _ = state.backend.shutdown_once();
        }
        previous_hook(panic_info);
    }));
}

fn shutdown_backend(state: &DesktopState) {
    let _ = state.backend.shutdown_once();
}

fn main() {
    let _single_instance_guard = match acquire_single_instance_guard() {
        Ok(Some(guard)) => guard,
        Ok(None) => {
            focus_existing_instance_window();
            eprintln!("ReefVision desktop is already running.");
            return;
        }
        Err(error) => {
            panic!("ReefVision could not establish its single-instance guard: {error}");
        }
    };

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![desktop_context, open_training_console])
        .setup(|app| {
            let data_dir = resolve_desktop_data_dir(app.handle())?;
            let handle = app.handle().clone();
            let port_file = backend_port_path(&data_dir);
            let mut backend = spawn_backend(&handle, &data_dir, &port_file)?;
            let port = match wait_for_backend_port(&port_file, BACKEND_STARTUP_TIMEOUT) {
                Ok(port) => port,
                Err(error) => {
                    let _ = shutdown_process(
                        &mut backend,
                        BACKEND_GRACEFUL_SHUTDOWN_TIMEOUT,
                        BACKEND_FORCE_SHUTDOWN_TIMEOUT,
                        BACKEND_SHUTDOWN_POLL_INTERVAL,
                    );
                    return Err(error.into());
                }
            };
            let context = DesktopContext {
                api_base_url: format!("http://127.0.0.1:{port}/api/v1"),
                data_dir: data_dir.display().to_string(),
                desktop_mode: true,
            };
            let app_handle = app.handle().clone();
            app.manage(DesktopState {
                backend: ManagedBackend::new(backend),
                context,
            });
            install_panic_shutdown_hook(app_handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("ReefVision desktop shell encountered an unrecoverable error");

    app.run(|app_handle, event| {
        if let Some(state) = app_handle.try_state::<DesktopState>() {
            match event {
                tauri::RunEvent::WindowEvent {
                    label,
                    event: WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed,
                    ..
                } if label == "main" => shutdown_backend(state.inner()),
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                    shutdown_backend(state.inner())
                }
                _ => {}
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    #[test]
    fn training_console_accepts_only_opaque_run_ids() {
        assert!(valid_training_run_id("b530769c-2a79-4d44-a36e-61d988d5fa78"));
        assert!(valid_training_run_id("run-1"));
        assert!(!valid_training_run_id(""));
        assert!(!valid_training_run_id("not a run"));
        assert!(!valid_training_run_id("foo'; Remove-Item C:"));
        assert!(!valid_training_run_id("../escape"));
        assert!(!valid_training_run_id(&"a".repeat(73)));
    }

    #[derive(Clone)]
    struct FakeProcessState {
        graceful_requests: Arc<AtomicUsize>,
        force_requests: Arc<AtomicUsize>,
    }

    impl FakeProcessState {
        fn new() -> Self {
            Self {
                graceful_requests: Arc::new(AtomicUsize::new(0)),
                force_requests: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    struct FakeProcess {
        state: FakeProcessState,
        running: bool,
        graceful_requested: bool,
        force_requested: bool,
        graceful_polls_until_stop: Option<usize>,
        force_polls_until_stop: usize,
    }

    impl FakeProcess {
        fn graceful_after(graceful_polls_until_stop: usize) -> (Self, FakeProcessState) {
            let state = FakeProcessState::new();
            (
                Self {
                    state: state.clone(),
                    running: true,
                    graceful_requested: false,
                    force_requested: false,
                    graceful_polls_until_stop: Some(graceful_polls_until_stop),
                    force_polls_until_stop: 0,
                },
                state,
            )
        }

        fn force_after(force_polls_until_stop: usize) -> (Self, FakeProcessState) {
            let state = FakeProcessState::new();
            (
                Self {
                    state: state.clone(),
                    running: true,
                    graceful_requested: false,
                    force_requested: false,
                    graceful_polls_until_stop: None,
                    force_polls_until_stop,
                },
                state,
            )
        }
    }

    impl ManagedProcess for FakeProcess {
        fn request_graceful_shutdown(&mut self) {
            self.graceful_requested = true;
            self.state.graceful_requests.fetch_add(1, Ordering::SeqCst);
        }

        fn has_stopped(&mut self) -> bool {
            if !self.running {
                return true;
            }

            if self.force_requested {
                if self.force_polls_until_stop == 0 {
                    self.running = false;
                } else {
                    self.force_polls_until_stop -= 1;
                }
                return !self.running;
            }

            if self.graceful_requested {
                if let Some(remaining_polls) = self.graceful_polls_until_stop.as_mut() {
                    if *remaining_polls == 0 {
                        self.running = false;
                    } else {
                        *remaining_polls -= 1;
                    }
                }
            }

            !self.running
        }

        fn force_terminate(&mut self) {
            self.force_requested = true;
            self.state.force_requests.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[test]
    fn shutdown_process_prefers_graceful_shutdown() {
        let (mut process, state) = FakeProcess::graceful_after(1);

        let outcome = shutdown_process(
            &mut process,
            Duration::from_millis(10),
            Duration::from_millis(10),
            Duration::from_millis(1),
        );

        assert_eq!(outcome, ShutdownOutcome::Graceful);
        assert_eq!(state.graceful_requests.load(Ordering::SeqCst), 1);
        assert_eq!(state.force_requests.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn shutdown_process_forces_after_grace_timeout() {
        let (mut process, state) = FakeProcess::force_after(1);

        let outcome = shutdown_process(
            &mut process,
            Duration::from_millis(2),
            Duration::from_millis(10),
            Duration::from_millis(1),
        );

        assert_eq!(outcome, ShutdownOutcome::Forced);
        assert_eq!(state.graceful_requests.load(Ordering::SeqCst), 1);
        assert_eq!(state.force_requests.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn managed_backend_shutdown_runs_only_once() {
        let (process, state) = FakeProcess::graceful_after(0);
        let backend = ManagedBackend::new(process);

        let first = backend.shutdown_once();
        let second = backend.shutdown_once();

        assert_eq!(first, Some(ShutdownOutcome::Graceful));
        assert_eq!(second, None);
        assert_eq!(state.graceful_requests.load(Ordering::SeqCst), 1);
        assert_eq!(state.force_requests.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn packaged_backend_path_resolves_from_backend_resource_directory() {
        let resource_dir = PathBuf::from("resources-root");

        let executable = packaged_backend_path_from_resource_dir(&resource_dir);

        assert_eq!(
            executable,
            resource_dir
                .join("backend")
                .join("reefvision-api")
                .join(packaged_backend_executable_name())
        );
    }

    #[test]
    fn packaged_model_catalog_path_resolves_inside_sidecar_resources() {
        let resource_dir = PathBuf::from("resources-root");

        assert_eq!(
            packaged_model_catalog_path_from_resource_dir(&resource_dir),
            resource_dir
                .join("backend")
                .join("reefvision-api")
                .join("_internal")
                .join("config")
                .join("model_catalog.json")
        );
    }

    #[test]
    fn desktop_dev_fallback_data_dir_lives_under_workspace_root() {
        let fallback = desktop_dev_fallback_data_dir().expect("fallback path should resolve");

        assert_eq!(
            fallback,
            workspace_root().unwrap().join(".desktop").join("dev-data")
        );
    }

    #[test]
    fn acceptance_data_dir_requires_explicit_mode_path_and_marker() {
        let token = format!("reefvision-acceptance-{}", std::process::id());
        let data_dir = std::env::temp_dir().join(token);
        fs::create_dir_all(&data_dir).unwrap();
        std::env::set_var(ACCEPTANCE_MODE_ENV, "1");
        std::env::set_var(ACCEPTANCE_DATA_DIR_ENV, &data_dir);

        assert!(acceptance_data_dir_from_environment().is_err());
        fs::write(data_dir.join(ACCEPTANCE_MARKER), b"acceptance-only\n").unwrap();
        assert_eq!(
            acceptance_data_dir_from_environment().unwrap(),
            Some(data_dir.clone())
        );

        std::env::remove_var(ACCEPTANCE_MODE_ENV);
        std::env::remove_var(ACCEPTANCE_DATA_DIR_ENV);
        fs::remove_dir_all(data_dir).unwrap();
    }
}
