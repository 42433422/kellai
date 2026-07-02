"""Cloud text-to-speech runtime.

Primary provider: Xiaomi MiMo V2.5 TTS.
Fallback provider: Microsoft Azure Speech when explicitly configured.
No local/macOS TTS fallback is used.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

import requests

logger = logging.getLogger(__name__)

MAX_TTS_CHARS = 900
DEFAULT_RATE = 185
TTS_CACHE_VERSION = "v1"
TTS_CACHE_DIRNAME = "tts_recordings"
TTS_CACHE_MAX_FILES = 240

DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MIMO_MODEL = "mimo-v2.5-tts"
DEFAULT_MIMO_VOICE = "冰糖"
DEFAULT_MIMO_STYLE = "用自然清晰、亲和专业的中文女声播报，适合软件教程讲解。语速适中，吐字清楚。"

DEFAULT_MICROSOFT_VOICE = "zh-CN-XiaoxiaoNeural"
MICROSOFT_OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
TTS_USER_AGENT = "kellai-desktop"


@dataclass(frozen=True)
class MimoTTSConfig:
    key: str
    base_url: str
    model: str
    voice: str
    style: str

    @property
    def configured(self) -> bool:
        return bool(self.key)


@dataclass(frozen=True)
class MicrosoftTTSConfig:
    key: str
    region: str
    endpoint: str
    voice: str

    @property
    def configured(self) -> bool:
        return bool(self.key and (self.region or self.endpoint))


@dataclass(frozen=True)
class TTSAudioResult:
    audio: bytes
    provider: str
    voice: str
    model: str = ""
    region: str = ""
    cached: bool = False
    cache_key: str = ""
    cache_path: str = ""


def _env_value(*names: str) -> str:
    try:
        from app.services.llm_config import _env_value as read_project_env

        return read_project_env(*names)
    except Exception:
        for name in names:
            value = (os.environ.get(name) or "").strip()
            if value:
                return value
        return ""


def _saved_mimo_llm_config() -> dict[str, str]:
    try:
        from app.services.llm_config import effective_config, normalize_provider

        config = effective_config()
        provider = normalize_provider(str(config.get("provider") or ""))
    except Exception:
        return {}
    base_url = str(config.get("base_url") or "").strip()
    if provider != "mimo" and "xiaomimimo.com" not in base_url.lower():
        return {}
    return {
        "key": str(config.get("api_key") or "").strip(),
        "base_url": base_url,
    }


def _clean_text(text: str) -> str:
    content = " ".join((text or "").replace("\u00a0", " ").split())
    return content[:MAX_TTS_CHARS]


def _safe_rate(rate: int) -> int:
    try:
        raw = int(rate or DEFAULT_RATE)
    except Exception:
        raw = DEFAULT_RATE
    return max(120, min(raw, 260))


def _data_root() -> Path:
    configured = (os.environ.get("KELLAI_DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "data"


def _tts_cache_dir() -> Path:
    cache_dir = _data_root() / TTS_CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _tts_cache_key(payload: dict) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tts_cache_paths(cache_key: str) -> tuple[Path, Path]:
    cache_dir = _tts_cache_dir()
    return cache_dir / f"{cache_key}.wav", cache_dir / f"{cache_key}.json"


def _read_cached_audio(cache_key: str) -> TTSAudioResult | None:
    try:
        audio_path, meta_path = _tts_cache_paths(cache_key)
        if not audio_path.exists() or not meta_path.exists() or audio_path.stat().st_size <= 64:
            return None
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        provider = str(metadata.get("provider") or "")
        voice = str(metadata.get("voice") or "")
        if not provider or not voice:
            return None
        audio = audio_path.read_bytes()
        now = time.time()
        os.utime(audio_path, (now, now))
        os.utime(meta_path, (now, now))
        return TTSAudioResult(
            audio=audio,
            provider=provider,
            voice=voice,
            model=str(metadata.get("model") or ""),
            region=str(metadata.get("region") or ""),
            cached=True,
            cache_key=cache_key,
            cache_path=str(audio_path),
        )
    except Exception:
        logger.debug("TTS 录音缓存读取失败", exc_info=True)
        return None


def _prune_tts_cache() -> None:
    try:
        cache_dir = _tts_cache_dir()
        audio_files = sorted(
            cache_dir.glob("*.wav"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale_audio in audio_files[TTS_CACHE_MAX_FILES:]:
            stale_meta = stale_audio.with_suffix(".json")
            stale_audio.unlink(missing_ok=True)
            stale_meta.unlink(missing_ok=True)
    except Exception:
        logger.debug("TTS 录音缓存清理失败", exc_info=True)


def _write_cached_audio(cache_key: str, result: TTSAudioResult, payload: dict) -> TTSAudioResult:
    try:
        audio_path, meta_path = _tts_cache_paths(cache_key)
        tmp_suffix = f".{os.getpid()}.{time.time_ns()}.tmp"
        tmp_audio = audio_path.with_name(f"{audio_path.name}{tmp_suffix}")
        tmp_meta = meta_path.with_name(f"{meta_path.name}{tmp_suffix}")
        tmp_audio.write_bytes(result.audio)
        metadata = {
            "version": TTS_CACHE_VERSION,
            "cache_key": cache_key,
            "provider": result.provider,
            "voice": result.voice,
            "model": result.model,
            "region": result.region,
            "rate": payload.get("rate"),
            "text_hash": hashlib.sha256(str(payload.get("text") or "").encode("utf-8")).hexdigest(),
            "text_preview": str(payload.get("text") or "")[:80],
            "audio_bytes": len(result.audio),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_audio.replace(audio_path)
        tmp_meta.replace(meta_path)
        _prune_tts_cache()
        return replace(result, cached=False, cache_key=cache_key, cache_path=str(audio_path))
    except Exception:
        logger.warning("TTS 录音缓存写入失败，继续返回实时合成音频", exc_info=True)
        return result


def _synthesize_with_recording_cache(
    payload: dict,
    synthesize: Callable[[], TTSAudioResult],
) -> TTSAudioResult:
    cache_key = _tts_cache_key(payload)
    cached = _read_cached_audio(cache_key)
    if cached:
        return cached
    result = synthesize()
    return _write_cached_audio(cache_key, result, payload)


def _mimo_config() -> MimoTTSConfig:
    saved = _saved_mimo_llm_config()
    key = _env_value(
        "MIMO_TTS_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_MIMO_API_KEY",
        "XIAOMIMIMO_API_KEY",
        "MI_MIMO_API_KEY",
        "MIMO_TOKEN",
        "XIAOMI_MIMO_TOKEN",
    ) or saved.get("key", "")
    base_url = _env_value(
        "MIMO_TTS_BASE_URL",
        "MIMO_BASE_URL",
        "MIMO_API_BASE",
        "XIAOMI_MIMO_BASE_URL",
        "XIAOMI_MIMO_API_BASE",
        "XIAOMIMIMO_BASE_URL",
        "XIAOMIMIMO_API_BASE",
        "MIMO_TOKEN_PLAN_API_BASE",
        "MIMO_TOKEN_PLAN_BASE_URL",
    ) or saved.get("base_url", "") or DEFAULT_MIMO_BASE_URL
    model = _env_value("MIMO_TTS_MODEL") or DEFAULT_MIMO_MODEL
    voice = _env_value("MIMO_TTS_VOICE") or DEFAULT_MIMO_VOICE
    style = _env_value("MIMO_TTS_STYLE") or DEFAULT_MIMO_STYLE
    return MimoTTSConfig(
        key=key,
        base_url=base_url.rstrip("/"),
        model=model,
        voice=voice,
        style=style,
    )


def _microsoft_config() -> MicrosoftTTSConfig:
    return MicrosoftTTSConfig(
        key=_env_value(
            "AZURE_SPEECH_KEY",
            "MICROSOFT_TTS_KEY",
            "AZURE_TTS_KEY",
            "SPEECH_KEY",
        ),
        region=_env_value(
            "AZURE_SPEECH_REGION",
            "MICROSOFT_TTS_REGION",
            "AZURE_TTS_REGION",
            "SPEECH_REGION",
        ),
        endpoint=_env_value(
            "AZURE_SPEECH_ENDPOINT",
            "MICROSOFT_TTS_ENDPOINT",
            "AZURE_TTS_ENDPOINT",
        ),
        voice=_env_value(
            "AZURE_SPEECH_VOICE",
            "MICROSOFT_TTS_VOICE",
            "AZURE_TTS_VOICE",
        )
        or DEFAULT_MICROSOFT_VOICE,
    )


def tts_available() -> bool:
    """Return whether any cloud TTS provider is configured."""
    return _mimo_config().configured or _microsoft_config().configured


def _microsoft_endpoint(config: MicrosoftTTSConfig) -> str:
    if config.endpoint:
        endpoint = config.endpoint.rstrip("/")
        if endpoint.endswith("/cognitiveservices/v1"):
            return endpoint
        return f"{endpoint}/cognitiveservices/v1"
    return f"https://{config.region}.tts.speech.microsoft.com/cognitiveservices/v1"


def _azure_rate_percent(rate: int) -> str:
    percent = round(((rate - DEFAULT_RATE) / DEFAULT_RATE) * 100)
    percent = max(-35, min(percent, 35))
    return f"{percent:+d}%"


def _voice_lang(voice: str) -> str:
    parts = voice.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return "zh-CN"


def _synthesize_mimo_audio(text: str, *, voice: str = "", rate: int = DEFAULT_RATE) -> TTSAudioResult:
    content = _clean_text(text)
    if not content:
        raise RuntimeError("朗读内容为空")

    config = _mimo_config()
    if not config.configured:
        raise RuntimeError("MiMo TTS Key 未配置")

    safe_rate = _safe_rate(rate)
    speed_hint = ""
    if safe_rate >= 215:
        speed_hint = "语速稍快。"
    elif safe_rate <= 155:
        speed_hint = "语速稍慢。"
    style = " ".join([config.style, speed_hint]).strip()
    selected_voice = (voice or config.voice or DEFAULT_MIMO_VOICE).strip()
    payload = {
        "model": config.model,
        "messages": [
            {"role": "user", "content": style},
            {"role": "assistant", "content": content},
        ],
        "audio": {
            "format": "wav",
            "voice": selected_voice,
        },
    }
    response = requests.post(
        f"{config.base_url}/chat/completions",
        headers={
            "api-key": config.key,
            "Authorization": f"Bearer {config.key}",
            "Content-Type": "application/json",
            "User-Agent": TTS_USER_AGENT,
        },
        json=payload,
        timeout=45,
    )
    if response.status_code >= 400:
        detail = response.text[:260].replace("\n", " ")
        raise RuntimeError(f"MiMo TTS 返回 {response.status_code}: {detail}")
    try:
        data = response.json()
        message = data["choices"][0]["message"]
        audio_data = message["audio"]["data"]
    except Exception as exc:
        logger.debug("MiMo TTS 原始响应解析失败: %s", response.text[:500], exc_info=True)
        raise RuntimeError(f"MiMo TTS 未返回可用音频: {exc}") from exc
    try:
        audio = base64.b64decode(audio_data)
    except Exception as exc:
        raise RuntimeError(f"MiMo TTS 音频解码失败: {exc}") from exc
    if not audio:
        raise RuntimeError("MiMo TTS 返回空音频")
    return TTSAudioResult(audio=audio, provider="mimo", voice=selected_voice, model=config.model)


def _synthesize_microsoft_audio(text: str, *, rate: int = DEFAULT_RATE) -> TTSAudioResult:
    content = _clean_text(text)
    if not content:
        raise RuntimeError("朗读内容为空")

    config = _microsoft_config()
    if not config.configured:
        raise RuntimeError("Azure Speech Key/Region 未配置")

    safe_rate = _safe_rate(rate)
    ssml = (
        f"<speak version='1.0' xml:lang='{escape(_voice_lang(config.voice))}' "
        "xmlns='http://www.w3.org/2001/10/synthesis'>"
        f"<voice name='{escape(config.voice)}'>"
        f"<prosody rate='{_azure_rate_percent(safe_rate)}'>{escape(content)}</prosody>"
        "</voice></speak>"
    )
    response = requests.post(
        _microsoft_endpoint(config),
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": config.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": MICROSOFT_OUTPUT_FORMAT,
            "User-Agent": TTS_USER_AGENT,
        },
        timeout=18,
    )
    if response.status_code >= 400:
        detail = response.text[:220].replace("\n", " ")
        raise RuntimeError(f"Azure Speech 返回 {response.status_code}: {detail}")
    if not response.content:
        raise RuntimeError("Azure Speech 未返回音频")
    return TTSAudioResult(
        audio=response.content,
        provider="microsoft",
        voice=config.voice,
        region=config.region,
    )


def synthesize_tts_audio(text: str, *, voice: str = "", rate: int = DEFAULT_RATE) -> TTSAudioResult:
    """Synthesize WAV audio bytes through MiMo first, then Azure when configured."""
    content = _clean_text(text)
    if not content:
        raise RuntimeError("朗读内容为空")
    safe_rate = _safe_rate(rate)

    mimo = _mimo_config()
    if mimo.configured:
        selected_voice = (voice or mimo.voice or DEFAULT_MIMO_VOICE).strip()
        payload = {
            "version": TTS_CACHE_VERSION,
            "provider": "mimo",
            "base_url": mimo.base_url,
            "model": mimo.model,
            "voice": selected_voice,
            "style": mimo.style,
            "rate": safe_rate,
            "text": content,
        }
        return _synthesize_with_recording_cache(
            payload,
            lambda: _synthesize_mimo_audio(content, voice=selected_voice, rate=safe_rate),
        )
    microsoft = _microsoft_config()
    if microsoft.configured:
        payload = {
            "version": TTS_CACHE_VERSION,
            "provider": "microsoft",
            "endpoint": _microsoft_endpoint(microsoft),
            "region": microsoft.region,
            "voice": microsoft.voice,
            "format": MICROSOFT_OUTPUT_FORMAT,
            "rate": safe_rate,
            "text": content,
        }
        return _synthesize_with_recording_cache(
            payload,
            lambda: _synthesize_microsoft_audio(content, rate=safe_rate),
        )
    raise RuntimeError("MiMo TTS Key 未配置，且 Azure Speech Key/Region 未配置")


def speak_text(text: str, *, voice: str = "", rate: int = DEFAULT_RATE) -> dict:
    """Compatibility endpoint: validate and synthesize cloud TTS audio."""
    try:
        result = synthesize_tts_audio(text, voice=voice, rate=rate)
    except Exception as exc:
        mimo = _mimo_config()
        microsoft = _microsoft_config()
        return {
            "success": False,
            "data": {
                "available": tts_available(),
                "provider": "mimo" if mimo.configured or not microsoft.configured else "microsoft",
                "mimo_configured": mimo.configured,
                "microsoft_configured": microsoft.configured,
            },
            "message": str(exc),
        }
    return {
        "success": True,
        "data": {
            "available": True,
            "provider": result.provider,
            "speaking": False,
            "audio_bytes": len(result.audio),
            "voice": result.voice,
            "model": result.model,
            "region": result.region,
            "rate": _safe_rate(rate),
            "cached": result.cached,
            "cache_key": result.cache_key,
            "cache_path": result.cache_path,
        },
    }


def stop_speech() -> dict:
    """Backend no longer owns playback; frontend audio elements stop locally."""
    return {"success": True, "data": {"stopped": False, "provider": "cloud"}}


def speech_status() -> dict:
    mimo = _mimo_config()
    microsoft = _microsoft_config()
    provider = "mimo" if mimo.configured or not microsoft.configured else "microsoft"
    return {
        "success": True,
        "data": {
            "available": tts_available(),
            "speaking": False,
            "provider": provider,
            "mimo_configured": mimo.configured,
            "mimo_model": mimo.model,
            "mimo_voice": mimo.voice,
            "mimo_base_url": mimo.base_url,
            "microsoft_configured": microsoft.configured,
            "microsoft_voice": microsoft.voice,
            "microsoft_region": microsoft.region,
            "recording_cache": True,
            "recording_cache_dir": str(_tts_cache_dir()),
            "recording_cache_max_files": TTS_CACHE_MAX_FILES,
        },
    }
