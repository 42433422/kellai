import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  LayoutDashboard,
  Filter,
  MessageSquare,
  Users,
  Bot,
  Settings,
  X,
} from "lucide-react";
import { clsx } from "clsx";

/** 搜索结果项类型 */
interface SearchResult {
  id: string;
  label: string;
  description?: string;
  icon: React.ElementType;
  action: () => void;
  category: string;
}

/** 导航页面配置 */
const NAV_PAGES = [
  { to: "/", label: "工作台", icon: LayoutDashboard, category: "页面" },
  { to: "/funnel", label: "漏斗看板", icon: Filter, category: "页面" },
  { to: "/messages", label: "消息中心", icon: MessageSquare, category: "页面" },
  { to: "/customers", label: "客户管理", icon: Users, category: "页面" },
  { to: "/ai", label: "AI 助手", icon: Bot, category: "页面" },
  { to: "/settings", label: "设置", icon: Settings, category: "页面" },
];

/** 搜索关键词映射：支持模糊匹配 */
const SEARCH_ALIASES: Record<string, string[]> = {
  "工作台": ["首页", "home", "dashboard"],
  "漏斗看板": ["漏斗", "看板", "funnel", "pipeline"],
  "消息中心": ["消息", "聊天", "message", "chat"],
  "客户管理": ["客户", "crm", "customer"],
  "AI 助手": ["ai", "助手", "bot", "机器人"],
  "设置": ["设置", "配置", "settings", "config"],
};

export default function SearchModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  /** 构建搜索结果 */
  const results = useCallback((): SearchResult[] => {
    if (!query.trim()) return [];

    const q = query.toLowerCase().trim();

    // 匹配导航页面
    const pageResults = NAV_PAGES.filter((page) => {
      // 直接匹配 label
      if (page.label.toLowerCase().includes(q)) return true;
      // 匹配别名
      const aliases = SEARCH_ALIASES[page.label] ?? [];
      return aliases.some((a) => a.toLowerCase().includes(q));
    }).map((page) => ({
      id: page.to,
      label: page.label,
      icon: page.icon,
      category: page.category,
      action: () => {
        navigate(page.to);
        onClose();
      },
    }));

    return pageResults;
  }, [query, navigate, onClose]);

  const resultItems = results();

  /** 打开时聚焦输入框 */
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  /** 全局键盘监听：Esc 关闭 */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  /** 键盘导航 */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev < resultItems.length - 1 ? prev + 1 : prev
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : 0));
    } else if (e.key === "Enter" && resultItems[selectedIndex]) {
      e.preventDefault();
      resultItems[selectedIndex].action();
    }
  };

  /** 滚动选中项到可见 */
  useEffect(() => {
    if (!resultsRef.current) return;
    const selected = resultsRef.current.querySelector(`[data-index="${selectedIndex}"]`);
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="全局搜索"
    >
      {/* 背景遮罩 */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 搜索面板 */}
      <div className="relative z-10 w-full max-w-xl overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-800">
        {/* 搜索输入区 */}
        <div className="flex items-center gap-3 border-b border-gray-100 px-4 dark:border-slate-700">
          <Search className="h-5 w-5 text-gray-400 dark:text-slate-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="搜索页面、功能..."
            className="flex-1 bg-transparent py-4 text-base text-gray-900 outline-none placeholder:text-gray-400 dark:text-slate-100 dark:placeholder:text-slate-500"
          />
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300"
            aria-label="关闭搜索"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 搜索结果 */}
        <div ref={resultsRef} className="max-h-80 overflow-y-auto p-2">
          {query && resultItems.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Search className="mb-2 h-8 w-8 text-gray-300 dark:text-slate-600" />
              <p className="text-sm text-gray-400 dark:text-slate-500">
                未找到「{query}」
              </p>
            </div>
          )}
          {!query && (
            <div className="py-6 text-center text-sm text-gray-400 dark:text-slate-500">
              输入关键词搜索页面和功能
            </div>
          )}
          {resultItems.length > 0 && (
            <div>
              {resultItems.map((item, idx) => (
                <button
                  key={item.id}
                  data-index={idx}
                  onClick={item.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={clsx(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                    idx === selectedIndex
                      ? "bg-blue-50 dark:bg-blue-500/15"
                      : "hover:bg-gray-50 dark:hover:bg-slate-700/50"
                  )}
                >
                  <item.icon
                    className={clsx(
                      "h-5 w-5 shrink-0",
                      idx === selectedIndex
                        ? "text-blue-600 dark:text-blue-400"
                        : "text-gray-400 dark:text-slate-500"
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className={clsx(
                      "text-sm font-medium",
                      idx === selectedIndex
                        ? "text-blue-900 dark:text-blue-200"
                        : "text-gray-700 dark:text-slate-200"
                    )}>
                      {item.label}
                    </div>
                  </div>
                  <span className={clsx(
                    "rounded px-1.5 py-0.5 text-xs",
                    idx === selectedIndex
                      ? "bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300"
                      : "bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-slate-500"
                  )}>
                    {item.category}
                  </span>
                  {idx === selectedIndex && (
                    <kbd className="hidden rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-400 dark:bg-slate-700 dark:text-slate-500 sm:inline-block">
                      Enter
                    </kbd>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 底部快捷键提示 */}
        <div className="flex items-center gap-4 border-t border-gray-100 px-4 py-2 text-xs text-gray-400 dark:border-slate-700 dark:text-slate-500">
          <span>
            <kbd className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono dark:bg-slate-700">↑↓</kbd>
            导航
          </span>
          <span>
            <kbd className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono dark:bg-slate-700">Enter</kbd>
            选择
          </span>
          <span>
            <kbd className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono dark:bg-slate-700">Esc</kbd>
            关闭
          </span>
        </div>
      </div>
    </div>
  );
}
