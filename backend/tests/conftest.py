"""Isolated tool integration fixtures; no real account or provider I/O."""
import httpx
import pytest_asyncio
from cryptography.fernet import Fernet

from app.channels import ChannelRegistry
from app.services import xcmax_integration


@pytest_asyncio.fixture
async def tool_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_WORKSPACE_ID", "1")
    monkeypatch.setenv("KELLAI_VAULT_KEY", Fernet.generate_key().decode())
    await ChannelRegistry().close_all()
    xcmax_integration._HANDOFFS.clear()

    async def unexpected_network(*args, **kwargs):
        raise AssertionError("Integration tests must not contact live account providers")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unexpected_network)
    yield tmp_path
    await ChannelRegistry().close_all()
    xcmax_integration._HANDOFFS.clear()
