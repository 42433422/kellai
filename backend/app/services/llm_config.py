"""Persistent LLM provider configuration for local Kellai deployments."""

from __future__ import annotations

import functools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.services.tenant_context import current_team_id, tenant_data_root


PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "custom": {
        "key_env": "KELLAI_LLM_API_KEY,OPENAI_COMPATIBLE_API_KEY,LLM_API_KEY,AI_API_KEY,MODEL_API_KEY",
        "base_url_env": "KELLAI_LLM_BASE_URL,OPENAI_COMPATIBLE_BASE_URL,OPENAI_COMPATIBLE_API_BASE,LLM_BASE_URL,AI_BASE_URL",
        "model_env": "KELLAI_LLM_MODEL,OPENAI_COMPATIBLE_MODEL,LLM_MODEL,AI_MODEL,MODEL_NAME",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "label": "自定义兼容",
    },
    "deepseek": {
        "key_env": "DEEPSEEK_API_KEY,DEEPSEEK_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL,DEEPSEEK_API_BASE,DEEPSEEK_API_URL",
        "model_env": "DEEPSEEK_MODEL,DEEPSEEK_LLM_MODEL",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "label": "DeepSeek",
    },
    "openai": {
        "key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL,OPENAI_API_BASE",
        "model_env": "OPENAI_MODEL",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "label": "OpenAI",
    },
    "qwen": {
        "key_env": "DASHSCOPE_API_KEY,QWEN_API_KEY,BAILIAN_API_KEY",
        "base_url_env": "DASHSCOPE_BASE_URL,QWEN_BASE_URL,DASHSCOPE_API_BASE,QWEN_API_BASE,BAILIAN_BASE_URL",
        "model_env": "DASHSCOPE_MODEL,QWEN_MODEL,BAILIAN_MODEL",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "label": "通义千问",
    },
    "moonshot": {
        "key_env": "MOONSHOT_API_KEY,KIMI_API_KEY",
        "base_url_env": "MOONSHOT_BASE_URL,KIMI_BASE_URL",
        "model_env": "MOONSHOT_MODEL,KIMI_MODEL",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "label": "Moonshot",
    },
    "siliconflow": {
        "key_env": "SILICONFLOW_API_KEY,SILICON_FLOW_API_KEY",
        "base_url_env": "SILICONFLOW_BASE_URL,SILICON_FLOW_BASE_URL",
        "model_env": "SILICONFLOW_MODEL,SILICON_FLOW_MODEL",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "label": "SiliconFlow",
    },
    "ark": {
        "key_env": "ARK_API_KEY,VOLCENGINE_ARK_API_KEY,VOLCENGINE_API_KEY,DOUBAO_API_KEY,DOUBAO_ARK_API_KEY",
        "base_url_env": "ARK_BASE_URL,ARK_API_BASE,VOLCENGINE_ARK_BASE_URL,VOLCENGINE_ARK_API_BASE,VOLCENGINE_BASE_URL,VOLCENGINE_API_BASE,DOUBAO_BASE_URL,DOUBAO_API_BASE,DOUBAO_ARK_BASE_URL,DOUBAO_ARK_API_BASE",
        "model_env": "ARK_MODEL,VOLCENGINE_ARK_MODEL,VOLCENGINE_MODEL,DOUBAO_MODEL,DOUBAO_ARK_MODEL",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1-6",
        "label": "火山方舟",
    },
    "zhipu": {
        "key_env": "ZHIPU_API_KEY,ZHIPUAI_API_KEY,GLM_API_KEY,BIGMODEL_API_KEY",
        "base_url_env": "ZHIPU_BASE_URL,ZHIPU_API_BASE,ZHIPUAI_BASE_URL,ZHIPUAI_API_BASE,GLM_BASE_URL,GLM_API_BASE,BIGMODEL_BASE_URL,BIGMODEL_API_BASE",
        "model_env": "ZHIPU_MODEL,ZHIPUAI_MODEL,GLM_MODEL,BIGMODEL_MODEL",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "label": "智谱 GLM",
    },
    "minimax": {
        "key_env": "MINIMAX_API_KEY,MINIMAX_GROUP_API_KEY",
        "base_url_env": "MINIMAX_BASE_URL,MINIMAX_API_BASE",
        "model_env": "MINIMAX_MODEL",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
        "label": "MiniMax",
    },
    "xai": {
        "key_env": "XAI_API_KEY,GROK_API_KEY",
        "base_url_env": "XAI_BASE_URL,XAI_API_BASE,GROK_BASE_URL,GROK_API_BASE",
        "model_env": "XAI_MODEL,GROK_MODEL",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3-mini",
        "label": "xAI Grok",
    },
    "mimo": {
        "key_env": "MIMO_API_KEY,XIAOMI_MIMO_API_KEY,XIAOMIMIMO_API_KEY,MI_MIMO_API_KEY",
        "base_url_env": "MIMO_BASE_URL,MIMO_API_BASE,XIAOMI_MIMO_BASE_URL,XIAOMI_MIMO_API_BASE,XIAOMIMIMO_BASE_URL,XIAOMIMIMO_API_BASE,MIMO_TOKEN_PLAN_BASE_URL,MIMO_TOKEN_PLAN_API_BASE",
        "model_env": "MIMO_MODEL,XIAOMI_MIMO_MODEL,XIAOMIMIMO_MODEL,MI_MIMO_MODEL",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "label": "Xiaomi MiMo",
    },
}

