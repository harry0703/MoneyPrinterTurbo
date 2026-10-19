// MoneyPrinterTurbo Desktop - Tauri v2 native shell.
//
// Manages the PyInstaller-frozen backend ("mpt-server" sidecar):
//  - picks a free local port (8501-8599) and spawns the sidecar with it,
//  - polls http://127.0.0.1:<port>/_stcore/health until the WebUI is up,
//  - navigates the main window from the splash page to the local WebUI,
//  - kills the whole sidecar process tree when the app exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
// Tauri sidecar naming convention: <name>-<target-triple>[.exe]
const SIDECAR_NAME: &str = "mpt-server-x86_64-pc-windows-msvc.exe";
const HEALTH_TIMEOUT_SECS: u64 = 240;

struct Backend {
    child: Mutex<Option<Child>>,
    port: u16,
}

fn find_free_port() -> Option<u16> {
    for port in 8501..=8599 {
        if std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return Some(port);
        }
    }
    None
}

/// Minimal HTTP health probe against the Streamlit server.
fn http_health_ok(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(mut stream) = TcpStream::connect(&addr) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(4)));
    let request = format!(
        "GET /_stcore/health HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 256];
    let n = stream.read(&mut buf).unwrap_or(0);
    String::from_utf8_lossy(&buf[..n]).starts_with("HTTP/1.1 200")
}

/// Locate the bundled sidecar in every plausible resources layout.
fn resolve_sidecar(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(res) = app.path().resource_dir() {
        candidates.push(res.join("mpt-server").join(SIDECAR_NAME));
        candidates.push(res.join("resources").join("mpt-server").join(SIDECAR_NAME));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("mpt-server").join(SIDECAR_NAME));
            candidates.push(dir.join("resources").join("mpt-server").join(SIDECAR_NAME));
        }
    }
    candidates.into_iter().find(|p| p.is_file())
}

fn spawn_backend(app: &AppHandle, port: u16) -> Result<Child, String> {
    let exe = resolve_sidecar(app)
        .ok_or_else(|| "sidecar binary (mpt-server) not found in bundled resources".to_string())?;
    let workdir = exe
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    let log_path = std::env::temp_dir().join("mpt-desktop-backend.log");
    let log = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&log_path)
        .map_err(|e| format!("cannot open backend log file: {e}"))?;
    let log_err = log
        .try_clone()
        .map_err(|e| format!("cannot clone backend log handle: {e}"))?;

    let mut cmd = Command::new(&exe);
    cmd.current_dir(&workdir)
        .env("MPT_WEBUI_HOST", "127.0.0.1")
        .env("MPT_WEBUI_PORT", port.to_string())
        .env("PYTHONIOENCODING", "utf-8")
        .creation_flags(CREATE_NO_WINDOW)
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_err));

    // Prefer the full FFmpeg build bundled next to the app resources;
    // the sidecar also carries its own copy under _internal/ffmpeg/bin.
    if let Ok(res) = app.path().resource_dir() {
        let ffmpeg_candidates = [
            res.join("ffmpeg").join("bin").join("ffmpeg.exe"),
            res.join("mpt-server")
                .join("_internal")
                .join("ffmpeg")
                .join("bin")
                .join("ffmpeg.exe"),
        ];
        for ffmpeg in ffmpeg_candidates {
            if ffmpeg.is_file() {
                cmd.env("MPT_FFMPEG_PATH", &ffmpeg);
                break;
            }
        }
    }

    cmd.spawn()
        .map_err(|e| format!("failed to spawn sidecar {exe:?}: {e}"))
}

fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<Backend>() {
        if let Ok(mut guard) = state.child.lock() {
            if let Some(mut child) = guard.take() {
                // Kill the whole process tree (uvicorn/ffmpeg children first).
                let pid = child.id().to_string();
                let _ = Command::new("taskkill")
                    .args(["/PID", &pid, "/T", "/F"])
                    .creation_flags(CREATE_NO_WINDOW)
                    .status();
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn set_status(window: &tauri::WebviewWindow, message: &str) {
    // Escape the message for embedding inside a double-quoted JS string.
    let mut safe = String::new();
    for c in message.chars() {
        match c {
            '"' => safe.push_str("\\\""),
            '\\' => safe.push_str("\\\\"),
            '\n' => safe.push_str("\\n"),
            '\r' => safe.push_str("\\r"),
            _ => safe.push(c),
        }
    }
    let _ = window.eval(&format!(
        "window.MPT_setStatus && window.MPT_setStatus(\"{safe}\")"
    ));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
                let _ = win.unminimize();
                let _ = win.set_focus();
            }
        }))
        .setup(|app| {
            let handle = app.handle().clone();

            let port = find_free_port()
                .ok_or_else(|| "no free TCP port available in range 8501-8599".to_string())?;

            let child = spawn_backend(&handle, port)?;
            app.manage(Backend {
                child: Mutex::new(Some(child)),
                port,
            });

            // Watchdog: poll the backend health endpoint; on success swap the
            // splash page for the real WebUI. Keep the splash status updated.
            let watchdog = handle.clone();
            std::thread::spawn(move || {
                let started = Instant::now();
                loop {
                    if http_health_ok(watchdog.state::<Backend>().port) {
                        if let Some(win) = watchdog.get_webview_window("main") {
                            set_status(&win, "Servidor listo. Abriendo interfaz...");
                            let _ = win.eval(&format!(
                                "window.location.replace('http://127.0.0.1:{port}/')"
                            ));
                        }
                        break;
                    }
                    if started.elapsed() > Duration::from_secs(HEALTH_TIMEOUT_SECS) {
                        if let Some(win) = watchdog.get_webview_window("main") {
                            set_status(
                                &win,
                                "Error: el servidor local no respondio a tiempo. \
                                 Consulte mpt-desktop-backend.log en la carpeta %TEMP%.",
                            );
                        }
                        break;
                    }
                    let secs = started.elapsed().as_secs();
                    if let Some(win) = watchdog.get_webview_window("main") {
                        set_status(
                            &win,
                            &format!("Inicializando servidor local (puerto {port})... {secs}s"),
                        );
                    }
                    std::thread::sleep(Duration::from_secs(1));
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_backend(app);
            }
        });
}


