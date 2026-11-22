use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;


const BACKEND_PORT: u16 = 8793;

pub fn build_info_json() -> &'static str {
    include_str!(concat!(env!("OUT_DIR"), "/kellai-build-info.json"))
}

#[derive(Default)]
struct BackendProcess(Mutex<Option<Child>>);

fn backend_is_healthy() -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    if stream.take(64 * 1024).read_to_string(&mut response).is_err()
        || !response.starts_with("HTTP/1.1 200")
    {
        return false;
    }
    let Some((_, body)) = response.split_once("\r\n\r\n") else { return false; };
    let Ok(health) = serde_json::from_str::<serde_json::Value>(body) else { return false; };
    let Ok(expected) = serde_json::from_str::<serde_json::Value>(build_info_json()) else { return false; };
    health["service"] == "kellai-account-tool" && health["protocol_version"] == 2
        && (expected["source_sha"].is_null() || health["build_info"] == expected)
}

fn start_bundled_backend(app: &tauri::AppHandle) -> Result<(), String> {
    if backend_is_healthy() {
        return Ok(());
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("无法定位应用资源目录：{error}"))?;
    let binary_name = if cfg!(target_os = "windows") { "backend/kellai-backend.exe" } else { "backend/kellai-backend" };
    let backend_binary = resource_dir.join(binary_name);
    if !backend_binary.is_file() {
        return Err(format!(
            "发布包缺少本地服务：{}",
            backend_binary.display()
        ));
    }

    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("无法定位应用数据目录：{error}"))?;
    let data_dir = app_data_dir.join("data");
    let log_dir = app_data_dir.join("logs");
    fs::create_dir_all(&data_dir).map_err(|error| format!("无法创建数据目录：{error}"))?;
    fs::create_dir_all(&log_dir).map_err(|error| format!("无法创建日志目录：{error}"))?;

    let log_path = log_dir.join("backend.log");
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("无法创建本地服务日志：{error}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|error| format!("无法初始化本地服务日志：{error}"))?;

    let mut child = Command::new(&backend_binary)
        .env("KELLAI_DATA_DIR", &data_dir)
        .env("KELLAI_PORT", BACKEND_PORT.to_string())
        .env("KELLAI_PARENT_PID", std::process::id().to_string())
        .env("KELLAI_LOG_LEVEL", "INFO")
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|error| format!("本地服务启动失败：{error}"))?;

    for _ in 0..80 {
        if backend_is_healthy() {
            app.state::<BackendProcess>()
                .0
                .lock()
                .map_err(|_| "本地服务状态锁异常".to_string())?
                .replace(child);
            return Ok(());
        }
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("无法读取本地服务状态：{error}"))?
        {
            return Err(format!(
                "本地服务提前退出（{status}），日志：{}",
                log_path.display()
            ));
        }
        thread::sleep(Duration::from_millis(125));
    }

    let _ = child.kill();
    let _ = child.wait();
    Err(format!(
        "本地服务启动超时，日志：{}",
        log_path.display()
    ))
}

fn stop_bundled_backend(app: &tauri::AppHandle) {
    if let Ok(mut process) = app.state::<BackendProcess>().0.lock() {
        if let Some(mut child) = process.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[tauri::command]
fn open_xcmax_desktop(app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_url("xcagi://data-sources", None::<&str>)
        .map_err(|_| "无法打开 XCMAX，请先安装并启动桌面端。".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .manage(BackendProcess::default())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                app.deep_link().register_all()?;
            }
            start_bundled_backend(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_xcmax_desktop,
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            stop_bundled_backend(app_handle);
        }
    });
}
