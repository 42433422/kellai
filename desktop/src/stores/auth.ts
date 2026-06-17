import { create } from "zustand";
import { request } from "../api/client";
import type {
  User,
  LoginRequest,
  SmsLoginRequest,
  RegisterRequest,
  LoginResponse,
} from "../types";

/* ============ 记忆账号 ============ */

const LAST_EMAIL_KEY = "kellai_last_email";
const REMEMBERED_EMAILS_KEY = "kellai_remembered_emails";
const SAVED_CREDENTIALS_KEY = "kellai_saved_credentials";
const MAX_REMEMBERED = 5;
/** 7 天免登录有效期（毫秒） */
const AUTO_LOGIN_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export interface RememberedAccount {
  email: string;
  /** 显示名称（登录成功时拿到，可为空） */
  displayName: string;
  /** 最后一次使用时间（ISO） */
  lastUsedAt: string;
}

/** 加密保存的登录凭据（用于记住密码 / 7 天免登录）。
 *  说明：localStorage 在 Tauri 桌面端是 WebView 的 per-user profile，
 *  仅本机用户可访问。此处用 base64+XOR 做"防误看"混淆，不构成真正的安全防护。 */
export interface SavedCredential {
  email: string;
  displayName: string;
  /** 异或混淆后 base64 编码的密码 */
  password: string;
  /** 是否启用"7 天免登录"（启动时静默登录） */
  autoLoginEnabled: boolean;
  /** 凭据保存时间（ISO） */
  savedAt: string;
  /** 上次自动登录时间（ISO，可选） */
  lastAutoLoginAt?: string;
}

function readRemembered(): RememberedAccount[] {
  try {
    const raw = localStorage.getItem(REMEMBERED_EMAILS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (x): x is RememberedAccount =>
        x && typeof x === "object" && typeof x.email === "string"
    );
  } catch {
    return [];
  }
}

function writeRemembered(list: RememberedAccount[]) {
  try {
    localStorage.setItem(REMEMBERED_EMAILS_KEY, JSON.stringify(list));
  } catch {
    /* quota 等原因忽略 */
  }
}

export function rememberEmail(email: string, displayName: string = ""): void {
  const normalized = (email || "").trim().toLowerCase();
  if (!normalized) return;
  const list = readRemembered().filter((x) => x.email.toLowerCase() !== normalized);
  list.unshift({
    email: normalized,
    displayName,
    lastUsedAt: new Date().toISOString(),
  });
  writeRemembered(list.slice(0, MAX_REMEMBERED));
  try {
    localStorage.setItem(LAST_EMAIL_KEY, normalized);
  } catch {
    /* noop */
  }
}

export function forgetEmail(email: string): void {
  const normalized = (email || "").trim().toLowerCase();
  if (!normalized) return;
  const list = readRemembered().filter((x) => x.email.toLowerCase() !== normalized);
  writeRemembered(list);
  try {
    if ((localStorage.getItem(LAST_EMAIL_KEY) || "").toLowerCase() === normalized) {
      localStorage.removeItem(LAST_EMAIL_KEY);
    }
  } catch {
    /* noop */
  }
}

export function getRememberedEmails(): RememberedAccount[] {
  return readRemembered();
}

export function getLastEmail(): string {
  try {
    return (localStorage.getItem(LAST_EMAIL_KEY) || "").trim();
  } catch {
    return "";
  }
}

/* ============ 凭据混淆（防误看，不构成安全防护） ============ */

const OBFUSCATION_KEY = "kellai-desktop-local-cred-v1";

function xorWithKey(plain: string): string {
  let out = "";
  for (let i = 0; i < plain.length; i++) {
    out += String.fromCharCode(
      plain.charCodeAt(i) ^ OBFUSCATION_KEY.charCodeAt(i % OBFUSCATION_KEY.length)
    );
  }
  return out;
}

export function obfuscatePassword(plain: string): string {
  try {
    return btoa(unescape(encodeURIComponent(xorWithKey(plain))));
  } catch {
    return "";
  }
}

export function deobfuscatePassword(enc: string): string {
  if (!enc) return "";
  try {
    const raw = decodeURIComponent(escape(atob(enc)));
    return xorWithKey(raw);
  } catch {
    return "";
  }
}

