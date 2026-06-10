/**
 * 侧边栏导航项。
 *
 * 单一职责：渲染一个激活态/折叠态/带未读徽标的导航链接。
 * 激活态判断交由 react-router 的 NavLink 处理（isActive），不在外部派生。
 *
 * 无障碍要点：
 * - 链接可访问名 = 标签 + 未读数描述（避免与可视文本重复朗读）
 * - 图标与徽标标记 aria-hidden，不污染可访问名
 * - 99+ 截断统一处理
 */
import { NavLink } from "react-router-dom";
import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";

export interface NavItemProps {
  to: string;
  icon: LucideIcon;
  label: string;
  /** 是否精确匹配（仅 to="/" 时需要） */
  end?: boolean;
  /** 未读数量，0 / undefined 表示无徽标 */
  badge?: number;
  /** 侧边栏是否折叠 */
  collapsed?: boolean;
  /** 新手教程锚点（写到 data-tour 属性） */
  dataTour?: string;
}

function formatBadge(n: number): string {
  return n > 99 ? "99+" : String(n);
}

export default function NavItem({
  to,
  icon: Icon,
  label,
  end,
  badge = 0,
  collapsed = false,
  dataTour,
}: NavItemProps) {
  const hasBadge = badge > 0;
  // 把未读上下文写进 aria-label，屏幕阅读器读为「消息中心，3 条未读消息」
  // 可视徽标和图标标记 aria-hidden，避免重复朗读
  const ariaLabel = hasBadge ? `${label}，${formatBadge(badge)} 条未读消息` : label;

  return (
    <NavLink
      to={to}
      end={end}
      aria-label={ariaLabel}
      {...(dataTour ? { "data-tour": dataTour } : {})}
      className={({ isActive }) =>
        clsx(
          "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
          isActive
            ? "bg-blue-50 text-blue-600 dark:bg-blue-500/30 dark:text-blue-300"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        )
      }
    >
      <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && hasBadge && (
        <span
          aria-hidden="true"
          className="flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-medium text-white"
        >
          {formatBadge(badge)}
        </span>
      )}
      {collapsed && hasBadge && (
        <span
          aria-hidden="true"
          className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500"
        />
      )}
    </NavLink>
  );
}
