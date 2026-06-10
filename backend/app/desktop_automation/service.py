"""Mac 微信桌面自动化（客来来）。

通过 macOS Accessibility API 和 AppleScript 操控微信客户端，
实现消息发送、未读计数、聊天列表获取等功能。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from . import applescript

logger = logging.getLogger(__name__)

# 环境变量：启用真实微信自动化
_ENV_ENABLED = "KELLAI_WECHAT_AUTOMATION"

# 单例
_instance: DesktopAutomationService | None = None


# ======================================================================
# MacWechatAutomation — 真实 Mac 微信自动化
# ======================================================================


class MacWechatAutomation:
    """Mac 微信桌面自动化。

    使用 subprocess 调用 osascript（AppleScript）操控微信客户端，
    不依赖 pyobjc，减少外部依赖。
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._app_ref: Any = None  # 预留 NSApplication 引用

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def check_wechat_running(self) -> bool:
        """检查微信是否在运行。"""
        try:
            return applescript.is_wechat_running()
        except Exception:
            logger.exception("检查微信运行状态失败")
            return False

    def check_wechat_logged_in(self) -> bool:
        """检查微信是否已登录。

        通过检查微信窗口标题判断：已登录时窗口标题通常为"微信"或包含联系人名。
        未登录时窗口标题为"登录"或为空。
        """
        try:
            title = applescript.get_wechat_window_title()
            if not title:
                return False
            # 未登录窗口标题通常包含"登录"或"Login"
            login_keywords = ("登录", "Login", "login", "扫码")
            return not any(kw in title for kw in login_keywords)
        except Exception:
            logger.exception("检查微信登录状态失败")
            return False

    def connect(self) -> dict[str, Any]:
        """连接微信客户端。

        Returns:
            {"connected": bool, "message": str}
        """
        try:
            if not self.check_wechat_running():
                return {"connected": False, "message": "微信未运行，请先启动微信"}

            if not self.check_wechat_logged_in():
                return {"connected": False, "message": "微信未登录，请先登录微信"}

            # 激活微信窗口
            if not applescript.activate_wechat():
                return {"connected": False, "message": "无法激活微信窗口"}

            self._connected = True
            logger.info("微信客户端连接成功")
            return {"connected": True, "message": "微信客户端连接成功"}
        except Exception as exc:
            logger.exception("连接微信客户端失败")
            self._connected = False
            return {"connected": False, "message": f"连接失败: {exc}"}

    def disconnect(self) -> None:
        """断开连接。"""
        self._connected = False
        self._app_ref = None
        logger.info("微信客户端连接已断开")

    # ------------------------------------------------------------------
    # 消息操作
    # ------------------------------------------------------------------

    def send_text_message(self, contact_name: str, message: str) -> dict[str, Any]:
        """发送文字消息。

        流程：
        1. 激活微信窗口
        2. 使用 Cmd+F 搜索联系人
        3. 输入消息
        4. 按 Enter 发送

        Args:
            contact_name: 联系人名称
            message: 消息文本

        Returns:
            {"success": bool, "message_sent": bool, "error": str}
        """
        if not self._connected:
            return {"success": False, "message_sent": False, "error": "未连接微信客户端"}

        contact = str(contact_name or "").strip()
        text = str(message or "").strip()
        if not contact or not text:
            return {"success": False, "message_sent": False, "error": "contact_or_message_empty"}

        try:
            # 1. 激活微信窗口
            if not applescript.activate_wechat():
                return {"success": False, "message_sent": False, "error": "无法激活微信窗口"}

            # 2. 搜索联系人
            if not applescript.search_contact(contact):
                return {
                    "success": False,
                    "message_sent": False,
                    "error": f"搜索联系人失败: {contact}",
                }

            # 3. 输入消息并发送
            if not applescript.send_message_in_chat(text):
                return {
                    "success": False,
                    "message_sent": False,
                    "error": "发送消息失败",
                }

            logger.info("微信消息发送成功: contact=%s len=%d", contact, len(text))
            return {"success": True, "message_sent": True, "error": ""}
        except Exception as exc:
            logger.exception("发送微信消息异常")
            return {"success": False, "message_sent": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # 信息获取
    # ------------------------------------------------------------------

    def get_unread_count(self) -> int:
        """获取未读消息数量（从 Dock 徽标读取）。"""
        try:
            return applescript.get_wechat_dock_badge()
        except Exception:
            logger.exception("获取未读消息数量失败")
            return 0

    def get_chat_list(self) -> list[dict[str, Any]]:
        """获取最近聊天列表。

        Returns:
            [{"name": str, "unread": int, "last_message": str}]
        """
        try:
            return applescript.get_chat_list_via_accessibility()
        except Exception:
            logger.exception("获取聊天列表失败")
            return []

    def get_chat_messages(self, contact_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取与某联系人的聊天记录。

        Args:
            contact_name: 联系人名称
            limit: 最大消息数量

        Returns:
            [{"sender": str, "content": str, "timestamp": str}]
        """
        try:
            return applescript.get_chat_messages_via_accessibility(contact_name, limit)
        except Exception:
            logger.exception("获取聊天记录失败")
            return []


# ======================================================================
# DesktopAutomationService — 对外服务层
# ======================================================================


class DesktopAutomationService:
    """桌面自动化服务。

    当环境变量 KELLAI_WECHAT_AUTOMATION=1 时使用真实微信自动化实现，
    否则返回 stub 响应。
    """

    def __init__(self) -> None:
        self._automation: MacWechatAutomation | None = None
        self._use_real: bool = os.environ.get(_ENV_ENABLED, "").strip() == "1"

    @property
    def automation(self) -> MacWechatAutomation:
        """获取 MacWechatAutomation 实例（懒加载）。"""
        if self._automation is None:
            self._automation = MacWechatAutomation()
        return self._automation

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def check_connection(self) -> dict[str, Any]:
        """检查微信连接状态。

        Returns:
            {"connected": bool, "message": str}
        """
        if not self._use_real:
            return {"connected": False, "message": "桌面自动化未启用（KELLAI_WECHAT_AUTOMATION≠1）"}
        return self.automation.connect()

    # ------------------------------------------------------------------
    # 消息发送（保留原有接口）
    # ------------------------------------------------------------------

    def send_wechat_message(self, contact_name: str, message: str) -> dict[str, Any]:
        """发送微信消息。

        Args:
            contact_name: 联系人名称
            message: 消息文本

        Returns:
            {"success": bool, "message_sent": bool, "error": str}
        """
        text = str(message or "").strip()
        contact = str(contact_name or "").strip()
        if not contact or not text:
            return {"success": False, "message_sent": False, "error": "contact_or_message_empty"}

        if not self._use_real:
            logger.info("wechat send stub contact=%s len=%s", contact, len(text))
            return {
                "success": False,
                "message_sent": False,
                "error": "desktop_automation_not_configured",
                "hint": "配置 KELLAI_WECHAT_AUTOMATION=1 并接入真实发送实现",
            }

        # 确保已连接
        if not self.automation._connected:
            conn = self.automation.connect()
            if not conn.get("connected"):
                return {
                    "success": False,
                    "message_sent": False,
                    "error": f"微信连接失败: {conn.get('message', '')}",
                }

        return self.automation.send_text_message(contact, text)

    # ------------------------------------------------------------------
    # 信息获取
    # ------------------------------------------------------------------

    def get_unread_count(self) -> int:
        """获取未读消息数量。"""
        if not self._use_real:
            return 0
        return self.automation.get_unread_count()

    def get_chat_list(self) -> list[dict[str, Any]]:
        """获取最近聊天列表。"""
        if not self._use_real:
            return []
        return self.automation.get_chat_list()

    def get_chat_messages(self, contact_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取与某联系人的聊天记录。"""
        if not self._use_real:
            return []
        return self.automation.get_chat_messages(contact_name, limit)


# ======================================================================
# 单例工厂
# ======================================================================


def get_desktop_automation_service() -> DesktopAutomationService:
    """获取 DesktopAutomationService 单例。"""
    global _instance
    if _instance is None:
        _instance = DesktopAutomationService()
    return _instance