/* ============ 保存凭据（记住密码 / 7 天免登录） ============ */

function readCredentials(): SavedCredential[] {
  try {
    const raw = localStorage.getItem(SAVED_CREDENTIALS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (x): x is SavedCredential =>
        x && typeof x === "object" && typeof x.email === "string" && typeof x.password === "string"
    );
  } catch {
    return [];
  }
}

function writeCredentials(list: SavedCredential[]) {
  try {
    localStorage.setItem(SAVED_CREDENTIALS_KEY, JSON.stringify(list));
  } catch {
    /* noop */
  }
}

/** 清理过期凭据（超过 7 天免登录有效期且未启用 autoLogin 的） */
function pruneExpiredCredentials(): SavedCredential[] {
  const now = Date.now();
  const list = readCredentials();
  const fresh = list.filter((c) => {
    if (!c.autoLoginEnabled) return true; // 仅记住密码的不过期
    const savedAt = c.savedAt ? new Date(c.savedAt).getTime() : 0;
    const last = c.lastAutoLoginAt ? new Date(c.lastAutoLoginAt).getTime() : savedAt;
    return now - last < AUTO_LOGIN_TTL_MS;
  });
  if (fresh.length !== list.length) writeCredentials(fresh);
  return fresh;
}

/** 获取所有有效凭据（自动清理过期） */
export function getSavedCredentials(): SavedCredential[] {
  return pruneExpiredCredentials();
}

/** 按邮箱查找凭据（自动清理过期） */
export function getSavedCredential(email: string): SavedCredential | null {
  if (!email) return null;
  const normalized = email.trim().toLowerCase();
  return pruneExpiredCredentials().find((c) => c.email.toLowerCase() === normalized) || null;
}

/** 保存凭据：email、密码（明文）；内部混淆。autoLogin=true 时启用 7 天免登录。 */
export function saveCredential(
  email: string,
  password: string,
  displayName: string = "",
  autoLogin: boolean = false
): void {
  const normalized = (email || "").trim().toLowerCase();
  if (!normalized || !password) return;
  const list = pruneExpiredCredentials().filter(
    (x) => x.email.toLowerCase() !== normalized
  );
  list.unshift({
    email: normalized,
    displayName,
    password: obfuscatePassword(password),
    autoLoginEnabled: autoLogin,
    savedAt: new Date().toISOString(),
  });
  writeCredentials(list);
}

/** 清除某个邮箱的保存凭据 */
export function clearSavedCredential(email: string): void {
  const normalized = (email || "").trim().toLowerCase();
  if (!normalized) return;
  const list = readCredentials().filter((x) => x.email.toLowerCase() !== normalized);
  writeCredentials(list);
}

/** 设置某个邮箱的"7 天免登录"开关（不重新保存密码） */
export function setAutoLoginEnabled(email: string, enabled: boolean): void {
  const normalized = (email || "").trim().toLowerCase();
  if (!normalized) return;
  const list = readCredentials();
  const idx = list.findIndex((x) => x.email.toLowerCase() === normalized);
  if (idx < 0) return;
  list[idx] = { ...list[idx], autoLoginEnabled: enabled };
  writeCredentials(list);
}

/** 取消所有 7 天免登录（保留"仅记住密码"） */
export function disableAllAutoLogin(): void {
  const list = readCredentials().map((c) => ({ ...c, autoLoginEnabled: false }));
  writeCredentials(list);
}

