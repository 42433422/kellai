import { useEffect, useState } from "react";
import { useOnboardingStore } from "../stores/onboarding";
import { Sparkles, Play, X, Check } from "lucide-react";

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

  // 首次进入：1.2s 后淡入
  useEffect(() => {
    if (state !== "not_started") {
      setShow(false);
      setVisible(false);
      return;
    }
    if (active) {
      // 教程已经在跑，隐藏面板
      setShow(false);
      setVisible(false);
      return;
    }
    // 1.2s 延迟弹，让 dashboard 先渲染
    const t = window.setTimeout(() => {
      setShow(true);
      // 下一帧加 visible 触发过渡
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
    // 24h 后再弹（如果还是 not_started）
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
      {/* 背景遮罩（轻一点） */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: visible ? "rgba(15, 23, 42, 0.45)" : "rgba(15, 23, 42, 0)",
          backdropFilter: visible ? "blur(2px)" : "none",
          zIndex: 999998,
          transition: "background .25s",
        }}
        onClick={handleLater}
      />

      {/* 中心卡片 */}
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
          width: "min(440px, calc(100vw - 32px))",
          background: "white",
          borderRadius: 16,
          boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
          padding: 0,
          overflow: "hidden",
          fontFamily: "inherit",
        }}
      >
        {/* 顶部渐变 banner */}
        <div
          style={{
            background: "linear-gradient(135deg, #3b82f6 0%, #6366f1 50%, #8b5cf6 100%)",
            padding: "28px 24px 22px",
            color: "white",
            position: "relative",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 12,
              right: 12,
              cursor: "pointer",
              padding: 4,
              borderRadius: 6,
              opacity: 0.7,
              transition: "opacity .15s, background .15s",
            }}
            onClick={handleLater}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "1";
              e.currentTarget.style.background = "rgba(255,255,255,.15)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "0.7";
              e.currentTarget.style.background = "transparent";
            }}
            aria-label="关闭"
          >
            <X size={18} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <Sparkles size={24} />
            <span style={{ fontSize: 13, opacity: 0.9, fontWeight: 500 }}>新手教程 · 1.0</span>
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, lineHeight: 1.3 }}>
            30 秒带你玩转 客来来
          </h1>
          <p style={{ margin: "6px 0 0", fontSize: 14, opacity: 0.95 }}>
            我会亲自动手演示 5 大核心功能
          </p>
        </div>

        {/* 内容区 */}
        <div style={{ padding: "20px 24px" }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              marginBottom: 20,
            }}
          >
            {[
              { icon: "🌪️", text: "拖拽客户卡片，5 秒更新状态" },
              { icon: "💬", text: "AI 自动写话术，省 3 分钟" },
              { icon: "👤", text: "客户 360° 画像，沟通更准" },
              { icon: "🤖", text: "智能分析意图，1 秒看穿客户" },
              { icon: "🔍", text: "⌘K 全局搜索，5 秒跳转" },
            ].map((item, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 12px",
                  background: "#f8fafc",
                  borderRadius: 8,
                  fontSize: 14,
                  color: "#334155",
                }}
              >
                <span style={{ fontSize: 18 }}>{item.icon}</span>
                <span style={{ flex: 1 }}>{item.text}</span>
                <Check size={14} style={{ color: "#10b981" }} />
              </div>
            ))}
          </div>

          {/* 主按钮 */}
          <button
            type="button"
            onClick={handleStart}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              width: "100%",
              padding: "12px 16px",
              background: "linear-gradient(135deg, #3b82f6 0%, #6366f1 100%)",
              color: "white",
              border: "none",
              borderRadius: 10,
              fontSize: 15,
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 4px 14px rgba(59, 130, 246, 0.35)",
              transition: "transform .15s, box-shadow .15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = "translateY(-1px)";
              e.currentTarget.style.boxShadow = "0 6px 20px rgba(59, 130, 246, 0.5)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = "";
              e.currentTarget.style.boxShadow = "0 4px 14px rgba(59, 130, 246, 0.35)";
            }}
          >
            <Play size={16} fill="white" />
            开始 30 秒教程
          </button>

          {/* 次要操作 */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginTop: 12,
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
              不用了，谢谢
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
