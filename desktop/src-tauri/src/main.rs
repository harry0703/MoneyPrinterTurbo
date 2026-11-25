#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use std::{
    fs::{self, OpenOptions},
    io::{self, BufRead, BufReader, Write},
    net::{Ipv4Addr, SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

#[cfg(windows)]
mod windows;

use base64::{engine::general_purpose::STANDARD, Engine};
use tauri::{
    webview::NewWindowResponse, Manager, RunEvent, Url, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, WindowEvent,
};

struct Backend {
    process: Child,
    session: tempfile::TempDir,
    #[cfg(windows)]
    _job: std::os::windows::io::OwnedHandle,
}

impl Backend {
    fn start(resources: &Path, data: &Path, storage: &Path, log_path: &Path) -> io::Result<Self> {
        fs::create_dir_all(data)?;
        fs::create_dir_all(log_path.parent().expect("backend log parent"))?;
        let session = tempfile::Builder::new().prefix("mpt-desktop-").tempdir()?;
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_path)?;
        #[cfg(windows)]
        let interpreter = resources.join("python/python.exe");
        #[cfg(unix)]
        let interpreter = resources.join("python/bin/python3.11");
        let mut command = Command::new(interpreter);
        command
            .args(["-I", "-B", "-u", "-X", "utf8"])
            .arg(resources.join("backend.py"))
            .arg(session.path().join("port"))
            .current_dir(data)
            .env("MPT_HOME", data)
            .env("MPT_DESKTOP_STORAGE_DEFAULT", storage)
            .stdout(log.try_clone()?)
            .stderr(log);
        #[cfg(unix)]
        command.stdin(Stdio::piped()).process_group(0);
        #[cfg(windows)]
        windows::hide_console(command.stdin(Stdio::null()));
        let process = command.spawn()?;
        #[cfg(windows)]
        let (process, _job) = windows::track_backend(process)?;
        Ok(Self {
            process,
            session,
            #[cfg(windows)]
            _job,
        })
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        // 通知后端退出，并给 Streamlit 一点时间写完任务状态。
        #[cfg(unix)]
        self.process.stdin.take();
        #[cfg(windows)]
        let _ = fs::write(self.session.path().join("shutdown"), []);
        for _ in 0..20 {
            if matches!(self.process.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(50));
        }
        // 后端无法正常退出时，收掉我们启动的整个进程组。
        #[cfg(unix)]
        unsafe {
            libc::killpg(self.process.id() as libc::pid_t, libc::SIGKILL)
        };
        #[cfg(windows)]
        let _ = self.process.kill();
        let _ = self.process.wait();
    }
}

type BackendState = Arc<Mutex<Option<Backend>>>;

fn wait_for_port(backend: &BackendState) -> io::Result<u16> {
    let deadline = Instant::now() + Duration::from_secs(45);
    while Instant::now() < deadline {
        let port = {
            let mut state = backend.lock().expect("backend lock");
            let Some(backend) = state.as_mut() else {
                return Err(io::Error::other("后端已停止"));
            };
            if let Some(status) = backend.process.try_wait()? {
                return Err(io::Error::other(format!("后端提前退出（{status}）")));
            }
            fs::read_to_string(backend.session.path().join("port"))
                .ok()
                .and_then(|value| value.trim().parse::<u16>().ok())
        };
        if let Some(port) = port.filter(|port| responds_to_health_check(*port)) {
            return Ok(port);
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err(io::Error::new(io::ErrorKind::TimedOut, "后端启动超时"))
}

fn responds_to_health_check(port: u16) -> bool {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let timeout = Duration::from_millis(200);
    let result = (|| -> io::Result<bool> {
        let mut stream = TcpStream::connect_timeout(&address, timeout)?;
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))?;
        write!(
            stream,
            "GET /_stcore/health HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
        )?;
        let mut status = String::new();
        BufReader::new(stream).read_line(&mut status)?;
        Ok(status.split_ascii_whitespace().nth(1) == Some("200"))
    })();
    result.unwrap_or(false)
}

