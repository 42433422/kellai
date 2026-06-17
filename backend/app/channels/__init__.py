"""统一渠道适配层。"""
from __future__ import annotations

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.douyin import DouyinAdapter
from app.channels.miniapp import MiniAppAdapter
from app.channels.phone import PhoneAdapter
from app.channels.registry import ChannelRegistry
from app.channels.wecom import WeComAdapter
from app.channels.wechat import WeChatAdapter
# 电商平台
from app.channels.pdd import PddAdapter
from app.channels.taobao import TaobaoAdapter
from app.channels.jd import JdAdapter
from app.channels.alibaba import AlibabaAdapter
# 海外
from app.channels.whatsapp import WhatsAppAdapter
from app.channels.telegram import TelegramAdapter
from app.channels.line import LineAdapter

__all__ = [
    "ChannelAdapter",
    "ChannelRegistry",
    "UnifiedMessage",
    "WeComAdapter",
    "WeChatAdapter",
    "PhoneAdapter",
    "DouyinAdapter",
    "MiniAppAdapter",
    "PddAdapter",
    "TaobaoAdapter",
    "JdAdapter",
    "AlibabaAdapter",
    "WhatsAppAdapter",
    "TelegramAdapter",
    "LineAdapter",
]


def _auto_register() -> None:
    """自动注册所有内置渠道适配器。"""
    reg = ChannelRegistry()
    # 即时通讯
    reg.register("wework", WeComAdapter)
    reg.register("wechat", WeChatAdapter)
    reg.register("phone", PhoneAdapter)
    reg.register("douyin", DouyinAdapter)
    reg.register("miniprogram", MiniAppAdapter)
    # 电商平台
    reg.register("pdd", PddAdapter)
    reg.register("taobao", TaobaoAdapter)
    reg.register("jd", JdAdapter)
    reg.register("alibaba", AlibabaAdapter)
    # 海外
    reg.register("whatsapp", WhatsAppAdapter)
    reg.register("telegram", TelegramAdapter)
    reg.register("line", LineAdapter)


_auto_register()
