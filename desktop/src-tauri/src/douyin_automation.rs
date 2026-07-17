use serde::Serialize;
use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

#[cfg(target_os = "macos")]
use crate::douyin_native_macos;

#[cfg(target_os = "macos")]
use core_foundation::{
    base::TCFType, boolean::CFBoolean, dictionary::CFDictionary, string::CFString,
};
#[cfg(target_os = "macos")]
use core_foundation_sys::{dictionary::CFDictionaryRef, string::CFStringRef};

#[cfg(target_os = "macos")]
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> u8;
    static kAXTrustedCheckOptionPrompt: CFStringRef;
}

const DOUYIN_BUNDLE_ID: &str = "com.bytedance.douyin.desktop";

static SEND_LOCK: Mutex<()> = Mutex::new(());
static CONTACT_CACHE: Mutex<Option<CachedContact>> = Mutex::new(None);

#[derive(Clone)]
struct CachedContact {
    contact_id: String,
    contact_name: String,
}

#[derive(Debug, serde::Deserialize)]
struct WindowBounds {
    #[serde(rename = "X")]
    x: f64,
    #[serde(rename = "Y")]
    y: f64,
    #[serde(rename = "Width")]
    width: f64,
    #[serde(rename = "Height")]
    height: f64,
}

#[derive(Debug, serde::Deserialize)]
struct SearchResultPoint {
    y: f64,
    height: f64,
}

#[derive(Serialize)]
struct DesktopSendResult {
    success: bool,
    message_id: String,
    error: String,
    source: &'static str,
    message_sent: bool,
    contact_name: String,
    contact_id: String,
    reused_conversation: bool,
    pending_portal_sync: bool,
}

#[derive(Clone, Copy)]
struct FlowCoordinates {
    message_icon_x: i64,
    message_icon_y: i64,
    search_x: i64,
    search_y: i64,
    input_x: i64,
    input_y: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ScriptPermissionError {
    Accessibility,
    Automation,
}

fn classify_permission_error(detail: &str) -> Option<ScriptPermissionError> {
    let lower = detail.to_lowercase();
    if lower.contains("not authorized to send apple events") || lower.contains("-1743") {
        return Some(ScriptPermissionError::Automation);
    }
    if detail.contains("不允许辅助访问")
        || lower.contains("not allowed assistive access")
        || lower.contains("-1719")
    {
        return Some(ScriptPermissionError::Accessibility);
    }
    None
}

fn compact_error_detail(detail: &str) -> String {
    let compact = detail.split_whitespace().collect::<Vec<_>>().join(" ");
    compact.chars().take(300).collect()
}

#[cfg(target_os = "macos")]
pub fn request_accessibility_permission_native() -> bool {
    let prompt_key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
    let options = CFDictionary::from_CFType_pairs(&[(prompt_key, CFBoolean::true_value())]);
    unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) != 0 }
}

#[cfg(not(target_os = "macos"))]
pub fn request_accessibility_permission_native() -> bool {
    false
}

