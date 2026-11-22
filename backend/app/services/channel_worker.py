"""Local account inbox polling only. Sending always originates in the host."""
from __future__ import annotations

import asyncio
import logging

from app.services.auth import workspace_id
from app.services.tenant_context import tenant_scope

logger = logging.getLogger(__name__)


async def run_once() -> dict:
    from app.channels import ChannelRegistry
    from app.channels.config_store import list_connections
    from app.services.channel_ingest import sync_inbox
    from app.services.message_store import migrate_account_bindings
    from app.services.outbound_delivery import ensure_schema

    summary = {"accounts": 0, "messages": 0, "errors": 0}
    with tenant_scope(workspace_id()):
        ensure_schema()
        migrate_account_bindings()
        capabilities = {row["channel_type"]: row["capabilities"] for row in ChannelRegistry().list_channels()}
        for account in list_connections():
            if not account.get("enabled") or not capabilities.get(account["channel_type"], {}).get("receive"):
                continue
            try:
                result = await sync_inbox(connection_id=account["connection_id"])
                summary["accounts"] += 1
                summary["messages"] += int((result.get("data") or {}).get("synced") or 0)
            except Exception as exc:
                logger.warning("账号收件待重试: %s (%s)", account["connection_id"], type(exc).__name__)
                summary["errors"] += 1
    return summary


async def run(stop: asyncio.Event, *, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            await run_once()
        except Exception as exc:
            logger.warning("账号工具收件待重试 (%s)", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
