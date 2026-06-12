import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";

export interface KpiItem {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: { value: string; positive?: boolean };
  className?: string;
}

export default function KpiGrid({
  items,
  cols = 4,
}: {
  items: KpiItem[];
  cols?: 2 | 3 | 4 | 6;
}) {
  const gridClass =
    cols === 2
      ? "sm:grid-cols-2"
      : cols === 3
        ? "sm:grid-cols-2 lg:grid-cols-3"
        : cols === 6
          ? "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
          : "sm:grid-cols-2 lg:grid-cols-4";

  return (
    <div className={clsx("grid grid-cols-1 gap-4", gridClass)}>
      {items.map((item) => (
        <div
          key={item.title}
          className={clsx(
            "rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800",
            item.className
          )}
        >
          <div className="flex items-start justify-between">
            <p className="text-sm text-gray-500 dark:text-slate-400">{item.title}</p>
            {item.icon && (
              <item.icon className="h-5 w-5 text-blue-500 dark:text-blue-400" />
            )}
          </div>
          <p className="mt-2 text-2xl font-bold text-gray-900 dark:text-slate-100">
            {item.value}
          </p>
          {item.subtitle && (
            <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">{item.subtitle}</p>
          )}
          {item.trend && (
            <p
              className={clsx(
                "mt-1 text-xs font-medium",
                item.trend.positive
                  ? "text-green-600 dark:text-green-400"
                  : "text-red-600 dark:text-red-400"
              )}
            >
              {item.trend.value}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