fn run_script(language: Option<&str>, script: &str) -> Result<String, String> {
    let mut command = Command::new("/usr/bin/osascript");
    if let Some(language) = language {
        command.args(["-l", language]);
    }
    let mut child = command
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("无法启动 macOS 自动化: {error}"))?;
    child
        .stdin
        .as_mut()
        .ok_or_else(|| "无法写入 macOS 自动化脚本".to_string())?
        .write_all(script.as_bytes())
        .map_err(|error| format!("无法写入 macOS 自动化脚本: {error}"))?;
    let output = child
        .wait_with_output()
        .map_err(|error| format!("macOS 自动化执行失败: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let detail = if stderr.is_empty() { stdout } else { stderr };
        let compact_detail = compact_error_detail(&detail);
        match classify_permission_error(&detail) {
            Some(ScriptPermissionError::Automation) => {
                return Err(format!(
                    "客来来未获得 macOS 自动化权限（System Events）。请在“系统设置 → 隐私与安全性 → 自动化 → 客来来”中打开“System Events”，然后完全退出并重新打开客来来。系统返回：{compact_detail}"
                ));
            }
            Some(ScriptPermissionError::Accessibility) => {
                return Err(format!(
                    "客来来运行时未获得 macOS 辅助功能权限。请在“系统设置 → 隐私与安全性 → 辅助功能”中打开“客来来”，然后完全退出并重新打开客来来。系统返回：{compact_detail}"
                ));
            }
            None => {}
        }
        return Err(format!("抖音桌面自动化失败: {compact_detail}"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn run_applescript(script: &str) -> Result<String, String> {
    run_script(None, script)
}

fn run_jxa(script: &str) -> Result<String, String> {
    run_script(Some("JavaScript"), script)
}

fn escape_applescript(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn raise_main_window() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::raise_main_window();
    }
    #[cfg(not(target_os = "macos"))]
    Err("抖音桌面自动化仅支持 macOS".to_string())
}

fn main_window_bounds() -> Result<WindowBounds, String> {
    #[cfg(target_os = "macos")]
    {
        let bounds = douyin_native_macos::main_window_bounds()?;
        return Ok(WindowBounds {
            x: bounds.x,
            y: bounds.y,
            width: bounds.width,
            height: bounds.height,
        });
    }
    #[cfg(not(target_os = "macos"))]
    Err("抖音桌面自动化仅支持 macOS".to_string())
}

fn coordinates(bounds: &WindowBounds) -> FlowCoordinates {
    FlowCoordinates {
        message_icon_x: (bounds.x + bounds.width * 0.84).round() as i64,
        message_icon_y: (bounds.y + bounds.height * 0.04).round() as i64,
        search_x: (bounds.x + bounds.width * 0.384).round() as i64,
        search_y: (bounds.y + bounds.height * 0.118).round() as i64,
        input_x: (bounds.x + bounds.width * 0.608).round() as i64,
        input_y: (bounds.y + bounds.height * 0.760).round() as i64,
    }
}

const FLOW_HANDLERS: &str = r#"
on focusMessageInput(inputX, inputY)
    tell application "System Events"
        set currentElement to click at {inputX, inputY}
        repeat with stepIndex from 1 to 4
            try
                if role of currentElement is "AXTextArea" then return currentElement
                set currentElement to value of attribute "AXParent" of currentElement
            on error
                exit repeat
            end try
        end repeat
    end tell
    return missing value
end focusMessageInput

on focusSearchField(inputX, inputY)
    tell application "System Events"
        set currentElement to click at {inputX, inputY}
        repeat with stepIndex from 1 to 4
            try
                if role of currentElement is "AXTextField" then return currentElement
                set currentElement to value of attribute "AXParent" of currentElement
            on error
                exit repeat
            end try
        end repeat
    end tell
    return missing value
end focusSearchField

on pasteFromEditMenu()
    tell application "System Events"
        tell process "抖音"
            click menu item "粘贴" of menu 1 of menu bar item "编辑" of menu bar 1
        end tell
    end tell
end pasteFromEditMenu

on clearFocusedField()
    tell application "System Events"
        tell process "抖音"
            click menu item "全选" of menu 1 of menu bar item "编辑" of menu bar 1
            key code 51
        end tell
    end tell
end clearFocusedField
"#;

fn ensure_message_panel(point: FlowCoordinates) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::ensure_message_panel(
            point.input_x as f64,
            point.input_y as f64,
            point.message_icon_x as f64,
            point.message_icon_y as f64,
        );
    }
    #[cfg(not(target_os = "macos"))]
    Err("抖音桌面自动化仅支持 macOS".to_string())
}

fn open_contact_from_search(contact_name: &str, point: FlowCoordinates) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::open_contact_from_search(
            contact_name,
            point.search_x as f64,
            point.search_y as f64,
        );
    }
    #[cfg(not(target_os = "macos"))]
    Err("抖音桌面自动化仅支持 macOS".to_string())
}

fn click_matching_search_result(contact_name: &str, bounds: &WindowBounds) -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::click_matching_search_result(
            contact_name,
            douyin_native_macos::NativeWindowBounds {
                x: bounds.x,
                y: bounds.y,
                width: bounds.width,
                height: bounds.height,
            },
        );
    }
    let target = serde_json::to_string(contact_name).map_err(|error| error.to_string())?;
    let template = r#"
