/**
 * 虚拟光标（教程演示用）
 *
 * 教程里会"自动点击"页面元素，但用户看不到鼠标动。加这个：
 * - 一个真实形态的鼠标 SVG
 * - 平滑移动到目标元素
 * - 到达后做一次 click 动画（波纹）
 * - 可选地显示一个标签文字（"点这个"、"拖到这里"）
 *
 * 暴露的 API：
 *   window.virtualCursor.moveTo(target, { duration?, click?, label? })
 *   window.virtualCursor.click(target, { duration?, label? })
 *
 * target: HTMLElement 或 { x, y } 绝对坐标
 */

import { useEffect, useRef, useState } from "react";

/** 全局可调用的 API 类型 */
export interface VirtualCursorApi {
  /** 移动到 target，可选 click + label */
  moveTo(
    target: HTMLElement | { x: number; y: number },
    options?: { duration?: number; click?: boolean; label?: string }
  ): void;
  /** 移动 + 点击 target（默认移动 500ms 后点） */
  click(
    target: HTMLElement,
    options?: { duration?: number; label?: string }
  ): void;
  /** 隐藏 */
  hide(): void;
  /** 显示 */
  show(): void;
}

declare global {
  interface Window {
    virtualCursor?: VirtualCursorApi;
  }
}

export default function VirtualCursor() {
  const wrapRef = useRef<HTMLDivElement>(null);
  // 用 state 存 transform + transition 时长，React 统一管理
  const [pos, setPos] = useState<{ x: number; y: number; duration: number } | null>(null);
  const [clicking, setClicking] = useState(false);
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    const moveTo: VirtualCursorApi["moveTo"] = (target, options = {}) => {
      const { duration = 500, click = false, label: lbl } = options;
      let x = 0;
      let y = 0;
      if (target instanceof Element) {
        try {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
        } catch {
          // ignore
        }
        // 滚到可视区后再次取 rect
        const r2 = target.getBoundingClientRect();
        x = r2.left + r2.width / 2;
        y = r2.top + r2.height / 2;
      } else {
        x = target.x;
        y = target.y;
      }
      setPos({ x, y, duration });

      if (lbl) setLabel(lbl);
      else setLabel(null);
      if (click) {
        window.setTimeout(() => {
          setClicking(true);
          window.setTimeout(() => setClicking(false), 280);
        }, duration);
      }
    };

    const clickFn: VirtualCursorApi["click"] = (target, options = {}) => {
      moveTo(target, { ...options, click: true });
    };

    const api: VirtualCursorApi = {
      moveTo,
      click: clickFn,
      hide: () => {
        // 完整收尾：位置、标签、点击波纹全部清掉，避免教程结束还残留
        setPos(null);
        setLabel(null);
        setClicking(false);
      },
      show: () => setPos({ x: window.innerWidth / 2, y: window.innerHeight / 2, duration: 0 }),
    };
    window.virtualCursor = api;

    return () => {
      delete window.virtualCursor;
    };
  }, []);

  // 计算当前样式
  const style: React.CSSProperties = pos
    ? {
        position: "fixed",
        top: 0,
        left: 0,
        transform: `translate(${pos.x}px, ${pos.y}px)`,
        zIndex: 2147483647,
        pointerEvents: "none",
        transition: pos.duration > 0
          ? `transform ${pos.duration}ms cubic-bezier(.4, 0, .2, 1)`
          : "none",
        opacity: 1,
      }
    : {
        position: "fixed",
        top: 0,
        left: 0,
        transform: "translate(-9999px, -9999px)",
        zIndex: 2147483647,
        pointerEvents: "none",
        opacity: 0,
      };

  return (
    <div ref={wrapRef} aria-hidden style={style}>
      {/* 鼠标指针 SVG */}
      <svg
        width="32"
        height="32"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,.5))" }}
      >
        <path
          d="M5 3 L19 12 L12.5 13.5 L9 20 Z"
          fill="white"
          stroke="black"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>

      {/* 点击波纹 */}
      {clicking && (
        <div
          key={Date.now()}
          style={{
            position: "absolute",
            top: -8,
            left: -8,
            width: 48,
            height: 48,
            borderRadius: "50%",
            border: "3px solid rgba(59,130,246,.7)",
            background: "rgba(59,130,246,.15)",
            animation: "vc-ripple 0.5s ease-out forwards",
          }}
        />
      )}

      {/* 浮动标签 */}
      {label && pos && (
        <div
          style={{
            position: "absolute",
            top: 32,
            left: 20,
            background: "rgba(15, 23, 42, 0.95)",
            color: "white",
            padding: "4px 10px",
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 600,
            whiteSpace: "nowrap",
            boxShadow: "0 2px 8px rgba(0,0,0,.3)",
            animation: "vc-label-in 0.2s ease-out",
          }}
        >
          {label}
        </div>
      )}

      {/* 全局样式（keyframes） */}
      <style>{`
        @keyframes vc-ripple {
          0% { transform: scale(0.4); opacity: 1; }
          100% { transform: scale(2.2); opacity: 0; }
        }
        @keyframes vc-label-in {
          0% { opacity: 0; transform: translateY(-4px); }
          100% { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
