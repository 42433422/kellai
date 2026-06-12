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
  TrendingUp,
  GitBranch,
  PenTool,
  Crosshair,
  Workflow,
  Wallet,
  Globe,
  Zap,
  BarChart3,
  Radar,
  Activity,
  LayoutTemplate,
  LineChart,
  Brain,
  Trophy,
  Puzzle,
  Code,
  BookOpen,
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
import NavGroup from "./NavGroup";
import OnboardingTutorial from "./OnboardingTutorial";
import OnboardingStartPanel from "./OnboardingStartPanel";
import VirtualCursor from "./VirtualCursor";

/** 侧边栏导航项配置 */
type NavConfig = {
  to: string;
  icon: LucideIcon;
  label: string;
  end?: boolean;
  badgeFrom: (state: { unreadTotal: number; unreadByCustomer: Record<string, number> }) => number;
  tour?: string;
};

const coreNavConfig: NavConfig[] = [
  { to: "/", icon: LayoutDashboard, label: "工作台", end: true, badgeFrom: () => 0, tour: "nav-dashboard" },
  { to: "/funnel", icon: Filter, label: "漏斗看板", badgeFrom: () => 0, tour: "nav-funnel" },
  { to: "/messages", icon: MessageSquare, label: "消息中心", badgeFrom: (s) => s.unreadTotal, tour: "nav-messages" },
  { to: "/customers", icon: Users, label: "客户管理", badgeFrom: () => 0, tour: "nav-customers" },
  { to: "/ai", icon: Bot, label: "AI 助手", badgeFrom: () => 0, tour: "nav-ai" },
  { to: "/settings", icon: Settings, label: "设置", badgeFrom: () => 0, tour: "nav-settings" },
];

/** 面包屑映射 */
export const breadcrumbMap: Record<string, string> = {
  "/": "工作台",
  "/funnel": "漏斗看板",
  "/messages": "消息中心",
  "/customers": "客户管理",
  "/ai": "AI 助手",
  "/settings": "设置",
  "/sales/flow": "自动销售流程",
  "/sales/performance": "业绩看板",
  "/content/studio": "内容创作",
  "/content/analytics": "内容效果",
  "/scout/hunter": "猎手巡检",
  "/scout/sentiment": "舆情监控",
  "/flow/designer": "流程设计器",
  "/flow/monitor": "流程监控",
  "/flow/templates": "模板市场",
  "/finance/dashboard": "财务看板",
  "/finance/ai": "AI 财务助手",
  "/finance/performance": "绩效看板",
  "/open": "开放平台",
  "/open/plugins": "插件市场",
  "/open/developer": "开发者门户",
  "/open/app-builder": "应用构建器",
  "/open/docs": "API 文档",
};

