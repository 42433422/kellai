"""AppleScript 命令封装 — 用于操控 Mac 微信客户端。"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

# AppleScript 执行超时（秒）
_SCRIPT_TIMEOUT = 5


def _run_applescript(script: str, timeout: int = _SCRIPT_TIMEOUT) -> tuple[bool, str]:
    """执行 AppleScript 并返回 (成功标志, 输出或错误信息)。

    Args:
        script: AppleScript 脚本内容
        timeout: 执行超时秒数

    Returns:
        (True, stdout) 成功时
        (False, error_message) 失败时
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        logger.warning("AppleScript 执行失败: %s", result.stderr.strip())
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.warning("AppleScript 执行超时 (%ss)", timeout)
        return False, f"applescript_timeout ({timeout}s)"
    except Exception as exc:
        logger.exception("AppleScript 执行异常")
        return False, str(exc)


def is_wechat_running() -> bool:
    """检查微信进程是否在运行。"""
    script = '''
    tell application "System Events"
        return (name of processes) contains "WeChat"
    end tell
    '''
    ok, out = _run_applescript(script)
    return ok and out.lower() == "true"


def activate_wechat() -> bool:
    """激活微信窗口（将其带到前台）。"""
    script = '''
    tell application "WeChat"
        activate
    end tell
    delay 0.3
    '''
    ok, _ = _run_applescript(script, timeout=3)
    return ok


def get_wechat_window_title() -> str:
    """获取微信当前窗口标题。"""
    script = '''
    tell application "WeChat"
        activate
    end tell
    delay 0.2
    tell application "System Events"
        tell process "WeChat"
            try
                return name of front window
            on error
                return ""
            end try
        end tell
    end tell
    '''
    ok, out = _run_applescript(script)
    return out if ok else ""


def search_contact(name: str) -> bool:
    """在微信中使用搜索功能查找联系人。

    流程：Cmd+F 打开搜索 → 输入联系人名称 → 等待搜索结果

    Args:
        name: 联系人名称

    Returns:
        是否成功搜索
    """
    # 对名称做基本转义，防止 AppleScript 注入
    safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "WeChat"
        activate
    end tell
    delay 0.3
    tell application "System Events"
        tell process "WeChat"
            -- 打开搜索框 (Cmd+F)
            keystroke "f" using command down
            delay 0.5
            -- 清空搜索框并输入联系人名称
            keystroke "a" using command down
            delay 0.1
            keystroke "{safe_name}"
            delay 1.0
            -- 按回车选中第一个搜索结果
            key code 36
            delay 0.5
        end tell
    end tell
    return true
    '''
    ok, _ = _run_applescript(script, timeout=8)
    return ok


def send_message_in_chat(text: str) -> bool:
    """在当前聊天窗口中输入并发送消息。

    前提：已经打开了某个联系人的聊天窗口。
    流程：输入文字 → 按 Enter 发送

    Args:
        text: 要发送的消息文本

    Returns:
        是否成功发送
    """
    # 对文本做基本转义
    safe_text = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "WeChat"
        activate
    end tell
    delay 0.2
    tell application "System Events"
        tell process "WeChat"
            -- 输入消息文本
            keystroke "{safe_text}"
            delay 0.3
            -- 按 Enter 发送
            key code 36
            delay 0.3
        end tell
    end tell
    return true
    '''
    ok, _ = _run_applescript(script, timeout=6)
    return ok


def get_wechat_dock_badge() -> int:
    """从 Dock 徽标读取微信未读消息数量。

    Returns:
        未读消息数量，读取失败返回 0
    """
    script = '''
    tell application "System Events"
        tell process "Dock"
            try
                -- 尝试读取 Dock 中微信图标的徽标
                set badge to value of attribute "AXBadgeValue" of UI element "WeChat" of list 1
                return badge as text
            on error
                return "0"
            end try
        end tell
    end tell
    '''
    ok, out = _run_applescript(script)
    if ok and out:
        try:
            return int(out)
        except ValueError:
            return 0
    return 0


def get_chat_list_via_accessibility() -> list[dict]:
    """通过 Accessibility API 获取最近聊天列表。

    当前通过 AppleScript 尝试读取侧边栏聊天列表。
    由于微信 UI 结构可能变化，此方法可能不稳定。

    Returns:
        聊天列表 [{"name": str, "unread": int, "last_message": str}]
    """
    script = '''
    tell application "WeChat"
        activate
    end tell
    delay 0.3
    tell application "System Events"
        tell process "WeChat"
            try
                set chatItems to {}
                -- 尝试获取聊天列表中的 UI 元素
                set sidebar to group 1 of scroll area 1 of front window
                set itemCount to count of UI elements of sidebar
                repeat with i from 1 to itemCount
                    if i > 20 then exit repeat
                    try
                        set itemTitle to name of UI element i of sidebar
                        set end of chatItems to itemTitle
                    on error
                        -- 跳过无法读取的元素
                    end try
                end repeat
                return chatItems
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
    end tell
    '''
    ok, out = _run_applescript(script, timeout=8)
    if not ok or not out:
        return []

    if out.startswith("ERROR:"):
        logger.warning("获取聊天列表失败: %s", out)
        return []

    # 解析 AppleScript 返回的列表
    results = []
    items = out.split(", ")
    for item in items:
        name = item.strip()
        if name:
            results.append({
                "name": name,
                "unread": 0,
                "last_message": "",
            })
    return results


def get_chat_messages_via_accessibility(contact_name: str, limit: int = 20) -> list[dict]:
    """通过 Accessibility API 获取与某联系人的聊天记录。

    当前通过 AppleScript 尝试读取聊天窗口中的消息。
    由于微信 UI 结构可能变化，此方法可能不稳定。

    Args:
        contact_name: 联系人名称
        limit: 最大消息数量

    Returns:
        消息列表 [{"sender": str, "content": str, "timestamp": str}]
    """
    safe_name = contact_name.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "WeChat"
        activate
    end tell
    delay 0.3
    tell application "System Events"
        tell process "WeChat"
            try
                set messages to {{}}
                -- 尝试获取聊天区域中的消息
                set chatArea to scroll area 2 of group 1 of front window
                set msgElements to UI elements of chatArea
                set msgCount to count of msgElements
                set startIdx to (msgCount - {limit} + 1)
                if startIdx < 1 then set startIdx to 1
                repeat with i from startIdx to msgCount
                    try
                        set msgText to name of UI element i of chatArea
                        set end of messages to msgText
                    on error
                        -- 跳过无法读取的元素
                    end try
                end repeat
                return messages
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
    end tell
    '''
    ok, out = _run_applescript(script, timeout=8)
    if not ok or not out:
        return []

    if out.startswith("ERROR:"):
        logger.warning("获取聊天记录失败: %s", out)
        return []

    # 解析返回的消息
    results = []
    items = out.split(", ")
    for item in items:
        content = item.strip()
        if content:
            results.append({
                "sender": "",
                "content": content,
                "timestamp": "",
            })
    return results[:limit]
