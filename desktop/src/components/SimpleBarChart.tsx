import { clsx } from "clsx";

export interface BarChartItem {
  label: string;
  value: number;
  color?: string;
}

export default function SimpleBarChart({
  items,
  unit = "%",
  maxValue,
}: {
  items: BarChartItem[];
  unit?: string;
  maxValue?: number;
}) {
  const max = maxValue ?? Math.max(...items.map((i) => i.value), 1);

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1 flex justify-between text-sm">
            <span className="text-gray-600 dark:text-slate-300">{item.label}</span>
            <span className="font-medium text-gray-900 dark:text-slate-100">
              {item.value}
              {unit}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
            <div
              className={clsx("h-full rounded-full transition-all", item.color ?? "bg-blue-500")}
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
