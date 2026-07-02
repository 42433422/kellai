/**
 * 新手教程（真操作版）
 *
 * 核心理念：教程不只是"介绍"，而是**自己动手做**。每一步进入后，教程
 * 会自动执行真实操作：拖卡片、点 AI 推荐、填话术、点分析意图、⌘K 搜客户…
 * 完成后 popover 文案变成"看！我刚才帮你 X 了"。
 *
 * 实现思路：
 * - 每一步的 onHighlightStarted 钩子触发一个"演示序列"
 * - 演示序列用 setTimeout 串行执行真实 DOM 操作
 * - 用一个 controller 防止重复触发 / 提前 stop
 *
 * 触发：
 * - 首次登录后自动弹
 * - 顶栏 "❓" 按钮手动重看
 * - 设置页"重新开始新手教程"
 */

import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { useOnboardingStore } from "../stores/onboarding";
import { useAdvancedPanelStore } from "../stores/advancedPanel";
import client from "../api/client";
import { toastStore } from "../stores/toast";
import { useTextToSpeech } from "../hooks/useTextToSpeech";
import { ONBOARDING_WELCOME_CACHE_KEY, ONBOARDING_WELCOME_DESCRIPTION, ONBOARDING_WELCOME_TITLE } from "../constants/onboardingTour";
import { buildOnboardingSpeechText, estimateSpeechHoldMs } from "../utils/onboardingSpeech";

type DriverInstance = ReturnType<typeof driver>;

type OnboardingSpeechWindow = Window & {
  __kellaiOnboardingWelcomePreplayedUntil?: number;
};

/** 教程动画速度倍率：>1 变慢，<1 变快。2.0 = 比默认慢一倍 */
const SPEED = 2.0;

function buildTourSpeechText(step?: DriveStep) {
  const popover = (step as { popover?: { title?: unknown; description?: unknown } } | undefined)?.popover;
  return buildOnboardingSpeechText(popover?.title, popover?.description);
}

/* ====================================================================
 * 演示工具
 * ==================================================================== */

