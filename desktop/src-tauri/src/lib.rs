use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;

mod douyin_automation;
#[cfg(target_os = "macos")]
mod douyin_native_macos;

const BACKEND_PORT: u16 = 8793;

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
    stream.read_to_string(&mut response).is_ok()
        && response.starts_with("HTTP/1.1 200")
        && response.contains("\"product\":\"客来来\"")
}

fn start_bundled_backend(app: &tauri::AppHandle) -> Result<(), String> {
    if backend_is_healthy() {
        return Ok(());
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("无法定位应用资源目录：{error}"))?;
    let backend_binary = resource_dir.join("backend/kellai-backend");
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
        .env("KELLAI_STRICT_AUTH", "1")
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
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to 客来来!", name)
}

#[tauri::command]
fn open_xcmax_desktop() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let bundle_ids = ["com.xcagi.desktop.enterprise", "com.xcagi.desktop.personal"];
        for bundle_id in bundle_ids {
            let opened = Command::new("open")
                .args(["-b", bundle_id])
                .status()
                .map(|status| status.success())
                .unwrap_or(false);
            if opened {
                return Ok(());
            }
        }
        return Err("未检测到 XCMAX 桌面端，请先安装并打开一次 XCAGI。".to_string());
    }

    #[cfg(not(target_os = "macos"))]
    {
        Err("当前系统暂未配置 XCMAX 桌面端唤起。".to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendProcess::default())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            start_bundled_backend(app.handle())?;
            #[cfg(target_os = "macos")]
            {
                douyin_automation::request_accessibility_permission_native();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            greet,
            open_xcmax_desktop,
            douyin_automation::douyin_desktop_send,
            douyin_automation::open_accessibility_settings,
            douyin_automation::request_accessibility_permission,
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
