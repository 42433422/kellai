import { useEffect, useState } from "react";
import { useOnboardingStore } from "../stores/onboarding";
import { X, ChevronRight } from "lucide-react";

/**
 * 教程启动面板
 * - 仅在 state === "not_started" 且教程没在跑时显示
 * - 用户点"开始"才真正启动教程，点"跳过"则标记完成（不再弹）
 * - 第一次登录后 1.2s 浮现
 */
export default function OnboardingStartPanel() {
  const state = useOnboardingStore((s) => s.state);
  const active = useOnboardingStore((s) => s.active);
  const setActive = useOnboardingStore((s) => s.setActive);
  const markCompleted = useOnboardingStore((s) => s.markCompleted);
  const [show, setShow] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (state !== "not_started") {
      setShow(false);
      setVisible(false);
      return;
    }
    if (active) {
      setShow(false);
      setVisible(false);
      return;
    }
    const t = window.setTimeout(() => {
      setShow(true);
      requestAnimationFrame(() => setVisible(true));
    }, 1200);
    return () => window.clearTimeout(t);
  }, [state, active]);

  if (!show) return null;

  const handleStart = () => {
    setVisible(false);
    window.setTimeout(() => {
      setActive(true);
      setShow(false);
    }, 200);
  };

  const handleSkip = () => {
    setVisible(false);
    window.setTimeout(() => {
      markCompleted();
      setShow(false);
    }, 200);
  };

  const handleLater = () => {
    setVisible(false);
    window.setTimeout(() => setShow(false), 200);
    window.setTimeout(() => {
      const s = useOnboardingStore.getState();
      if (s.state === "not_started" && !s.active) {
        setShow(true);
        requestAnimationFrame(() => setVisible(true));
      }
    }, 24 * 60 * 60 * 1000);
  };

  return (
    <>
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: visible ? "rgba(15, 23, 42, 0.4)" : "rgba(15, 23, 42, 0)",
          backdropFilter: visible ? "blur(2px)" : "none",
          zIndex: 999998,
          transition: "background .25s",
        }}
        onClick={handleLater}
      />

      <div
        role="dialog"
        aria-label="新手教程"
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: visible
            ? "translate(-50%, -50%) scale(1)"
            : "translate(-50%, -50%) scale(0.95)",
          opacity: visible ? 1 : 0,
          transition: "transform .3s cubic-bezier(.34, 1.56, .64, 1), opacity .2s",
          zIndex: 999999,
          width: "min(420px, calc(100vw - 32px))",
          background: "white",
          borderRadius: 12,
          boxShadow: "0 12px 40px rgba(0, 0, 0, 0.15)",
          padding: 0,
          overflow: "hidden",
          fontFamily: "inherit",
        }}
      >
        {/* 顶部区域 */}
        <div
          style={{
            padding: "24px 24px 0",
          }}
        >
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span
              style={{
                fontSize: 12,
                fontWeight: 500,
                color: "#6366f1",
                background: "#eef2ff",
                padding: "2px 8px",
                borderRadius: 4,
              }}
            >
              新手引导
            </span>
            <div
              style={{
                cursor: "pointer",
                padding: 4,
                borderRadius: 6,
                color: "#94a3b8",
                transition: "color .15s",
              }}
              onClick={handleLater}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "#475569";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "#94a3b8";
              }}
              aria-label="关闭"
            >
              <X size={16} />
            </div>
          </div>
          <h1
            style={{
              margin: "12px 0 4px",
              fontSize: 20,
              fontWeight: 600,
              lineHeight: 1.4,
              color: "#0f172a",
            }}
          >
            60 秒了解客来来
          </h1>
          <p style={{ margin: 0, fontSize: 14, color: "#64748b" }}>
            跟随引导完成核心功能配置
          </p>
        </div>

        {/* 功能列表 */}
        <div style={{ padding: "16px 24px" }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 1,
              background: "#f1f5f9",
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            {[
              { text: "接入渠道，接收客户消息", tag: "必选" },
              { text: "配置 AI 助手，启用智能功能", tag: "必选" },
              { text: "工作台与漏斗看板", tag: "核心" },
              { text: "消息中心与客户详情", tag: "核心" },
              { text: "自动销售流程与业绩看板 (v3)", tag: "增长" },
              { text: "开放平台与插件生态 (v8)", tag: "生态" },
              { text: "全局搜索 ⌘K", tag: "效率" },
            ].map((item, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  background: "white",
                  fontSize: 13,
                  color: "#334155",
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 500,
                    color: item.tag === "必选" ? "#2563eb" : item.tag === "核心" ? "#7c3aed" : item.tag === "增长" ? "#059669" : item.tag === "生态" ? "#d97706" : "#64748b",
                    background: item.tag === "必选" ? "#eff6ff" : item.tag === "核心" ? "#f5f3ff" : item.tag === "增长" ? "#ecfdf5" : item.tag === "生态" ? "#fffbeb" : "#f1f5f9",
                    padding: "1px 6px",
                    borderRadius: 3,
                    flexShrink: 0,
                  }}
                >
                  {item.tag}
                </span>
                <span style={{ flex: 1 }}>{item.text}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 操作区 */}
        <div
          style={{
            padding: "0 24px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <button
            type="button"
            onClick={handleStart}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              width: "100%",
              padding: "10px 16px",
              background: "#0f172a",
              color: "white",
              border: "none",
              borderRadius: 8,
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
              transition: "background .15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#1e293b";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#0f172a";
            }}
          >
            开始引导
            <ChevronRight size={14} />
          </button>

          <div
            style={{
              display: "flex",
              justifyContent: "center",
              gap: 16,
              fontSize: 13,
            }}
          >
            <button
              type="button"
              onClick={handleLater}
              style={{
                background: "transparent",
                border: "none",
                color: "#64748b",
                cursor: "pointer",
                padding: "4px 8px",
                fontSize: 13,
              }}
            >
              稍后再说
            </button>
            <button
              type="button"
              onClick={handleSkip}
              style={{
                background: "transparent",
                border: "none",
                color: "#94a3b8",
                cursor: "pointer",
                padding: "4px 8px",
                fontSize: 13,
              }}
            >
              跳过
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
