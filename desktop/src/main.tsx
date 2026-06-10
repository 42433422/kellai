import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import App from "./App";
import "./index.css";

/**
 * React Query 全局配置
 * - staleTime 30s：30s 内的相同请求直接使用缓存
 * - refetchOnWindowFocus false：避免窗口聚焦时频繁重新拉取
 * - retry 1：失败重试 1 次（401 等业务错误由 axios 拦截器处理，不在此重试）
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* 全局 toast 容器：右上角显示，主题跟随系统 */}
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 3000,
          style: {
            borderRadius: "8px",
            background: "#1f2937",
            color: "#fff",
            fontSize: "14px",
          },
          // 成功/错误样式在 react-hot-toast 默认基础上略作调整
          success: { iconTheme: { primary: "#10b981", secondary: "#fff" } },
          error: { iconTheme: { primary: "#ef4444", secondary: "#fff" } },
        }}
      />
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
