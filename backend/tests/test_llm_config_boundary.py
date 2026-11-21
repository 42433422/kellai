from __future__ import annotations

import httpx
import pytest

from app.services import llm_config
from app.services.tenant_context import tenant_scope


@pytest.fixture(autouse=True)
def isolated_model_config(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(llm_config, "_dotenv_paths", lambda: [])
    for meta in llm_config.PROVIDER_CONFIGS.values():
        for field in ("key_env", "base_url_env", "model_env"):
            for name in llm_config._env_names(meta[field]):
                monkeypatch.delenv(name, raising=False)
                monkeypatch.delenv("VITE_" + name, raising=False)
    llm_config._LAST_PROBE_BY_TEAM.clear()


def test_tenant_url_cannot_receive_shared_environment_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-shared-secret")
    with tenant_scope(7):
        public = llm_config.save_config({"provider": "deepseek", "base_url": "https://tenant-gateway.test/v1"})
        assert public["ready"] is False
        assert llm_config.effective_config() == {}
        monkeypatch.setattr(httpx, "Client", lambda **_kw: pytest.fail("untrusted endpoint must not be contacted"))
        assert llm_config.probe_llm_connection()["success"] is False


def test_explicit_tenant_key_precedes_shared_server_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-shared-secret")
    with tenant_scope(7):
        llm_config.save_config({"provider": "custom", "base_url": "https://tenant-gateway.test/v1", "api_key": "tenant-owned-secret"})
        config = llm_config.effective_config()
        assert config["source"] == "saved_config"
        assert config["api_key"] == "tenant-owned-secret"
        assert config["base_url"] == "https://tenant-gateway.test/v1"


def test_changing_endpoint_without_key_does_not_move_saved_secret():
    with tenant_scope(7):
        llm_config.save_config({"provider": "custom", "base_url": "https://first.test/v1", "api_key": "first-secret"})
        llm_config.save_config({"provider": "custom", "base_url": "https://second.test/v1", "api_key": ""})
        assert llm_config.effective_config() == {}
        assert not llm_config._read_disk().get("api_key")


def test_same_endpoint_model_change_preserves_key_and_resets_probe():
    with tenant_scope(7):
        llm_config.save_config({"provider": "custom", "base_url": "https://first.test/v1", "api_key": "first-secret"})
        disk = llm_config._read_disk()
        disk["last_probe"] = {"success": True}
        llm_config._write_disk(disk)
        llm_config._LAST_PROBE_BY_TEAM[7] = {"success": True}
        public = llm_config.save_config({"provider": "custom", "model": "new-model", "api_key": ""})
        assert llm_config.effective_config()["api_key"] == "first-secret"
        assert public["connected"] is False


def test_provider_change_resets_previous_endpoint_model_and_key():
    with tenant_scope(7):
        llm_config.save_config({"provider": "custom", "base_url": "https://first.test/v1", "model": "old-model", "api_key": "first-secret"})
        public = llm_config.save_config({"provider": "deepseek", "api_key": ""})
        assert public["base_url"] == llm_config.PROVIDER_CONFIGS["deepseek"]["base_url"]
        assert public["model"] == llm_config.PROVIDER_CONFIGS["deepseek"]["model"]
        assert llm_config.effective_config() == {}


def test_server_controlled_gateway_and_default_resources_still_work(monkeypatch):
    monkeypatch.setenv("KELLAI_LLM_API_KEY", "server-gateway-secret")
    monkeypatch.setenv("KELLAI_LLM_BASE_URL", "https://operator-gateway.test/v1")
    monkeypatch.setenv("KELLAI_LLM_MODEL", "operator-model")
    with tenant_scope(7):
        config = llm_config.effective_config()
        assert config["provider"] == "custom" and config["model"] == "operator-model"
        assert config["base_url"] == "https://operator-gateway.test/v1"
        llm_config.save_config({"provider": "auto"})
        assert llm_config.effective_config()["api_key"] == "server-gateway-secret"


def test_shared_key_must_match_full_endpoint_not_hostname_only(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-shared-secret")
    with tenant_scope(7):
        for endpoint in ("http://api.deepseek.com/v1", "https://api.deepseek.com.evil.test/v1",
                         "https://api.deepseek.com/v1/redirect", "https://api.deepseek.com/v1?target=other"):
            llm_config.save_config({"provider": "deepseek", "base_url": endpoint})
            assert llm_config.effective_config() == {}
        llm_config.save_config({"provider": "deepseek", "base_url": "https://api.deepseek.com/v1/"})
        assert llm_config.effective_config()["api_key"] == "server-shared-secret"


def test_old_saved_untrusted_url_does_not_capture_fallback_provider_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-secret")
    with tenant_scope(7):
        llm_config._write_disk({"provider": "deepseek", "base_url": "https://legacy-tenant.test/v1", "model": "deepseek-chat"})
        assert llm_config.effective_config() == {}


def test_tenant_saved_key_is_not_reused_by_other_team():
    with tenant_scope(7):
        llm_config.save_config({"provider": "custom", "base_url": "https://first.test/v1", "api_key": "team-seven-key"})
    with tenant_scope(8):
        assert llm_config.effective_config() == {}


@pytest.mark.parametrize("secret", ["server-secret-never-displayed", "server-secret-never-displayed" * 30])
def test_probe_error_cannot_echo_shared_secret(monkeypatch, secret):
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    transport = httpx.MockTransport(lambda request: httpx.Response(
        401, json={"error": "bad authorization " + request.headers["Authorization"]}))
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=transport, **kwargs))
    with tenant_scope(7):
        llm_config.save_config({"provider": "deepseek"})
        report = llm_config.probe_llm_connection()
        assert report["success"] is False
        assert "server-secret-never-displayed" not in report["error"]
        assert "[redacted]" in report["error"]
        assert "server-secret-never-displayed" not in str(llm_config._read_disk())