AUTO_PROVIDER_ORDER = (
    "custom",
    "deepseek",
    "openai",
    "qwen",
    "moonshot",
    "siliconflow",
    "ark",
    "zhipu",
    "minimax",
    "mimo",
    "xai",
)
_LAST_PROBE_BY_TEAM: dict[int, dict[str, Any]] = {}


def _last_probe() -> dict[str, Any]:
    return dict(_LAST_PROBE_BY_TEAM.get(current_team_id()) or {})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_root() -> Path:
    root = tenant_data_root(required=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dotenv_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = (os.environ.get("KELLAI_ENV_FILE") or "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    root = _project_root()
    paths.extend(
        [
            root / ".env",
            root / ".env.local",
            root / ".env.production",
            root / "backend" / ".env",
            root / "backend" / ".env.local",
            root / "backend" / ".env.production",
            root / "desktop" / ".env",
            root / "desktop" / ".env.local",
            root / "desktop" / ".env.production",
        ]
    )
    return paths


@functools.lru_cache(maxsize=8)
def _read_dotenv(path_value: str) -> dict[str, str]:
    path = Path(path_value)
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        out[key] = value
    return out


def _env_name_candidates(name: str) -> list[str]:
    key = str(name or "").strip()
    if not key:
        return []
    candidates = [key]
    vite_key = f"VITE_{key}"
    if vite_key not in candidates:
        candidates.append(vite_key)
    return candidates


def _env_value(*names: str) -> str:
    for name in names:
        for key in _env_name_candidates(str(name or "")):
            value = (os.environ.get(key) or "").strip()
            if value:
                return value
    for path in _dotenv_paths():
        data = _read_dotenv(str(path))
        for name in names:
            for key in _env_name_candidates(str(name or "")):
                value = str(data.get(key) or "").strip()
                if value:
                    return value
    return ""


def _env_names(raw: str) -> list[str]:
    return [name.strip() for name in str(raw or "").split(",") if name.strip()]


def _env_key_value(*names: str) -> tuple[str, str]:
    all_candidates: list[str] = []
    for name in names:
        for item in _env_names(name):
            for candidate in _env_name_candidates(item):
                if candidate not in all_candidates:
                    all_candidates.append(candidate)
    if not all_candidates:
        return "", ""

    for candidate in all_candidates:
        value = (os.environ.get(candidate) or "").strip()
        if value:
            return candidate, value
    for path in _dotenv_paths():
        data = _read_dotenv(str(path))
        for candidate in all_candidates:
            value = str(data.get(candidate) or "").strip()
            if value:
                return candidate, value
    return "", ""


def _config_path() -> Path:
    return _data_root() / "llm_config.json"


def trust_env_proxy() -> bool:
    """Whether LLM HTTP calls should inherit system proxy variables."""
    return str(os.environ.get("KELLAI_LLM_TRUST_ENV_PROXY") or "").strip().lower() in {"1", "true", "yes", "on"}


def needs_mimo_thinking_disabled(provider: str, base_url: str = "") -> bool:
    return normalize_provider(provider) == "mimo" or "xiaomimimo.com" in str(base_url or "").lower()


def _read_disk() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_disk(data: dict[str, Any]) -> dict[str, Any]:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def normalize_provider(provider: str | None) -> str:
    value = str(provider or "deepseek").strip().lower()
    aliases = {
        "dashscope": "qwen",
        "tongyi": "qwen",
        "aliyun": "qwen",
        "openai-compatible": "custom",
        "compatible": "custom",
        "自定义": "custom",
        "兼容": "custom",
        "volcengine": "ark",
        "volcengine-ark": "ark",
        "volcengine_ark": "ark",
        "huoshan": "ark",
        "doubao": "ark",
        "doubao-ark": "ark",
        "doubao_ark": "ark",
        "火山": "ark",
        "方舟": "ark",
        "zhipuai": "zhipu",
        "glm": "zhipu",
        "bigmodel": "zhipu",
        "智谱": "zhipu",
        "grok": "xai",
        "xiaomi": "mimo",
        "xiaomi-mimo": "mimo",
        "xiaomi_mimo": "mimo",
        "xiaomimimo": "mimo",
        "mi-mimo": "mimo",
        "mi_mimo": "mimo",
        "小米": "mimo",
        "xcauto": "auto",
        "auto": "auto",
    }
    value = aliases.get(value, value)
    if value == "auto" or value in PROVIDER_CONFIGS:
        return value
    return "deepseek"


def _is_provider_name(value: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return False
    aliases = {
        "dashscope",
        "tongyi",
        "aliyun",
        "openai-compatible",
        "compatible",
        "自定义",
        "兼容",
        "volcengine",
        "volcengine-ark",
        "volcengine_ark",
        "huoshan",
        "doubao",
        "doubao-ark",
        "doubao_ark",
        "火山",
        "方舟",
        "zhipuai",
        "glm",
        "bigmodel",
        "智谱",
        "grok",
        "xiaomi",
        "xiaomi-mimo",
        "xiaomi_mimo",
        "xiaomimimo",
        "mi-mimo",
        "mi_mimo",
        "小米",
        "xcauto",
        "auto",
    }
    return raw in aliases or raw in PROVIDER_CONFIGS


def _provider_defaults(provider: str) -> dict[str, str]:
    base = dict(PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["deepseek"]))
    base_url_envs = _env_names(str(base.get("base_url_env") or ""))
    model_envs = _env_names(str(base.get("model_env") or ""))
    base["base_url"] = _env_value(*base_url_envs) or base["base_url"]
    base["model"] = _env_value(*model_envs) or base["model"]
    return base


def public_config() -> dict[str, Any]:
    cfg = _read_disk()
    effective = effective_config()
    provider = normalize_provider(str(cfg.get("provider") or effective.get("provider") or "deepseek"))
    api_key = str(cfg.get("api_key") or "")
    key_prefix = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) >= 12 else ("已保存" if api_key else "")
    disk_probe = cfg.get("last_probe") if isinstance(cfg.get("last_probe"), dict) else {}
    probe = disk_probe or _last_probe()
    ready = bool(effective.get("api_key"))
    connected = bool(probe.get("success")) if probe else False
    message = "LLM 已连通" if connected else ("已保存 Key，尚未通过连通验证" if ready else "请先在设置页保存真实 LLM API Key")
    return {
        "provider": provider,
        "model": str(cfg.get("model") or effective.get("model") or ""),
        "base_url": str(cfg.get("base_url") or effective.get("base_url") or ""),
        "key_prefix": key_prefix or effective.get("key_prefix", ""),
        "ready": ready,
        "connected": connected,
        "verified": connected,
        "source": effective.get("source", ""),
        "lastProbe": probe,
        "autoReplyEnabled": bool(cfg.get("auto_reply_enabled")),
        "autoReplyStages": cfg.get("auto_reply_stages") if isinstance(cfg.get("auto_reply_stages"), list) else [],
        "confirmScenarios": cfg.get("confirm_scenarios") if isinstance(cfg.get("confirm_scenarios"), list) else [],
        "message": message,
    }


def diagnostics() -> dict[str, Any]:
    """Return redacted LLM configuration diagnostics for support and delivery checks."""

    saved = _read_disk()
    effective = effective_config()
    dotenvs: list[dict[str, Any]] = []
    for path in _dotenv_paths():
        data = _read_dotenv(str(path))
        dotenvs.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "llm_keys_present": sorted(
                    key
                    for key, value in data.items()
                    if value
                    and any(
                        part in key.upper()
                        for part in (
                            "LLM",
                            "OPENAI",
                            "DEEPSEEK",
                            "DASHSCOPE",
                            "QWEN",
                            "BAILIAN",
                            "MOONSHOT",
                            "KIMI",
                            "SILICONFLOW",
                            "SILICON_FLOW",
                            "ARK",
                            "VOLCENGINE",
                            "DOUBAO",
                            "ZHIPU",
                            "ZHIPUAI",
                            "GLM",
                            "BIGMODEL",
                            "MINIMAX",
                            "MIMO",
                            "XIAOMI",
                            "XIAOMIMIMO",
                            "XAI",
                            "GROK",
                        )
                    )
                ),
            }
        )

    env_presence: dict[str, bool] = {}
    for provider, meta in PROVIDER_CONFIGS.items():
        names: list[str] = []
        for raw in (meta.get("key_env", ""), meta.get("base_url_env", ""), meta.get("model_env", "")):
            names.extend([name.strip() for name in raw.split(",") if name.strip()])
        for name in names:
            env_presence[name] = bool(_env_value(name))

    probe = (
        saved.get("last_probe")
        if isinstance(saved.get("last_probe"), dict)
        else _last_probe()
    )
    return {
        "config_path": str(_config_path()),
        "config_exists": _config_path().is_file(),
        "saved_provider": str(saved.get("provider") or ""),
        "saved_model": str(saved.get("model") or ""),
        "saved_has_api_key": bool(str(saved.get("api_key") or "").strip()),
        "effective_provider": str(effective.get("provider") or ""),
        "effective_model": str(effective.get("model") or ""),
        "effective_base_url": str(effective.get("base_url") or ""),
        "effective_source": str(effective.get("source") or ""),
        "effective_has_api_key": bool(effective.get("api_key")),
        "dotenvs": dotenvs,
        "env_presence": env_presence,
        "last_probe": {
            "success": bool(probe.get("success")) if isinstance(probe, dict) else False,
            "checked_at": str(probe.get("checked_at") or "") if isinstance(probe, dict) else "",
            "provider": str(probe.get("provider") or "") if isinstance(probe, dict) else "",
            "model": str(probe.get("model") or "") if isinstance(probe, dict) else "",
            "latency_ms": int(probe.get("latency_ms") or 0) if isinstance(probe, dict) else 0,
            "error": str(probe.get("error") or "")[:300] if isinstance(probe, dict) else "",
        },
    }


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_disk()
    provider = normalize_provider(str(payload.get("provider") or payload.get("model") or current.get("provider") or "deepseek"))
    provider_defaults = _provider_defaults(provider if provider != "auto" else "deepseek")
    raw_model = str(payload.get("llm_model") or payload.get("model_name") or payload.get("model") or "").strip()
    if raw_model and _is_provider_name(raw_model):
        raw_model = ""

    next_cfg = dict(current)
    next_cfg["provider"] = provider
    next_cfg["model"] = str(raw_model or current.get("model") or provider_defaults["model"]).strip()
    next_cfg["base_url"] = str(payload.get("base_url") or current.get("base_url") or provider_defaults["base_url"]).strip()

    api_key = payload.get("api_key")
    if api_key is not None:
        key_value = str(api_key).strip()
        if key_value:
            next_cfg["api_key"] = key_value

    next_cfg["auto_reply_enabled"] = bool(payload.get("auto_reply_enabled", current.get("auto_reply_enabled", False)))
    if isinstance(payload.get("auto_reply_stages"), list):
        next_cfg["auto_reply_stages"] = [str(x) for x in payload.get("auto_reply_stages") if str(x).strip()]
    else:
        next_cfg.setdefault("auto_reply_stages", [])
    if isinstance(payload.get("confirm_scenarios"), list):
        next_cfg["confirm_scenarios"] = [str(x) for x in payload.get("confirm_scenarios") if str(x).strip()]
    else:
        next_cfg.setdefault("confirm_scenarios", [])
    next_cfg["updated_at"] = _now_iso()

    _write_disk(next_cfg)
    return public_config()


