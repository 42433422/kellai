use core_foundation::{base::TCFType, boolean::CFBoolean, string::CFString};
use core_foundation_sys::{
    array::{CFArrayGetCount, CFArrayGetTypeID, CFArrayGetValueAtIndex, CFArrayRef},
    base::{CFGetTypeID, CFRelease, CFRetain, CFTypeRef},
    string::{CFStringGetTypeID, CFStringRef},
};
use std::ffi::c_void;
use std::io::Write;
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

type AXUIElementRef = *const c_void;
type AXError = i32;

const AX_SUCCESS: AXError = 0;
const AX_NOT_AUTHORIZED: AXError = -25211;
const AX_VALUE_CG_POINT: isize = 1;
const AX_VALUE_CG_SIZE: isize = 2;

const CG_EVENT_LEFT_MOUSE_DOWN: u32 = 1;
const CG_EVENT_LEFT_MOUSE_UP: u32 = 2;
const CG_EVENT_MOUSE_MOVED: u32 = 5;
const CG_EVENT_TAP_HID: u32 = 0;
const CG_MOUSE_BUTTON_LEFT: u32 = 0;
const CG_EVENT_FLAG_COMMAND: u64 = 1 << 20;

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct CGSize {
    width: f64,
    height: f64,
}

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> AXError;
    fn AXUIElementSetAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: CFTypeRef,
    ) -> AXError;
    fn AXUIElementCopyElementAtPosition(
        application: AXUIElementRef,
        x: f32,
        y: f32,
        element: *mut AXUIElementRef,
    ) -> AXError;
    fn AXValueGetValue(value: CFTypeRef, value_type: isize, value_ptr: *mut c_void) -> u8;
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventCreateMouseEvent(
        source: *const c_void,
        mouse_type: u32,
        mouse_cursor_position: CGPoint,
        mouse_button: u32,
    ) -> CFTypeRef;
    fn CGEventCreateKeyboardEvent(
        source: *const c_void,
        virtual_key: u16,
        key_down: u8,
    ) -> CFTypeRef;
    fn CGEventSetFlags(event: CFTypeRef, flags: u64);
    fn CGEventPost(tap: u32, event: CFTypeRef);
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct NativeWindowBounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Clone, Copy, Debug)]
struct Rect {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

struct OwnedAX(AXUIElementRef);

impl Drop for OwnedAX {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { CFRelease(self.0 as CFTypeRef) };
        }
    }
}

fn ax_error(context: &str, code: AXError) -> String {
    if code == AX_NOT_AUTHORIZED {
        format!(
            "客来来进程尚未获得 macOS 辅助功能权限（系统错误 {code}）。请在“系统设置 → 隐私与安全性 → 辅助功能”中打开“客来来”并完全重启应用。"
        )
    } else {
        format!("{context}（macOS 错误 {code}）")
    }
}

fn douyin_pid() -> Result<i32, String> {
    let output = Command::new("/usr/bin/pgrep")
        .args(["-x", "抖音"])
        .output()
        .map_err(|error| format!("无法查找抖音桌面端进程: {error}"))?;
    let raw = String::from_utf8_lossy(&output.stdout);
    raw.lines()
        .find_map(|line| line.trim().parse::<i32>().ok())
        .ok_or_else(|| "未找到抖音桌面端进程，请先打开并登录抖音".to_string())
}

fn douyin_app() -> Result<OwnedAX, String> {
    let pid = douyin_pid()?;
    let element = unsafe { AXUIElementCreateApplication(pid) };
    if element.is_null() {
        Err("无法连接抖音桌面端的辅助功能界面".to_string())
    } else {
        Ok(OwnedAX(element))
    }
}

fn copy_attribute(element: AXUIElementRef, name: &str) -> Result<CFTypeRef, AXError> {
    let name = CFString::new(name);
    let mut value: CFTypeRef = std::ptr::null();
    let code =
        unsafe { AXUIElementCopyAttributeValue(element, name.as_concrete_TypeRef(), &mut value) };
    if code == AX_SUCCESS && !value.is_null() {
        Ok(value)
    } else {
        Err(code)
    }
}

