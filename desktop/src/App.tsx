import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Funnel from "./pages/Funnel";
import Messages from "./pages/Messages";
import CustomerDetail from "./pages/CustomerDetail";
import AIAssistant from "./pages/AIAssistant";
import Settings from "./pages/Settings";
import ErrorBoundary from "./components/ErrorBoundary";
import { useAuthStore } from "./stores/auth";
import { useThemeStore } from "./stores/theme";
import { useMessageStore } from "./stores/message";
import {
  useOnboardingStore,
} from "./stores/onboarding";
import { Loader2, Users } from "lucide-react";

/** 认证守卫：未登录时重定向到登录页 */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loadFromStorage, user } = useAuthStore();
  const loadOnboarding = useOnboardingStore((s) => s.loadForUser);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  // 首次登录后：把当前用户的教程状态加载到 store
  useEffect(() => {
    if (isAuthenticated && user?.id) {
      loadOnboarding(String(user.id));
    }
  }, [isAuthenticated, user?.id, loadOnboarding]);

  // 加载完成后：若状态为 not_started，自动弹出教程
  useEffect(() => {
    if (!isAuthenticated) return;
    // 首次登录自动显示启动面板（不再是直接启动教程）
    // 用户点"开始"才会真正进教程，点"跳过"则标记为已完成
    // 教程启动在 OnboardingStartPanel 里处理
  }, [isAuthenticated]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

/**
 * 启动期：根据"7 天免登录"凭据自动登录。
 *
 * 状态机：
 *   - idle：尚未尝试
 *   - trying：正在用保存的密码静默登录
 *   - done：已结束（成功 or 失败），由 Router 接管
 */
function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);
  const attemptSilentAutoLogin = useAuthStore((s) => s.attemptSilentAutoLogin);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [phase, setPhase] = useState<"idle" | "trying" | "done">("idle");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // 1) 优先看 localStorage 里的 token（用户上次没登出）
      loadFromStorage();
      if (cancelled) return;
      if (useAuthStore.getState().isAuthenticated) {
        setPhase("done");
        return;
      }
      // 2) 没有 token，但可能有"7 天免登录"凭据
      setPhase("trying");
      await attemptSilentAutoLogin();
      if (!cancelled) setPhase("done");
    })();
    return () => {
      cancelled = true;
    };
  }, [loadFromStorage, attemptSilentAutoLogin]);

  // 启动期：短暂显示"启动中"遮罩；只显示一次（phase==trying 时）
  if (phase === "trying" && !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <p className="text-sm">正在为您自动登录…</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

/** 消息未读轮询桥接：登录后启动轮询，登出时清理。
 *  仅做"挂载即订阅、卸载即清理"，不直接渲染 DOM。 */
function MessagePollingBridge() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const startPolling = useMessageStore((s) => s.startPolling);
  const stopPolling = useMessageStore((s) => s.stopPolling);
  const resetMessages = useMessageStore((s) => s.reset);

  useEffect(() => {
    if (isAuthenticated) {
      startPolling();
    } else {
      stopPolling();
      resetMessages();
    }
    return () => stopPolling();
  }, [isAuthenticated, startPolling, stopPolling, resetMessages]);

  return null;
}

/** 占位页面组件 */
function PlaceholderPage({
  title,
  icon: Icon,
  description,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-100 dark:bg-slate-800">
          <Icon className="h-8 w-8 text-gray-400 dark:text-slate-500" />
        </div>
        <h2 className="text-xl font-semibold text-gray-700 dark:text-slate-200">{title}</h2>
        <p className="mt-2 text-sm text-gray-400 dark:text-slate-500">{description}</p>
      </div>
    </div>
  );
}

/** 主题初始化组件：挂载时从 localStorage 恢复主题并订阅系统变化 */
function ThemeBootstrap({ children }: { children: React.ReactNode }) {
  const loadFromStorage = useThemeStore((s) => s.loadFromStorage);
  const initSystemListener = useThemeStore((s) => s.initSystemListener);

  useEffect(() => {
    loadFromStorage();
    const cleanup = initSystemListener();
    return cleanup;
  }, [loadFromStorage, initSystemListener]);

  return <>{children}</>;
}

export default function App() {
  return (
    <ThemeBootstrap>
      <AuthBootstrap>
        <MessagePollingBridge />
        <BrowserRouter>
          <Routes>
            {/* 登录页 */}
            <Route path="/login" element={<Login />} />

            {/* 需要认证的页面 - ErrorBoundary 包在 Layout 外面但 Route 里面 */}
            <Route
              path="/"
              element={
                <AuthGuard>
                  <Layout />
                </AuthGuard>
              }
            >
              {/* 工作台 - 每个页面独立 ErrorBoundary，避免一个页面崩溃影响全局 */}
              <Route index element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
              <Route path="funnel" element={<ErrorBoundary><Funnel /></ErrorBoundary>} />
              <Route path="messages" element={<ErrorBoundary><Messages /></ErrorBoundary>} />
              <Route path="customers/:id" element={<ErrorBoundary><CustomerDetail /></ErrorBoundary>} />
              <Route path="customers" element={<ErrorBoundary><PlaceholderPage title="客户管理" icon={Users} description="客户信息管理、标签分组、跟进记录，功能开发中..." /></ErrorBoundary>} />
              <Route path="ai" element={<ErrorBoundary><AIAssistant /></ErrorBoundary>} />
              <Route path="settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
            </Route>

            {/* 404 兜底 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthBootstrap>
    </ThemeBootstrap>
  );
}