ObjC.import('ApplicationServices')
ObjC.import('AppKit')
const target = normalize(__TARGET__)
const running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('com.bytedance.douyin.desktop')
if (Number(running.count) < 1) throw new Error('未找到抖音桌面端进程')
const app = $.AXUIElementCreateApplication(Number(running.objectAtIndex(0).processIdentifier))
function attribute(element, name) {
  const ref = Ref()
  const error = $.AXUIElementCopyAttributeValue(element, $(name), ref)
  if (Number(error) !== 0) return null
  return ref[0]
}
function objectValue(rawValue) { return rawValue ? ObjC.castRefToObject(rawValue) : null }
function stringValue(rawValue) {
  if (!rawValue) return ''
  try { return String(ObjC.unwrap(objectValue(rawValue)) || '') } catch (_) { return '' }
}
function normalize(value) { return String(value || '').replace(/\s+/g, ' ').trim() }
function rectValue(element) {
  const position = objectValue(attribute(element, 'AXPosition'))
  if (!position) return null
  const positionText = String(position.description.js || '')
  const positionMatch = positionText.match(/x:([\d.-]+)\s+y:([\d.-]+)/)
  if (!positionMatch) return null
  const size = objectValue(attribute(element, 'AXSize'))
  const sizeText = size ? String(size.description.js || '') : ''
  const sizeMatch = sizeText.match(/w:([\d.-]+)\s+h:([\d.-]+)/)
  return {
    x: Number(positionMatch[1]),
    y: Number(positionMatch[2]),
    width: sizeMatch ? Number(sizeMatch[1]) : 0,
    height: sizeMatch ? Number(sizeMatch[2]) : 0,
  }
}
const windowsRaw = attribute(app, 'AXWindows')
if (!windowsRaw) throw new Error('无法读取抖音窗口')
const windows = objectValue(windowsRaw)
let mainWindow = null
for (let index = 0; index < Number(windows.count); index++) {
  const candidate = windows.objectAtIndex(index)
  if (stringValue(attribute(candidate, 'AXTitle')) === '抖音') { mainWindow = candidate; break }
}
if (!mainWindow) throw new Error('未找到抖音主窗口')
const stack = [mainWindow]
let selected = null
let inspected = 0
while (stack.length && inspected < 10000 && !selected) {
  const element = stack.pop()
  inspected++
  const role = stringValue(attribute(element, 'AXRole'))
  if (role === 'AXStaticText') {
    const value = normalize(stringValue(attribute(element, 'AXValue')))
    const title = normalize(stringValue(attribute(element, 'AXTitle')))
    const exactName = value === target || title === target
    const rowWithMetadata = value.startsWith(target + ' ')
    if (exactName || rowWithMetadata) {
      const rect = rectValue(element)
      if (rect) {
        const centerX = rect.x + Math.max(rect.width / 2, 8)
        const centerY = rect.y + Math.max(rect.height / 2, 8)
        if (
          centerX >= __MIN_X__ && centerX <= __MAX_X__ &&
          centerY >= __MIN_Y__ && centerY <= __MAX_Y__
        ) selected = rect
      }
    }
  }
  const childrenRaw = attribute(element, 'AXChildren')
  if (childrenRaw) {
    const children = objectValue(childrenRaw)
    for (let index = 0; index < Number(children.count); index++) stack.push(children.objectAtIndex(index))
  }
}
JSON.stringify(selected)
"#;
    let script = template
        .replace("__TARGET__", &target)
        .replace("__MIN_X__", &(bounds.x + bounds.width * 0.28).to_string())
        .replace("__MAX_X__", &(bounds.x + bounds.width * 0.55).to_string())
        .replace("__MIN_Y__", &(bounds.y + bounds.height * 0.10).to_string())
        .replace("__MAX_Y__", &(bounds.y + bounds.height * 0.82).to_string());
    let raw = run_jxa(&script)?;
    if raw.trim().is_empty() || raw.trim() == "null" {
        return Ok(false);
    }
    let point: SearchResultPoint = serde_json::from_str(&raw)
        .map_err(|error| format!("无法读取抖音联系人搜索结果位置: {error}"))?;
    // 回车后抖音显示“联系人 / 发消息”结果页。点联系人文字不会进入会话，
    // 必须点同一行右侧的“发消息”按钮。名称匹配只用来锁定正确行的纵坐标。
    let click_x = (bounds.x + bounds.width * 0.477).round() as i64;
    let click_y = (point.y + (point.height / 2.0).max(8.0)).round() as i64;
    let click_script = format!(
        "tell application \"System Events\" to click at {{{click_x}, {click_y}}}\ndelay 1.2\nreturn \"clicked\""
    );
    run_applescript(&click_script)?;
    Ok(true)
}

fn current_conversation_matches(contact_name: &str, bounds: &WindowBounds) -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::current_conversation_matches(
            contact_name,
            douyin_native_macos::NativeWindowBounds {
                x: bounds.x,
                y: bounds.y,
                width: bounds.width,
                height: bounds.height,
            },
        );
    }
    let target = serde_json::to_string(contact_name).map_err(|error| error.to_string())?;
    let template = r#"