fn attribute_string(element: AXUIElementRef, name: &str) -> Option<String> {
    let raw = copy_attribute(element, name).ok()?;
    if unsafe { CFGetTypeID(raw) } != unsafe { CFStringGetTypeID() } {
        unsafe { CFRelease(raw) };
        return None;
    }
    let value = unsafe { CFString::wrap_under_create_rule(raw as CFStringRef) };
    Some(value.to_string())
}

fn attribute_point(element: AXUIElementRef, name: &str, value_type: isize) -> Option<CGPoint> {
    let raw = copy_attribute(element, name).ok()?;
    let mut value = CGPoint::default();
    let success =
        unsafe { AXValueGetValue(raw, value_type, &mut value as *mut CGPoint as *mut c_void) } != 0;
    unsafe { CFRelease(raw) };
    success.then_some(value)
}

fn attribute_size(element: AXUIElementRef) -> Option<CGSize> {
    let raw = copy_attribute(element, "AXSize").ok()?;
    let mut value = CGSize::default();
    let success = unsafe {
        AXValueGetValue(
            raw,
            AX_VALUE_CG_SIZE,
            &mut value as *mut CGSize as *mut c_void,
        )
    } != 0;
    unsafe { CFRelease(raw) };
    success.then_some(value)
}

fn element_rect(element: AXUIElementRef) -> Option<Rect> {
    let position = attribute_point(element, "AXPosition", AX_VALUE_CG_POINT)?;
    let size = attribute_size(element).unwrap_or_default();
    Some(Rect {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    })
}

fn main_window() -> Result<OwnedAX, String> {
    let app = douyin_app()?;
    let raw = copy_attribute(app.0, "AXWindows")
        .map_err(|code| ax_error("无法读取抖音窗口列表", code))?;
    if unsafe { CFGetTypeID(raw) } != unsafe { CFArrayGetTypeID() } {
        unsafe { CFRelease(raw) };
        return Err("抖音窗口列表格式异常".to_string());
    }

    let array = raw as CFArrayRef;
    let count = unsafe { CFArrayGetCount(array) };
    let mut selected: AXUIElementRef = std::ptr::null();
    let mut selected_area = 0.0;
    for index in 0..count {
        let candidate = unsafe { CFArrayGetValueAtIndex(array, index) } as AXUIElementRef;
        if candidate.is_null() {
            continue;
        }
        let size = attribute_size(candidate).unwrap_or_default();
        let area = size.width * size.height;
        let title = attribute_string(candidate, "AXTitle").unwrap_or_default();
        if size.width >= 700.0 && (title == "抖音" || area > selected_area) {
            selected = candidate;
            selected_area = area;
            if title == "抖音" {
                break;
            }
        }
    }
    let selected = if selected.is_null() {
        None
    } else {
        Some(unsafe { CFRetain(selected as CFTypeRef) } as AXUIElementRef)
    };
    unsafe { CFRelease(raw) };
    selected
        .map(OwnedAX)
        .ok_or_else(|| "未找到抖音主窗口".to_string())
}

pub(crate) fn raise_main_window() -> Result<(), String> {
    let _ = Command::new("/usr/bin/open")
        .args(["-b", "com.bytedance.douyin.desktop"])
        .output();
    thread::sleep(Duration::from_millis(700));
    let app = douyin_app()?;
    let attribute = CFString::new("AXFrontmost");
    let enabled = CFBoolean::true_value();
    let code = unsafe {
        AXUIElementSetAttributeValue(
            app.0,
            attribute.as_concrete_TypeRef(),
            enabled.as_CFTypeRef(),
        )
    };
    if code != AX_SUCCESS {
        return Err(ax_error("无法将抖音切换到前台", code));
    }
    thread::sleep(Duration::from_millis(400));
    Ok(())
}

