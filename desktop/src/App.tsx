import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState, lazy, Suspense } from "react";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Funnel from "./pages/Funnel";
import Messages from "./pages/Messages";
import CustomerDetail from "./pages/CustomerDetail";
import AIAssistant from "./pages/AIAssistant";
import Settings from "./pages/Settings";
import SalesFlow from "./pages/SalesFlow";
import Performance from "./pages/Performance";
import ContentStudio from "./pages/ContentStudio";
import ContentAnalytics from "./pages/ContentAnalytics";
import ScoutHunter from "./pages/ScoutHunter";
import SentimentMonitor from "./pages/SentimentMonitor";
import FlowMonitor from "./pages/FlowMonitor";
import TemplateMarket from "./pages/TemplateMarket";
import FinanceDashboard from "./pages/FinanceDashboard";
import FinanceAI from "./pages/FinanceAI";
import PerformanceBoard from "./pages/PerformanceBoard";
import OpenPlatform from "./pages/OpenPlatform";
import PluginMarket from "./pages/PluginMarket";
import DeveloperPortal from "./pages/DeveloperPortal";
import AppBuilder from "./pages/AppBuilder";
import APIDocs from "./pages/APIDocs";
import ErrorBoundary from "./components/ErrorBoundary";
import Loading from "./components/Loading";
import { useAuthStore } from "./stores/auth";
import { useThemeStore } from "./stores/theme";
import { useMessageStore } from "./stores/message";
import { useOnboardingStore } from "./stores/onboarding";
import { useSalesStore } from "./stores/salesStore";
import { useFinanceStore } from "./stores/financeStore";
import { useOpenPlatformStore } from "./stores/openPlatformStore";
import { Loader2, Users } from "lucide-react";

const FlowDesigner = lazy(() => import("./pages/FlowDesigner"));

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
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [phase, setPhase] = useState<"idle" | "trying" | "done">("idle");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      loadFromStorage();
      if (cancelled) return;
      if (useAuthStore.getState().isAuthenticated) {
        setPhase("done");
        return;
      }
      setPhase("trying");
      await attemptSilentAutoLogin();
      if (!cancelled) setPhase("done");
    })();
    return () => { cancelled = true; };
  }, [loadFromStorage, attemptSilentAutoLogin]);

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
  return <ErrorBoundary>{children}</ErrorBoundary>;
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
              <Route path="customers" element={<Page><PlaceholderPage title="客户管理" icon={Users} description="客户信息管理、标签分组、跟进记录，功能开发中..." /></Page>} />
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
              <Route path="flow/designer" element={<Page><Suspense fallback={<Loading />}><FlowDesigner /></Suspense></Page>} />
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