/* ============ Auth Store ============ */

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  /** 启动时静默登录中（用于显示加载状态） */
  silentAutoLoginRunning: boolean;

  /** 邮箱密码登录 */
  login: (email: string, password: string) => Promise<void>;
  /** 手机验证码登录 */
  loginBySms: (phone: string, code: string) => Promise<void>;
  /** 注册 */
  register: (data: RegisterRequest) => Promise<void>;
  /** 获取当前用户信息 */
  fetchMe: () => Promise<void>;
  /** 登出 */
  logout: () => void;
  /** 从 localStorage 恢复登录状态 */
  loadFromStorage: () => void;
  /** 启动时尝试静默自动登录（基于 7 天免登录凭据） */
  attemptSilentAutoLogin: () => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  user: null,
  isAuthenticated: false,
  silentAutoLoginRunning: false,

  login: async (email: string, password: string) => {
    const data = await request<LoginResponse>(
      "post",
      "/api/kellai/auth/login",
      { email, password } satisfies LoginRequest
    );
    localStorage.setItem("auth_token", data.access_token);
    if (data.refresh_token) {
      localStorage.setItem("auth_refresh_token", data.refresh_token);
    }
    localStorage.setItem("auth_user", JSON.stringify(data.user));
    rememberEmail(email, data.user?.display_name || data.user?.name || "");
    set({
      token: data.access_token,
      user: data.user,
      isAuthenticated: true,
    });
  },

  loginBySms: async (phone: string, code: string) => {
    const data = await request<LoginResponse>(
      "post",
      "/api/kellai/auth/login",
      { phone, code } satisfies SmsLoginRequest
    );
    localStorage.setItem("auth_token", data.access_token);
    if (data.refresh_token) {
      localStorage.setItem("auth_refresh_token", data.refresh_token);
    }
    localStorage.setItem("auth_user", JSON.stringify(data.user));
    set({
      token: data.access_token,
      user: data.user,
      isAuthenticated: true,
    });
  },

  register: async (data: RegisterRequest) => {
    const result = await request<LoginResponse>(
      "post",
      "/api/kellai/auth/register",
      data satisfies RegisterRequest
    );
    localStorage.setItem("auth_token", result.access_token);
    if (result.refresh_token) {
      localStorage.setItem("auth_refresh_token", result.refresh_token);
    }
    localStorage.setItem("auth_user", JSON.stringify(result.user));
    rememberEmail(
      result.user?.email || data.email,
      result.user?.display_name || result.user?.name || data.display_name
    );
    set({
      token: result.access_token,
      user: result.user,
      isAuthenticated: true,
    });
  },

  fetchMe: async () => {
    const user = await request<User>("get", "/api/kellai/auth/me");
    localStorage.setItem("auth_user", JSON.stringify(user));
    set({ user });
  },

  logout: () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_refresh_token");
    localStorage.removeItem("auth_user");
    // 注意：不清理 kellai_last_email / kellai_remembered_emails
    // 不清理 kellai_saved_credentials（用户可能想 7 天免登录）
    set({ token: null, user: null, isAuthenticated: false });
  },

  loadFromStorage: () => {
    const token = localStorage.getItem("auth_token");
    const userStr = localStorage.getItem("auth_user");
    if (token && userStr) {
      try {
        const user = JSON.parse(userStr) as User;
        set({ token, user, isAuthenticated: true });
      } catch {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
      }
    }
  },

  /**
   * 启动时尝试静默自动登录。
   * 逻辑：
   *   1) 如果已经登录（token + user 都在），直接返回 true。
   *   2) 否则查找有 autoLoginEnabled 的最新凭据。
   *   3) 用保存的密码调用 login()，成功即进入；失败则清除该凭据的 autoLogin 开关。
   *   4) 如果没有任何可自动登录的凭据，返回 false。
   */
  attemptSilentAutoLogin: async () => {
    if (get().isAuthenticated) return true;
    set({ silentAutoLoginRunning: true });
    try {
      const creds = pruneExpiredCredentials();
      const target = creds.find((c) => c.autoLoginEnabled);
      if (!target) return false;
      const pwd = deobfuscatePassword(target.password);
      if (!pwd) {
        setAutoLoginEnabled(target.email, false);
        return false;
      }
      try {
        await get().login(target.email, pwd);
        // 成功：更新 lastAutoLoginAt
        const list = readCredentials();
        const idx = list.findIndex(
          (x) => x.email.toLowerCase() === target.email.toLowerCase()
        );
        if (idx >= 0) {
          list[idx] = {
            ...list[idx],
            lastAutoLoginAt: new Date().toISOString(),
          };
          writeCredentials(list);
        }
        return true;
      } catch {
        // 失败（密码错误 / 账号异常）：关闭该凭据的 autoLogin，避免下次再失败
        setAutoLoginEnabled(target.email, false);
        return false;
      }
    } finally {
      set({ silentAutoLoginRunning: false });
    }
  },
}));