pub(crate) fn main_window_bounds() -> Result<NativeWindowBounds, String> {
    let window = main_window()?;
    let position = attribute_point(window.0, "AXPosition", AX_VALUE_CG_POINT)
        .ok_or_else(|| "无法读取抖音窗口位置".to_string())?;
    let size = attribute_size(window.0).ok_or_else(|| "无法读取抖音窗口尺寸".to_string())?;
    Ok(NativeWindowBounds {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    })
}

fn post_mouse_event(event_type: u32, point: CGPoint) -> Result<(), String> {
    let event = unsafe {
        CGEventCreateMouseEvent(std::ptr::null(), event_type, point, CG_MOUSE_BUTTON_LEFT)
    };
    if event.is_null() {
        return Err("无法创建 macOS 鼠标事件".to_string());
    }
    unsafe {
        CGEventPost(CG_EVENT_TAP_HID, event);
        CFRelease(event);
    }
    Ok(())
}

fn click_at(x: f64, y: f64) -> Result<(), String> {
    let point = CGPoint { x, y };
    post_mouse_event(CG_EVENT_MOUSE_MOVED, point)?;
    thread::sleep(Duration::from_millis(50));
    post_mouse_event(CG_EVENT_LEFT_MOUSE_DOWN, point)?;
    post_mouse_event(CG_EVENT_LEFT_MOUSE_UP, point)?;
    thread::sleep(Duration::from_millis(120));
    Ok(())
}

fn press_key(key_code: u16, command: bool) -> Result<(), String> {
    for key_down in [true, false] {
        let event =
            unsafe { CGEventCreateKeyboardEvent(std::ptr::null(), key_code, u8::from(key_down)) };
        if event.is_null() {
            return Err("无法创建 macOS 键盘事件".to_string());
        }
        unsafe {
            if command {
                CGEventSetFlags(event, CG_EVENT_FLAG_COMMAND);
            }
            CGEventPost(CG_EVENT_TAP_HID, event);
            CFRelease(event);
        }
        thread::sleep(Duration::from_millis(35));
    }
    Ok(())
}

fn clipboard_text() -> Vec<u8> {
    Command::new("/usr/bin/pbpaste")
        .output()
        .map(|output| output.stdout)
        .unwrap_or_default()
}

fn set_clipboard_text(value: &[u8]) -> Result<(), String> {
    let mut child = Command::new("/usr/bin/pbcopy")
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|error| format!("无法写入剪贴板: {error}"))?;
    child
        .stdin
        .as_mut()
        .ok_or_else(|| "无法连接 macOS 剪贴板".to_string())?
        .write_all(value)
        .map_err(|error| format!("无法写入剪贴板: {error}"))?;
    let status = child
        .wait()
        .map_err(|error| format!("无法等待剪贴板写入: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("写入 macOS 剪贴板失败".to_string())
    }
}

fn paste_text(value: &str) -> Result<(), String> {
    let previous = clipboard_text();
    set_clipboard_text(value.as_bytes())?;
    let paste_result = press_key(9, true);
    thread::sleep(Duration::from_millis(180));
    let restore_result = set_clipboard_text(&previous);
    paste_result?;
    restore_result
}

fn element_at_position(x: f64, y: f64) -> Result<OwnedAX, String> {
    let app = douyin_app()?;
    let mut element: AXUIElementRef = std::ptr::null();
    let code = unsafe { AXUIElementCopyElementAtPosition(app.0, x as f32, y as f32, &mut element) };
    if code != AX_SUCCESS || element.is_null() {
        Err(ax_error("无法读取抖音界面元素", code))
    } else {
        Ok(OwnedAX(element))
    }
}

fn ancestor_with_role(x: f64, y: f64, expected: &str) -> Result<OwnedAX, String> {
    let mut current = element_at_position(x, y)?;
    for _ in 0..6 {
        if attribute_string(current.0, "AXRole").as_deref() == Some(expected) {
            return Ok(current);
        }
        let parent = copy_attribute(current.0, "AXParent")
            .map_err(|code| ax_error("无法读取抖音界面元素层级", code))?;
        current = OwnedAX(parent as AXUIElementRef);
    }
    Err(format!("未找到抖音界面元素 {expected}"))
}

