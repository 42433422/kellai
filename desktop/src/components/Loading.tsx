import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { clsx } from "clsx";

/**
 * 全局 Loading 组件
 * 提供三种形态：
 * - spinner: 居中旋转图标 + 文案（默认）
 * - skeleton: 骨架屏（适合列表/卡片）
 * - block: 块级占位（适合大块区域）
 *
 * 通过 `visible` 配合 `delay` / `minDuration` 可避免：
 * 1) 接口过快返回时 Loading 一闪而过
 * 2) 接口较慢时 Loading 过晚出现
 */
interface LoadingProps {
  /** 是否可见（配合 delay / minDuration 使用；不传则默认总是显示） */
  visible?: boolean;
  /** 延迟显示（ms）。响应 < delay 时不展示，避免闪烁。默认 0 */
  delay?: number;
  /** 最短显示时长（ms）。从首次显示起算，避免一闪而过。默认 0 */
  minDuration?: number;
  /** 加载提示文案（spinner 模式展示，skeleton 模式作为 sr-only 读屏提示） */
  text?: string;
  /** 加载形态 */
  variant?: "spinner" | "skeleton" | "block";
  /** 自定义类名 */
  className?: string;
  /** 骨架屏行数（仅 skeleton 模式） */
  rows?: number;
  /**
   * 骨架屏每行标题宽度比例 0-1（仅 skeleton 模式）
   * 传单个数字则所有行相同；传数组则按顺序取值，最后一个值循环复用
   * 例：[1, 0.6, 0.8] 表示三行宽度递减
   */
  widths?: number | number[];
  /** spinner 尺寸（spinner / block 模式生效） */
  size?: "sm" | "md" | "lg";
}

const sizeMap = {
  sm: { box: "h-4 w-4", gap: "gap-1", text: "text-xs" },
  md: { box: "h-6 w-6", gap: "gap-2", text: "text-sm" },
  lg: { box: "h-8 w-8", gap: "gap-3", text: "text-base" },
} as const;

export default function Loading({
  visible = true,
  delay = 0,
  minDuration = 0,
  text = "加载中...",
  variant = "spinner",
  className,
  rows = 3,
  widths = 1,
  size = "md",
}: LoadingProps) {
  // 显隐状态机：综合 visible / delay / minDuration
  const [shown, setShown] = useState<boolean>(visible && delay <= 0);
  const shownAtRef = useRef<number | null>(
    visible && delay <= 0 ? Date.now() : null
  );
  const showTimerRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);

  useEffect(() => {
    // 清掉旧 timer
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }

    if (visible) {
      if (delay <= 0) {
        setShown(true);
        shownAtRef.current = Date.now();
      } else {
        showTimerRef.current = window.setTimeout(() => {
          setShown(true);
          shownAtRef.current = Date.now();
          showTimerRef.current = null;
        }, delay);
      }
      return;
    }

    // visible === false：尊重 minDuration
    if (minDuration > 0 && shownAtRef.current !== null) {
      const elapsed = Date.now() - shownAtRef.current;
      const remain = minDuration - elapsed;
      if (remain > 0) {
        hideTimerRef.current = window.setTimeout(() => {
          setShown(false);
          shownAtRef.current = null;
          hideTimerRef.current = null;
        }, remain);
        return;
      }
    }
    setShown(false);
    shownAtRef.current = null;
  }, [visible, delay, minDuration]);

  // 卸载时清 timer
  useEffect(() => {
    return () => {
      if (showTimerRef.current !== null) {
        window.clearTimeout(showTimerRef.current);
      }
      if (hideTimerRef.current !== null) {
        window.clearTimeout(hideTimerRef.current);
      }
    };
  }, []);

  if (!shown) return null;

  const sz = sizeMap[size];
  const a11y = {
    role: "status" as const,
    "aria-live": "polite" as const,
    "aria-busy": "true" as const,
    "aria-label": text,
  };

  if (variant === "skeleton") {
    const widthList = Array.isArray(widths) ? widths : [widths];
    return (
      <div className={clsx("space-y-3", className)} {...a11y}>
        {/* sr-only 提示：让传进来的 text 在骨架屏也生效（读屏 + 调试可见） */}
        <span className="sr-only">{text}</span>
        {Array.from({ length: rows }).map((_, i) => {
          const w = widthList[i] ?? widthList[widthList.length - 1] ?? 1;
          const clamped = Math.max(0.2, Math.min(1, w));
          const titleStyle = { width: `${clamped * 100}%` };
          // 副标题略宽于标题，更接近真实排版
          const subtitleStyle = {
            width: `${Math.min(1, clamped * 1.5) * 100}%`,
          };
          return (
            <div
              key={i}
              className="flex animate-pulse items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800"
              aria-hidden="true"
            >
              <div className="h-10 w-10 shrink-0 rounded-full bg-gray-200 dark:bg-slate-700" />
              <div className="flex-1 space-y-2">
                <div
                  className="h-3 rounded bg-gray-200 dark:bg-slate-700"
                  style={titleStyle}
                />
                <div
                  className="h-2.5 rounded bg-gray-200/80 dark:bg-slate-700"
                  style={subtitleStyle}
                />
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  if (variant === "block") {
    return (
      <div
        className={clsx(
          // 兜底 min-h-48，避免父容器无高度时塌成一排
          "flex h-full min-h-48 w-full animate-pulse items-center justify-center rounded-lg bg-gray-100 dark:bg-slate-800",
          className
        )}
        {...a11y}
      >
        <Loader2 className={clsx(sz.box, "animate-spin text-gray-400")} />
      </div>
    );
  }

  return (
    <div
      className={clsx(
        "flex flex-1 flex-col items-center justify-center py-8 text-gray-400 dark:text-slate-400",
        sz.gap,
        sz.text,
        className
      )}
      {...a11y}
    >
      <Loader2 className={clsx(sz.box, "animate-spin")} />
      <span>{text}</span>
    </div>
  );
}
