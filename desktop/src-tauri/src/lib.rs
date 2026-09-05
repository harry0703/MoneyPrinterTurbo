// 影创AI 桌面壳：负责拉起打包后的 Python 后端，等待服务就绪后加载 WebUI。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WindowEvent};

/// 托管后端子进程，便于窗口关闭时回收。
struct BackendProcess(Mutex<Option<Child>>);

/// WebUI 地址（Streamlit 固定绑定 127.0.0.1，避免 0.0.0.0 访问问题）。
const READY_URL: &str = "http://127.0.0.1:8501";
const HEALTH_PATH: &str = "/_stcore/health";

/// 解析打包后的后端所在目录：<bundle>/Contents/Resources/backend-<ARCH>/。
fn resource_backend_dir() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|p| p.to_path_buf()))
        .and_then(|exe_dir| {
            // macOS 的 .app 中，可执行文件在 Contents/MacOS，资源在 Contents/Resources
            exe_dir
                .parent()
                .map(|p| p.join("Resources"))
                .map(|r| r.join(format!("backend-{}", std::env::consts::ARCH)))
        })
}

/// 定位后端启动器：优先用环境变量 MPT_BACKEND 覆盖（开发/CI 用），
/// 否则在打包目录下找 PyInstaller 生成的 mpt-backend 启动器。
fn find_backend() -> PathBuf {
    if let Ok(p) = std::env::var("MPT_BACKEND") {
        let p = PathBuf::from(p);
        if p.exists() {
            return p;
        }
    }
    if let Some(dir) = resource_backend_dir() {
        let candidate = dir.join("mpt-backend");
        if candidate.exists() {
            return candidate;
        }
        if dir.exists() {
            return dir;
        }
    }
    PathBuf::from("mpt-backend")
}

/// 轮询 Streamlit 健康检查端点，直到就绪或超时。
fn wait_ready(timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if let Ok(mut stream) = TcpStream::connect("127.0.0.1:8501") {
            let req = format!(
                "GET {} HTTP/1.1\r\nHost: 127.0.0.1:8501\r\nConnection: close\r\n\r\n",
                HEALTH_PATH
            );
            let _ = stream.write_all(req.as_bytes());
            let mut buf = [0u8; 256];
            if let Ok(n) = stream.read(&mut buf) {
                let resp = String::from_utf8_lossy(&buf[..n]);
                if resp.contains(" 200") || resp.contains("200 OK") {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let backend_path = find_backend();
            eprintln!("[影创AI] launching backend: {}", backend_path.display());

            let child = Command::new(&backend_path).spawn().expect(
                "failed to launch backend process; set MPT_BACKEND to the bundled launcher path",
            );
            *app.state::<BackendProcess>().0.lock().unwrap() = Some(child);

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_ready(Duration::from_secs(120)) {
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.eval(&format!("window.location.replace('{READY_URL}')"));
                    }
                } else {
                    eprintln!("[影创AI] backend did not become ready in time");
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.eval(
                            "document.body.innerHTML = '<div style=\"font-family:sans-serif;display:flex;height:100vh;align-items:center;justify-content:center;color:#eaeaea;background:#1c1c1e;\">启动本地服务失败，请查看日志。</div>';",
                        );
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::Destroyed = event {
                if let Some(mut child) = window
                    .state::<BackendProcess>()
                    .0
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