fn open_system_browser(url: &Url) {
    if matches!(url.scheme(), "http" | "https") {
        let url = url.to_string();
        thread::spawn(move || {
            #[cfg(unix)]
            let _ = Command::new("/usr/bin/open").arg(url).status();
            #[cfg(windows)]
            windows::open_system_browser(&url);
        });
    }
}

fn show_startup_error(window: &WebviewWindow, log_path: &Path, error: &str) {
    let message = format!("启动失败。{error}。日志位于 {}", log_path.display());
    if let Ok(message) = serde_json::to_string(&message) {
        let _ = window.eval(format!(
            "document.querySelector('main').setAttribute('data-startup-error', '');
             document.getElementById('status').textContent = {message};
             document.getElementById('status-en').textContent = 'Startup failed. See the log for details.';"
        ));
    }
}

fn startup_script() -> String {
    let icon = STANDARD.encode(include_bytes!("../../ui/icon.png"));
    let assets = serde_json::json!({
        "page": include_str!("../../ui/index.html"),
        "style": include_str!("../../ui/style.css"),
        "icon": format!("data:image/png;base64,{icon}"),
    });
    format!("({})({assets});", include_str!("../../ui/startup.js"))
}

fn main() {
    let backend: BackendState = Arc::default();
    let backend_for_setup = backend.clone();
    let app = tauri::Builder::default()
        .setup(move |app| {
            let resources = app.path().resource_dir()?;
            let log_path = app.path().app_log_dir()?.join("backend.log");
            let data = std::env::var_os("MPT_HOME")
                .map(PathBuf::from)
                .filter(|path| path.is_absolute())
                .unwrap_or(app.path().app_data_dir()?);
            let documents = app
                .path()
                .document_dir()
                .or_else(|_| app.path().home_dir().map(|home| home.join("Documents")))?;
            let storage = documents.join("MoneyPrinterTurbo").join("storage");
            let local_url: Arc<OnceLock<Url>> = Arc::default();
            let allowed_url = local_url.clone();
            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("MoneyPrinterTurbo")
                    .inner_size(1360.0, 930.0)
                    .min_inner_size(920.0, 660.0)
                    .prevent_overflow()
                    .center()
                    .initialization_script(startup_script())
                    .on_navigation(move |url| {
                        if matches!(
                            (url.scheme(), url.host_str()),
                            ("tauri", Some("localhost")) | ("http", Some("tauri.localhost"))
                        ) {
                            return true;
                        }
                        if allowed_url
                            .get()
                            .is_some_and(|local| url.origin() == local.origin())
                        {
                            return true;
                        }
                        open_system_browser(url);
                        false
                    })
                    .on_new_window(|url, _| {
                        open_system_browser(&url);
                        NewWindowResponse::Deny
                    })
                    .build()?;
            #[cfg(windows)]
            windows::install_dpi_icons(&window);
            let backend = backend_for_setup.clone();
            thread::spawn(move || {
                let start = || -> Result<(), Box<dyn std::error::Error>> {
                    let process = Backend::start(&resources, &data, &storage, &log_path)?;
                    *backend.lock().expect("backend lock") = Some(process);
                    let port = wait_for_port(&backend)?;
                    let url: Url = format!("http://127.0.0.1:{port}/").parse()?;
                    let _ = local_url.set(url.clone());
                    window.navigate(url)?;
                    Ok(())
                };
                if let Err(error) = start() {
                    backend.lock().expect("backend lock").take();
                    show_startup_error(&window, &log_path, &error.to_string());
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            match event {
                #[cfg(target_os = "macos")]
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    // 保留 WebView 会话和后端，用户可从程序坞重新打开窗口。
                    let _ = window.hide();
                }
                #[cfg(windows)]
                WindowEvent::CloseRequested { api, .. } => {
                    if !windows::confirm_exit(window) {
                        api.prevent_close();
                    }
                }
                #[cfg(not(target_os = "macos"))]
                WindowEvent::Destroyed => window.app_handle().exit(0),
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("unable to build desktop application");

    app.run(move |_app, event| match event {
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => {
            if let Some(window) = _app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        RunEvent::Exit => {
            backend.lock().expect("backend lock").take();
        }
        _ => {}
    });
}
