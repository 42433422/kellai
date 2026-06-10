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
import client from "../api/client";

type DriverInstance = ReturnType<typeof driver>;

/** 教程动画速度倍率：>1 变慢，<1 变快。2.0 = 比默认慢一倍 */
const SPEED = 2.0;

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

/** 安全地触发一个元素的 click（带容错 + 虚拟光标动画） */
function safeClick(selector: string, label?: string, duration = 500 * SPEED): boolean {
  const el = document.querySelector(selector) as HTMLElement | null;
  if (!el) return false;
  // 把元素滚进可视区，避免被遮罩盖住
  try {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch {
    // ignore
  }
  cursorClick(el, label, duration);
  return true;
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

type DemoResult = { ok: boolean; fallbackMsg?: string };

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
  // 3) 光标飞到"扫码授权"按钮并真实点击（视觉 + 真实 el.click）
  timers.set(() => cursorClick(firstConfigBtn, "📱 扫码授权", 700 * SPEED), 1800 * SPEED);
  // 4) 高亮弹出的 QR 码
  // 时序：真实点击发生在 1800+700=2500*SPEED 时刻，React 渲染 modal 大约 1 帧，
  // QR 码 3.5s 后自动跳到「已扫描」。我们在 3200*SPEED 高亮一下 QR 码，给用户聚焦。
  timers.set(() => {
    const qr = document.querySelector<HTMLElement>('[data-tour="channel-qrcode"]');
    if (qr) {
      qr.style.transition = "outline .3s, outline-offset .3s";
      qr.style.outline = "3px solid #10b981";
      qr.style.outlineOffset = "6px";
    } else {
      console.warn("[onboarding] step1: QR 码未出现，跳过高亮");
    }
  }, 3200 * SPEED);
  // 5) 演示"等待扫码 → 已扫"的过渡：什么都不做，弹窗自带状态机会跑
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

/** Step 3（消息）：自动点第一个联系人 → AI 推荐 → 等 AI 返回 → 填入第一条话术
 *  用 data-tour / data-contact-id / data-suggestion-fill 锚点
 *  关键：AI 推荐会触发后端请求 + loading，必须等"填入"按钮真的出现再点，
 *  不能写死时序（之前写 2800ms 不够，SPEED=2 时等于 5.6s，但 AI 后端也卡的话仍会失败） */
function demoMessages(timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const list = document.querySelector<HTMLElement>('[data-tour="messages-contact-list"]');
  if (!list) return { ok: false, fallbackMsg: "消息页面未加载，请刷新" };

  // 抓第一个联系人的真实 id，后面 Step 6 跳详情页要用
  let firstContactId: string | null = null;
  const firstContactEl = document.querySelector<HTMLElement>(
    '[data-tour="messages-contact-list"] [data-contact-id]'
  );
  if (firstContactEl) firstContactId = firstContactEl.getAttribute("data-contact-id");
  // 暴露给外层 runStep 用
  (window as unknown as { __tutorialFirstContact?: string | null }).__tutorialFirstContact = firstContactId;

  // 1) 点开第一个联系人
  timers.set(() => {
    const firstContact = document.querySelector<HTMLElement>(
      '[data-tour="messages-contact-list"] [data-contact-id]'
    );
    if (firstContact) {
      firstContact.style.transition = "background .3s";
      firstContact.style.background = "#dbeafe";
      cursorClick(firstContact, "💬 选这个客户", 800 * SPEED);
      setTimeout(() => (firstContact.style.background = ""), 600 * SPEED);
    }
  }, 200 * SPEED);

  // 2) 点 AI 推荐按钮
  timers.set(() => safeClick('[data-tour="messages-ai-suggest"]', "✨ AI 推荐", 800 * SPEED), 1200 * SPEED);

  // 3) 等 AI 返回（轮询 data-suggestion-fill 锚点出现，最长 4*SPEED 秒）
  let aiWaited = 0;
  const aiStart = 2200 * SPEED; // 第 2 步点完后开始等
  const aiMax = 4000 * SPEED;
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

/** Step 4（客户详情）：滚动到 AI 画像区域
 *  锚点用 data-tour="customer-ai-profile"，不再走"按 h 文本猜祖先"那种 fragile 逻辑 */
function demoCustomerDetail(_timers: ReturnType<typeof makeTimerGroup>): DemoResult {
  const card = document.querySelector<HTMLElement>('[data-tour="customer-ai-profile"]');
  if (!card) return { ok: false, fallbackMsg: "客户详情页 AI 画像区域未找到" };
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.style.transition = "outline .3s, outline-offset .3s";
  card.style.outline = "2px solid #3b82f6";
  card.style.outlineOffset = "4px";
  setTimeout(() => {
    card.style.outline = "";
    card.style.outlineOffset = "";
  }, 1500 * SPEED);
  return { ok: true };
}

/** Step 5（AI 助手）：选第一个客户 + 输入示例文本 + 点分析意图
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

  // 2) 等下拉展开后，点第一个客户
  timers.set(() => {
    const opt = document.querySelector<HTMLElement>("[data-customer-option]");
    if (opt) {
      opt.style.transition = "background .3s";
      opt.style.background = "#dbeafe";
      cursorClick(opt, "👤 选这个", 700 * SPEED);
      setTimeout(() => (opt.style.background = ""), 600 * SPEED);
    }
  }, 1100 * SPEED);

  // 3) 在输入框填入示例客户话（用 data-tour="ai-input" 锚点）
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
  }, 1900 * SPEED);

  // 4) 点分析意图（用 data-tour 锚点，不再 selector 二义）
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
  }, 3000 * SPEED);
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
  const active = useOnboardingStore((s) => s.active);
  const markCompleted = useOnboardingStore((s) => s.markCompleted);
  const markSkipped = useOnboardingStore((s) => s.markSkipped);
  const navigate = useNavigate();
  // 关键修复：useNavigate() 在 Declarative 模式下每次渲染返回新引用，
  // 放进 useEffect 依赖会触发 effect 反复 cleanup / 重跑，把 runStep 链斩断。
  // 用 ref 持有最新值，effect 只依赖真正"会变化"的项。
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  /** 构造一个新的 driver.js 实例（每次教程启动都重新创建，保证状态干净） */
  const buildDriver = (): DriverInstance =>
    driver({
      animate: true,
      // 教程模式 = 围观模式：用户不能点页面，只能看虚拟光标做演示。
      // 蒙版拦住下方所有元素，但 popover 自身（×/暂停/跳过/CTA）可点。
      overlayOpacity: 0.55,
      stagePadding: 6,
      stageRadius: 10,
      allowClose: true,
      // overlay 点击 = no-op（避免误关；关闭走 popover 内的 ×）
      overlayClickBehavior: () => {},
      showProgress: true,
      progressText: "第 {{current}} 步 / 共 {{total}} 步",
      nextBtnText: "下一步 →",
      prevBtnText: "← 上一步",
      doneBtnText: "完成，开始使用 🚀",
      overlayColor: "rgba(15, 23, 42, 0.55)",
      popoverClass: "kellai-tour-popover",
      onDestroyed: () => {
        // 注意：不在这里调 setActive(false)！
        // runStep 每步会销毁旧 driver 重建新的，如果这里调 setActive(false)
        // 会导致 useEffect cleanup 把 cancelled=true，整个教程链断裂。
        // setActive(false) 只在 onCloseClick（用户点×）和教程自然结束时调用。
        if (timersRef.current) timersRef.current.clear();
      },
      onCloseClick: () => {
        // 关键修复：× 关闭要"无论如何都能关掉"。
        // markSkipped() 会改 active=false，触发 useEffect cleanup 收尾。
        // 但 React 状态更新是异步的，driver.js 紧接着调 destroy() → onDestroyed
        // 也 setActive(false)，期间可能漏掉一次 cleanup。所以这里同步做一次兜底：
        // 1) 立刻停掉所有定时器
        // 2) 立刻隐藏虚拟光标
        // 3) 把 driver 实例主动 destroy
        if (timersRef.current) timersRef.current.clear();
        try {
          window.virtualCursor?.hide();
        } catch {
          // ignore
        }
        try {
          document.body.classList.remove("tutorial-active");
        } catch {
          // ignore
        }
        try {
          driverRef.current?.destroy();
        } catch {
          // ignore
        }
        markSkipped();
      },
      /* 每次 popover 渲染时，注入 ⏸/⏭ 控制按钮 + 收尾 CTA */
      onPopoverRender: (popover) => {
        const popoverEl = popover.wrapper as HTMLElement | undefined;
        if (!popoverEl) return;
        // 等一帧让 driver.js 完成 popover 插入
        window.setTimeout(() => {
          const idx = currentStepRef.current;
          // 修复：之前写死 idx === 7（只有 8 步时才对），现在 SCHEDULE 长度 10，
          // 收尾是 idx === SCHEDULE.length - 1。
          // 构造时把总步数挂到 driver 实例上，保证 onPopoverRender 拿得到。
          const totalSteps = (driverRef.current as unknown as { __totalSteps?: number } | null)?.__totalSteps ?? 10;
          const isLast = idx === totalSteps - 1;
          // 1) 清理旧的（避免重复注入）
          const old = popoverEl.querySelector(".kellai-tour-ctl");
          if (old) old.remove();
          const oldCta = popoverEl.querySelector(".kellai-tour-cta");
          if (oldCta) oldCta.remove();

          // 2) 注入 ⏸/⏭（每步都有）
          if (!isLast) {
            const ctl = document.createElement("div");
            ctl.className = "kellai-tour-ctl";
            ctl.style.cssText = `
              display:flex; justify-content:space-between; align-items:center;
              margin-top:12px; padding-top:10px; border-top:1px dashed #e2e8f0;
            `;
            const pauseBtn = document.createElement("button");
            pauseBtn.className = "kellai-tour-btn-pause";
            pauseBtn.type = "button";
            pauseBtn.setAttribute("aria-label", "暂停 / 继续");
            const updatePauseUI = () => {
              const ctrl = (driverRef as unknown as { __controls?: { isPaused: () => boolean; resume: () => void; pause: () => void } }).__controls;
              if (!ctrl) return;
              if (ctrl.isPaused()) {
                pauseBtn.textContent = "▶ 继续";
                pauseBtn.style.color = "#10b981";
              } else {
                pauseBtn.textContent = "⏸ 暂停";
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
              const ctrl = (driverRef as unknown as { __controls?: { isPaused: () => boolean; resume: () => void; pause: () => void } }).__controls;
              if (!ctrl) return;
              if (ctrl.isPaused()) ctrl.resume();
              else ctrl.pause();
              updatePauseUI();
            };

            const skipBtn = document.createElement("button");
            skipBtn.type = "button";
            skipBtn.setAttribute("aria-label", "跳过当前步");
            skipBtn.textContent = "⏭ 跳过";
            skipBtn.style.cssText = `
              background:transparent; border:none; cursor:pointer;
              font-size:12px; padding:4px 8px; border-radius:4px;
              color:#64748b; transition:background .15s;
            `;
            skipBtn.onmouseover = () => (skipBtn.style.background = "#f1f5f9");
            skipBtn.onmouseout = () => (skipBtn.style.background = "transparent");
            skipBtn.onclick = () => {
              const ctrl = (driverRef as unknown as { __controls?: { skip: () => void } }).__controls;
              if (ctrl) ctrl.skip();
            };

            ctl.appendChild(pauseBtn);
            ctl.appendChild(skipBtn);
            popoverEl.appendChild(ctl);
            updatePauseUI();
          }

          // 3) 收尾步注入 CTA 大按钮
          if (isLast) {
            const cta = document.createElement("button");
            cta.className = "kellai-tour-cta";
            cta.type = "button";
            cta.textContent = "🚀 现在去添加你的第一个客户";
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
              const ctrl = (driverRef as unknown as { __controls?: { cta: () => void } }).__controls;
              if (ctrl) ctrl.cta();
            };
            popoverEl.appendChild(cta);
          }
        }, 30);
      },
      steps: [
        /* ===== Step 0 - 欢迎 ===== */
        {
          popover: {
            title: "👋 欢迎使用 客来来",
            description:
              "<b>60 秒</b>看完<b>真实使用流程</b>，不是 PPT 介绍：\n\n1️⃣ <b>先渠道、配</b>绑定 AI\n2️⃣ <b>再</b>看工作台、漏斗、消息\n3️⃣ 拖卡片 / AI 话术 / ⌘K 搜索\n\n跟着我的顺序走,这就是真实用户的使用路径 🚀",
            align: "center",
          },
        },

        /* ===== Step 1 - 设置·渠道管理（真实工作流第一步） ===== */
        {
          element: '[data-tour="settings-channels"]',
          popover: {
            title: "🔌 ① 第一步：扫码授权接渠道",
            description:
              "没有渠道,客户消息进不来,后面的<b>漏斗</b>、<b>消息中心</b>全是空的。\n\n👀 我刚：\n1️⃣ 找到「企业微信」卡片\n2️⃣ 点了<b>「扫码授权」</b>\n3️⃣ 弹出 QR 码 → 手机扫 → 自动确认 → 完成\n\n💡 <b>比填凭据简单 10 倍</b>,真实工作流就是这样,扫码就行。",
            side: "left",
            align: "start",
          },
        },

        /* ===== Step 2 - 设置·AI 助手（LLM 配置） ===== */
        {
          element: '[data-tour="settings-channels"]',
          popover: {
            title: "🤖 ② 第二步:配 LLM",
            description:
              "AI 话术 / 意图分析 / 客户画像全靠这一步,没配的话所有 AI 功能 = 摆设。\n\n👀 我刚帮你切到 <b>AI 助手</b> tab,扫了 2 个核心区:\n• <b>模型配置</b>:选厂商 + 填 API Key\n• <b>自动回复策略</b>:哪些阶段让 AI 自动接\n\n💡 真实流程:开通 LLM 账号 → 拿 Key → 回来粘 → 测通 → 启用自动回复。",
            side: "left",
            align: "start",
          },
        },

        /* ===== Step 3 - 工作台（4 个 KpiTile 总览） ===== */
        {
          element: '[data-tour="dashboard-todo"]',
          popover: {
            title: "📊 ③ 工作台:业务首页",
            description:
              "渠道 + AI 都配好之后,这里开始有数据。\n\n👀 工作台是 4 个<b>方形入口</b>，不是大表格：\n• <b>今日待办</b> = AI 排好序的待跟进客户\n• <b>线索动态</b> = 刚进来的消息流\n• <b>漏斗概览</b> = 客户分布\n• <b>AI 建议</b> = 智能提醒\n\n💡 想看哪个<b>点一下就跳进去</b>，每个方块背后都有一个完整页面。",
            side: "bottom",
            align: "center",
          },
        },

        /* ===== Step 4 - 漏斗 ===== */
        {
          element: '[data-tour="funnel-board"]',
          popover: {
            title: "🌪️ ④ 漏斗看板:拖客户就这么简单",
            description:
              "👀 我刚把一张客户卡从「<b>已建联</b>」拖到了「<b>需求采集</b>」。\n\n状态已经存到客户档案里,刷新不会丢。\n\n💡 不用手填「下一步是什么」,<b>拖一下就完事</b>。",
            side: "bottom",
            align: "center",
          },
        },

        /* ===== Step 5 - 消息中心 ===== */
        {
          element: '[data-tour="messages-contact-list"]',
          popover: {
            title: "💬 ⑤ 消息中心:AI 帮你写话术",
            description:
              "👀 我刚:\n1️⃣ 选了一个客户\n2️⃣ 点了「<b>AI 推荐</b>」\n3️⃣ 把推荐的话术<b>填进输入框</b>\n\n💡 <b>省了 3 分钟</b>想词时间,发消息不用再咬笔头。",
            side: "left",
            align: "start",
          },
        },

        /* ===== Step 6 - 客户详情 ===== */
        {
          element: '[data-tour="customer-detail"]',
          popover: {
            title: "👤 ⑥ 客户详情:360° 画像",
            description:
              "👀 我刚自动滚到「<b>AI 画像</b>」区域。\n\n这里聚合了客户的需求、预算、决策角色、所有跟进记录…\n\n💡 打电话前<b> 5 秒看完</b>,再也不怕被客户问倒。",
            side: "right",
            align: "start",
          },
        },

        /* ===== Step 7 - AI 助手（分析意图） ===== */
        {
          element: '[data-tour="ai-analyze"]',
          popover: {
            title: "🚀 ⑦ AI 助手:一秒看懂客户想法",
            description:
              "👀 我刚帮你:\n1️⃣ 选了一个客户\n2️⃣ 输入:\"<i>老板在考虑换更便宜的供应商</i>\"\n3️⃣ 点了「<b>分析意图</b>」\n\nAI 会告诉你:<b>客户正在比价</b>,<b>推荐话术</b>也跟着出来。\n\n💡 以前靠经验判断,现在 1 秒看结论。",
            side: "left",
            align: "start",
          },
        },

        /* ===== Step 8 - 全局搜索 ===== */
        {
          element: '[data-tour="topbar-search"]',
          popover: {
            title: "🔍 ⑧ 全局搜索:⌘K",
            description:
              "👀 我刚按了 <kbd>⌘K</kbd>,输入了「<b>客</b>」。\n\n任意页面都能用:搜客户、消息、订单都行。\n\n💡 不用记菜单在哪,<b>键盘一按就到</b>。",
            side: "bottom",
            align: "start",
          },
        },

        /* ===== Step 9 - 收尾（带 CTA） ===== */
        {
          popover: {
            title: "🎉 60 秒看完了!",
            description:
              "你现在掌握了<b>真实使用流程</b>:\n\n<b>① 先</b>绑渠道 → <b>② 再</b>配 AI\n→ <b>③</b> 工作台看全局 → <b>④~⑦</b> 漏斗/消息/详情/AI\n→ <b>⑧</b> ⌘K 跳转\n\n💡 <b>记住这条主线</b>就行,中间不懂的功能随时问 AI 助手。\n\n右上角 ❓ 随时可以再走一遍。",
            align: "center",
          },
        },
      ] as DriveStep[],
    });

  /* ---------- 响应 store.active 启动 / 停止 ----------
   * 链式调度：每一步顺序：navigate → poll for element → run demo → drive → 等 duration → 进下一步
   * 完全不依赖 driver.js 的 onNextClick（按钮已隐藏） */
  useEffect(() => {
    if (active) {
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

      // 2) 构造新实例
      const obj = buildDriver();
      driverRef.current = obj;
      // 把总步数挂到 driver 实例上，给 onPopoverRender 用
      (obj as unknown as { __totalSteps: number }).__totalSteps = 10;

      // 3) 链式调度表（v2 压缩到 ~30 秒，SPEED=2 时约 60 秒）
      type StepSchedule = {
        path: string; // 导航目标（先 navigate 再等元素）
        waitFor: string; // 等这个 selector 出现再跑 demo
        demo: (timers: ReturnType<typeof makeTimerGroup>) => { ok: boolean; fallbackMsg?: string };
        duration: number; // 演示完后等多久进下一步
        demoFirst?: boolean; // true = 先跑 demo 再显示 popover（避免 popover 挡住操作目标）
      };
      const SCHEDULE: StepSchedule[] = [
        // Step 0: 欢迎 — 给足时间读（之前 1500ms 太短）
        {
          path: "/",
          waitFor: '[data-tour="dashboard-todo"]',
          demo: () => ({ ok: true }),
          duration: 4500 * SPEED,
        },
        // Step 1: 设置 → 渠道管理（必须先配，漏斗/消息才有数据来源）
        // 扫码流程：点击 + 等待 3.5s + 已扫 2s + 成功 1.2s ≈ 9s
        {
          path: "/settings?tab=channels",
          waitFor: '[data-tour="settings-channel-card"]',
          demo: (t) => demoChannelBind(t),
          duration: 9000 * SPEED,
        },
        // Step 2: 设置 → AI 助手（配 LLM，后面 AI 功能才工作）
        // 不导航到 /settings?tab=ai（React Router 同路由 searchParams 变化可能不触发 re-render），
        // 而是留在 /settings，demo 函数会直接点击 AI tab 按钮
        {
          path: "/settings",
          waitFor: '[data-tour="settings-channels"]',
          demo: (t) => demoAiSetup(t),
          duration: 5500 * SPEED,
        },
        // Step 3: 工作台（4 大模块总览）
        {
          path: "/",
          waitFor: '[data-tour="dashboard-todo"]',
          demo: (t) => demoDashboard(t),
          duration: 4500 * SPEED,
        },
        // Step 4: 漏斗（拖卡片改阶段）
        {
          path: "/funnel",
          waitFor: '[data-tour="funnel-board"]',
          demo: (t) => demoFunnelDrag(t),
          duration: 3500 * SPEED,
        },
        // Step 5: 消息（AI 话术）— AI 填入可能耗时较长，给够 7.5s 看完整流程
        {
          path: "/messages",
          waitFor: '[data-tour="messages-contact-list"]',
          demo: (t) => demoMessages(t),
          duration: 7500 * SPEED,
        },
        // Step 6: 客户详情（360° 画像）
        // 路径用 Step 5 抓到的真实 contact id，不写死 1（之前写死 /customers/1
        //  经常撞到不存在的客户，详情页 fallback 走"客户不存在"空态）
        {
          path: "__USE_FIRST_CONTACT__",
          waitFor: '[data-tour="customer-detail"]',
          demo: (t) => demoCustomerDetail(t),
          duration: 2500 * SPEED,
        },
        // Step 7: AI 助手（分析意图）— 看到分析结果再走
        {
          path: "/ai",
          waitFor: '[data-tour="ai-analyze"]',
          demo: (t) => demoAiAssistant(t),
          duration: 6000 * SPEED,
        },
        // Step 8: 全局搜索（⌘K）— 输入关键词 + 看结果
        {
          path: "/",
          waitFor: '[data-tour="topbar-search"]',
          demo: (t) => demoGlobalSearch(t),
          duration: 2500 * SPEED,
          demoFirst: true, // 先按 ⌘K + 输入，再显示 popover（避免面板挡搜索框）
        },
        // Step 9: 收尾（带 CTA）
        {
          path: "/",
          waitFor: "body",
          demo: () => ({ ok: true }),
          duration: 999999, // 不自动关闭，等用户点 CTA
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
        let realPath = step.path;
        if (step.path === "__USE_FIRST_CONTACT__") {
          const cid = (window as unknown as { __tutorialFirstContact?: string | null }).__tutorialFirstContact;
          realPath = cid ? `/customers/${cid}` : "/customers";
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
        const timeout = 10000;
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

        // d) ★ 推进 driver.js 到当前步骤 + 跑 demo
        //    demoFirst=true 时：先跑 demo 再显示 popover（避免面板挡住操作目标）
        //    否则：先显示 popover 再跑 demo（默认，用户能边看说明边看演示）

        const runDemo = async () => {
          const t = makeTimerGroup();
          timersRef.current = t;
          let demoResult: DemoResult = { ok: true };
          try {
            demoResult = step.demo(t);
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
          return demoResult;
        };

        const advanceDriver = () => {
          if (idx === 0) {
            try {
              obj.drive(0);
              console.log(`[onboarding] step ${idx}: drive(0) OK`);
            } catch (e) {
              console.warn(`[onboarding] step ${idx}: drive(0) failed`, e);
            }
          } else {
            try {
              (obj as unknown as { moveNext: () => void }).moveNext();
              console.log(`[onboarding] step ${idx}: moveNext() OK`);
            } catch (e) {
              console.warn(`[onboarding] step ${idx}: moveNext() failed, fallback to drive`, e);
              try { obj.drive(idx); } catch {}
            }
          }
        };

        let demoResult: DemoResult;
        if (step.demoFirst) {
          // 先跑 demo（popover 还没出来，不挡操作目标）
          demoResult = await runDemo();
          await sleep(300);
          // 再显示 popover
          advanceDriver();
          await sleep(200);
        } else {
          // 先显示 popover
          advanceDriver();
          await sleep(200);
          // 再跑 demo
          demoResult = await runDemo();
        }

        // f) 等 duration（期间检查暂停 / 跳过）
        if (idx === SCHEDULE.length - 1) {
          // 收尾步：不自动进，等用户点 CTA 或 ×
          return;
        }
        const dur = demoResult.ok ? step.duration : 2000 * SPEED;
        const stepStart = Date.now();
        while (!cancelled && Date.now() - stepStart < dur) {
          await waitWhilePaused();
          if (skipRequestedRef.current) {
            skipRequestedRef.current = false;
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
        // runStep(0) 内部会调 obj.drive(0) 启动 driver，这里不需要再调
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
          // 收尾 CTA：完成 + 跳漏斗
          markCompleted();
          try {
            obj.destroy();
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
      // active 变 false 时也确保清掉 class
      try { document.body.classList.remove("tutorial-active"); } catch { /* ignore */ }
    }
  }, [active, markCompleted, markSkipped]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (timersRef.current) timersRef.current.clear();
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
