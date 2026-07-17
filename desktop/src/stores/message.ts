/**
 * 消息未读 store（全局共享）。
 *
 * 设计原则：
 * 1. 单一数据源：侧边栏徽标、消息中心、铃铛、面包屑等所有展示未读数的地方都从这取
 * 2. 轮询可控：start/stop 接口明确，避免在未登录时继续请求
 * 3. 错误静默：未读汇总不是关键数据，失败用旧值兜底
 */
import { create } from "zustand";
import { getUnreadSummary, markMessagesRead, syncInboxMessages } from "../api/messages";
import { useAuthStore } from "./auth";

interface MessageState {
  /** 团队级未读总数 */
  unreadTotal: number;
  /** 按客户分桶的未读数（key 为字符串化的 customer_id） */
  unreadByCustomer: Record<string, number>;
  /** 最近一次拉取时间（ms） */
  lastFetchedAt: number;
  /** 正在拉取中（避免重入） */
  loading: boolean;
  /** 后台轮询定时器 id */
  pollTimer: number | null;

  /** 拉取一次团队级未读汇总 */
  fetchUnread: () => Promise<void>;
  /** 标记指定客户为已读，并更新本地 store */
  markCustomerRead: (customerId: number | string) => Promise<void>;
  /** 标记全部为已读 */
  markAllRead: () => Promise<void>;
  /** 启动后台轮询（已登录时调用） */
  startPolling: (intervalMs?: number) => void;
  /** 停止后台轮询（登出时调用） */
  stopPolling: () => void;
  /** 重置 store（登出时调用） */
  reset: () => void;
}

const DEFAULT_POLL_MS = 15_000;

export const useMessageStore = create<MessageState>((set, get) => ({
  unreadTotal: 0,
  unreadByCustomer: {},
  lastFetchedAt: 0,
  loading: false,
  pollTimer: null,

  fetchUnread: async () => {
    // 未登录时直接跳过（避免 401 风暴）
    if (!useAuthStore.getState().isAuthenticated) return;
    if (get().loading) return;
    set({ loading: true });
    try {
      // 抖音 Webhook 落在公网 SSOT；先拉取并落到本地客户/消息库，
      // 再统计未读，确保用户不进入消息页也能看到新消息徽标。
      await syncInboxMessages("douyin", 50).catch(() => undefined);
      const summary = await getUnreadSummary();
      set({
        unreadTotal: summary.total,
        unreadByCustomer: summary.by_customer ?? {},
        lastFetchedAt: Date.now(),
        loading: false,
      });
    } catch {
      // 静默失败：未读不是关键数据，不弹 toast
      set({ loading: false });
    }
  },

  markCustomerRead: async (customerId: number | string) => {
    const key = String(customerId);
    const prev = get().unreadByCustomer;
    if (!prev[key]) return;
    // 乐观更新：先把本地清零
    const nextBy = { ...prev };
    delete nextBy[key];
    set({
      unreadByCustomer: nextBy,
      unreadTotal: Math.max(0, get().unreadTotal - (prev[key] || 0)),
    });
    try {
      await markMessagesRead({ customerId: Number(customerId) });
    } catch {
      // 失败则恢复（以服务端为准下次轮询会覆盖）
      set({ unreadByCustomer: prev, unreadTotal: get().unreadTotal + (prev[key] || 0) });
    }
  },

  markAllRead: async () => {
    if (get().unreadTotal === 0) return;
    const prevTotal = get().unreadTotal;
    const prevBy = get().unreadByCustomer;
    set({ unreadTotal: 0, unreadByCustomer: {} });
    try {
      await markMessagesRead({ all: true });
    } catch {
      // 失败回滚
      set({ unreadTotal: prevTotal, unreadByCustomer: prevBy });
    }
  },

  startPolling: (intervalMs: number = DEFAULT_POLL_MS) => {
    // 已登录校验（无 token 就不启）
    if (!useAuthStore.getState().isAuthenticated) return;
    // 避免重复启
    if (get().pollTimer) return;
    // 立即拉一次，再启定时器
    void get().fetchUnread();
    const timer = window.setInterval(() => {
      void get().fetchUnread();
    }, intervalMs);
    set({ pollTimer: timer });
  },

  stopPolling: () => {
    const timer = get().pollTimer;
    if (timer) {
      window.clearInterval(timer);
      set({ pollTimer: null });
    }
  },

  reset: () => {
    get().stopPolling();
    set({
      unreadTotal: 0,
      unreadByCustomer: {},
      lastFetchedAt: 0,
      loading: false,
    });
  },
}));

/** 便捷 selector：取未读总数 */
export const selectUnreadTotal = (s: MessageState) => s.unreadTotal;
