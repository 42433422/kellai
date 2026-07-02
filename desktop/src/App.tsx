import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState, lazy, Suspense } from "react";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import ErrorBoundary from "./components/ErrorBoundary";
import Loading from "./components/Loading";
import { useAuthStore } from "./stores/auth";
import { useThemeStore } from "./stores/theme";
import { useMessageStore } from "./stores/message";
import { useOnboardingStore } from "./stores/onboarding";
import { useSalesStore } from "./stores/salesStore";
import { useFinanceStore } from "./stores/financeStore";
import { useOpenPlatformStore } from "./stores/openPlatformStore";
import { Loader2 } from "lucide-react";

/* 路由级代码分割：除登录页外的页面按需懒加载，显著减小首屏 bundle。
   每个 Page 包裹了 Suspense 兜底（见下方 Page 组件）。 */
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Funnel = lazy(() => import("./pages/Funnel"));
const Messages = lazy(() => import("./pages/Messages"));
const CustomerDetail = lazy(() => import("./pages/CustomerDetail"));
const Customers = lazy(() => import("./pages/Customers"));
const AIAssistant = lazy(() => import("./pages/AIAssistant"));
const Settings = lazy(() => import("./pages/Settings"));
const SalesFlow = lazy(() => import("./pages/SalesFlow"));
const Performance = lazy(() => import("./pages/Performance"));
const ContentStudio = lazy(() => import("./pages/ContentStudio"));
const ContentAnalytics = lazy(() => import("./pages/ContentAnalytics"));
const ScoutHunter = lazy(() => import("./pages/ScoutHunter"));
const SentimentMonitor = lazy(() => import("./pages/SentimentMonitor"));
const FlowDesigner = lazy(() => import("./pages/FlowDesigner"));
const FlowMonitor = lazy(() => import("./pages/FlowMonitor"));
const TemplateMarket = lazy(() => import("./pages/TemplateMarket"));
const FinanceDashboard = lazy(() => import("./pages/FinanceDashboard"));
const FinanceAI = lazy(() => import("./pages/FinanceAI"));
const PerformanceBoard = lazy(() => import("./pages/PerformanceBoard"));
const OpenPlatform = lazy(() => import("./pages/OpenPlatform"));
const PluginMarket = lazy(() => import("./pages/PluginMarket"));
const DeveloperPortal = lazy(() => import("./pages/DeveloperPortal"));
const AppBuilder = lazy(() => import("./pages/AppBuilder"));
const APIDocs = lazy(() => import("./pages/APIDocs"));

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loadFromStorage, user } = useAuthStore();
  const loadOnboarding = useOnboardingStore((s) => s.loadForUser);
  const loadSales = useSalesStore((s) => s.loadFromStorage);
  const loadFinance = useFinanceStore((s) => s.loadFromStorage);
  const loadOpen = useOpenPlatformStore((s) => s.loadFromStorage);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  useEffect(() => {
    if (isAuthenticated && user?.id) {
      loadOnboarding(String(user.id));
      loadSales();
      loadFinance();
      loadOpen();
    }
  }, [isAuthenticated, user?.id, loadOnboarding, loadSales, loadFinance, loadOpen]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);
  const attemptSilentAutoLogin = useAuthStore((s) => s.attemptSilentAutoLogin);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [phase, setPhase] = useState<"idle" | "trying" | "done">("idle");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      loadFromStorage();
      if (cancelled) return;
      if (useAuthStore.getState().isAuthenticated) {
        setPhase("trying");
        try {
          await fetchMe();
        } catch {
          logout();
          await attemptSilentAutoLogin();
        }
        if (cancelled) return;
        setPhase("done");
        return;
      }
      setPhase("trying");
      await attemptSilentAutoLogin();
      if (!cancelled) setPhase("done");
    })();
    return () => { cancelled = true; };
  }, [loadFromStorage, fetchMe, logout, attemptSilentAutoLogin]);

  if (phase !== "done" && !isAuthenticated) {
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

function Page({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<Loading className="min-h-[60vh]" text="页面加载中..." />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <ThemeBootstrap>
      <AuthBootstrap>
        <MessagePollingBridge />
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/"
              element={
                <AuthGuard>
                  <Layout />
                </AuthGuard>
              }
            >
              <Route index element={<Page><Dashboard /></Page>} />
              <Route path="funnel" element={<Page><Funnel /></Page>} />
              <Route path="messages" element={<Page><Messages /></Page>} />
              <Route path="customers/:id" element={<Page><CustomerDetail /></Page>} />
              <Route path="customers" element={<Page><Customers /></Page>} />
              <Route path="ai" element={<Page><AIAssistant /></Page>} />
              <Route path="settings" element={<Page><Settings /></Page>} />
              {/* v3 Sales */}
              <Route path="sales/flow" element={<Page><SalesFlow /></Page>} />
              <Route path="sales/performance" element={<Page><Performance /></Page>} />
              {/* v4 Content */}
              <Route path="content/studio" element={<Page><ContentStudio /></Page>} />
              <Route path="content/analytics" element={<Page><ContentAnalytics /></Page>} />
              {/* v5 Scout */}
              <Route path="scout/hunter" element={<Page><ScoutHunter /></Page>} />
              <Route path="scout/sentiment" element={<Page><SentimentMonitor /></Page>} />
              {/* v6 Flow */}
              <Route path="flow/designer" element={<Page><FlowDesigner /></Page>} />
              <Route path="flow/monitor" element={<Page><FlowMonitor /></Page>} />
              <Route path="flow/templates" element={<Page><TemplateMarket /></Page>} />
              {/* v7 Finance */}
              <Route path="finance/dashboard" element={<Page><FinanceDashboard /></Page>} />
              <Route path="finance/ai" element={<Page><FinanceAI /></Page>} />
              <Route path="finance/performance" element={<Page><PerformanceBoard /></Page>} />
              {/* v8 Open */}
              <Route path="open" element={<Page><OpenPlatform /></Page>} />
              <Route path="open/plugins" element={<Page><PluginMarket /></Page>} />
              <Route path="open/developer" element={<Page><DeveloperPortal /></Page>} />
              <Route path="open/app-builder" element={<Page><AppBuilder /></Page>} />
              <Route path="open/docs" element={<Page><APIDocs /></Page>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthBootstrap>
    </ThemeBootstrap>
  );
}
