import { useCallback, useEffect, useRef, useState } from 'react';

type SpeakOptions = {
  preferLocal?: boolean;
  waitForEnd?: boolean;
  cacheKey?: string;
  onPlaybackStart?: (info: PlaybackInfo) => void;
  onPlaybackEnd?: (info: PlaybackInfo) => void;
};

const TTS_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8793').replace(/\/$/, '');

type PlaybackInfo = {
  engine: 'web-audio' | 'html-audio';
  durationSeconds: number | null;
};

type AudioWindow = Window & {
  webkitAudioContext?: typeof AudioContext;
  __kellaiTtsDebug?: Record<string, unknown>;
};

let sharedAudioContext: AudioContext | null = null;
let sharedAudioUnlocked = false;
let sharedMediaAudio: HTMLAudioElement | null = null;
let sharedMediaUnlocked = false;
const MAX_TTS_CACHE_ENTRIES = 12;
const ttsAudioCache = new Map<string, Blob | Promise<Blob>>();
const SILENT_WAV_DATA_URL = 'data:audio/wav;base64,UklGRgQCAABXQVZFZm10IBAAAAABAAEAwF0AAIC7AAACABAAZGF0YeABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function normalizeSpeechText(text: string) {
  return text.trim();
}

function speechCacheKey(content: string, cacheKey?: string) {
  return cacheKey || normalizeSpeechText(content).replace(/\s+/g, ' ');
}

function getSharedAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AudioContextCtor = window.AudioContext || (window as AudioWindow).webkitAudioContext;
  if (!AudioContextCtor) return null;
  if (!sharedAudioContext || sharedAudioContext.state === 'closed') {
    sharedAudioContext = new AudioContextCtor();
  }
  return sharedAudioContext;
}

function getSharedMediaAudio(): HTMLAudioElement | null {
  if (typeof window === 'undefined' || typeof Audio === 'undefined') return null;
  if (!sharedMediaAudio) {
    sharedMediaAudio = new Audio();
    sharedMediaAudio.preload = 'auto';
    sharedMediaAudio.setAttribute('playsinline', 'true');
    sharedMediaAudio.style.display = 'none';
  }
  if (document.body && !sharedMediaAudio.isConnected) {
    document.body.appendChild(sharedMediaAudio);
  }
  return sharedMediaAudio;
}

function setDebugState(patch: Record<string, unknown>): void {
  if (typeof window === 'undefined') return;
  const target = window as AudioWindow;
  target.__kellaiTtsDebug = {
    ...(target.__kellaiTtsDebug || {}),
    ...patch,
    updatedAt: new Date().toISOString(),
  };
}

async function resumeAudioContext(ctx: AudioContext, timeoutMs = 1200): Promise<boolean> {
  if (ctx.state === 'running') return true;
  try {
    await Promise.race([ctx.resume(), sleep(timeoutMs)]);
  } catch (error) {
    console.warn('[kellai-tts] audio context resume failed', error);
    return false;
  }
  return String(ctx.state) === 'running';
}

function unlockSharedAudio(): void {
  const ctx = getSharedAudioContext();
  if (ctx) {
    void resumeAudioContext(ctx, 1500).then((running) => {
      if (!running || sharedAudioUnlocked) return;
      const buffer = ctx.createBuffer(1, 1, 22050);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start(0);
      sharedAudioUnlocked = true;
      setDebugState({ audioContextUnlocked: true });
    }).catch((error) => {
      console.warn('[kellai-tts] audio context unlock failed', error);
    });
  }

  const media = getSharedMediaAudio();
  if (!media || sharedMediaUnlocked) return;
  try {
    media.pause();
    media.muted = true;
    media.src = SILENT_WAV_DATA_URL;
    const playPromise = media.play();
    void playPromise.then(() => {
      media.pause();
      media.currentTime = 0;
      media.muted = false;
      sharedMediaUnlocked = true;
      setDebugState({ mediaAudioUnlocked: true });
    }).catch((error) => {
      console.warn('[kellai-tts] media audio unlock failed', error);
    });
  } catch (error) {
    console.warn('[kellai-tts] media audio unlock failed', error);
  }
}

export function unlockTextToSpeechAudio(): void {
  unlockSharedAudio();
}