function resolveBreadcrumb(pathname: string): string {
  if (breadcrumbMap[pathname]) return breadcrumbMap[pathname];
  const customerMatch = pathname.match(/^\/customers\/(\d+)$/);
  if (customerMatch) return "客户详情";
  return "工作台";
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const { user, logout } = useAuthStore();
  const { applied, toggle } = useThemeStore();
  const unreadTotal = useMessageStore(selectUnreadTotal);
  const unreadByCustomer = useMessageStore((s) => s.unreadByCustomer);
  const messageState = { unreadTotal, unreadByCustomer };
  const navigate = useNavigate();
  const location = useLocation();

  const setOnboardingActive = useOnboardingStore((s) => s.setActive);
  const resetOnboarding = useOnboardingStore((s) => s.reset);
  const startOnboarding = (v: boolean) => {
    if (v) resetOnboarding();
    setOnboardingActive(v);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

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

  const currentBreadcrumb = resolveBreadcrumb(location.pathname);
  const isDark = applied === "dark";

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-slate-900">
      <aside
        data-tour="sidebar"
        className={clsx(
          "flex shrink-0 flex-col border-r border-gray-200 bg-white text-slate-700 transition-all duration-300 dark:border-slate-700/50 dark:bg-slate-900 dark:text-slate-200",
          collapsed ? "w-16" : "w-60"
        )}
      >
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

        <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3" aria-label="主导航">
          {coreNavConfig.map((item) => (
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

          <NavGroup
            id="sales"
            label="销售增长"
            icon={TrendingUp}
            collapsed={collapsed}
            defaultOpen
            items={[
              { to: "/sales/flow", icon: GitBranch, label: "自动销售", dataTour: "nav-sales-flow" },
              { to: "/sales/performance", icon: BarChart3, label: "业绩看板", dataTour: "nav-sales-performance" },
            ]}
          />
          <NavGroup
            id="content"
            label="内容矩阵"
            icon={PenTool}
            collapsed={collapsed}
            items={[
              { to: "/content/studio", icon: PenTool, label: "内容创作" },
              { to: "/content/analytics", icon: LineChart, label: "效果分析" },
            ]}
          />
          <NavGroup
            id="scout"
            label="精准猎手"
            icon={Crosshair}
            collapsed={collapsed}
            items={[
              { to: "/scout/hunter", icon: Radar, label: "猎手巡检" },
              { to: "/scout/sentiment", icon: Activity, label: "舆情监控" },
            ]}
          />
          <NavGroup
            id="flow"
            label="流程闭环"
            icon={Workflow}
            collapsed={collapsed}
            items={[
              { to: "/flow/designer", icon: Workflow, label: "流程设计" },
              { to: "/flow/monitor", icon: Activity, label: "流程监控" },
              { to: "/flow/templates", icon: LayoutTemplate, label: "模板市场" },
            ]}
          />
          <NavGroup
            id="finance"
            label="智能财务"
            icon={Wallet}
            collapsed={collapsed}
            items={[
              { to: "/finance/dashboard", icon: Wallet, label: "财务看板" },
              { to: "/finance/ai", icon: Brain, label: "AI 财务" },
              { to: "/finance/performance", icon: Trophy, label: "绩效看板" },
            ]}
          />
          <NavGroup
            id="open"
            label="开放平台"
            icon={Globe}
            collapsed={collapsed}
            items={[
              { to: "/open", icon: Globe, label: "生态首页" },
              { to: "/open/plugins", icon: Puzzle, label: "插件市场" },
              { to: "/open/developer", icon: Code, label: "开发者" },
              { to: "/open/app-builder", icon: Zap, label: "应用构建" },
              { to: "/open/docs", icon: BookOpen, label: "API 文档" },
            ]}
          />
        </nav>

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

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 dark:border-slate-700 dark:bg-slate-800">
          <div className="flex items-center gap-2 text-sm">
            <Home className="h-4 w-4 text-gray-400 dark:text-slate-500" />
            <span className="text-gray-400 dark:text-slate-500">/</span>
            <span className="font-medium text-gray-700 dark:text-slate-200">{currentBreadcrumb}</span>
          </div>

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

          <div className="flex items-center gap-3">
            <button
              onClick={() => startOnboarding(true)}
              title="新手教程"
              aria-label="新手教程"
              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
            >
              <HelpCircle className="h-5 w-5" />
            </button>
            <button
              onClick={toggle}
              title={isDark ? "切换到浅色模式" : "切换到暗色模式"}
              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              aria-label={isDark ? "切换到浅色模式" : "切换到暗色模式"}
            >
              {isDark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <NotificationDropdown />
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
              {userMenuOpen && (
                <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  <div className="border-b border-gray-100 px-4 py-2.5 dark:border-slate-700">
                    <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{user?.name || "用户"}</p>
                    <p className="text-xs text-gray-500 dark:text-slate-400">{user?.email || ""}</p>
                  </div>
                  <button
                    onClick={() => { setUserMenuOpen(false); navigate("/settings"); }}
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

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="mx-auto flex h-full w-full max-w-7xl flex-1 flex-col p-6">
            <Outlet />
          </div>
        </main>
      </div>

      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
      <OnboardingStartPanel />
      <OnboardingTutorial />
      <VirtualCursor />
    </div>
  );
}
