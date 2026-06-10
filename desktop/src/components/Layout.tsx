import { useState, useRef, useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Filter,
  MessageSquare,
  Users,
  Bot,
  Settings,
  Search,
  ChevronLeft,
  ChevronRight,
  LogOut,
  User as UserIcon,
  ChevronDown,
  Home,
  Sun,
  Moon,
  HelpCircle,
  type LucideIcon,
} from "lucide-react";
import { useAuthStore } from "../stores/auth";
import { useThemeStore } from "../stores/theme";
import { useMessageStore, selectUnreadTotal } from "../stores/message";
import { useOnboardingStore } from "../stores/onboarding";
import { clsx } from "clsx";
import SearchModal from "./SearchModal";
import NotificationDropdown from "./NotificationDropdown";
import NavItem from "./NavItem";
import OnboardingTutorial from "./OnboardingTutorial";
import OnboardingStartPanel from "./OnboardingStartPanel";
import VirtualCursor from "./VirtualCursor";

/** 侧边栏导航项配置（badge 不再硬编码，由 store 注入） */
type NavConfig = {
  to: string;
  icon: LucideIcon;
  label: string;
  end?: boolean;
  /** 未读数来源：返回 0 表示无徽标 */
  badgeFrom: (state: { unreadTotal: number; unreadByCustomer: Record<string, number> }) => number;
  /** 新手教程锚点（CSS 选择器值，会写到 data-tour 属性） */
  tour?: string;
};

const navConfig: NavConfig[] = [
    { to: "/", icon: LayoutDashboard, label: "工作台", end: true, badgeFrom: () => 0, tour: "nav-dashboard" },
    { to: "/funnel", icon: Filter, label: "漏斗看板", badgeFrom: () => 0, tour: "nav-funnel" },
    {
      to: "/messages",
      icon: MessageSquare,
      label: "消息中心",
      badgeFrom: (s) => s.unreadTotal,
      tour: "nav-messages",
    },
    { to: "/customers", icon: Users, label: "客户管理", badgeFrom: () => 0, tour: "nav-customers" },
    { to: "/ai", icon: Bot, label: "AI 助手", badgeFrom: () => 0, tour: "nav-ai" },
    { to: "/settings", icon: Settings, label: "设置", badgeFrom: () => 0, tour: "nav-settings" },
  ];