ObjC.import('ApplicationServices')
ObjC.import('AppKit')
const target = __TARGET__
const running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('com.bytedance.douyin.desktop')
if (Number(running.count) < 1) throw new Error('未找到抖音桌面端进程')
const app = $.AXUIElementCreateApplication(Number(running.objectAtIndex(0).processIdentifier))
function attribute(element, name) {
  const ref = Ref()
  const error = $.AXUIElementCopyAttributeValue(element, $(name), ref)
  if (Number(error) !== 0) return null
  return ref[0]
}
function objectValue(rawValue) { return rawValue ? ObjC.castRefToObject(rawValue) : null }
function stringValue(rawValue) {
  if (!rawValue) return ''
  try { return String(ObjC.unwrap(objectValue(rawValue)) || '') } catch (_) { return '' }
}
const windowsRaw = attribute(app, 'AXWindows')
if (!windowsRaw) throw new Error('无法读取抖音窗口')
const windows = objectValue(windowsRaw)
let mainWindow = null
for (let index = 0; index < Number(windows.count); index++) {
  const candidate = windows.objectAtIndex(index)
  if (stringValue(attribute(candidate, 'AXTitle')) === '抖音') { mainWindow = candidate; break }
}
if (!mainWindow) throw new Error('未找到抖音主窗口')
const stack = [mainWindow]
let matched = false
let inspected = 0
while (stack.length && inspected < 10000 && !matched) {
  const element = stack.pop()
  inspected++
  const role = stringValue(attribute(element, 'AXRole'))
  const value = stringValue(attribute(element, 'AXValue'))
  if (role === 'AXStaticText' && value === target) {
    const position = objectValue(attribute(element, 'AXPosition'))
    const description = position ? String(position.description.js || '') : ''
    const match = description.match(/x:([\d.-]+)\s+y:([\d.-]+)/)
    if (match) {
      const x = Number(match[1]); const y = Number(match[2])
      matched = x >= __MIN_X__ && x <= __MAX_X__ && y >= __MIN_Y__ && y <= __MAX_Y__
    }
  }
  const childrenRaw = attribute(element, 'AXChildren')
  if (childrenRaw) {
    const children = objectValue(childrenRaw)
    for (let index = 0; index < Number(children.count); index++) stack.push(children.objectAtIndex(index))
  }
}
matched ? 'true' : 'false'
"#;
    let script = template
        .replace("__TARGET__", &target)
        .replace("__MIN_X__", &(bounds.x + bounds.width * 0.52).to_string())
        .replace("__MAX_X__", &(bounds.x + bounds.width * 0.92).to_string())
        .replace("__MIN_Y__", &(bounds.y + bounds.height * 0.04).to_string())
        .replace("__MAX_Y__", &(bounds.y + bounds.height * 0.20).to_string());
    Ok(run_jxa(&script)?.trim().eq_ignore_ascii_case("true"))
}

fn fill_and_send(content: &str, point: FlowCoordinates) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return douyin_native_macos::fill_and_send(
            content,
            point.input_x as f64,
            point.input_y as f64,
        );
    }
    let script = format!(
        "{FLOW_HANDLERS}\nset messageText to \"{}\"\nset oldClipboard to missing value\ntry\n    set oldClipboard to the clipboard as text\nend try\ntry\n    set messageInput to my focusMessageInput({}, {})\n    if messageInput is missing value then error \"未找到抖音消息输入框，请确认已登录并打开消息能力\"\n    tell application \"System Events\" to click messageInput\n    my clearFocusedField()\n    set the clipboard to messageText\n    my pasteFromEditMenu()\n    delay 0.3\n    tell application \"System Events\"\n        tell process \"抖音\" to key code 36\n    end tell\n    delay 0.5\n    try\n        tell application \"System Events\" to set remainingText to value of attribute \"AXValue\" of messageInput as text\n        if remainingText contains messageText then error \"回车后输入框未清空，消息可能没有发送\"\n    end try\non error errMsg number errNum\n    if oldClipboard is not missing value then set the clipboard to oldClipboard\n    error errMsg number errNum\nend try\nif oldClipboard is not missing value then set the clipboard to oldClipboard\nreturn \"sent\"",
        escape_applescript(content),
        point.input_x,
        point.input_y,
    );
    run_applescript(&script).map(|_| ())
}