fn find_role_element<F>(
    root: AXUIElementRef,
    expected_role: &str,
    mut accepts: F,
) -> Option<(OwnedAX, Rect)>
where
    F: FnMut(Rect) -> bool,
{
    let retained = unsafe { CFRetain(root as CFTypeRef) } as AXUIElementRef;
    let mut stack = vec![retained];
    let mut inspected = 0usize;
    while let Some(element) = stack.pop() {
        inspected += 1;
        if attribute_string(element, "AXRole").as_deref() == Some(expected_role) {
            if let Some(rect) = element_rect(element) {
                if accepts(rect) {
                    for pending in stack {
                        unsafe { CFRelease(pending as CFTypeRef) };
                    }
                    return Some((OwnedAX(element), rect));
                }
            }
        }
        if inspected < 10_000 {
            if let Ok(raw) = copy_attribute(element, "AXChildren") {
                if unsafe { CFGetTypeID(raw) } == unsafe { CFArrayGetTypeID() } {
                    let array = raw as CFArrayRef;
                    let count = unsafe { CFArrayGetCount(array) };
                    for index in 0..count {
                        let child =
                            unsafe { CFArrayGetValueAtIndex(array, index) } as AXUIElementRef;
                        if !child.is_null() {
                            stack.push(unsafe { CFRetain(child as CFTypeRef) } as AXUIElementRef);
                        }
                    }
                }
                unsafe { CFRelease(raw) };
            }
        }
        unsafe { CFRelease(element as CFTypeRef) };
    }
    None
}

fn find_rightmost_role_rect<F>(
    root: AXUIElementRef,
    expected_role: &str,
    mut accepts: F,
) -> Option<Rect>
where
    F: FnMut(Rect) -> bool,
{
    let retained = unsafe { CFRetain(root as CFTypeRef) } as AXUIElementRef;
    let mut stack = vec![retained];
    let mut inspected = 0usize;
    let mut selected: Option<Rect> = None;
    while let Some(element) = stack.pop() {
        inspected += 1;
        if attribute_string(element, "AXRole").as_deref() == Some(expected_role) {
            if let Some(rect) = element_rect(element) {
                if accepts(rect) && selected.is_none_or(|current| rect.x > current.x) {
                    selected = Some(rect);
                }
            }
        }
        if inspected < 10_000 {
            if let Ok(raw) = copy_attribute(element, "AXChildren") {
                if unsafe { CFGetTypeID(raw) } == unsafe { CFArrayGetTypeID() } {
                    let array = raw as CFArrayRef;
                    let count = unsafe { CFArrayGetCount(array) };
                    for index in 0..count {
                        let child =
                            unsafe { CFArrayGetValueAtIndex(array, index) } as AXUIElementRef;
                        if !child.is_null() {
                            stack.push(unsafe { CFRetain(child as CFTypeRef) } as AXUIElementRef);
                        }
                    }
                }
                unsafe { CFRelease(raw) };
            }
        }
        unsafe { CFRelease(element as CFTypeRef) };
    }
    selected
}

fn message_input() -> Result<Option<(OwnedAX, Rect)>, String> {
    let window = main_window()?;
    Ok(find_role_element(window.0, "AXTextArea", |rect| {
        rect.width >= 120.0 && rect.height >= 24.0
    }))
}

fn message_input_near(input_x: f64, input_y: f64) -> Result<Option<(OwnedAX, Rect)>, String> {
    if let Some(input) = message_input()? {
        return Ok(Some(input));
    }

    // Chromium's accessibility tree can briefly omit descendants while the
    // message overlay is repainting. Fall back to the element under the known
    // input point and walk upwards instead of treating that transient state as
    // a logged-out session.
    let Ok(element) = ancestor_with_role(input_x, input_y, "AXTextArea") else {
        return Ok(None);
    };
    let rect = element_rect(element.0).unwrap_or(Rect {
        x: input_x,
        y: input_y,
        width: 1.0,
        height: 1.0,
    });
    Ok(Some((element, rect)))
}

