"""Small consumer for the existing inbox/auto-reply queues.

The CRM server handles API transports; the Tauri bridge alone claims native
Douyin jobs. A Douyin bridge server only relays its durable inbox to the CRM
consumer, so it must not advance that consumer's acknowledgement cursor or
create its own reply job. SQLite leases coordinate the local reply workers.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from app.services.tenant_context import tenant_scope

logger = logging.getLogger(__name__)


def _owners() -> list[dict]:
    from app.services.auth import _conn
    with _conn() as connection:
        rows = connection.execute(
            "SELECT id, team_id, role FROM kellai_users "
            "WHERE is_active=1 AND team_id>0 AND role IN ('owner','admin') ORDER BY id"
        ).fetchall()
    owners: dict[int, dict] = {}
    for row in rows:
        owners.setdefault(int(row["team_id"]), dict(row))
    return list(owners.values())


async def run_once() -> dict:
    from app.channels import ChannelRegistry
    from app.channels.config_store import get_all
    from app.services.auth import get_user
    from app.services.auto_reply_runtime import claim_jobs, complete_job
    from app.services.channel_ingest import sync_inbox
    from app.services.douyin_channel import bridge_server_enabled
    from app.services.messaging import send

    summary = {"tenants": 0, "jobs": 0, "errors": 0}
    for owner in _owners():
        team_id = int(owner["team_id"])
        with tenant_scope(team_id):
            try:
                server_channels = []
                for row in ChannelRegistry().list_channels():
                    kind = row["channel_type"]
                    # The remote inbox has one downstream acknowledgement
                    # cursor. Its bridge process must leave ownership with the
                    # desktop/CRM consumer, just like the webhook ingress does.
                    if kind == "douyin" and bridge_server_enabled():
                        continue
                    capability = row.get("capabilities") or {}
                    config = get_all(kind)
                    if not config.get("enabled"):
                        continue
                    if capability.get("receive"):
                        synced = await sync_inbox(team_id=team_id, channel_type=kind)
                        if not synced.get("success"):
                            summary["errors"] += 1
                    # A hybrid catalog entry is resolved per recipient before
                    # a lease is acquired. It must not exclude official Douyin
                    # API jobs, or lease native jobs that this process cannot run.
                    if capability.get("auto_reply") and capability.get("transport") in {"api", "hybrid"}:
                        server_channels.append(kind)
                summary["tenants"] += 1
                jobs = await asyncio.to_thread(claim_jobs, team_id=team_id, limit=3,
                                              channel_types=server_channels, transport="api")
                for job in jobs:
                    body = SimpleNamespace(
                        customer_id=job["customer_id"], channel_type=job["channel_type"],
                        contact_id=job["contact_id"], content=job["reply_content"],
                        client_request_id=job["delivery_key"], desktop_result=None, delivery_token="",
                        auto_reply_inbound_id=job["inbound_message_id"],
                        auto_reply_lease_token=job["lease_token"],
                    )
                    try:
                        await send(body, user=get_user(int(owner["id"])), native_allowed=False)
                        summary["jobs"] += 1
                    except Exception:
                        logger.exception("自动回复处理未完成: team=%s", team_id)
                        complete_job(
                            job["inbound_message_id"], success=False, error="worker_send_incomplete",
                            team_id=team_id, lease_token=job["lease_token"],
                            delivery_key=job["delivery_key"],
                        )
                        summary["errors"] += 1
            except Exception:
                logger.exception("渠道工作循环失败: team=%s", team_id)
                summary["errors"] += 1
    return summary


async def run(stop: asyncio.Event, *, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            await run_once()
        except Exception:
            logger.exception("渠道工作循环暂不可用")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