fn execute_send(contact_name: &str, contact_id: &str, content: &str) -> Result<Value, String> {
    let _guard = SEND_LOCK
        .lock()
        .map_err(|_| "抖音桌面发送锁异常".to_string())?;
    let reuse_cached = CONTACT_CACHE
        .lock()
        .ok()
        .and_then(|cache| cache.clone())
        .is_some_and(|cache| {
            cache.contact_name == contact_name
                && (contact_id.is_empty()
                    || cache.contact_id.is_empty()
                    || cache.contact_id == contact_id)
        });

    raise_main_window()?;
    let bounds = main_window_bounds()?;
    let point = coordinates(&bounds);
    ensure_message_panel(point)?;

    let mut reused = false;
    if reuse_cached {
        reused = current_conversation_matches(contact_name, &bounds).unwrap_or(false);
    }
    if !reused {
        open_contact_from_search(contact_name, point)?;
        let mut matched = false;
        for attempt in 0..2 {
            matched = current_conversation_matches(contact_name, &bounds).unwrap_or(false);
            if matched {
                break;
            }
            if attempt < 1 {
                thread::sleep(Duration::from_millis(400));
            }
        }
        if !matched && click_matching_search_result(contact_name, &bounds)? {
            for attempt in 0..3 {
                matched = current_conversation_matches(contact_name, &bounds).unwrap_or(false);
                if matched {
                    break;
                }
                if attempt < 2 {
                    thread::sleep(Duration::from_millis(400));
                }
            }
        }
        if !matched {
            return Err(format!(
                "搜索结果中未选中目标联系人: {contact_name}，已取消发送"
            ));
        }
    }

    fill_and_send(content, point)?;
    if let Ok(mut cache) = CONTACT_CACHE.lock() {
        *cache = Some(CachedContact {
            contact_id: contact_id.to_string(),
            contact_name: contact_name.to_string(),
        });
    }
    serde_json::to_value(DesktopSendResult {
        success: true,
        message_id: String::new(),
        error: String::new(),
        source: "douyin_desktop_automation",
        message_sent: true,
        contact_name: contact_name.to_string(),
        contact_id: contact_id.to_string(),
        reused_conversation: reused,
        pending_portal_sync: true,
    })
    .map_err(|error| error.to_string())
}

fn restore_kellai_window() {
    let _ = Command::new("/usr/bin/open")
        .args(["-b", "com.kellai.desktop"])
        .output();
}

#[tauri::command]
pub async fn douyin_desktop_send(
    contact_name: String,
    contact_id: String,
    content: String,
) -> Result<Value, String> {
    let contact_name = contact_name.trim().to_string();
    let contact_id = contact_id.trim().to_string();
    let content = content.trim().to_string();
    if contact_name.is_empty() {
        return Err("缺少抖音联系人名称".to_string());
    }
    if content.is_empty() {
        return Err("消息内容为空".to_string());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let result = execute_send(&contact_name, &contact_id, &content);
        restore_kellai_window();
        result
    })
    .await
    .map_err(|error| format!("抖音桌面发送任务失败: {error}"))?
}

#[tauri::command]
pub fn open_accessibility_settings() -> Result<(), String> {
    Command::new("/usr/bin/open")
        .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        .status()
        .map_err(|error| format!("无法打开辅助功能设置: {error}"))?
        .success()
        .then_some(())
        .ok_or_else(|| "无法打开辅助功能设置".to_string())
}

#[tauri::command]
pub fn request_accessibility_permission() -> bool {
    request_accessibility_permission_native()
}

#[cfg(test)]
mod tests {
    use super::{classify_permission_error, compact_error_detail, ScriptPermissionError};

    #[test]
    fn classifies_accessibility_denial() {
        assert_eq!(
            classify_permission_error(
                "execution error: System Events got an error: osascript is not allowed assistive access. (-1719)"
            ),
            Some(ScriptPermissionError::Accessibility)
        );
    }

    #[test]
    fn classifies_automation_denial_before_other_errors() {
        assert_eq!(
            classify_permission_error(
                "Not authorized to send Apple events to System Events. (-1743)"
            ),
            Some(ScriptPermissionError::Automation)
        );
    }

    #[test]
    fn compacts_and_limits_error_detail() {
        let raw = format!("first\n  second {}", "x".repeat(400));
        let compact = compact_error_detail(&raw);
        assert!(compact.starts_with("first second "));
        assert_eq!(compact.chars().count(), 300);
    }
}
