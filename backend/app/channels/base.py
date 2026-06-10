"""统一渠道适配层 — 基类与数据模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class UnifiedMessage(BaseModel):
    """统一消息数据模型。"""

    id: str
    customer_id: int
    channel_type: str
    contact_id: str
    contact_name: str
    direction: str  # "inbound" / "outbound"
    content: str
    content_type: str = "text"  # text / image / file
    metadata: dict = {}
    created_at: str


class ChannelAdapter(ABC):
    """统一渠道适配器基类。"""

    channel_type: str  # "wechat", "wecom", "phone", "douyin", "miniapp"

    @abstractmethod
    async def send_message(self, contact_id: str, content: str, **kwargs) -> dict:
        """发送消息，返回 {"success": bool, "message_id": str, "error": str}。"""

    @abstractmethod
    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """获取新消息。"""

    @abstractmethod
    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        """获取联系人/群列表。"""

    @abstractmethod
    async def test_connection(self) -> dict:
        """测试渠道连接，返回 {"connected": bool, "message": str}。"""
