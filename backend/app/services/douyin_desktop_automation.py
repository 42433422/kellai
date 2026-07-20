"""抖音 macOS 桌面端私信自动化。

第三方客服网页负责收取和同步消息，本模块负责在本机抖音客户端完成发送：
打开消息面板、搜索联系人、点击“发消息”、粘贴文本并回车。连续回复同一联系人
时会缓存当前会话并跳过搜索步骤。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.crm_store import _crm_db_path

logger = logging.getLogger(__name__)

_ENV_ENABLED = "KELLAI_DOUYIN_DESKTOP_AUTOMATION"
_APP_BUNDLE_ID = "com.bytedance.douyin.desktop"
_APP_PROCESS_NAME = "抖音"
_SCRIPT_TIMEOUT = 20
_SEND_LOCK = threading.Lock()


class DouyinDesktopAutomationError(RuntimeError):
    """抖音桌面端自动化失败。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_path() -> Path:
    from app.services.tenant_context import tenant_data_root

    return tenant_data_root(required=False) / "douyin-desktop-automation.json"


def _read_cache() -> dict[str, Any]:
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_cache(*, contact_id: str, contact_name: str) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contact_id": str(contact_id or ""),
        "contact_name": str(contact_name or ""),
        "updated_at": _now_iso(),
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def automation_enabled(*, team_id: int = 0, source: str = "") -> bool:
    """未显式配置时，仅为已连接的抖音客服网页来源自动启用。"""
    configured = os.environ.get(_ENV_ENABLED, "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return platform.system() == "Darwin"
    if configured in {"0", "false", "no", "off"}:
        return False
    if platform.system() != "Darwin" or source != "douyin_web_portal" or team_id <= 0:
        return False
    try:
        from app.services.douyin_web_portal import status

        return bool(status(int(team_id)).get("connected"))
    except Exception:
        logger.debug("读取抖音客服网页连接状态失败", exc_info=True)
        return False


def _escape_applescript(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _run_process(
    args: list[str],
    *,
    script: str = "",
    timeout: int = _SCRIPT_TIMEOUT,
) -> str:
    try:
        completed = subprocess.run(
            args,
            input=script or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DouyinDesktopAutomationError("抖音桌面自动化执行超时") from exc
    except OSError as exc:
        raise DouyinDesktopAutomationError(f"无法启动 macOS 自动化: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "未知错误").strip()
        if "不允许辅助访问" in detail or "not allowed assistive access" in detail.lower():
            raise DouyinDesktopAutomationError(
                "后台自动化进程没有辅助功能权限；请使用最新版客来来桌面端发送，让系统权限正确归属到客来来"
            )
        raise DouyinDesktopAutomationError(f"抖音桌面自动化失败: {detail}")
    return completed.stdout.strip()


def _run_applescript(script: str) -> str:
    return _run_process(["osascript", "-"], script=script)


def _run_jxa(script: str) -> str:
    return _run_process(["osascript", "-l", "JavaScript", "-"], script=script)


def _raise_main_window() -> None:
    subprocess.run(
        ["open", "-b", _APP_BUNDLE_ID],
        capture_output=True,
        text=True,
        timeout=8,
    )
    script = f'''
try
    tell application id "{_APP_BUNDLE_ID}" to activate
on error
    tell application "{_APP_PROCESS_NAME}" to activate
end try
delay 0.8
tell application "System Events"
    if not (exists process "{_APP_PROCESS_NAME}") then error "未找到抖音桌面端进程"
    tell process "{_APP_PROCESS_NAME}"
        set frontmost to true
        try
            click menu item "抖音" of menu 1 of menu bar item "窗口" of menu bar 1
        end try
    end tell
end tell
delay 0.5
'''
    _run_applescript(script)


def _main_window_bounds() -> dict[str, float]:
    raw = _run_jxa(
        r'''
ObjC.import('CoreGraphics')
ObjC.import('Foundation')
const list = ObjC.castRefToObject(
  $.CGWindowListCopyWindowInfo(
    $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements,
    $.kCGNullWindowID
  )
)
let selected = null
for (let i = 0; i < Number(list.count); i++) {
  const item = list.objectAtIndex(i)
  const owner = String(ObjC.unwrap(item.objectForKey($('kCGWindowOwnerName'))) || '')
  const name = String(ObjC.unwrap(item.objectForKey($('kCGWindowName'))) || '')
  const bounds = ObjC.deepUnwrap(item.objectForKey($('kCGWindowBounds')))
  if (owner !== '抖音' || !bounds || Number(bounds.Width) < 900) continue
  const area = Number(bounds.Width) * Number(bounds.Height)
  if (!selected || name === '抖音' || area > selected.area) {
    selected = {X:Number(bounds.X),Y:Number(bounds.Y),Width:Number(bounds.Width),Height:Number(bounds.Height),area}
  }
}
if (!selected) throw new Error('未找到抖音主窗口')
delete selected.area
JSON.stringify(selected)
'''
    )
    try:
        bounds = json.loads(raw)
        return {key: float(bounds[key]) for key in ("X", "Y", "Width", "Height")}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DouyinDesktopAutomationError(f"无法读取抖音窗口位置: {raw}") from exc


def _current_conversation_matches(
    *,
    contact_name: str,
    bounds: dict[str, float],
) -> bool:
    """校验消息面板当前会话标题。

    同一昵称可能同时出现在左侧联系人列表或背后的搜索页，
    因此还需用 AXPosition 限定到消息面板右上方的标题区域。
    """
    target = json.dumps(str(contact_name or ""), ensure_ascii=False)
    min_x = float(bounds["X"]) + float(bounds["Width"]) * 0.52
    max_x = float(bounds["X"]) + float(bounds["Width"]) * 0.92
    min_y = float(bounds["Y"]) + float(bounds["Height"]) * 0.04
    max_y = float(bounds["Y"]) + float(bounds["Height"]) * 0.20
    raw = _run_jxa(
        f'''
ObjC.import('ApplicationServices')
ObjC.import('AppKit')
const target = {target}
const running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('{_APP_BUNDLE_ID}')
if (Number(running.count) < 1) throw new Error('未找到抖音桌面端进程')
const app = $.AXUIElementCreateApplication(Number(running.objectAtIndex(0).processIdentifier))

function attribute(element, name) {{
  const ref = Ref()
  const error = $.AXUIElementCopyAttributeValue(element, $(name), ref)
  if (Number(error) !== 0) return null
  return ref[0]
}}

function objectValue(rawValue) {{
  return rawValue ? ObjC.castRefToObject(rawValue) : null
}}

function stringValue(rawValue) {{
  if (!rawValue) return ''
  try {{ return String(ObjC.unwrap(objectValue(rawValue)) || '') }} catch (_) {{ return '' }}
}}

const windowsRaw = attribute(app, 'AXWindows')
if (!windowsRaw) throw new Error('无法读取抖音窗口')
const windows = objectValue(windowsRaw)
let mainWindow = null
for (let index = 0; index < Number(windows.count); index++) {{
  const candidate = windows.objectAtIndex(index)
  if (stringValue(attribute(candidate, 'AXTitle')) === '抖音') {{
    mainWindow = candidate
    break
  }}
}}
if (!mainWindow) throw new Error('未找到抖音主窗口')

const stack = [mainWindow]
let matched = false
let inspected = 0
while (stack.length && inspected < 10000 && !matched) {{
  const element = stack.pop()
  inspected++
  const role = stringValue(attribute(element, 'AXRole'))
  const value = stringValue(attribute(element, 'AXValue'))
  if (role === 'AXStaticText' && value === target) {{
    const position = objectValue(attribute(element, 'AXPosition'))
    const description = position ? String(position.description.js || '') : ''
    const match = description.match(/x:([\\d.-]+)\\s+y:([\\d.-]+)/)
    if (match) {{
      const x = Number(match[1])
      const y = Number(match[2])
      matched = x >= {min_x} && x <= {max_x} && y >= {min_y} && y <= {max_y}
    }}
  }}
  const childrenRaw = attribute(element, 'AXChildren')
  if (childrenRaw) {{
    const children = objectValue(childrenRaw)
    for (let index = 0; index < Number(children.count); index++) {{
      stack.push(children.objectAtIndex(index))
    }}
  }}
}}
matched ? 'true' : 'false'
'''
    )
    return raw.strip().lower() == "true"


_FLOW_HANDLERS = r'''
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
'''


def _flow_coordinates(bounds: dict[str, float]) -> dict[str, int]:
    x = bounds["X"]
    y = bounds["Y"]
    width = bounds["Width"]
    height = bounds["Height"]
    # 抖音 8.x 消息浮层随主窗口等比缩放；所有点击点均按窗口比例计算。
    return {
        "message_icon_x": round(x + width * 0.84),
        "message_icon_y": round(y + height * 0.04),
        "search_x": round(x + width * 0.384),
        "search_y": round(y + height * 0.118),
        "first_result_x": round(x + width * 0.477),
        "first_result_y": round(y + height * 0.251),
        # 抖音 8.1 将消息编辑器向右移；留在输入区中部，避免点到左侧容器。
        "input_x": round(x + width * 0.70),
        "input_y": round(y + height * 0.72),
    }


def _ensure_message_panel(coordinates: dict[str, int]) -> None:
    script = f'''
{_FLOW_HANDLERS}
set messageInput to my focusMessageInput({coordinates["input_x"]}, {coordinates["input_y"]})
if messageInput is missing value then
    tell application "System Events" to click at {{{coordinates["message_icon_x"]}, {coordinates["message_icon_y"]}}}
    delay 1.0
    set messageInput to my focusMessageInput({coordinates["input_x"]}, {coordinates["input_y"]})
end if
if messageInput is missing value then error "未找到抖音消息输入框，请确认已登录并打开消息能力"
return "ready"
'''
    _run_applescript(script)


def _open_contact_from_search(
    *,
    contact_name: str,
    coordinates: dict[str, int],
) -> None:
    safe_contact = _escape_applescript(contact_name)
    script = f'''
{_FLOW_HANDLERS}
set contactText to "{safe_contact}"
set searchField to my focusSearchField({coordinates["search_x"]}, {coordinates["search_y"]})
if searchField is missing value then error "未找到抖音联系人搜索框"
tell application "System Events" to set value of attribute "AXValue" of searchField to contactText
delay 1.5
tell application "System Events" to click at {{{coordinates["first_result_x"]}, {coordinates["first_result_y"]}}}
delay 1.0
return "opened"
'''
    _run_applescript(script)


def _fill_and_maybe_send(
    *,
    content: str,
    coordinates: dict[str, int],
    prepare_only: bool,
) -> str:
    safe_content = _escape_applescript(content)
    only_prepare = "true" if prepare_only else "false"
    script = f'''
{_FLOW_HANDLERS}
set messageText to "{safe_content}"
set prepareOnly to {only_prepare}
set oldClipboard to missing value
try
    set oldClipboard to the clipboard as text
end try

try
    set messageInput to my focusMessageInput({coordinates["input_x"]}, {coordinates["input_y"]})
    if messageInput is missing value then error "未找到抖音消息输入框，请确认已登录并打开消息能力"
    tell application "System Events" to click messageInput
    my clearFocusedField()
    set the clipboard to messageText
    my pasteFromEditMenu()
    delay 0.3
    if not prepareOnly then
        tell application "System Events"
            tell process "{_APP_PROCESS_NAME}" to key code 36
        end tell
        delay 0.5
        try
            tell application "System Events" to set remainingText to value of attribute "AXValue" of messageInput as text
            if remainingText contains messageText then error "回车后输入框未清空，消息可能没有发送"
        end try
    end if
on error errMsg number errNum
    if oldClipboard is not missing value then set the clipboard to oldClipboard
    error errMsg number errNum
end try

if oldClipboard is not missing value then set the clipboard to oldClipboard
if prepareOnly then return "prepared"
return "sent"
'''
    return _run_applescript(script)


def _execute_flow(
    *,
    contact_name: str,
    content: str,
    reuse_cached_conversation: bool,
    prepare_only: bool,
) -> str:
    _raise_main_window()
    bounds = _main_window_bounds()
    coordinates = _flow_coordinates(bounds)
    _ensure_message_panel(coordinates)

    reused = False
    if reuse_cached_conversation:
        try:
            reused = _current_conversation_matches(
                contact_name=contact_name,
                bounds=bounds,
            )
        except DouyinDesktopAutomationError:
            # 安全优先：无法验证当前会话时重新搜索，避免发错联系人。
            logger.warning("无法校验抖音当前会话，将重新搜索联系人", exc_info=True)

    if not reused:
        _open_contact_from_search(
            contact_name=contact_name,
            coordinates=coordinates,
        )
        matched = False
        for attempt in range(3):
            try:
                matched = _current_conversation_matches(
                    contact_name=contact_name,
                    bounds=bounds,
                )
            except DouyinDesktopAutomationError:
                logger.debug("搜索后校验抖音会话失败", exc_info=True)
            if matched:
                break
            if attempt < 2:
                time.sleep(0.4)
        if not matched:
            raise DouyinDesktopAutomationError(
                f"未打开目标联系人会话: {contact_name}，已取消发送"
            )

    status = _fill_and_maybe_send(
        content=content,
        coordinates=coordinates,
        prepare_only=prepare_only,
    )
    return f"{status}|{str(reused).lower()}"


def send_message(
    *,
    contact_name: str,
    content: str,
    contact_id: str = "",
    force_search: bool = False,
    prepare_only: bool = False,
) -> dict[str, Any]:
    """通过抖音桌面端准备或发送一条文本消息。"""
    contact = str(contact_name or "").strip()
    text = str(content or "").strip()
    if not contact:
        return {"success": False, "message_id": "", "error": "缺少抖音联系人名称"}
    if not text:
        return {"success": False, "message_id": "", "error": "消息内容为空"}
    if platform.system() != "Darwin":
        return {"success": False, "message_id": "", "error": "抖音桌面自动发送仅支持 macOS"}

    with _SEND_LOCK:
        cache = _read_cache()
        reuse_cached = not force_search and (
            str(cache.get("contact_name") or "") == contact
            and (
                not contact_id
                or not cache.get("contact_id")
                or str(cache.get("contact_id")) == str(contact_id)
            )
        )
        try:
            output = _execute_flow(
                contact_name=contact,
                content=text,
                reuse_cached_conversation=reuse_cached,
                prepare_only=prepare_only,
            )
        except DouyinDesktopAutomationError as exc:
            logger.warning("抖音桌面发送失败: contact=%s error=%s", contact, exc)
            return {"success": False, "message_id": "", "error": str(exc)}

        status, _, reused_raw = output.partition("|")
        reused = reused_raw.strip().lower() == "true"
        if status not in {"prepared", "sent"}:
            return {
                "success": False,
                "message_id": "",
                "error": f"抖音桌面自动化返回异常: {output or 'empty'}",
            }
        _write_cache(contact_id=contact_id, contact_name=contact)
        return {
            "success": True,
            "message_id": "",
            "error": "",
            "source": "douyin_desktop_automation",
            "prepared_only": prepare_only,
            "message_sent": not prepare_only,
            "contact_name": contact,
            "contact_id": str(contact_id or ""),
            "reused_conversation": reused,
            "pending_portal_sync": not prepare_only,
        }