def probe_llm_connection(*, update_disk: bool = True, timeout_sec: float = 15.0) -> dict[str, Any]:
    """Call the configured provider once and return a sanitized connectivity report."""
    cfg = effective_config()
    if not cfg.get("api_key"):
        result = {
            "success": False,
            "connected": False,
            "checked_at": _now_iso(),
            "provider": "",
            "model": "",
            "latency_ms": 0,
            "error": "未配置真实 LLM API Key",
        }
    else:
        provider = str(cfg.get("provider") or "")
        model = str(cfg.get("model") or "")
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout_sec, trust_env=trust_env_proxy()) as client:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是连通性检测助手，只输出 OK。"},
                        {"role": "user", "content": "请回复 OK"},
                    ],
                    "temperature": 0,
                    "max_tokens": 64,
                }
                if needs_mimo_thinking_disabled(provider, base_url):
                    payload["thinking"] = {"type": "disabled"}

                resp = client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {cfg['api_key']}",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                message = ((data.get("choices") or [{}])[0].get("message") or {})
                content = str(message.get("content") or message.get("reasoning_content") or "").strip()
            result = {
                "success": bool(content),
                "connected": bool(content),
                "checked_at": _now_iso(),
                "provider": provider,
                "model": model,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": "" if content else "模型返回为空",
            }
        except httpx.TimeoutException:
            result = {
                "success": False,
                "connected": False,
                "checked_at": _now_iso(),
                "provider": provider,
                "model": model,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": "LLM 连通测试超时",
            }
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = str(exc.response.json())[:300]
            except Exception:
                detail = exc.response.text[:300]
            result = {
                "success": False,
                "connected": False,
                "checked_at": _now_iso(),
                "provider": provider,
                "model": model,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": f"HTTP {exc.response.status_code}: {detail}",
            }
        except Exception as exc:
            result = {
                "success": False,
                "connected": False,
                "checked_at": _now_iso(),
                "provider": provider,
                "model": model,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc)[:300],
            }

    _LAST_PROBE_BY_TEAM[current_team_id()] = result
    if update_disk:
        disk = _read_disk()
        if disk:
            disk["last_probe"] = result
            disk["updated_at"] = _now_iso()
            _write_disk(disk)
    return result