fn focus_element(element: AXUIElementRef) -> Result<(), String> {
    let attribute = CFString::new("AXFocused");
    let enabled = CFBoolean::true_value();
    let code = unsafe {
        AXUIElementSetAttributeValue(
            element,
            attribute.as_concrete_TypeRef(),
            enabled.as_CFTypeRef(),
        )
    };
    if code == AX_SUCCESS {
        Ok(())
    } else {
        Err(ax_error("无法聚焦抖音消息输入框", code))
    }
}

pub(crate) fn ensure_message_panel(
    input_x: f64,
    input_y: f64,
    message_icon_x: f64,
    message_icon_y: f64,
) -> Result<(), String> {
    if let Some((element, rect)) = message_input_near(input_x, input_y)? {
        click_at(rect.x + rect.width * 0.35, rect.y + rect.height * 0.5)?;
        let _ = focus_element(element.0);
        return Ok(());
    }
    click_at(message_icon_x, message_icon_y)?;
    thread::sleep(Duration::from_secs(1));
    if let Some((element, rect)) = message_input_near(input_x, input_y)? {
        click_at(rect.x + rect.width * 0.35, rect.y + rect.height * 0.5)?;
        let _ = focus_element(element.0);
        return Ok(());
    }
    click_at(input_x, input_y)?;
    Err("未找到抖音消息输入框，请确认已登录并打开消息能力".to_string())
}

pub(crate) fn open_contact_from_search(
    contact_name: &str,
    search_x: f64,
    search_y: f64,
) -> Result<(), String> {
    let window = main_window()?;
    let (search_element, search) = find_role_element(window.0, "AXTextField", |rect| {
        let center_x = rect.x + rect.width * 0.5;
        let center_y = rect.y + rect.height * 0.5;
        (center_x - search_x).abs() <= 180.0 && (center_y - search_y).abs() <= 100.0
    })
    .ok_or_else(|| "未找到抖音联系人搜索框".to_string())?;
    click_at(
        search.x + search.width * 0.4,
        search.y + search.height * 0.5,
    )?;
    let _ = focus_element(search_element.0);
    press_key(0, true)?;
    press_key(51, false)?;
    paste_text(contact_name)?;
    press_key(36, false)?;
    thread::sleep(Duration::from_millis(1200));
    Ok(())
}

