"""Mac 微信桌面自动化模块。"""

from __future__ import annotations

from .service import DesktopAutomationService, MacWechatAutomation, get_desktop_automation_service

__all__ = [
    "DesktopAutomationService",
    "MacWechatAutomation",
    "get_desktop_automation_service",
]
