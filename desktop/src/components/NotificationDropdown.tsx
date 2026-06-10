import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCircle2, AlertTriangle, Clock, Inbox } from "lucide-react";
import { clsx } from "clsx";
import { getReminders, type FollowUpReminder } from "../api/ai";
import { useMessageStore, selectUnreadTotal } from "../stores/message";

/** 通知项（前端统一视图） */
interface NotificationItem {
  /** 稳定 key：用 customer_id；非客户通知用 'sys' 兜底 */
  id: string;
  title: string;
  description: string;
  type: "info" | "warning" | "success";
  /** 距上次跟进的小时数（仅 follow-up 类） */
  hoursSince?: number;
  /** 客户 id，跳转时携带 */
  customerId?: number;
  read: boolean;
}

/** 提醒紧迫度 → 类型 */
function reminderToType(stage: string, hours: number): NotificationItem["type"] {
  if (hours >= 72 || stage === "negotiation" || stage === "contract_pending") {
    return "warning";
  }
  if (stage === "signed" || stage === "delivered") {
    return "success";
  }
  return "info";
}

/** 把"距上次跟进 X 小时"格式化成"X小时未跟进" */
function formatHoursAgo(hours: number): string {
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${Math.round(hours)} 小时未跟进`;
  const days = Math.floor(hours / 24);
  return `${days} 天未跟进`;
}

/** 通知类型图标 */
const typeIconMap = {
  info: Clock,
  warning: AlertTriangle,
  success: CheckCircle2,
};

/** 通知类型颜色 */
const typeColorMap = {
  info: "text-blue-500 dark:text-blue-400",
  warning: "text-amber-500 dark:text-amber-400",
  success: "text-green-500 dark:text-green-400",
};

export default function NotificationDropdown() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  /** 团队级未读消息数（与侧栏徽标同源） */
  const messageUnread = useMessageStore(selectUnreadTotal);
  const markCustomerRead = useMessageStore((s) => s.markCustomerRead);
  const markAllRead = useMessageStore((s) => s.markAllRead);

  /** 加载提醒数据 */
  const loadNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const list: FollowUpReminder[] = await getReminders(48, 10);
      setNotifications(
        list.map((r) => ({
          id: `c-${r.customer_id}`,
          title: `${r.display_name || `客户${r.customer_id}`} 待跟进`,
          description: r.suggested_action || "请及时跟进客户",
          type: reminderToType(r.stage, r.hours_since_last_contact),
          hoursSince: r.hours_since_last_contact,
          customerId: r.customer_id,
          read: false,
        }))
      );
    } catch {
      // 失败时给出明确空态，不要伪造假数据误导用户
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, []);

  /** 首次展开时加载；后续不再重复拉（避免对后端造成压力） */
  useEffect(() => {
    if (open && notifications.length === 0 && !loading) {
      void loadNotifications();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /** 点击外部关闭 + ESC 关闭 */
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  /** 单条标记已读：本地乐观更新 + 同步调 store 标记该客户消息已读 */
  const markRead = (item: NotificationItem) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === item.id ? { ...n, read: true } : n))
    );
    if (item.customerId !== undefined) {
      void markCustomerRead(item.customerId);
    }
  };

  /** 全部标记已读：调用 store（团队级） */
  const handleMarkAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    void markAllRead();
  };

  /** 跳到客户详情 */
  const goCustomer = (item: NotificationItem) => {
    markRead(item);
    if (item.customerId !== undefined) {
      setOpen(false);
      navigate(`/customers/${item.customerId}`);
    }
  };

  /** 铃铛徽标 = 团队未读消息数 + 本地未读提醒数（取大者，便于发现遗漏） */
  const reminderUnread = notifications.filter((n) => !n.read).length;
  const badgeCount = Math.max(messageUnread, reminderUnread);

  return (
    <div className="relative" ref={containerRef}>
      {/* 铃铛按钮 */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          badgeCount > 0 ? `通知，${badgeCount} 条未读` : "通知"
        }
        className="relative rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
      >
        <Bell className="h-5 w-5" />
        {badgeCount > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-medium text-white">
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </button>

      {/* 下拉面板 */}
      {open && (
        <div
          role="menu"
          aria-label="通知列表"
          className="absolute right-0 top-full z-50 mt-2 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800"
        >
          {/* 头部 */}
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-slate-700">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-gray-500 dark:text-slate-400" />
              <span className="text-sm font-semibold text-gray-900 dark:text-slate-100">
                通知
              </span>
              {reminderUnread > 0 && (
                <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600 dark:bg-red-500/15 dark:text-red-400">
                  {reminderUnread} 条待跟进
                </span>
              )}
            </div>
            {reminderUnread > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="flex items-center gap-1 text-xs text-blue-600 transition hover:text-blue-700 dark:text-blue-400"
              >
                <CheckCircle2 className="h-3 w-3" />
                全部已读
              </button>
            )}
          </div>

          {/* 通知列表 */}
          <div className="max-h-96 overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center py-8">
                <div
                  className="h-5 w-5 animate-spin rounded-full border-2 border-gray-200 border-t-blue-500"
                  aria-label="加载中"
                />
              </div>
            )}
            {!loading && notifications.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <Inbox className="mb-2 h-10 w-10 text-gray-300 dark:text-slate-600" />
                <p className="text-sm text-gray-500 dark:text-slate-400">
                  暂无待跟进提醒
                </p>
                <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">
                  所有客户都在 48 小时内有跟进记录
                </p>
              </div>
            )}
            {!loading &&
              notifications.map((notification) => {
                const Icon = typeIconMap[notification.type];
                return (
                  <div
                    key={notification.id}
                    role="menuitem"
                    tabIndex={0}
                    onClick={() => goCustomer(notification)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        goCustomer(notification);
                      }
                    }}
                    className={clsx(
                      "flex cursor-pointer items-start gap-3 border-b border-gray-50 px-4 py-3 transition-colors last:border-0 hover:bg-gray-50 focus:bg-gray-50 focus:outline-none dark:border-slate-700/50 dark:hover:bg-slate-700/50 dark:focus:bg-slate-700/50",
                      !notification.read && "bg-blue-50/30 dark:bg-blue-500/5"
                    )}
                  >
                    <div
                      className={clsx(
                        "mt-0.5 shrink-0",
                        typeColorMap[notification.type]
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium text-gray-900 dark:text-slate-100">
                          {notification.title}
                        </p>
                        {!notification.read && (
                          <span
                            className="h-2 w-2 shrink-0 rounded-full bg-blue-500"
                            aria-label="未读"
                          />
                        )}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-xs text-gray-500 dark:text-slate-400">
                        {notification.description}
                      </p>
                      {notification.hoursSince !== undefined && (
                        <p className="mt-1 text-[10px] text-gray-400 dark:text-slate-500">
                          {formatHoursAgo(notification.hoursSince)}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>

          {/* 底部：跳到消息中心（用全局未读数作引导） */}
          {messageUnread > 0 && (
            <div className="border-t border-gray-100 px-4 py-2 dark:border-slate-700">
              <button
                onClick={() => {
                  setOpen(false);
                  navigate("/messages");
                }}
                className="w-full text-center text-xs text-blue-600 transition hover:text-blue-700 dark:text-blue-400"
              >
                查看全部 {messageUnread} 条未读消息 →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
