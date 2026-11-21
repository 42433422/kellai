"""统一渠道适配层。"""
from __future__ import annotations

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.douyin import DouyinAdapter
from app.channels.miniapp import MiniAppAdapter
from app.channels.phone import PhoneAdapter, PHONE_CONFIG_SCHEMA
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
from app.channels.chatwoot import ChatwootAdapter
from app.channels.capabilities import CAPABILITIES, CHATWOOT_CONFIG_SCHEMA

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
    "ChatwootAdapter",
]


def _auto_register() -> None:
    """自动注册所有内置渠道适配器。"""
    reg = ChannelRegistry()
    # 即时通讯
    reg.register("wework", WeComAdapter, capabilities=CAPABILITIES["wework"])
    reg.register("wechat", WeChatAdapter, capabilities=CAPABILITIES["wechat"])
    reg.register("phone", PhoneAdapter, config_schema=PHONE_CONFIG_SCHEMA, capabilities=CAPABILITIES["phone"])
    reg.register("douyin", DouyinAdapter, capabilities=CAPABILITIES["douyin"])
    reg.register("miniprogram", MiniAppAdapter, capabilities=CAPABILITIES["miniprogram"])
    # 电商平台
    reg.register("pdd", PddAdapter, capabilities=CAPABILITIES["pdd"])
    reg.register("taobao", TaobaoAdapter, capabilities=CAPABILITIES["taobao"])
    reg.register("jd", JdAdapter, capabilities=CAPABILITIES["jd"])
    reg.register("alibaba", AlibabaAdapter, capabilities=CAPABILITIES["alibaba"])
    # 海外
    reg.register("whatsapp", WhatsAppAdapter, capabilities=CAPABILITIES["whatsapp"])
    reg.register("telegram", TelegramAdapter, capabilities=CAPABILITIES["telegram"])
    reg.register("line", LineAdapter, capabilities=CAPABILITIES["line"])
    reg.register("chatwoot", ChatwootAdapter, config_schema=CHATWOOT_CONFIG_SCHEMA,
                 capabilities=CAPABILITIES["chatwoot"])


_auto_register()
