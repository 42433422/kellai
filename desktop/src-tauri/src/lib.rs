use std::process::Command;

mod douyin_automation;
#[cfg(target_os = "macos")]
mod douyin_native_macos;

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
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|_app| {
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
