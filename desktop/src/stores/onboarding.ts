/**
 * 新手教程状态（zustand + localStorage 持久化）
 *
 * 设计要点：
 * 1. 教程是否完成按"用户"维度记录（per-user + per-device）
 *    - key = `kellai:onboarding:<userId>`
 * 2. 用户主动跳过 / 完成后不再自动弹出
 * 3. 用户在设置页可以随时"重新开始新手教程"
 * 4. 不阻塞 UI：startTutorial() 触发后即返回，driver 实例由组件挂载
 */

import { create } from "zustand";

const ONBOARDING_PREFIX = "kellai:onboarding:";

/** 教程状态枚举（序列化到 localStorage） */
export type OnboardingState =
  | "not_started" // 未开始
  | "completed" // 已完成
  | "skipped"; // 用户主动跳过

interface OnboardingStore {
  /** 当前用户的教程状态 */
  state: OnboardingState;
  /** 当前用户 id（用于本地存储 key） */
  userId: string | null;
  /** driver.js 是否在运行（react 侧判断） */
  active: boolean;

  /** 初始化：读 localStorage（必须在拿到 userId 后调用） */
  loadForUser: (userId: string) => void;
  /** 标记完成 */
  markCompleted: () => void;
  /** 标记跳过（用户点击"下次再说"） */
  markSkipped: () => void;
  /** 标记未开始（设置页点"重新开始"） */
  reset: () => void;
  /** 设置 driver.js 是否在运行（让 UI 知道要不要显示遮罩） */
  setActive: (v: boolean) => void;
}

function readFromStorage(userId: string): OnboardingState {
  try {
    const raw = localStorage.getItem(ONBOARDING_PREFIX + userId);
    if (raw === "completed" || raw === "skipped" || raw === "not_started") {
      return raw;
    }
    // 默认未开始（首次登录）
    return "not_started";
  } catch {
    return "not_started";
  }
}

function writeToStorage(userId: string, state: OnboardingState) {
  try {
    localStorage.setItem(ONBOARDING_PREFIX + userId, state);
  } catch {
    // localStorage 满 / 隐私模式：忽略
  }
}

export const useOnboardingStore = create<OnboardingStore>((set, get) => ({
  state: "not_started",
  userId: null,
  active: false,

  loadForUser: (userId) => {
    const state = readFromStorage(userId);
    set({ userId, state });
  },

  markCompleted: () => {
    const { userId } = get();
    if (!userId) return;
    writeToStorage(userId, "completed");
    set({ state: "completed", active: false });
  },

  markSkipped: () => {
    const { userId } = get();
    if (!userId) return;
    writeToStorage(userId, "skipped");
    set({ state: "skipped", active: false });
  },

  reset: () => {
    const { userId } = get();
    if (!userId) return;
    writeToStorage(userId, "not_started");
    set({ state: "not_started" });
  },

  setActive: (v) => set({ active: v }),
}));

/** 辅助：当前是否应该自动弹出教程（仅 not_started 时弹） */
export function shouldAutoShowTutorial(state: OnboardingState): boolean {
  return state === "not_started";
}