/** 面包屑映射 */
const breadcrumbMap: Record<string, string> = {
  "/": "工作台",
  "/funnel": "漏斗看板",
  "/messages": "消息中心",
  "/customers": "客户管理",
  "/ai": "AI 助手",
  "/settings": "设置",
};

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const { user, logout } = useAuthStore();
  const { applied, toggle } = useThemeStore();
  // 订阅未读汇总；只订阅需要的字段避免全量 re-render
  const unreadTotal = useMessageStore(selectUnreadTotal);
  const unreadByCustomer = useMessageStore((s) => s.unreadByCustomer);
  const messageState = { unreadTotal, unreadByCustomer };
  const navigate = useNavigate();
  const location = useLocation();

  // 新手教程
  const setOnboardingActive = useOnboardingStore((s) => s.setActive);
  const resetOnboarding = useOnboardingStore((s) => s.reset);
  const startOnboarding = (v: boolean) => {
    if (v) resetOnboarding();
    setOnboardingActive(v);
  };

  /** 退出登录 */
  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  /** 点击外部关闭用户菜单 */
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        userMenuRef.current &&
        !userMenuRef.current.contains(e.target as Node)
      ) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /** 全局快捷键：Cmd/Ctrl+K 打开搜索 */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  /** 当前页面面包屑 */
  const currentBreadcrumb = breadcrumbMap[location.pathname] || "工作台";
  const isDark = applied === "dark";

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-slate-900">
      {/* 侧边栏 */}
      <aside
        data-tour="sidebar"
        className={clsx(
          "flex shrink-0 flex-col border-r border-gray-200 bg-white text-slate-700 transition-all duration-300 dark:border-slate-700/50 dark:bg-slate-900 dark:text-slate-200",
          collapsed ? "w-16" : "w-60"
        )}
      >
        {/* Logo 区域 */}
        <div
          className={clsx(
            "flex h-14 items-center border-b border-slate-700/50 px-4",
            collapsed ? "justify-center" : "justify-between"
          )}
        >
          {!collapsed && (
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600">
                <span className="text-sm font-bold text-white">客</span>
              </div>
              <span className="text-base font-bold text-slate-900 dark:text-white">客来来</span>
            </div>
          )}
          {collapsed && (
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600">
              <span className="text-sm font-bold text-white">客</span>
            </div>
          )}
        </div>

        {/* 导航列表 */}
        <nav className="flex-1 space-y-1 px-2 py-3" aria-label="主导航">
          {navConfig.map((item) => (
            <NavItem
              key={item.to}
              to={item.to}
              icon={item.icon}
              label={item.label}
              end={item.end}
              collapsed={collapsed}
              badge={item.badgeFrom(messageState)}
              dataTour={item.tour}
            />
          ))}
        </nav>

        {/* 底部折叠按钮 */}
        <div className="border-t border-gray-200 p-2 dark:border-slate-700/50">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <>
                <ChevronLeft className="h-4 w-4" />
                <span>收起侧栏</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* 主内容区 */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 顶部栏 */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 dark:border-slate-700 dark:bg-slate-800">
          {/* 左侧：面包屑导航 */}
          <div className="flex items-center gap-2 text-sm">
            <Home className="h-4 w-4 text-gray-400 dark:text-slate-500" />
            <span className="text-gray-400 dark:text-slate-500">/</span>
            <span className="font-medium text-gray-700 dark:text-slate-200">
              {currentBreadcrumb}
            </span>
          </div>

          {/* 中间：全局搜索框（点击打开搜索面板） */}
          <button
            onClick={() => setSearchOpen(true)}
            data-tour="topbar-search"
            className="flex items-center gap-2 rounded-lg bg-gray-100 px-3 py-2 dark:bg-slate-700"
            aria-label="打开搜索"
          >
            <Search className="h-4 w-4 text-gray-400 dark:text-slate-400" />
            <span className="text-sm text-gray-400 dark:text-slate-400">搜索客户、消息...</span>
            <kbd className="ml-2 hidden rounded bg-white px-1.5 py-0.5 font-mono text-xs text-gray-400 dark:bg-slate-600 dark:text-slate-300 sm:inline-block">
              ⌘K
            </kbd>
          </button>

          {/* 右侧：通知 + 暗色模式 + 用户菜单 */}
          <div className="flex items-center gap-3">
            {/* 帮助 / 新手教程按钮 */}
            <button
              onClick={() => startOnboarding(true)}
              title="新手教程"
              aria-label="新手教程"
              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
            >
              <HelpCircle className="h-5 w-5" />
            </button>

            {/* 暗色模式切换按钮 */}
            <button
              onClick={toggle}
              title={isDark ? "切换到浅色模式" : "切换到暗色模式"}
              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              aria-label={isDark ? "切换到浅色模式" : "切换到暗色模式"}
            >
              {isDark ? (
                <Sun className="h-5 w-5" />
              ) : (
                <Moon className="h-5 w-5" />
              )}
            </button>

            {/* 通知铃铛 */}
            <NotificationDropdown />

            {/* 用户头像下拉菜单 */}
            <div className="relative" ref={userMenuRef}>
              <button
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                data-tour="user-menu"
                className="flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-gray-100 dark:hover:bg-slate-700"
                aria-label="用户菜单"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-xs font-medium text-white">
                  {user?.name?.charAt(0) || "U"}
                </div>
                <span className="hidden text-sm font-medium text-gray-700 dark:text-slate-200 sm:inline">
                  {user?.name || "用户"}
                </span>
                <ChevronDown
                  className={clsx(
                    "hidden h-4 w-4 text-gray-400 transition-transform dark:text-slate-400 sm:inline-block",
                    userMenuOpen && "rotate-180"
                  )}
                />
              </button>

              {/* 下拉菜单 */}
              {userMenuOpen && (
                <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  <div className="border-b border-gray-100 px-4 py-2.5 dark:border-slate-700">
                    <p className="text-sm font-medium text-gray-900 dark:text-slate-100">
                      {user?.name || "用户"}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-slate-400">
                      {user?.email || ""}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setUserMenuOpen(false);
                      navigate("/settings");
                    }}
                    aria-label="个人信息"
                    className="flex w-full items-center gap-2 px-4 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-50 dark:text-slate-200 dark:hover:bg-slate-700"
                  >
                    <UserIcon className="h-4 w-4" />
                    个人信息
                  </button>
                  <button
                    onClick={handleLogout}
                    aria-label="退出登录"
                    className="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 transition-colors hover:bg-red-50 dark:hover:bg-red-500/10"
                  >
                    <LogOut className="h-4 w-4" />
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* 页面内容
            - main 自身 overflow-hidden，h 由 flex-1 决定
            - 内层 wrapper 用 h-full flex flex-col：让子页面的 h-full 真正拿到这个受限高度
              （之前 wrapper 没有 height，导致 AI/Settings/Messages 的 h-full = auto，内容自由撑高 main） */}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="mx-auto flex h-full w-full max-w-7xl flex-1 flex-col p-6">
            <Outlet />
          </div>
        </main>
      </div>

      {/* 全局搜索面板 */}
      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />

      {/* 新手教程控制器：放在 Layout 内部，能用 useNavigate 跳路由 */}
      <OnboardingStartPanel />
      <OnboardingTutorial />
      <VirtualCursor />
    </div>
  );
}
