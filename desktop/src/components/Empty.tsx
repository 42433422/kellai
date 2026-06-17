import { Inbox, type LucideIcon } from "lucide-react";
import { clsx } from "clsx";

/**
 * 全局空状态组件
 * 当列表/数据为空时展示
 */
interface EmptyProps {
  /** 标题 */
  title?: string;
  /** 描述文案 */
  description?: string;
  /** 自定义图标（默认 Inbox） */
  icon?: LucideIcon;
  /** 额外的操作按钮（React 节点） */
  action?: React.ReactNode;
  /** 自定义类名 */
  className?: string;
  /** 图标颜色类名 */
  iconClassName?: string;
}

export default function Empty({
  title = "暂无数据",
  description = "这里还是空的",
  icon: Icon = Inbox,
  action,
  className,
  iconClassName = "text-gray-300 dark:text-slate-600",
}: EmptyProps) {
  return (
    <div
      className={clsx(
        "flex flex-1 flex-col items-center justify-center py-10 text-center",
        className
      )}
    >
      <div
        className={clsx(
          "mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gray-100 dark:bg-slate-800",
          iconClassName
        )}
      >
        <Icon className="h-7 w-7" />
      </div>
      <p className="text-sm font-medium text-gray-700 dark:text-slate-300">
        {title}
      </p>
      <p className="mt-1 max-w-xs text-xs text-gray-400 dark:text-slate-500">
        {description}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