def _provider_candidates(selected: str) -> list[str]:
    provider = normalize_provider(selected)
    if provider == "auto":
        return list(AUTO_PROVIDER_ORDER)
    return [provider] + [p for p in AUTO_PROVIDER_ORDER if p != provider]


def effective_config() -> dict[str, Any]:
    saved = _read_disk()
    selected = normalize_provider(str(saved.get("provider") or "deepseek"))
    saved_key = str(saved.get("api_key") or "").strip()

    for provider in _provider_candidates(selected):
        defaults = _provider_defaults(provider)
        key_envs = _env_names(str(defaults.get("key_env") or ""))
        source, env_key = _env_key_value(*key_envs)
        if env_key:
            return {
                "provider": provider,
                "api_key": env_key,
                "base_url": str(saved.get("base_url") or defaults["base_url"]),
                "model": str(saved.get("model") or defaults["model"]),
                "source": source or defaults["key_env"],
                "key_prefix": f"{source or defaults['key_env']} 环境变量",
            }

    if saved_key:
        provider = selected if selected != "auto" else "deepseek"
        defaults = _provider_defaults(provider)
        return {
            "provider": provider,
            "api_key": saved_key,
            "base_url": str(saved.get("base_url") or defaults["base_url"]),
            "model": str(saved.get("model") or defaults["model"]),
            "source": "saved_config",
            "key_prefix": f"{saved_key[:6]}...{saved_key[-4:]}" if len(saved_key) >= 12 else "已保存",
        }

    return {}
