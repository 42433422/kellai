import axios, {
  AxiosError,
  type AxiosAdapter,
  type InternalAxiosRequestConfig,
} from "axios";
import type { ApiResponse } from "../types";
import { toastStore } from "../stores/toast";
import { shouldUseMock } from "../mocks";
import { appPath } from "../utils/routing";

/** axios 实例，baseURL 从环境变量读取，默认 http://127.0.0.1:8793
 *  如果开了 mock 模式（VITE_USE_MOCK=true 或 localStorage kellai:useMock=1），
 *  就把请求交给我们自己写的 mockAdapter 拦截，UI 用本地数据跑起来。 */
const configuredApiBaseUrl = String(import.meta.env.VITE_API_BASE_URL || "").trim();
const useDevelopmentProxy =
  import.meta.env.DEV &&
  typeof window !== "undefined" &&
  (window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost");

/**
 * 浏览器开发页统一走 Vite 同源代理，避免嵌入式浏览器把跨端口
 * 127.0.0.1:1420 -> 127.0.0.1:8793 请求拦截为 Network Error。
 * Tauri/生产包仍直接连接本机后端。
 */
export const API_BASE_URL = useDevelopmentProxy
  ? ""
  : configuredApiBaseUrl || "http://127.0.0.1:8793";
const mockModeEnabled = import.meta.env.DEV && shouldUseMock();
const developmentMockAdapter: AxiosAdapter | undefined = mockModeEnabled
  ? async (config) => {
      const { mockAdapter } = await import("../mocks/handlers");
      return mockAdapter(config);
    }
  : undefined;

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
  },
  adapter: developmentMockAdapter,
});

/**
 * Desktop-to-desktop handoffs must always use the real loopback backend.  This
 * keeps an optional product-data mock mode from intercepting authorization.
 */
export const loopbackClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

// 控制台提示一下，免得忘了关 mock
if (mockModeEnabled) {
  // eslint-disable-next-line no-console
  console.info(
    "%c[客来来] Mock 数据模式已开启",
    "background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px",
    "所有 /api/kellai/* 请求会走本地 mock。\n关掉方法：设置页取消勾选 / 清掉 localStorage('kellai:useMock') / 改 .env"
  );
}

/**
 * 标记需要跳过 loading toast 的请求（避免覆盖业务侧主动控制的提示）
 * 使用方式：client.get(url, { skipLoading: true })
 */
declare module "axios" {
  export interface AxiosRequestConfig {
    skipLoading?: boolean;
    skipErrorToast?: boolean;
  }
  export interface InternalAxiosRequestConfig {
    skipLoading?: boolean;
    skipErrorToast?: boolean;
  }
}

/* ===== Token 工具方法 ===== */

const TOKEN_KEY = "auth_token";
const REFRESH_TOKEN_KEY = "auth_refresh_token";
const USER_KEY = "auth_user";

/** 防止多个 401 并发刷新：同一时刻只允许一个刷新请求 */
let refreshingPromise: Promise<string | null> | null = null;
type LoadingRequestConfig = InternalAxiosRequestConfig & {
  __retried?: boolean;
  __loadingId?: string;
  __loadingTimer?: number;
};

function clearRequestLoading(config?: LoadingRequestConfig) {
  if (!config) return;
  if (config.__loadingTimer) {
    window.clearTimeout(config.__loadingTimer);
    config.__loadingTimer = undefined;
  }
  if (config.__loadingId) {
    toastStore.dismiss(config.__loadingId);
    config.__loadingId = undefined;
  }
}

/**
 * 尝试用 refresh_token 换取新的 access_token
 * 返回新 token；失败返回 null
 */
async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return null;

  try {
    // 注意：此处使用裸 axios 避免触发拦截器递归
    const response = await axios.post<{ success: boolean; access_token?: string; refresh_token?: string }>(
      `${client.defaults.baseURL}/api/kellai/auth/refresh`,
      { refresh_token: refreshToken }
    );
    // 后端直接返回 flat 格式：{ success, access_token, refresh_token, ... }
    const newToken = response.data?.access_token;
    const newRefresh = response.data?.refresh_token;
    if (newToken) {
      localStorage.setItem(TOKEN_KEY, newToken);
      if (newRefresh) localStorage.setItem(REFRESH_TOKEN_KEY, newRefresh);
      return newToken;
    }
    return null;
  } catch {
    return null;
  }
}

/** 跳转到登录页并清理本地认证信息 */
function redirectToLogin() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  // 避免在登录页重复跳转
  const loginPath = appPath("/login");
  if (window.location.pathname !== loginPath) {
    window.location.href = loginPath;
  }
}