fn normalize(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn find_text_rect<F>(root: AXUIElementRef, mut matches: F) -> Option<Rect>
where
    F: FnMut(&str, &str, Rect) -> bool,
{
    let retained = unsafe { CFRetain(root as CFTypeRef) } as AXUIElementRef;
    let mut stack = vec![retained];
    let mut inspected = 0usize;
    let mut selected = None;
    while let Some(element) = stack.pop() {
        inspected += 1;
        if attribute_string(element, "AXRole").as_deref() == Some("AXStaticText") {
            let value = attribute_string(element, "AXValue").unwrap_or_default();
            let title = attribute_string(element, "AXTitle").unwrap_or_default();
            if let Some(rect) = element_rect(element) {
                if matches(&value, &title, rect) {
                    selected = Some(rect);
                }
            }
        }
        if selected.is_none() && inspected < 10_000 {
            if let Ok(raw) = copy_attribute(element, "AXChildren") {
                if unsafe { CFGetTypeID(raw) } == unsafe { CFArrayGetTypeID() } {
                    let array = raw as CFArrayRef;
                    let count = unsafe { CFArrayGetCount(array) };
                    for index in 0..count {
                        let child =
                            unsafe { CFArrayGetValueAtIndex(array, index) } as AXUIElementRef;
                        if !child.is_null() {
                            stack.push(unsafe { CFRetain(child as CFTypeRef) } as AXUIElementRef);
                        }
                    }
                }
                unsafe { CFRelease(raw) };
            }
        }
        unsafe { CFRelease(element as CFTypeRef) };
        if selected.is_some() {
            break;
        }
    }
    for element in stack {
        unsafe { CFRelease(element as CFTypeRef) };
    }
    selected
}

pub(crate) fn click_matching_search_result(
    contact_name: &str,
    bounds: NativeWindowBounds,
) -> Result<bool, String> {
    let window = main_window()?;
    let target = normalize(contact_name);
    let min_x = bounds.x + bounds.width * 0.28;
    let max_x = bounds.x + bounds.width * 0.55;
    let min_y = bounds.y + bounds.height * 0.10;
    let max_y = bounds.y + bounds.height * 0.82;
    let selected = find_text_rect(window.0, |value, title, rect| {
        let value = normalize(value);
        let title = normalize(title);
        let name_match =
            value == target || title == target || value.starts_with(&format!("{target} "));
        let center_x = rect.x + (rect.width / 2.0).max(8.0);
        let center_y = rect.y + (rect.height / 2.0).max(8.0);
        name_match
            && center_x >= min_x
            && center_x <= max_x
            && center_y >= min_y
            && center_y <= max_y
    });
    let Some(rect) = selected else {
        return Ok(false);
    };
    let click_x = bounds.x + bounds.width * 0.477;
    let click_y = rect.y + (rect.height / 2.0).max(8.0);
    click_at(click_x, click_y)?;
    thread::sleep(Duration::from_millis(1200));
    Ok(true)
}

pub(crate) fn current_conversation_matches(
    contact_name: &str,
    bounds: NativeWindowBounds,
) -> Result<bool, String> {
    let window = main_window()?;
    let min_x = bounds.x + bounds.width * 0.52;
    let max_x = bounds.x + bounds.width * 0.92;
    let min_y = bounds.y + bounds.height * 0.04;
    let max_y = bounds.y + bounds.height * 0.20;
    Ok(find_text_rect(window.0, |value, _, rect| {
        rect.x >= min_x
            && rect.x <= max_x
            && rect.y >= min_y
            && rect.y <= max_y
            && value == contact_name
    })
    .is_some())
}

pub(crate) fn fill_and_send(content: &str, input_x: f64, input_y: f64) -> Result<(), String> {
    let (input_element, input) = message_input_near(input_x, input_y)?
        .ok_or_else(|| "未找到抖音消息输入框，请确认已登录并打开消息能力".to_string())?;
    click_at(input.x + input.width * 0.35, input.y + input.height * 0.5)?;
    let _ = focus_element(input_element.0);
    press_key(0, true)?;
    press_key(51, false)?;
    paste_text(content)?;
    thread::sleep(Duration::from_millis(300));
    let window = main_window()?;
    let send_icon = find_rightmost_role_rect(window.0, "AXImage", |rect| {
        let center_x = rect.x + rect.width * 0.5;
        let center_y = rect.y + rect.height * 0.5;
        center_x >= input.x + input.width * 0.55
            && center_y >= input.y - 18.0
            && center_y <= input.y + input.height + 18.0
    })
    .ok_or_else(|| "未找到抖音输入框右侧的发送按钮".to_string())?;
    click_at(
        send_icon.x + send_icon.width * 0.5,
        send_icon.y + send_icon.height * 0.5,
    )?;
    thread::sleep(Duration::from_millis(800));
    if let Some((current_element, current_input)) = message_input()? {
        let remaining = attribute_string(current_element.0, "AXValue").unwrap_or_default();
        if remaining.contains(content) || current_input.height > input.height * 1.35 {
            return Err("点击发送后输入框仍保留内容，消息可能未发送".to_string());
        }
    }
    let _ = (input_x, input_y);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::normalize;

    #[test]
    fn normalizes_contact_text_for_exact_row_matching() {
        assert_eq!(normalize("  小猫头大\n 发消息 "), "小猫头大 发消息");
    }
}