/** 让虚拟光标"飞过去"再点击（如果 API 已就绪） */
function cursorClick(el: HTMLElement, label?: string, duration = 500 * SPEED) {
  const cursor = (window as unknown as { virtualCursor?: { click: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
  if (cursor) {
    // 视觉点击：飞过去 + 波纹
    cursor.click(el, { duration, label });
    // 视觉结束后，真正触发 DOM click 事件（关键：否则按钮 onClick 不会执行）
    window.setTimeout(() => {
      try {
        el.click();
      } catch {
        // ignore
      }
    }, duration);
  } else {
    el.click();
  }
}

/** 模拟键盘事件 */
function fireKey(key: string, code: string, meta = false) {
  const ev = new KeyboardEvent("keydown", {
    key,
    code,
    metaKey: meta,
    ctrlKey: !meta && /Win|Linux/.test(navigator.platform),
    bubbles: true,
    cancelable: true,
  });
  document.dispatchEvent(ev);
}

/** 创建一组可清理的定时器 */
function makeTimerGroup() {
  const ids: number[] = [];
  return {
    set(fn: () => void, ms: number) {
      const id = window.setTimeout(fn, ms);
      ids.push(id);
    },
    clear() {
      ids.forEach((id) => window.clearTimeout(id));
      ids.length = 0;
    },
  };
}

/* ====================================================================
 * 各步骤的自动演示
 *
 * 约定：每个 demo 接收 timers，由它自己 setTimeout 串行执行真实操作。
 *       demo 应在 ~2.5s 内完成全部动作。
 * ==================================================================== */

type DemoResult = { ok: boolean; fallbackMsg?: string; stop?: boolean; redirectPath?: string };

const TUTORIAL_CONTACT_STORAGE_KEY = "kellai:tutorial:first-contact";

function extractResponseData(payload: unknown): any {
  const response = payload as { data?: unknown } | undefined;
  const body = response?.data ?? payload;
  if (body && typeof body === "object" && "data" in body) {
    return (body as { data?: unknown }).data;
  }
  return body;
}

function setRememberedTutorialCustomer(customerId: unknown) {
  const id = Number(customerId);
  if (!Number.isFinite(id) || id <= 0) return "";
  const customerIdText = String(id);
  (window as unknown as { __tutorialFirstContact?: string }).__tutorialFirstContact = customerIdText;
  try {
    sessionStorage.setItem(TUTORIAL_CONTACT_STORAGE_KEY, customerIdText);
  } catch {
    // ignore
  }
  return customerIdText;
}

function readRememberedTutorialCustomer() {
  const fromWindow = (window as unknown as { __tutorialFirstContact?: string | null }).__tutorialFirstContact;
  if (fromWindow) return fromWindow;
  try {
    return sessionStorage.getItem(TUTORIAL_CONTACT_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function readVisibleTutorialContact() {
  const fromMessages = document
    .querySelector<HTMLElement>('[data-tour="messages-contact-list"] [data-contact-id]')
    ?.getAttribute("data-contact-id");
  if (fromMessages) return setRememberedTutorialCustomer(fromMessages);
  const fromFunnel = document.querySelector<HTMLElement>("[data-customer-id]")?.getAttribute("data-customer-id");
  if (fromFunnel) return setRememberedTutorialCustomer(fromFunnel);
  return "";
}

function rememberTutorialCustomer(customerId: unknown, result?: unknown) {
  const customerIdText = setRememberedTutorialCustomer(customerId);
  if (!customerIdText) return false;
  if (result !== undefined) {
    (window as unknown as { __tutorialFullFlow?: unknown }).__tutorialFullFlow = result;
  }
  window.dispatchEvent(new CustomEvent("kellai:onboarding:full-flow-ready", { detail: result }));
  return true;
}

async function seedTutorialCustomerFromScriptedSimulation() {
  const res = await client.post(
    "/api/kellai/demo/simulate-customer-behavior",
    { count: 8, scenario_set: "tutorial" },
    { skipErrorToast: true, skipLoading: true, timeout: 60000 }
  );
  const result = extractResponseData(res);
  const scenarios = Array.isArray(result?.scenario_results) ? result.scenario_results : [];
  const signedScenario =
    scenarios.find((item: any) => item?.passed && item?.final_stage === "signed" && Number(item?.customer_id) > 0) ||
    scenarios.find((item: any) => item?.passed && Number(item?.customer_id) > 0) ||
    scenarios.find((item: any) => Number(item?.customer_id) > 0);
  if (!signedScenario || !rememberTutorialCustomer(signedScenario.customer_id, result)) {
    return null;
  }
  return { result, scenario: signedScenario };
}

async function demoTutorialCustomerFullFlow(timers: ReturnType<typeof makeTimerGroup>): Promise<DemoResult> {
  const btn = document.querySelector<HTMLElement>('[data-tour="dashboard-simulate-customer"]');
  const anchor = btn || document.querySelector<HTMLElement>('[data-tour="dashboard-customer-workbench"]');

  if (anchor) {
    anchor.scrollIntoView({ behavior: "smooth", block: "center" });
    timers.set(() => {
      const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
      if (cursor) cursor.moveTo(anchor, { duration: 700 * SPEED, label: "创建教程客户" });
      anchor.style.transition = "outline .3s, outline-offset .3s, box-shadow .3s";
      anchor.style.outline = "2px solid #10b981";
      anchor.style.outlineOffset = "4px";
      anchor.style.boxShadow = "0 0 0 6px rgba(16,185,129,.15)";
    }, 100 * SPEED);
  }

  try {
    const scriptedSeed = await seedTutorialCustomerFromScriptedSimulation();
    if (scriptedSeed) {
      timers.set(() => {
        if (!anchor) return;
        anchor.style.outline = "2px solid #059669";
        anchor.style.boxShadow = "0 0 0 6px rgba(5,150,105,.18)";
      }, 900 * SPEED);
      timers.set(() => {
        if (!anchor) return;
        anchor.style.outline = "";
        anchor.style.outlineOffset = "";
        anchor.style.boxShadow = "";
      }, 2600 * SPEED);
      toastStore.show(`教学模式已创建 ${scriptedSeed.result?.summary?.total || 8} 个模拟客户场景`);
      return {
        ok: true,
        fallbackMsg:
          `教学模式已自动创建 <b>${scriptedSeed.result?.summary?.total || 8}</b> 个模拟客户场景，并选择客户 <b>#${scriptedSeed.scenario.customer_id}</b> 继续演示。<br/>` +
          `后续步骤会直接使用这批入库客户验证消息、漏斗、客户详情和 AI 助手。` +
          (!btn ? `<br/>提示：本次通过教程接口创建客户，不依赖进阶功能按钮。` : ""),
      };
    }
    if (anchor) {
      anchor.style.outline = "";
      anchor.style.outlineOffset = "";
      anchor.style.boxShadow = "";
    }
    return {
      ok: false,
      stop: true,
      redirectPath: "/",
      fallbackMsg: "无法创建教程客户。请确认后端服务已启动，再重新开始教学模式。",
    };
  } catch {
    if (anchor) {
      anchor.style.outline = "";
      anchor.style.outlineOffset = "";
      anchor.style.boxShadow = "";
    }
    return {
      ok: false,
      stop: true,
      redirectPath: "/",
      fallbackMsg: "无法连接客户行为模拟接口。请确认后端服务已启动。",
    };
  }
}

/** Step 1（设置·渠道管理）：演示「扫码授权」真实工作流
 *  真实链路：找到「企业微信」卡片 → 点「扫码授权」→ 弹窗出现 QR
 *  → 模拟手机扫 → 已扫待确认 → 授权成功 → 弹窗自动关闭
 *  教程只触发到"弹窗出现 QR"，剩余状态由组件自带 3.5s+2s+1.2s 自动机走完。
 *  用 data-tour 锚点，不依赖 CSS class 名。 */
function demoChannelBind(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const root = document.querySelector<HTMLElement>('[data-tour="settings-channels"]');
  if (!root) return { ok: false, fallbackMsg: "设置页渠道管理未加载" };
  root.scrollIntoView({ behavior: "smooth", block: "start" });
  // 找第一张渠道卡
  const firstCard = root.querySelector<HTMLElement>('[data-tour="settings-channel-card"]');
  if (!firstCard) return { ok: false, fallbackMsg: "没有找到渠道卡片" };
  // 优先用稳定锚点，找不到再回退到 aria-label 模糊匹配
  const firstConfigBtn =
    firstCard.querySelector<HTMLButtonElement>('[data-tour="settings-channel-config-btn"]') ||
    firstCard.querySelector<HTMLButtonElement>('button[aria-label^="配置"]') ||
    firstCard.querySelector<HTMLButtonElement>('button[aria-label^="扫码"]');
  if (!firstConfigBtn) return { ok: false, fallbackMsg: "没有找到「扫码授权/配置」按钮" };

  // 1) 光标飞到第一张卡
  timers.set(() => {
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(firstCard, { duration: 900 * SPEED, label: "📡 渠道卡" });
  }, 300 * SPEED);
  // 2) 高亮卡
  timers.set(() => {
    firstCard.style.transition = "outline .3s, outline-offset .3s";
    firstCard.style.outline = "2px solid #3b82f6";
    firstCard.style.outlineOffset = "4px";
  }, 1100 * SPEED);
  // 3) 光标飞到"接入向导"按钮并真实点击（视觉 + 真实 el.click）
  timers.set(() => cursorClick(firstConfigBtn, "📱 接入向导", 700 * SPEED), 1800 * SPEED);
  // 4) 新主流程会先打开接入向导，再点一次「扫码授权」进入 QR。
  timers.set(() => {
    const scanBtn = document.querySelector<HTMLButtonElement>('[data-tour="channel-onboarding-scan"]');
    if (scanBtn) {
      cursorClick(scanBtn, "📱 扫码授权", 600 * SPEED);
    }
  }, 3200 * SPEED);
  // 5) 高亮弹出的 QR 码
  // 时序：真实点击发生在 1800+700=2500*SPEED 时刻，向导渲染后再点扫码，
  // 因此在 4300*SPEED 高亮 QR 码，兼容旧的直接扫码弹窗和新的接入向导。
  timers.set(() => {
    const qr = document.querySelector<HTMLElement>('[data-tour="channel-qrcode"]');
    if (qr) {
      qr.style.transition = "outline .3s, outline-offset .3s";
      qr.style.outline = "3px solid #10b981";
      qr.style.outlineOffset = "6px";
    } else {
      console.warn("[onboarding] step1: QR 码未出现，跳过高亮");
    }
  }, 4300 * SPEED);
  // 6) 演示"等待扫码 → 已扫"的过渡：什么都不做，弹窗自带状态机会跑
  //    教程在 7000*SPEED 左右关掉高亮，让用户知道流程已结束
  timers.set(() => {
    const qr = document.querySelector<HTMLElement>('[data-tour="channel-qrcode"]');
    if (qr) {
      qr.style.outline = "";
      qr.style.outlineOffset = "";
    }
    firstCard.style.outline = "";
    firstCard.style.outlineOffset = "";
  }, 7000 * SPEED);
  return { ok: true };
}

/** Step 2（设置·AI 助手）：先点 AI tab 切换，再演示"配 LLM"的核心控件
 *  不依赖 URL ?tab=ai 切换（React Router 同路由 searchParams 变化可能不触发 re-render），
 *  而是直接点击左侧 AI tab 按钮，更可靠也更直观。 */
function demoAiSetup(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  // 0) 先点 AI 助手 tab 按钮（如果当前不在 AI tab）
  // 更可靠：找包含"AI"文字的 tab 按钮
  const allTabBtns = document.querySelectorAll<HTMLElement>('nav button');
  let aiBtn: HTMLElement | null = null;
  allTabBtns.forEach(btn => {
    if (btn.textContent?.includes('AI') || btn.textContent?.includes('助手')) {
      aiBtn = btn;
    }
  });

  if (aiBtn) {
    timers.set(() => cursorClick(aiBtn!, "🤖 切到 AI 助手", 600 * SPEED), 100 * SPEED);
  }

  // 等 tab 切换渲染（React setState → re-render → DOM 更新）
  const AI_WAIT = 1200 * SPEED;

  // 1) 高亮"模型配置"卡片
  timers.set(() => {
    const modelCard = document.querySelector<HTMLElement>('[data-tour="ai-model-card"]');
    if (!modelCard) return;
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(modelCard, { duration: 800 * SPEED, label: "🤖 模型" });
    modelCard.style.transition = "outline .3s, outline-offset .3s";
    modelCard.style.outline = "2px solid #3b82f6";
    modelCard.style.outlineOffset = "4px";
    setTimeout(() => {
      modelCard.style.outline = "";
      modelCard.style.outlineOffset = "";
    }, 1500 * SPEED);
  }, AI_WAIT + 300 * SPEED);

  // 2) 高亮"自动回复策略"卡片
  timers.set(() => {
    const autoReplyCard = document.querySelector<HTMLElement>('[data-tour="ai-auto-reply-card"]');
    if (!autoReplyCard) return;
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(autoReplyCard, { duration: 800 * SPEED, label: "⚙️ 自动回复" });
    autoReplyCard.style.transition = "outline .3s, outline-offset .3s";
    autoReplyCard.style.outline = "2px solid #10b981";
    autoReplyCard.style.outlineOffset = "4px";
    setTimeout(() => {
      autoReplyCard.style.outline = "";
      autoReplyCard.style.outlineOffset = "";
    }, 1500 * SPEED);
  }, AI_WAIT + 1700 * SPEED);

  // 3) 高亮保存按钮（不真的点，避免误改用户配置）
  timers.set(() => {
    const saveBtn = document.querySelector<HTMLElement>('[data-tour="ai-save-config"]');
    if (!saveBtn) return;
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(saveBtn, { duration: 700 * SPEED, label: "💾 保存" });
    saveBtn.style.transition = "outline .3s, outline-offset .3s";
    saveBtn.style.outline = "2px solid #f59e0b";
    saveBtn.style.outlineOffset = "4px";
    setTimeout(() => {
      saveBtn.style.outline = "";
      saveBtn.style.outlineOffset = "";
    }, 1200 * SPEED);
  }, AI_WAIT + 3100 * SPEED);

  return { ok: true };
}

/** Step 3（工作台）：dashboard 现在是 4 个 KpiTile 平铺，每个点一下说明用途
 *  用 data-module-id 定位（Dashboard.tsx 写在 KpiTile 上），4 个依次扫过 */
function demoDashboard(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const todo = document.querySelector<HTMLElement>('[data-module-id="dashboard-todo"]');
  const messages = document.querySelector<HTMLElement>('[data-module-id="dashboard-messages"]');
  const funnel = document.querySelector<HTMLElement>('[data-module-id="dashboard-funnel"]');
  const ai = document.querySelector<HTMLElement>('[data-module-id="dashboard-ai"]');
  if (!todo) return { ok: false, fallbackMsg: "工作台未加载" };

  // 滚到顶部，把 4 个 tile 拉到视口里
  todo.scrollIntoView({ behavior: "smooth", block: "center" });

  // 高亮一个方块的辅助：设 outline + 移光标 + 写小标
  const highlight = (el: HTMLElement | null, color: string, label: string) => {
    if (!el) return;
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(el, { duration: 700 * SPEED, label });
    el.style.transition = "outline .3s, outline-offset .3s, box-shadow .3s, transform .3s";
    el.style.outline = `2px solid ${color}`;
    el.style.outlineOffset = "4px";
    el.style.boxShadow = `0 0 0 6px ${color}22`;
  };
  const clear = (el: HTMLElement | null) => {
    if (!el) return;
    el.style.outline = "";
    el.style.outlineOffset = "";
    el.style.boxShadow = "";
  };

  // 1) 今日待办
  timers.set(() => highlight(todo, "#3b82f6", "📋 待办"), 300 * SPEED);
  // 2) 线索动态
  timers.set(() => {
    clear(todo);
    highlight(messages, "#06b6d4", "💬 线索");
  }, 1100 * SPEED);
  // 3) 漏斗概览
  timers.set(() => {
    clear(messages);
    highlight(funnel, "#6366f1", "🌪️ 漏斗");
  }, 1900 * SPEED);
  // 4) AI 建议
  timers.set(() => {
    clear(funnel);
    highlight(ai, "#f59e0b", "✨ AI");
  }, 2700 * SPEED);
  // 5) 收尾：全部清掉
  timers.set(() => {
    [todo, messages, funnel, ai].forEach(clear);
  }, 3500 * SPEED);
  return { ok: true };
}

/** Step 2（漏斗）：自动把第一张客户卡片从当前阶段移到下一阶段
 *  真实调用 API：POST /api/kellai/pipeline/stage  body: { customer_id, stage, note }
 *  （之前写成了 PUT /api/kellai/pipeline/customer/{id}/stage + { stage_id }，
 *   这是错的，对不上后端 handler，调试模式下也会 404。） */
function demoFunnelDrag(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  // 找一张客户卡片（data 属性带 customer_id）
  const card = document.querySelector(
    '[data-customer-id]'
  ) as HTMLElement | null;
  if (!card) {
    return {
      ok: false,
      fallbackMsg: "漏斗里暂时没有客户卡片。请先在设置里打开 <b>Mock 数据</b>，或手动添加一个客户后再走这一步。",
    };
  }
  const customerId = card.getAttribute("data-customer-id");
  if (!customerId) return { ok: false, fallbackMsg: "客户卡片缺少 ID 数据" };
  setRememberedTutorialCustomer(customerId);

  // 找到下一阶段列：找所有 stage 列，取 current+1
  const cols = document.querySelectorAll<HTMLElement>("[data-stage-id]");
  if (cols.length === 0) return { ok: false, fallbackMsg: "找不到阶段列" };
  const curCol = card.closest<HTMLElement>("[data-stage-id]");
  if (!curCol) return { ok: false, fallbackMsg: "客户卡片不在任何阶段列里" };
  const curId = curCol.getAttribute("data-stage-id");
  const idx = Array.from(cols).findIndex((c) => c.getAttribute("data-stage-id") === curId);
  const nextCol = cols[idx + 1] || cols[0];
  const nextId = nextCol.getAttribute("data-stage-id");
  if (!nextId || nextId === curId) return { ok: false, fallbackMsg: "找不到下一阶段" };

  // 在下一阶段里制造一个高亮"目标"提示
  const ghost = document.createElement("div");
  ghost.style.cssText = `
    position:absolute; inset:8px; border:2px dashed #3b82f6; border-radius:8px;
    background:rgba(59,130,246,.08); pointer-events:none; z-index:5;
    display:flex; align-items:center; justify-content:center;
    color:#3b82f6; font-size:13px; font-weight:600;
  `;
  ghost.textContent = "← 拖到这里";
  nextCol.style.position = "relative";
  nextCol.appendChild(ghost);

  // 阶段 A：客户卡片微微"抬起"，光标飞过去
  timers.set(() => {
    card.style.transition = "transform .25s, box-shadow .25s";
    card.style.transform = "scale(1.05) rotate(-2deg)";
    card.style.boxShadow = "0 10px 30px rgba(59,130,246,.35)";
    cursorClick(card, "👆 按住这张卡片", 900 * SPEED);
  }, 100 * SPEED);

  // 阶段 B：飞向下一阶段，光标跟随（慢一点，看清楚）
  timers.set(() => {
    const r1 = card.getBoundingClientRect();
    const r2 = nextCol.getBoundingClientRect();
    const dx = r2.left - r1.left + 16;
    const dy = r2.top - r1.top + 16;
    card.style.transition = "transform .9s cubic-bezier(.45,.05,.3,1)";
    card.style.transform = `translate(${dx}px, ${dy}px) scale(.95) rotate(2deg)`;
    // 光标飞向"目标列"
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(nextCol, { duration: 1000 * SPEED, label: "📥 拖到这里" });
  }, 900 * SPEED);

  // 阶段 C：调用真实 API（POST /api/kellai/pipeline/stage）
  timers.set(async () => {
    try {
      const customerIdNum = Number(customerId);
      const resp = await client.post(
        `/api/kellai/pipeline/stage`,
        { customer_id: Number.isFinite(customerIdNum) ? customerIdNum : customerId, stage: nextId, note: "[tutorial] 拖到下一阶段" }
      );
      // 触发自定义事件让 Funnel 页 React Query 失效并重拉
      window.dispatchEvent(new CustomEvent("kellai:onboarding:funnel-moved", { detail: { customerId, nextId, resp } }));
    } catch (e) {
      console.warn("[onboarding] funnel demo: API failed", e);
    }
  }, 1900 * SPEED);

  // 阶段 D：落位 + 提示
  timers.set(() => {
    ghost.remove();
    card.style.transition = "all .3s";
    card.style.transform = "scale(1) rotate(0)";
    card.style.boxShadow = "";
    card.style.outline = "2px solid #10b981";
    card.style.outlineOffset = "2px";
    setTimeout(() => {
      card.style.outline = "";
      card.style.outlineOffset = "";
    }, 1200 * SPEED);
  }, 2400 * SPEED);
  return { ok: true };
}

/** Step 5（消息中心）：自动点第一个联系人 → AI 推荐 → 等 AI 返回 → 填入第一条话术
 *  用 data-tour / data-contact-id / data-suggestion-fill 锚点
 *  关键修复：
 *  1. cursorClick 的真实 click 在 duration 后才触发，所以"点联系人"后必须等足够久
 *     再点 AI 推荐按钮（之前 1200*SPEED 不够，联系人选中状态还没更新）
 *  2. AI 推荐按钮在未选中联系人时 disabled，必须确认联系人已选中
 *  3. AI 推荐会触发后端请求 + loading，必须等"填入"按钮真的出现再点
 *  4. 联系人列表是异步加载的，必须轮询等 data-contact-id 出现再操作
 *     （之前直接 querySelector，如果列表还在 loading 骨架屏阶段就找不到） */
function demoMessages(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const list = document.querySelector<HTMLElement>('[data-tour="messages-contact-list"]');
  if (!list) return { ok: false, fallbackMsg: "消息页面未加载，请刷新" };
  const preferredContactId = readRememberedTutorialCustomer();
  const contactSelector = preferredContactId
    ? `[data-tour="messages-contact-list"] [data-contact-id="${preferredContactId}"]`
    : '[data-tour="messages-contact-list"] [data-contact-id]';

  // 0) 轮询等待联系人列表加载完成（骨架屏 → 真实联系人）
  //    最多等 5*SPEED 秒；找到后设置 __tutorialFirstContact
  let contactPollElapsed = 0;
  const contactPollMax = 5000 * SPEED;
  timers.set(function pollContact() {
    const firstContactEl = document.querySelector<HTMLElement>(contactSelector) ||
      document.querySelector<HTMLElement>('[data-tour="messages-contact-list"] [data-contact-id]');
    if (firstContactEl) {
      const cid = firstContactEl.getAttribute("data-contact-id");
      setRememberedTutorialCustomer(cid);
      return;
    }
    contactPollElapsed += 200 * SPEED;
    if (contactPollElapsed < contactPollMax) {
      timers.set(pollContact, 200 * SPEED);
    } else {
      // 超时：保留前面步骤记住的客户；没有则详情页走 fallback。
    }
  }, 100 * SPEED);

  // 1) 点开第一个联系人（轮询等待联系人出现，而非直接 querySelector）
  //    联系人列表是异步加载的，SCHEDULE 的 waitFor 已确保 [data-contact-id] 出现，
  //    但这里加一层保险：如果还没出现就等一下再试
  timers.set(() => {
    const tryClickContact = () => {
      const firstContact = document.querySelector<HTMLElement>(contactSelector) ||
        document.querySelector<HTMLElement>('[data-tour="messages-contact-list"] [data-contact-id]');
      if (firstContact) {
        firstContact.style.transition = "background .3s";
        firstContact.style.background = "#dbeafe";
        cursorClick(firstContact, "💬 选这个客户", 800 * SPEED);
        setTimeout(() => (firstContact.style.background = ""), 600 * SPEED);
      } else {
        // 还没加载，100ms 后重试
        timers.set(tryClickContact, 100 * SPEED);
      }
    };
    tryClickContact();
  }, 200 * SPEED);

  // 2) 点 AI 推荐按钮 — 必须等联系人选中完成（cursorClick duration=800*SPEED + React 渲染 ~1 帧）
  //    之前 1200*SPEED 不够，改为 1600*SPEED 确保联系人已选中
  //    同时用轮询确认按钮不再是 disabled
  timers.set(() => {
    const tryClickAiBtn = () => {
      const btn = document.querySelector<HTMLButtonElement>('[data-tour="messages-ai-suggest"]');
      if (btn && !btn.disabled) {
        cursorClick(btn, "✨ AI 推荐", 800 * SPEED);
      } else {
        // 按钮还没就绪，100ms 后重试
        timers.set(tryClickAiBtn, 100 * SPEED);
      }
    };
    tryClickAiBtn();
  }, 1600 * SPEED);

  // 3) 等 AI 返回（轮询 data-suggestion-fill 锚点出现，最长 6*SPEED 秒）
  let aiWaited = 0;
  const aiStart = 2800 * SPEED; // 留足够时间给 AI 推荐请求
  const aiMax = 6000 * SPEED;
  timers.set(function pollAi() {
    const fillBtn = document.querySelector<HTMLElement>('[data-suggestion-fill="0"]') ||
      document.querySelector<HTMLElement>('[data-tour="messages-suggestion-fill"]');
    if (fillBtn) {
      // 找到了，再高亮一下等用户看清，再点
      fillBtn.style.transition = "outline .3s, outline-offset .3s";
      fillBtn.style.outline = "2px solid #3b82f6";
      fillBtn.style.outlineOffset = "3px";
      setTimeout(() => {
        fillBtn.style.outline = "";
        fillBtn.style.outlineOffset = "";
        cursorClick(fillBtn, "📋 填入", 600 * SPEED);
      }, 500 * SPEED);
      return;
    }
    aiWaited += 120 * SPEED;
    if (aiWaited > aiMax - aiStart) {
      // 兜底：超时后用 aria-label 模糊匹配
      const fb = document.querySelector<HTMLElement>('[aria-label*="使用推荐话术"]');
      if (fb) cursorClick(fb, "📋 填入", 600 * SPEED);
      return;
    }
    timers.set(pollAi, 120 * SPEED);
  }, aiStart);
  return { ok: true };
}

/** Step 6（客户详情）：先展示 AI 画像，再切到销售 Tab 展示 LTV 预测
 *  修复：之前只滚动高亮 AI 画像，交互太弱。现在增加切换 Tab 和展示销售功能的演示。 */
function demoCustomerDetail(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const detailRoot = document.querySelector<HTMLElement>('[data-tour="customer-detail"]');
  if (!detailRoot) return { ok: false, fallbackMsg: "客户详情页未加载" };

  // 1) 高亮 AI 画像区域
  timers.set(() => {
    const card = document.querySelector<HTMLElement>('[data-tour="customer-ai-profile"]');
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
      if (cursor) cursor.moveTo(card, { duration: 700 * SPEED, label: "🧠 AI 画像" });
      card.style.transition = "outline .3s, outline-offset .3s";
      card.style.outline = "2px solid #3b82f6";
      card.style.outlineOffset = "4px";
    }
  }, 200 * SPEED);

  // 2) 清除 AI 画像高亮
  timers.set(() => {
    const card = document.querySelector<HTMLElement>('[data-tour="customer-ai-profile"]');
    if (card) {
      card.style.outline = "";
      card.style.outlineOffset = "";
    }
  }, 1400 * SPEED);

  // 3) 点击"销售"Tab（用 aria-label 定位）
  timers.set(() => {
    const tabBtns = detailRoot.querySelectorAll<HTMLButtonElement>("button");
    let salesTab: HTMLButtonElement | null = null;
    tabBtns.forEach((btn) => {
      if (btn.textContent?.trim() === "销售") {
        salesTab = btn;
      }
    });
    if (salesTab) {
      cursorClick(salesTab, "📊 销售 Tab", 600 * SPEED);
    }
  }, 1600 * SPEED);

  // 4) 高亮 LTV 预测区域（等 Tab 切换渲染完成）
  timers.set(() => {
    // 销售 Tab 渲染后，找 LTV 预测卡片（包含"预测"或"LTV"文字的区域）
    const ltvCard = detailRoot.querySelector<HTMLElement>("h3")?.closest<HTMLElement>(".rounded-xl");
    if (ltvCard) {
      ltvCard.scrollIntoView({ behavior: "smooth", block: "center" });
      const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
      if (cursor) cursor.moveTo(ltvCard, { duration: 700 * SPEED, label: "💰 LTV 预测" });
      ltvCard.style.transition = "outline .3s, outline-offset .3s";
      ltvCard.style.outline = "2px solid #10b981";
      ltvCard.style.outlineOffset = "4px";
      setTimeout(() => {
        ltvCard.style.outline = "";
        ltvCard.style.outlineOffset = "";
      }, 1200 * SPEED);
    }
  }, 2600 * SPEED);

  return { ok: true };
}

/** Step 7（AI 助手）：选第一个客户 + 输入示例文本 + 点分析意图
 *  修复：
 *  1. cursorClick 点击搜索框后，真实 click 在 duration 后触发，下拉可能还没展开
 *     改为轮询等待 data-customer-option 出现再点击
 *  2. 模拟打字后需要等打字完成再点分析意图
 *  锚点全用 data-tour / data-customer-option */
function demoAiAssistant(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const analyzeArea = document.querySelector<HTMLElement>('[data-tour="ai-analyze"]');
  if (!analyzeArea) return { ok: false, fallbackMsg: "AI 助手页未加载" };

  // 1) 点搜索框展开下拉
  timers.set(() => {
    const searchInput = document.querySelector<HTMLInputElement>(
      'input[aria-label="搜索选择客户"], input[placeholder*="搜索选择"]'
    );
    if (searchInput) {
      cursorClick(searchInput, "🔍 选客户", 800 * SPEED);
    }
  }, 200 * SPEED);

  // 2) 轮询等待下拉展开后，点第一个客户（之前写死 1100*SPEED，下拉可能还没出现）
  let customerWaited = 0;
  const customerMaxWait = 3000 * SPEED;
  timers.set(function pollCustomer() {
    const opt = document.querySelector<HTMLElement>("[data-customer-option]");
    if (opt) {
      opt.style.transition = "background .3s";
      opt.style.background = "#dbeafe";
      cursorClick(opt, "👤 选这个", 700 * SPEED);
      setTimeout(() => (opt.style.background = ""), 600 * SPEED);
      return;
    }
    customerWaited += 150 * SPEED;
    if (customerWaited < customerMaxWait) {
      timers.set(pollCustomer, 150 * SPEED);
    }
  }, 1100 * SPEED);

  // 3) 在输入框填入示例客户话（用 data-tour="ai-input" 锚点）
  //    延迟加大，确保客户已选中
  timers.set(() => {
    const textarea =
      document.querySelector<HTMLTextAreaElement>('[data-tour="ai-input"]') ||
      document.querySelector<HTMLTextAreaElement>(
        'textarea[placeholder*="客户"], textarea[placeholder*="输入"]'
      );
    if (textarea) {
      const phrase = "我们老板在考虑要不要换一家更便宜的供应商";
      // 光标飞向 textarea
      const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
      if (cursor) cursor.moveTo(textarea, { duration: 800 * SPEED, label: "⌨️ 模拟打字" });
      let i = 0;
      const typer = window.setInterval(() => {
        textarea.value = phrase.slice(0, ++i);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        if (i >= phrase.length) window.clearInterval(typer);
      }, 35 * SPEED);
    }
  }, 2400 * SPEED);

  // 4) 点分析意图（用 data-tour 锚点，不再 selector 二义）
  //    延迟加大，确保打字完成
  timers.set(() => {
    const btn = document.querySelector<HTMLElement>('[data-tour="ai-analyze"]');
    if (btn) {
      btn.style.transition = "transform .15s, box-shadow .15s";
      btn.style.transform = "scale(1.08)";
      btn.style.boxShadow = "0 0 0 4px rgba(99,102,241,.4)";
      cursorClick(btn, "🚀 分析", 700 * SPEED);
      setTimeout(() => {
        btn.style.transform = "";
        btn.style.boxShadow = "";
      }, 600 * SPEED);
    }
  }, 3800 * SPEED);
  return { ok: true };
}

/** Step 6（全局搜索）：按 ⌘K → 输入"客" */
function demoGlobalSearch(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const search = document.querySelector<HTMLElement>('[data-tour="topbar-search"]');
  if (!search) return { ok: false, fallbackMsg: "顶栏搜索入口未找到" };
  // 1) 按 ⌘K
  timers.set(() => {
    // 把光标先放到顶栏搜索框位置
    const cursor = (window as unknown as { virtualCursor?: { moveTo: (el: HTMLElement, opts?: { duration?: number; label?: string }) => void } }).virtualCursor;
    if (cursor) cursor.moveTo(search, { duration: 800 * SPEED, label: "🔍 ⌘K" });
    setTimeout(() => fireKey("k", "KeyK", true), 700 * SPEED);
  }, 200 * SPEED);

  // 2) 输入文字（用 "客户" 而不是 "客"：让搜索结果真正出现，看完整 ⌘K 流程）
  timers.set(() => {
    const input = document.querySelector<HTMLInputElement>(
      'input[placeholder*="搜索"], [role="dialog"] input[type="text"]'
    );
    if (input) {
      input.focus();
      const phrase = "客户";
      let i = 0;
      const typer = window.setInterval(() => {
        input.value = phrase.slice(0, ++i);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        if (i >= phrase.length) window.clearInterval(typer);
      }, 80 * SPEED);
    }
  }, 900 * SPEED);
  return { ok: true };
}

/* ====================================================================
 * 主组件
 * ==================================================================== */
export default function OnboardingTutorial() {
  const driverRef = useRef<DriverInstance | null>(null);
  const timersRef = useRef<ReturnType<typeof makeTimerGroup> | null>(null);
  // 教程控制：暂停 / 跳到下一步 / 收尾 CTA
  const pausedRef = useRef(false);
  const skipRequestedRef = useRef(false);
  const currentStepRef = useRef(0);
  const speechHoldUntilRef = useRef(0);
  const active = useOnboardingStore((s) => s.active);
  const setActive = useOnboardingStore((s) => s.setActive);
  const markCompleted = useOnboardingStore((s) => s.markCompleted);
  const markSkipped = useOnboardingStore((s) => s.markSkipped);
  const setAdvancedPanelOpen = useAdvancedPanelStore((s) => s.setOpen);
  const navigate = useNavigate();
  // 关键修复：useNavigate() 在 Declarative 模式下每次渲染返回新引用，
  // 放进 useEffect 依赖会触发 effect 反复 cleanup / 重跑，把 runStep 链斩断。
  // 用 ref 持有最新值，effect 只依赖真正"会变化"的项。
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const speech = useTextToSpeech();
  const speechRef = useRef(speech);
  speechRef.current = speech;

  /** 教程步骤定义（独立于 driver 实例，避免从 driver 内部读取 steps） */
  const TOUR_STEPS: DriveStep[] = [
    /* ===== Step 0 - 欢迎 ===== */
    {
      popover: {
        title: ONBOARDING_WELCOME_TITLE,
        description: ONBOARDING_WELCOME_DESCRIPTION,
        align: "center",
      },
    },

    /* ===== Step 1 - 模拟客户全流程闭环 ===== */
    {
      element: '[data-tour="dashboard-customer-workbench"]',
      popover: {
        title: "模拟客户全流程闭环",
        description:
          "我会自动创建夜间咨询、复购、比价、签约、付款后交付等客户行为，并把消息、客户档案和漏斗阶段全部写入系统。\n\n通过后，后面的消息中心和客户详情会继续使用这些测试客户。",
        side: "bottom",
        align: "end",
      },
    },

    /* ===== Step 2 - 设置·渠道管理 ===== */
    {
      element: '[data-tour="settings-channels"]',
      popover: {
        title: "第一步：接入渠道",
        description:
          "渠道是所有功能的入口，未接入前漏斗和消息中心无数据。\n\n刚才的操作：\n1. 找到「企业微信」卡片\n2. 点击「<b>扫码授权</b>」\n3. 手机扫码 → 自动确认 → 完成\n\n扫码授权比填写凭据更便捷。",
        side: "left",
        align: "start",
      },
    },

    /* ===== Step 3 - 设置·AI 助手 ===== */
    {
      element: '[data-tour="settings-channels"]',
      popover: {
        title: "第二步：配置 AI 助手",
        description:
          "AI 话术、意图分析、客户画像均依赖此配置。\n\n刚才切换到 <b>AI 助手</b> 页面，包含两个核心区域：\n• <b>模型配置</b>：选择厂商并填写 API Key\n• <b>自动回复策略</b>：设置 AI 自动接管的阶段\n\n配置流程：开通账号 → 获取 Key → 填入 → 测试连通 → 启用。",
        side: "left",
        align: "start",
      },
    },

    /* ===== Step 4 - 工作台 ===== */
    {
      element: '[data-tour="dashboard-todo"]',
      popover: {
        title: "工作台",
        description:
          "渠道和 AI 配置完成后，工作台开始展示数据。\n\n四个功能入口：\n• <b>今日待办</b>：AI 排序的待跟进客户\n• <b>线索动态</b>：最新消息流\n• <b>漏斗概览</b>：客户阶段分布\n• <b>AI 建议</b>：智能提醒\n\n点击任一模块可进入对应页面。",
        side: "bottom",
        align: "center",
      },
    },

    /* ===== Step 5 - 漏斗 ===== */
    {
      element: '[data-tour="funnel-board"]',
      popover: {
        title: "漏斗看板",
        description:
          "刚才将一张客户卡片从「<b>已建联</b>拖拽至「<b>需求采集</b>」。\n\n阶段变更已自动保存至客户档案。\n\n拖拽即可更新客户阶段，无需手动填写。",
        side: "bottom",
        align: "center",
      },
    },

    /* ===== Step 6 - 消息中心 ===== */
    {
      element: '[data-tour="messages-contact-list"]',
      popover: {
        title: "消息中心",
        description:
          "刚才的操作：\n1. 选择一个客户\n2. 点击「<b>AI 推荐</b>」\n3. 将推荐话术填入输入框\n\nAI 话术可减少消息撰写时间。",
        side: "left",
        align: "start",
      },
    },

    /* ===== Step 7 - 客户详情 ===== */
    {
      element: '[data-tour="customer-detail"]',
      popover: {
        title: "客户详情",
        description:
          "刚才的操作：\n1. 滚动至「<b>AI 画像</b>」区域查看客户全貌\n2. 切换到「<b>销售</b>」Tab 查看 LTV 预测\n\nAI 画像聚合客户的需求、预算、决策角色及全部跟进记录。\n销售 Tab 展示 LTV 预测、智能报价和自动销售流程。\n\n沟通前可快速了解客户全貌。",
        side: "right",
        align: "start",
      },
    },

    /* ===== Step 8 - AI 助手 ===== */
    {
      element: '[data-tour="ai-analyze"]',
      popover: {
        title: "AI 助手",
        description:
          "刚才的操作：\n1. 选择一个客户\n2. 输入：「<i>老板在考虑换更便宜的供应商</i>」\n3. 点击「<b>分析意图</b>」\n\nAI 返回分析结论（如客户正在比价）及对应推荐话术。\n\n将经验判断转化为即时结论。",
        side: "left",
        align: "start",
      },
    },

    /* ===== Step 9 - 自动销售流程 (v3) ===== */
    {
      element: '[data-tour="sales-flow-wizard"]',
      popover: {
        title: "自动销售流程 (v3)",
        description:
          "AI 从对话者升级为成交者。\n\n四步自动化：\n• <b>需求确认</b> → <b>方案推荐</b>\n• <b>促单</b> → <b>签约</b>\n\n右侧可查看 LTV 预测、智能报价，并一键生成合同。",
        side: "bottom",
        align: "center",
      },
    },

    /* ===== Step 10 - 开放平台 (v8) ===== */
    {
      element: '[data-tour="open-platform-home"]',
      popover: {
        title: "开放平台 (v8)",
        description:
          "客来来生态入口：\n\n• <b>插件市场</b>：安装第三方扩展\n• <b>开发者门户</b>：API 密钥与 Webhook\n• <b>应用构建器</b>：低代码自定义应用\n\n侧栏还有内容矩阵、精准猎手、流程闭环、智能财务等模块。",
        side: "bottom",
        align: "center",
      },
    },

    /* ===== Step 11 - 全局搜索 ===== */
    {
      element: '[data-tour="topbar-search"]',
      popover: {
        title: "全局搜索",
        description:
          "刚才按下 <kbd>⌘K</kbd>，输入「<b>销售</b>」或「<b>开放</b>」。\n\n任意页面可用，支持搜索全部 v3–v8 新页面。\n\n快捷键直达，无需记忆菜单位置。",
        side: "bottom",
        align: "end",
      },
    },

    /* ===== Step 12 - 收尾 ===== */
    {
      popover: {
        title: "引导完成",
        description:
          "核心使用流程：\n\n<b>①</b> 接入渠道 → <b>②</b> 配置 AI → <b>③</b> 工作台/漏斗/消息\n<b>④</b> 自动销售 (v3) → <b>⑤</b> 开放平台 (v8) → <b>⑥</b> ⌘K 搜索\n\n侧栏分组导航可探索：内容矩阵、精准猎手、流程闭环、智能财务。\n\n点击右上角 <b>?</b> 可重新查看引导。",
        align: "center",
      },
    },
  ];

  /* ---------- 响应 store.active 启动 / 停止 ----------
   * 链式调度：每一步顺序：navigate → poll for element → run demo → drive → 等 duration → 进下一步
   * 完全不依赖 driver.js 的 onNextClick（按钮已隐藏） */
  useEffect(() => {
    if (active) {
      setAdvancedPanelOpen(true);
      // 1) 清理旧实例（如有）
      if (driverRef.current) {
        try {
          driverRef.current.destroy();
        } catch {
          // ignore
        }
        driverRef.current = null;
      }
      if (timersRef.current) timersRef.current.clear();

      // 启动：body 加 tutorial-active class 屏蔽全站指针（仅 popover / overlay 可点）
      try { document.body.classList.add("tutorial-active"); } catch { /* ignore */ }

      // 2) 链式调度表（v2 压缩到 ~30 秒，SPEED=2 时约 60 秒）
      type StepSchedule = {
        path: string; // 导航目标（先 navigate 再等元素）
        waitFor: string; // 等这个 selector 出现再跑 demo
        waitTimeout?: number; // 个别真实页面接口多，需要更长等待
        demo: (timers: ReturnType<typeof makeTimerGroup>) => DemoResult | Promise<DemoResult>;
        duration: number; // 演示完后等多久进下一步
      };
      const SCHEDULE: StepSchedule[] = [
        // Step 0: 欢迎 — 给足时间读（之前 1500ms 太短）
        {
          path: "/",
          waitFor: "body",
          demo: () => ({ ok: true }),
          duration: 4500 * SPEED,
        },
        // Step 1: 模拟客户行为闭环（先生成真实入库数据，保证教程不被 LLM Key 阻塞）
        {
          path: "/",
          waitFor: '[data-tour="dashboard-customer-workbench"]',
          demo: (t) => demoTutorialCustomerFullFlow(t),
          duration: 3500 * SPEED,
        },
        // Step 2: 设置 → 渠道管理（必须先配，漏斗/消息才有数据来源）
        // 扫码流程：点击 + 等待 3.5s + 已扫 2s + 成功 1.2s ≈ 9s
        {
          path: "/settings?tab=channels",
          waitFor: '[data-tour="settings-channel-card"]',
          demo: (t) => demoChannelBind(t),
          duration: 9000 * SPEED,
        },
        // Step 3: 设置 → AI 助手（配 LLM，后面 AI 功能才工作）
        // 不导航到 /settings?tab=ai（React Router 同路由 searchParams 变化可能不触发 re-render），
        // 而是留在 /settings，demo 函数会直接点击 AI tab 按钮
        {
          path: "/settings",
          waitFor: '[data-tour="settings-channels"]',
          demo: (t) => demoAiSetup(t),
          duration: 5500 * SPEED,
        },
        // Step 4: 工作台（4 大模块总览）
        {
          path: "/",
          waitFor: '[data-tour="dashboard-todo"]',
          demo: (t) => demoDashboard(t),
          duration: 4500 * SPEED,
        },
        // Step 5: 漏斗（拖卡片改阶段）
        // 修复：waitFor 改为等客户卡片出现，而非只等看板容器（卡片是异步加载的）
        {
          path: "/funnel",
          waitFor: '[data-customer-id]',
          demo: (t) => demoFunnelDrag(t),
          duration: 3500 * SPEED,
        },
        // Step 6: 消息（AI 话术）— AI 填入可能耗时较长，给够 9s 看完整流程
        // 修复：waitFor 改为等联系人出现，而非只等列表容器（联系人是异步加载的）
        {
          path: "/messages",
          waitFor: '[data-tour="messages-contact-list"] [data-contact-id]',
          demo: (t) => demoMessages(t),
          duration: 9000 * SPEED,
        },
        // Step 7: 客户详情（360° 画像 + 销售 Tab + LTV 预测）
        // 路径用 Step 5 抓到的真实 contact id，不写死 1（之前写死 /customers/1
        //  经常撞到不存在的客户，详情页 fallback 走"客户不存在"空态）
        // 修复：fallback 改为 /customers/1001（mock 数据第一个客户），而非 /customers（无 id 时
        //  详情页不会渲染 data-tour="customer-detail"，导致 waitFor 超时）
        {
          path: "__USE_FIRST_CONTACT__",
          waitFor: '[data-tour="customer-detail"]',
          waitTimeout: 25000,
          demo: (t) => demoCustomerDetail(t),
          duration: 4500 * SPEED,
        },
        // Step 8: AI 助手（分析意图）— 轮询等客户选项 + 打字 + 分析，给够 8s
        {
          path: "/ai",
          waitFor: '[data-tour="ai-analyze"]',
          demo: (t) => demoAiAssistant(t),
          duration: 8000 * SPEED,
        },
        // Step 9: 自动销售流程 (v3)
        {
          path: "/sales/flow",
          waitFor: '[data-tour="sales-flow-wizard"]',
          demo: () => ({ ok: true }),
          duration: 4000 * SPEED,
        },
        // Step 10: 开放平台 (v8)
        {
          path: "/open",
          waitFor: '[data-tour="open-platform-home"]',
          demo: () => ({ ok: true }),
          duration: 4000 * SPEED,
        },
        // Step 11: 全局搜索（⌘K）
        {
          path: "/",
          waitFor: '[data-tour="topbar-search"]',
          demo: (t) => demoGlobalSearch(t),
          duration: 2500 * SPEED,
        },
        // Step 12: 收尾（带 CTA）
        {
          path: "/",
          waitFor: "body",
          demo: () => ({ ok: true }),
          duration: 999999,
        },
      ];

      let cancelled = false;
      const sleep = (ms: number) =>
        new Promise<void>((res) => window.setTimeout(res, ms));

      // 暂停时阻塞等待
      const waitWhilePaused = async () => {
        while (pausedRef.current && !cancelled) {
          await sleep(120);
        }
      };

      // 4) 链式执行器：跑第 idx 步
      const runStep = async (idx: number) => {
        if (cancelled) return;
        currentStepRef.current = idx;
        if (idx >= SCHEDULE.length) return;

        const step = SCHEDULE[idx];
        console.log(
          `[onboarding] step ${idx}: navigate to ${step.path}, wait for ${step.waitFor}`
        );

        // a) resolve 实际路径
        //    "__USE_FIRST_CONTACT__" 是 Step 6 的占位，会用 Step 5 在 window 上挂的
        //    __tutorialFirstContact 替换成真实客户 id。
        //    修复：fallback 改为 /customers/1001（mock 数据第一个客户），
        //    而非 /customers（无 id 时详情页不渲染 data-tour="customer-detail"）
        let realPath = step.path;
        if (step.path === "__USE_FIRST_CONTACT__") {
          const cid = readRememberedTutorialCustomer() || readVisibleTutorialContact();
          realPath = cid ? `/customers/${cid}` : "/customers/1001";
        }

        // b) navigate
        try {
          navigateRef.current(realPath);
        } catch {
          // ignore
        }
        // 等一帧让 React Router 处理 URL 变化 + 触发 re-render
        // （从 /settings?tab=channels → /settings?tab=ai 时，React 需要 1-2 帧
        //  处理 useSearchParams 更新 + useEffect 切 tab + 渲染新 tab 内容）
        await sleep(300);

        // c) poll for element（最多 10s，Settings tab 切换需要 React 渲染新内容）
        const start = Date.now();
        const timeout = step.waitTimeout ?? 10000;
        let elementFound = false;
        while (!cancelled && Date.now() - start < timeout) {
          if (step.waitFor === "body" || document.querySelector(step.waitFor)) {
            elementFound = true;
            break;
          }
          await sleep(150);
        }
        if (cancelled) return;

        // 如果元素没找到，记录警告但继续（driver.js 会显示无 element 的 popover）
        if (!elementFound && step.waitFor !== "body") {
          console.warn(`[onboarding] step ${idx}: element "${step.waitFor}" not found after ${timeout}ms`);
        }

        // d) ★ 每步销毁旧 driver + 重建单步 driver + drive()
        const stepDef = TOUR_STEPS[idx];
        const speechText = buildTourSpeechText(stepDef);
        let speechDone = !speechText;
        speechHoldUntilRef.current = 0;
        const holdForCurrentSpeech = (durationSeconds?: number | null) => {
          if (!speechText) return;
          speechHoldUntilRef.current = Math.max(
            speechHoldUntilRef.current,
            Date.now() + estimateSpeechHoldMs(speechText, durationSeconds)
          );
        };
        const welcomePreplayedUntil =
          idx === 0
            ? Number((window as OnboardingSpeechWindow).__kellaiOnboardingWelcomePreplayedUntil || 0)
            : 0;
        const welcomeAlreadyPlaying = Boolean(speechText && idx === 0 && welcomePreplayedUntil > Date.now());
        if (welcomeAlreadyPlaying) {
          speechDone = true;
          speechHoldUntilRef.current = Math.max(speechHoldUntilRef.current, welcomePreplayedUntil);
        }
        const playSpeechForStep = async (replayBtn?: HTMLButtonElement) => {
          if (!speechText) return false;
          let playbackStarted = false;
          if (replayBtn) {
            replayBtn.textContent = "生成中...";
            replayBtn.title = "正在生成当前步骤语音";
          }
          const ok = await speechRef.current.speak(speechText, {
            preferLocal: true,
            waitForEnd: true,
            cacheKey: idx === 0 ? ONBOARDING_WELCOME_CACHE_KEY : undefined,
            onPlaybackStart: (info) => {
              playbackStarted = true;
              holdForCurrentSpeech(info.durationSeconds);
              if (replayBtn) {
                replayBtn.textContent = "播放中";
                replayBtn.title = "语音正在播放，画面会等本段播完";
              }
            },
            onPlaybackEnd: () => {
              if (replayBtn) {
                replayBtn.textContent = "重播语音";
                replayBtn.title = "";
              }
            },
          });
          if (!ok || !playbackStarted) {
            holdForCurrentSpeech(null);
          }
          if (replayBtn && (!ok || !playbackStarted)) {
            const errorText = speechRef.current.lastError || "浏览器未允许自动播放，请点击播放语音";
            replayBtn.textContent = "点击播放语音";
            replayBtn.title = errorText;
          }
          return ok;
        };

        // 销毁旧 driver
        if (driverRef.current) {
          try { driverRef.current.destroy(); } catch { /* ignore */ }
          driverRef.current = null;
        }

        // 构建单步 driver
        const stepDriver = driver({
          animate: true,
          overlayOpacity: 0.55,
          stagePadding: 6,
          stageRadius: 10,
          allowClose: true,
          overlayClickBehavior: () => {},
          showProgress: true,
          progressText: `第 ${idx + 1} 步 / 共 ${SCHEDULE.length} 步`,
          nextBtnText: "下一步 →",
          prevBtnText: "← 上一步",
          doneBtnText: "完成",
          overlayColor: "rgba(15, 23, 42, 0.55)",
          popoverClass: "kellai-tour-popover",
          onDestroyed: () => {
            if (timersRef.current) timersRef.current.clear();
            speechRef.current.stop();
          },
          onCloseClick: () => {
            if (timersRef.current) timersRef.current.clear();
            speechRef.current.stop();
            try { window.virtualCursor?.hide(); } catch { /* ignore */ }
            try { document.body.classList.remove("tutorial-active"); } catch { /* ignore */ }
            try { driverRef.current?.destroy(); } catch { /* ignore */ }
            markSkipped();
            cancelled = true;
          },
          onPopoverRender: (popover) => {
            const popoverEl = popover.wrapper as HTMLElement | undefined;
            if (!popoverEl) return;
            window.setTimeout(() => {
              const totalSteps = SCHEDULE.length;
              const isLast = idx === totalSteps - 1;
              const old = popoverEl.querySelector(".kellai-tour-ctl");
              if (old) old.remove();
              const oldCta = popoverEl.querySelector(".kellai-tour-cta");
              if (oldCta) oldCta.remove();

              if (!isLast) {
                const ctl = document.createElement("div");
                ctl.className = "kellai-tour-ctl";
                ctl.style.cssText = `
                  display:flex; justify-content:space-between; align-items:center;
                  margin-top:12px; padding-top:10px; border-top:1px dashed #e2e8f0;
                `;
                const leftCtl = document.createElement("div");
                leftCtl.style.cssText = `
                  display:flex; align-items:center; gap:6px;
                `;
                const pauseBtn = document.createElement("button");
                pauseBtn.className = "kellai-tour-btn-pause";
                pauseBtn.type = "button";
                pauseBtn.setAttribute("aria-label", "暂停 / 继续");
                const updatePauseUI = () => {
                  if (pausedRef.current) {
                    pauseBtn.textContent = "继续";
                    pauseBtn.style.color = "#10b981";
                  } else {
                    pauseBtn.textContent = "暂停";
                    pauseBtn.style.color = "#64748b";
                  }
                };
                pauseBtn.style.cssText = `
                  background:transparent; border:none; cursor:pointer;
                  font-size:12px; padding:4px 8px; border-radius:4px;
                  transition:background .15s;
                `;
                pauseBtn.onmouseover = () => (pauseBtn.style.background = "#f1f5f9");
                pauseBtn.onmouseout = () => (pauseBtn.style.background = "transparent");
                pauseBtn.onclick = () => {
                  pausedRef.current = !pausedRef.current;
                  if (pausedRef.current) {
                    speechRef.current.stop();
                  } else {
                    void playSpeechForStep();
                  }
                  updatePauseUI();
                };

                const replayBtn = document.createElement("button");
                replayBtn.type = "button";
                replayBtn.setAttribute("aria-label", "重播当前步骤语音");
                replayBtn.textContent = "重播语音";
                replayBtn.style.cssText = `
                  background:transparent; border:none; cursor:pointer;
                  font-size:12px; padding:4px 8px; border-radius:4px;
                  color:#2563eb; transition:background .15s;
                `;
                replayBtn.onmouseover = () => (replayBtn.style.background = "#eff6ff");
                replayBtn.onmouseout = () => (replayBtn.style.background = "transparent");
                replayBtn.onclick = () => {
                  void playSpeechForStep(replayBtn);
                };

                const skipBtn = document.createElement("button");
                skipBtn.type = "button";
                skipBtn.setAttribute("aria-label", "跳过当前步");
                skipBtn.textContent = "跳过";
                skipBtn.style.cssText = `
                  background:transparent; border:none; cursor:pointer;
                  font-size:12px; padding:4px 8px; border-radius:4px;
                  color:#64748b; transition:background .15s;
                `;
                skipBtn.onmouseover = () => (skipBtn.style.background = "#f1f5f9");
                skipBtn.onmouseout = () => (skipBtn.style.background = "transparent");
                skipBtn.onclick = () => {
                  skipRequestedRef.current = true;
                };

                leftCtl.appendChild(pauseBtn);
                leftCtl.appendChild(replayBtn);
                ctl.appendChild(leftCtl);
                ctl.appendChild(skipBtn);
                popoverEl.appendChild(ctl);
                updatePauseUI();
              }

              if (isLast) {
                const cta = document.createElement("button");
                cta.className = "kellai-tour-cta";
                cta.type = "button";
                cta.textContent = "开始使用";
                cta.style.cssText = `
                  display:block; width:100%; margin-top:12px; padding:10px 16px;
                  background:linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
                  color:white; border:none; border-radius:8px; font-size:14px;
                  font-weight:600; cursor:pointer; box-shadow:0 4px 12px rgba(59,130,246,.35);
                  transition:transform .15s, box-shadow .15s;
                `;
                cta.onmouseover = () => {
                  cta.style.transform = "translateY(-1px)";
                  cta.style.boxShadow = "0 6px 18px rgba(59,130,246,.5)";
                };
                cta.onmouseout = () => {
                  cta.style.transform = "";
                  cta.style.boxShadow = "0 4px 12px rgba(59,130,246,.35)";
                };
                cta.onclick = () => {
                  speechRef.current.stop();
                  markCompleted();
                  try { driverRef.current?.destroy(); } catch { /* ignore */ }
                  try { navigateRef.current("/funnel"); } catch { /* ignore */ }
                };
                popoverEl.appendChild(cta);
              }
            }, 30);
          },
          steps: stepDef ? [stepDef] : [],
        });
        driverRef.current = stepDriver;
        try { stepDriver.drive(); } catch (e) {
          console.warn(`[onboarding] step ${idx} drive failed`, e);
        }
        // 等 driver.js 渲染完 popover + 蒙版
        await sleep(100);
        if (speechText && welcomeAlreadyPlaying) {
          const replayBtn = document.querySelector<HTMLButtonElement>(
            '.driver-popover.kellai-tour-popover [aria-label="重播当前步骤语音"]'
          );
          if (replayBtn) {
            replayBtn.textContent = "播放中";
            replayBtn.title = "语音正在播放，画面会等本段播完";
            window.setTimeout(() => {
              if (replayBtn.textContent === "播放中") {
                replayBtn.textContent = "重播语音";
                replayBtn.title = "";
              }
            }, Math.max(500, welcomePreplayedUntil - Date.now()));
          }
        } else if (speechText) {
          const replayBtn = document.querySelector<HTMLButtonElement>(
            '.driver-popover.kellai-tour-popover [aria-label="重播当前步骤语音"]'
          );
          void playSpeechForStep(replayBtn || undefined).then((ok) => {
            if (!ok) {
              console.warn("[onboarding] tour speech failed", speechRef.current.lastError);
              const currentReplayBtn = document.querySelector<HTMLButtonElement>(
                '.driver-popover.kellai-tour-popover [aria-label="重播当前步骤语音"]'
              );
              if (currentReplayBtn) {
                currentReplayBtn.textContent = "点击播放语音";
                currentReplayBtn.title = speechRef.current.lastError || "浏览器未允许自动播放，请点击播放语音";
              }
            }
            return ok;
          }).finally(() => {
            speechDone = true;
          });
        }

        // e) run demo（在正确的蒙版下执行动画）
        const t = makeTimerGroup();
        timersRef.current = t;
        let demoResult: DemoResult = { ok: true };
        try {
          demoResult = await step.demo(t);
        } catch (e) {
          console.warn(`[onboarding] step ${idx} demo failed`, e);
          demoResult = { ok: false, fallbackMsg: "演示遇到问题，已跳过这一步。" };
        }
        // demo 失败 → 改气泡文案
        if (!demoResult.ok && demoResult.fallbackMsg) {
          const desc = document.querySelector(
            ".driver-popover.kellai-tour-popover .driver-popover-description"
          );
          if (desc) {
            desc.innerHTML = `<div style="color:#f59e0b;font-weight:600">⚠️ 这一步的演示没成功</div><div style="margin-top:4px;font-size:12px">${demoResult.fallbackMsg}</div>`;
          }
        }
        if (!demoResult.ok && demoResult.stop) {
          await sleep(2800 * SPEED);
          if (cancelled) return;
          cancelled = true;
          if (timersRef.current) timersRef.current.clear();
          speechRef.current.stop();
          try { window.virtualCursor?.hide(); } catch { /* ignore */ }
          try { document.body.classList.remove("tutorial-active"); } catch { /* ignore */ }
          try { driverRef.current?.destroy(); } catch { /* ignore */ }
          try { navigateRef.current(demoResult.redirectPath || "/settings?tab=ai"); } catch { /* ignore */ }
          setActive(false);
          return;
        }

        // f) 等 duration（期间检查暂停 / 跳过）
        if (idx === SCHEDULE.length - 1) {
          // 收尾步：不自动进，等用户点 CTA 或 ×
          return;
        }
        const dur = demoResult.ok ? step.duration : 2000 * SPEED;
        const stepStart = Date.now();
        while (!cancelled) {
          await waitWhilePaused();
          if (skipRequestedRef.current) {
            skipRequestedRef.current = false;
            break;
          }
          const durationDone = Date.now() - stepStart >= dur;
          const speechHoldDone =
            !speechText ||
            (speechHoldUntilRef.current > 0 && Date.now() >= speechHoldUntilRef.current);
          if (durationDone && speechDone && speechHoldDone) {
            break;
          }
          await sleep(120);
        }
        if (cancelled) return;
        await runStep(idx + 1);
      };

      // 启动：200ms 后从 Step 0 开始
      const startTimer = window.setTimeout(() => {
        if (cancelled) return;
        runStep(0);
      }, 200);

      // 把控制函数挂到 ref，让 onPopoverRender 能调到
      (driverRef as unknown as { __controls: unknown }).__controls = {
        pause: () => {
          pausedRef.current = true;
        },
        resume: () => {
          pausedRef.current = false;
        },
        isPaused: () => pausedRef.current,
        skip: () => {
          skipRequestedRef.current = true;
        },
        cta: () => {
          // 收尾 CTA：完成 + 销毁当前 driver + 跳漏斗
          speechRef.current.stop();
          markCompleted();
          try {
            driverRef.current?.destroy();
          } catch {
            // ignore
          }
          try {
            navigateRef.current("/funnel");
          } catch {
            // ignore
          }
        },
      };

      return () => {
        cancelled = true;
        clearTimeout(startTimer);
        if (timersRef.current) timersRef.current.clear();
        speechRef.current.stop();
        pausedRef.current = false;
        skipRequestedRef.current = false;
        // 销毁当前 driver 实例（蒙版 + popover）
        if (driverRef.current) {
          try { driverRef.current.destroy(); } catch { /* ignore */ }
          driverRef.current = null;
        }
        // 收尾：隐藏虚拟光标（demo 最后停在某个元素上，教程结束必须收掉）
        try {
          window.virtualCursor?.hide();
        } catch {
          // ignore
        }
        // 兜底：移除 tutorial-active，避免 React 状态异步更新期间漏掉清理
        try {
          document.body.classList.remove("tutorial-active");
        } catch {
          // ignore
        }
      };
    } else {
      if (timersRef.current) timersRef.current.clear();
      speechRef.current.stop();
      // active 变 false 时也确保清掉 class
      try { document.body.classList.remove("tutorial-active"); } catch { /* ignore */ }
    }
  }, [active, markCompleted, markSkipped, setActive, setAdvancedPanelOpen]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (timersRef.current) timersRef.current.clear();
      speechRef.current.stop();
      if (driverRef.current) {
        try {
          driverRef.current.destroy();
        } catch {
          // ignore
        }
        driverRef.current = null;
      }
    };
  }, []);

  return null;
}
