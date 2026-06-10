import { create } from "zustand";

/** 主题模式：light 浅色 / dark 暗色 / system 跟随系统 */
export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "kellai_theme_mode";

/** 解析当前实际应用的主题（用于判断是否需要给 document 加 dark class） */
function resolveAppliedTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") {
    if (typeof window !== "undefined" && window.matchMedia) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }
    return "light";
  }
  return mode;
}

/** 将主题模式应用到 document.documentElement（添加/移除 .dark class） */
function applyThemeToDom(mode: ThemeMode) {
  if (typeof document === "undefined") return;
  const applied = resolveAppliedTheme(mode);
  const root = document.documentElement;
  if (applied === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
  root.setAttribute("data-theme", applied);
}

interface ThemeState {
  mode: ThemeMode;
  /** 当前实际生效的主题（计算属性） */
  applied: "light" | "dark";

  /** 设置主题模式并持久化 */
  setMode: (mode: ThemeMode) => void;
  /** 在 light / dark 之间循环切换（不进入 system 模式） */
  toggle: () => void;
  /** 从 localStorage 恢复并应用 */
  loadFromStorage: () => void;
  /** 监听系统主题变化（仅在 mode === 'system' 时生效） */
  initSystemListener: () => () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: "system",
  applied: "light",

  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    applyThemeToDom(mode);
    set({ mode, applied: resolveAppliedTheme(mode) });
  },

  toggle: () => {
    const current = get().applied;
    const nextMode: ThemeMode = current === "dark" ? "light" : "dark";
    get().setMode(nextMode);
  },

  loadFromStorage: () => {
    const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
    const mode: ThemeMode =
      stored === "light" || stored === "dark" || stored === "system"
        ? stored
        : "system";
    applyThemeToDom(mode);
    set({ mode, applied: resolveAppliedTheme(mode) });
  },

  initSystemListener: () => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return () => {};
    }
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      if (get().mode === "system") {
        applyThemeToDom("system");
        set({ applied: resolveAppliedTheme("system") });
      }
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  },
}));

export default useThemeStore;