function describeSpeechError(error: unknown): string {
  const err = error as {
    code?: string;
    message?: string;
    name?: string;
    response?: { status?: number };
  };
  if (err?.code === 'ECONNABORTED') return 'MiMo 语音生成超时，请重试';
  if (err?.response?.status) return `云端语音接口返回 ${err.response.status}`;
  if (err?.name === 'NotAllowedError') return '浏览器拦截了自动播放，请点一次重播语音';
  if (err?.name === 'EncodingError') return '浏览器无法解码语音音频';
  if (err?.name) return `语音播放失败：${err.name}`;
  if (err?.message) return `语音播放失败：${err.message}`;
  return '云端语音启动失败';
}

function authHeaders(): HeadersInit {
  try {
    const token = window.localStorage?.getItem('auth_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 60000): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if ((error as { name?: string })?.name === 'AbortError') {
      throw { code: 'ECONNABORTED', message: 'request timeout' };
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function cacheAudioBlob(key: string, value: Blob | Promise<Blob>) {
  if (!ttsAudioCache.has(key) && ttsAudioCache.size >= MAX_TTS_CACHE_ENTRIES) {
    const oldestKey = ttsAudioCache.keys().next().value;
    if (oldestKey) ttsAudioCache.delete(oldestKey);
  }
  ttsAudioCache.set(key, value);
}

async function fetchAudioBlob(content: string): Promise<Blob> {
  const response = await fetchWithTimeout(
    `${TTS_API_BASE_URL}/api/kellai/tts/audio`,
    {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text: content }),
    },
    60000
  );
  if (!response.ok) throw { response: { status: response.status } };
  return response.blob();
}

async function getOrCreateAudioBlob(content: string, cacheKey?: string): Promise<Blob> {
  const key = speechCacheKey(content, cacheKey);
  const cached = ttsAudioCache.get(key);
  if (cached instanceof Blob) return cached;
  if (cached) return cached;

  const pending = fetchAudioBlob(content);
  cacheAudioBlob(key, pending);
  try {
    const blob = await pending;
    cacheAudioBlob(key, blob);
    return blob;
  } catch (error) {
    if (ttsAudioCache.get(key) === pending) {
      ttsAudioCache.delete(key);
    }
    throw error;
  }
}

function getPreparedAudioBlob(content: string, cacheKey?: string): Blob | null {
  const cached = ttsAudioCache.get(speechCacheKey(content, cacheKey));
  return cached instanceof Blob ? cached : null;
}

export function playPreparedTextToSpeech(
  text: string,
  cacheKey?: string,
  options: {
    onPlaybackStart?: (info: PlaybackInfo) => void;
    onPlaybackEnd?: (info: PlaybackInfo) => void;
    onPlaybackError?: (error: unknown) => void;
  } = {}
): boolean {
  const content = normalizeSpeechText(text);
  const blob = getPreparedAudioBlob(content, cacheKey);
  if (!content || !blob) return false;

  const audio = getSharedMediaAudio();
  if (!audio) return false;

  const objectUrl = URL.createObjectURL(blob);
  audio.pause();
  audio.onended = null;
  audio.onerror = null;
  audio.src = objectUrl;
  audio.preload = 'auto';
  audio.setAttribute('playsinline', 'true');
  audio.muted = false;
  audio.volume = 1;
  if (document.body && !audio.isConnected) {
    document.body.appendChild(audio);
  }
  const playbackInfo = (): PlaybackInfo => ({
    engine: 'html-audio',
    durationSeconds: Number.isFinite(audio.duration) ? audio.duration : null,
  });
  audio.onended = () => {
    URL.revokeObjectURL(objectUrl);
    setDebugState({ state: 'ended', engine: 'html-audio', prepared: true });
    options.onPlaybackEnd?.(playbackInfo());
  };
  audio.onerror = () => {
    URL.revokeObjectURL(objectUrl);
    const error = new Error('预加载语音播放失败');
    setDebugState({ state: 'failed', engine: 'html-audio', prepared: true, error: error.message });
    options.onPlaybackError?.(error);
  };
  try {
    const playPromise = audio.play();
    void playPromise.then(() => {
      setDebugState({ state: 'playing', engine: 'html-audio', prepared: true });
      options.onPlaybackStart?.(playbackInfo());
    }).catch((error) => {
      URL.revokeObjectURL(objectUrl);
      setDebugState({ state: 'failed', engine: 'html-audio', prepared: true, error: describeSpeechError(error) });
      options.onPlaybackError?.(error);
    });
    return true;
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    options.onPlaybackError?.(error);
    return false;
  }
}

export async function preloadTextToSpeech(text: string, cacheKey?: string): Promise<boolean> {
  const content = normalizeSpeechText(text);
  if (!content) return false;
  const key = speechCacheKey(content, cacheKey);
  const cached = ttsAudioCache.get(key);
  if (cached) {
    try {
      await getOrCreateAudioBlob(content, cacheKey);
      return true;
    } catch {
      return false;
    }
  }
  try {
    setDebugState({ state: 'preloading', text: content, error: '' });
    const res = await fetchWithTimeout(
      `${TTS_API_BASE_URL}/api/kellai/tts/status`,
      { headers: authHeaders() },
      12000
    );
    if (!res.ok) throw { response: { status: res.status } };
    const raw = await res.json();
    const payload = (raw?.data ?? raw) as { available?: boolean } | undefined;
    if (!payload?.available) {
      setDebugState({ state: 'preload-unavailable', text: content });
      return false;
    }
    await getOrCreateAudioBlob(content, cacheKey);
    setDebugState({ state: 'preloaded', text: content });
    return true;
  } catch (error) {
    setDebugState({ state: 'preload-failed', text: content, error: describeSpeechError(error) });
    console.warn('[kellai-tts] preload failed', error);
    return false;
  }
}

export function useTextToSpeech() {
  const [cloudSupported, setCloudSupported] = useState(false);
  const [speakingText, setSpeakingText] = useState<string | null>(null);
  const [lastError, setLastError] = useState('');
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const cleanupAudio = useCallback(() => {
    if (sourceRef.current) {
      try {
        sourceRef.current.stop();
      } catch {
        // ignore already-ended sources
      }
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (audioRef.current) {
      const activeAudio = audioRef.current;
      audioRef.current.pause();
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.src = '';
      if (activeAudio !== sharedMediaAudio) {
        activeAudio.remove();
      }
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  const refreshSupport = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(
        `${TTS_API_BASE_URL}/api/kellai/tts/status`,
        { headers: authHeaders() },
        12000
      );
      if (!res.ok) throw { response: { status: res.status } };
      const raw = await res.json();
      const payload = (raw?.data ?? raw) as { available?: boolean } | undefined;
      const available = Boolean(payload?.available);
      setCloudSupported(available);
      if (!available) setLastError('MiMo TTS 未配置，请先设置 MIMO_API_KEY');
      return available;
    } catch (error) {
      setCloudSupported(false);
      setLastError('云端语音状态检查失败，请确认后端服务已启动');
      console.warn('[kellai-tts] status check failed', error);
      return false;
    }
  }, []);

  useEffect(() => {
    void refreshSupport();

    const unlock = () => unlockSharedAudio();
    window.addEventListener('pointerdown', unlock, { capture: true });
    window.addEventListener('keydown', unlock, { capture: true });

    return () => {
      window.removeEventListener('pointerdown', unlock, { capture: true });
      window.removeEventListener('keydown', unlock, { capture: true });
      cleanupAudio();
    };
  }, [cleanupAudio, refreshSupport]);

  const stop = useCallback(() => {
    cleanupAudio();
    setSpeakingText(null);
  }, [cleanupAudio]);

  const playBlob = useCallback(async (blob: Blob, content: string, options: SpeakOptions = {}) => {
    const waitForEnd = Boolean(options.waitForEnd);
    const ctx = getSharedAudioContext();
    if (ctx) {
      try {
        const running = await resumeAudioContext(ctx);
        if (!running) {
          throw new Error(`AudioContext not running: ${ctx.state}`);
        }
        const arrayBuffer = await blob.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer.slice(0));
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        const playbackInfo: PlaybackInfo = {
          engine: 'web-audio',
          durationSeconds: audioBuffer.duration,
        };
        const ended = new Promise<void>((resolve) => {
          source.onended = () => {
            if (sourceRef.current === source) {
              sourceRef.current = null;
            }
            setSpeakingText((current) => (current === content ? null : current));
            setDebugState({ state: 'ended', engine: 'web-audio' });
            options.onPlaybackEnd?.(playbackInfo);
            console.info('[kellai-tts] playback ended', { engine: 'web-audio' });
            resolve();
          };
        });
        sourceRef.current = source;
        source.start(0);
        options.onPlaybackStart?.(playbackInfo);
        setDebugState({
          engine: 'web-audio',
          state: 'playing',
          waitForEnd,
          durationSeconds: audioBuffer.duration,
        });
        console.info('[kellai-tts] playback started', {
          engine: 'web-audio',
          seconds: Math.round(audioBuffer.duration * 10) / 10,
          waitForEnd,
        });
        if (waitForEnd) {
          await ended;
        }
        return true;
      } catch (error) {
        console.warn('[kellai-tts] web audio playback failed, fallback to media element', error);
      }
    }

    const objectUrl = URL.createObjectURL(blob);
    const audio = getSharedMediaAudio() || new Audio();
    audio.pause();
    audio.src = objectUrl;
    audio.preload = 'auto';
    audio.setAttribute('playsinline', 'true');
    audio.muted = false;
    audio.volume = 1;
    audio.style.display = 'none';
    if (document.body && !audio.isConnected) {
      document.body.appendChild(audio);
    }
    objectUrlRef.current = objectUrl;
    audioRef.current = audio;
    const mediaPlaybackInfo = (): PlaybackInfo => ({
      engine: 'html-audio',
      durationSeconds: Number.isFinite(audio.duration) ? audio.duration : null,
    });
    const ended = new Promise<void>((resolve, reject) => {
      audio.onended = () => {
        cleanupAudio();
        setSpeakingText(null);
        setDebugState({ state: 'ended', engine: 'html-audio' });
        options.onPlaybackEnd?.(mediaPlaybackInfo());
        console.info('[kellai-tts] playback ended', { engine: 'html-audio' });
        resolve();
      };
      audio.onerror = () => {
        cleanupAudio();
        setSpeakingText(null);
        setLastError('云端语音播放失败');
        reject(new Error('云端语音播放失败'));
      };
    });
    await audio.play();
    options.onPlaybackStart?.(mediaPlaybackInfo());
    setDebugState({
      engine: 'html-audio',
      state: 'playing',
      waitForEnd,
      durationSeconds: Number.isFinite(audio.duration) ? audio.duration : null,
    });
    console.info('[kellai-tts] playback started', { engine: 'html-audio', waitForEnd });
    if (waitForEnd) {
      await ended;
    }
    return true;
  }, [cleanupAudio]);

  const speak = useCallback(
    async (text: string, _options: SpeakOptions = {}) => {
      unlockSharedAudio();
      const content = normalizeSpeechText(text);
      if (!content) return false;

      if (speakingText === content && audioRef.current && !audioRef.current.paused) {
        stop();
        return true;
      }

      const available = await refreshSupport();
      if (!available) {
        setLastError('MiMo TTS 未配置，请先设置 MIMO_API_KEY');
        setSpeakingText(null);
        return false;
      }

      cleanupAudio();
      setLastError('');
      setSpeakingText(content);
      setDebugState({
        state: 'requesting',
        text: content,
        waitForEnd: Boolean(_options.waitForEnd),
        error: '',
      });

      try {
        const blob = await getOrCreateAudioBlob(content, _options.cacheKey);
        await playBlob(blob, content, _options);
        return true;
      } catch (error) {
        cleanupAudio();
        setSpeakingText(null);
        setLastError(describeSpeechError(error));
        setDebugState({ state: 'failed', error: describeSpeechError(error) });
        console.warn('[kellai-tts] speak failed', error);
        return false;
      }
    },
    [cleanupAudio, playBlob, refreshSupport, speakingText, stop]
  );

  const isSpeaking = useCallback(
    (text: string) => speakingText === text.trim(),
    [speakingText]
  );

  return {
    supported: cloudSupported,
    browserSupported: false,
    localSupported: false,
    lastError,
    speakingText,
    speak,
    stop,
    unlock: unlockSharedAudio,
    isSpeaking,
  };
}
