import axios, { type InternalAxiosRequestConfig } from 'axios';

export interface ToolSession {
  access_token: string;
  expires_at: number | string;
  user: { id: number; team_id: number; display_name: string; role: string };
}

const SESSION_KEY = 'kellai:tool-session:v2';
let session: ToolSession | null = null;
let revision = 0;
const listeners = new Set<() => void>();
export const subscribeSession = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export const getSession = () => session;
export const currentAccountKey = () => session ? `${session.user.team_id}:${session.user.id}:${revision}` : '';

export function setToolSession(value: ToolSession | null) {
  session = value;
  revision += 1;
  if (value) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
  else sessionStorage.removeItem(SESSION_KEY);
  listeners.forEach((listener) => listener());
}

export function restoreSession() {
  // Retired SaaS passwords and refresh tokens must never be reused by the tool.
  for (const key of ['auth_token', 'auth_refresh_token', 'auth_user', 'kellai_saved_credentials']) {
    localStorage.removeItem(key);
  }
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null') as ToolSession | null;
    const raw = value?.expires_at;
    const expiry = typeof raw === 'number' ? raw * 1000 : Date.parse(raw || '');
    if (value && typeof value.access_token === 'string' && value.access_token
      && Number(value.user?.id) > 0 && Number(value.user?.team_id) > 0 && expiry > Date.now()) {
      setToolSession(value);
    } else setToolSession(null);
  } catch { setToolSession(null); }
}

function localBaseUrl() {
  const configured = String(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8793');
  const url = new URL(configured);
  if (!['http:', 'https:'].includes(url.protocol)
    || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('客来来只连接本机工具服务');
  }
  return import.meta.env.DEV ? '' : url.origin;
}

export const API_BASE_URL = localBaseUrl();
const client = axios.create({ baseURL: API_BASE_URL, timeout: 15000 });
const handoffClient = axios.create({ baseURL: API_BASE_URL, timeout: 15000 });

declare module 'axios' {
  export interface InternalAxiosRequestConfig { toolSessionRevision?: number }
}

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (!session) throw new Error('请先从 XCMAX 连接客来来');
  config.toolSessionRevision = revision;
  config.headers.Authorization = `Bearer ${session.access_token}`;
  return config;
});
client.interceptors.response.use((response) => {
  if (response.config.toolSessionRevision !== revision) throw new Error('连接已切换，已丢弃原连接的响应');
  return response;
}, (error: unknown) => {
  if (axios.isAxiosError(error) && error.response?.status === 401
    && error.config?.toolSessionRevision === revision) setToolSession(null);
  // Never replay a mutation under a refreshed or different operator session.
  return Promise.reject(error);
});

export async function beginHandoff() {
  const startRevision = revision;
  const response = await handoffClient.post('/api/kellai/auth/xcmax-desktop', {}, {
    headers: { 'X-Kellai-Desktop-Handoff': '1' },
  });
  if (startRevision !== revision) throw new Error('连接已切换，请重新发起授权');
  const data = response.data;
  if (!data?.success || !data.access_token || !data.user) throw new Error(data?.error || 'XCMAX 尚未发起连接');
  setToolSession(data as ToolSession);
  return data as ToolSession;
}

export async function request<T>(method: 'get' | 'post' | 'patch' | 'delete', path: string, data?: unknown): Promise<T> {
  const response = await client.request({ method, url: `/api/kellai${path}`, data });
  if (response.data?.success !== true) throw new Error(response.data?.error || '工具请求未完成');
  return response.data.data as T;
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = error.response?.data;
    if (typeof body?.error === 'string') return body.error;
    if (typeof body?.detail === 'string') return body.detail;
    return error.response ? `请求失败（${error.response.status}）` : '无法连接本机客来来服务';
  }
  return error instanceof Error ? error.message : '操作未完成，请重试';
}

export default client;