/* ===== 拦截器 ===== */

/**
 * 请求拦截器：
 * 1. 自动注入 Authorization: Bearer <token>
 * 2. 非 GET 请求且未显式 skipLoading 时弹出 loading toast
 */
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // 仅对写操作（POST/PUT/PATCH/DELETE）显示 loading
    const method = (config.method || "get").toLowerCase();
    const isWriteOp = method !== "get" && method !== "head";
    if (isWriteOp && !config.skipLoading) {
      // 快速请求不展示 loading，避免短请求反复闪烁；超过 300ms 才提示。
      const loadingConfig = config as LoadingRequestConfig;
      loadingConfig.__loadingTimer = window.setTimeout(() => {
        loadingConfig.__loadingId = toastStore.loading("处理中...");
        loadingConfig.__loadingTimer = undefined;
      }, 300);
    }

    return config;
  },
  (error) => Promise.reject(error)
);

loopbackClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * 响应拦截器：
 * 1. 关闭对应的 loading toast
 * 2. 统一错误处理：401 尝试 refresh_token，重试原请求
 * 3. 其他错误统一 toast 提示
 */
client.interceptors.response.use(
  (response) => {
    clearRequestLoading(response.config as LoadingRequestConfig);
    return response;
  },
  async (error: AxiosError<ApiResponse<unknown>>) => {
    const originalConfig = error.config as LoadingRequestConfig | undefined;

    // 关闭 loading toast
    clearRequestLoading(originalConfig);

    const status = error.response?.status;

    // 401：尝试 refresh_token 续签
    if (status === 401 && originalConfig && !originalConfig.__retried) {
      originalConfig.__retried = true;

      // 登录/刷新接口本身 401 不重试
      const url = originalConfig.url || "";
      if (url.includes("/auth/login") || url.includes("/auth/refresh")) {
        if (!originalConfig.skipErrorToast) {
          toastStore.error("登录已过期，请重新登录");
        }
        redirectToLogin();
        return Promise.reject(error);
      }

      // 并发复用：避免多个 401 触发多次 refresh
      if (!refreshingPromise) {
        refreshingPromise = refreshAccessToken().finally(() => {
          refreshingPromise = null;
        });
      }
      const newToken = await refreshingPromise;

      if (newToken && originalConfig.headers) {
        originalConfig.headers.Authorization = `Bearer ${newToken}`;
        // 重新发起原请求
        return client.request(originalConfig);
      }

      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      if (!originalConfig.skipErrorToast) {
        toastStore.error("登录已过期，请重新登录");
      }
      redirectToLogin();
      return Promise.reject(error);
    }

    // 其他错误：统一 toast 提示
    if (!originalConfig?.skipErrorToast) {
      const message = extractErrorMessage(error);
      toastStore.error(message);
    }

    return Promise.reject(error);
  }
);

/** 从 axios 错误对象中提取人类可读的错误信息 */
function extractErrorMessage(error: AxiosError<ApiResponse<unknown>>): string {
  // 业务后端返回 { code, message, data }
  const data = error.response?.data;
  if (data && typeof data === "object" && typeof data.message === "string" && data.message) {
    return data.message;
  }
  // HTTP 状态码兜底
  if (error.response?.status) {
    const map: Record<number, string> = {
      400: "请求参数错误",
      403: "没有权限",
      404: "资源不存在",
      408: "请求超时",
      500: "服务器异常",
      502: "网关错误",
      503: "服务暂不可用",
      504: "网关超时",
    };
    if (map[error.response.status]) return map[error.response.status];
  }
  if (error.code === "ECONNABORTED") return "请求超时，请稍后重试";
  if (error.message === "Network Error") return "网络连接异常";
  return error.message || "请求失败";
}

/** 通用请求方法，自动解包 ApiResponse
 * 兼容两种后端风格：
 * 1) 包装响应：{ code, message, data: T }
 * 2) 裸返回：直接是 T（如 auth 接口返回 { success, access_token, user, ... }）
 */
export async function request<T>(
  method: "get" | "post" | "put" | "delete" | "patch",
  url: string,
  data?: unknown
): Promise<T> {
  const response = await client.request<ApiResponse<T> | T>({
    method,
    url,
    [method === "get" ? "params" : "data"]: data,
  });
  const body = response.data as ApiResponse<T> | T;
  if (body && typeof body === "object" && "data" in body && (body as ApiResponse<T>).data !== undefined) {
    return (body as ApiResponse<T>).data;
  }
  return body as T;
}

export default client;
