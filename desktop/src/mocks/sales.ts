import { MOCK_CUSTOMERS } from './customers';
import type {
  SalesFlow,
  SalesFlowStep,
  SalesFlowTimelineEntry,
  Quote,
  Contract,
  LTVForecast,
  SalesPerformance,
  SalesRep,
  AttributionReport,
  FunnelTrace,
  SalesScriptHint,
} from '../types';

const FLOW_STEPS: SalesFlowStep[] = ['requirement', 'proposal', 'promotion', 'signing'];
const STEP_LABELS: Record<SalesFlowStep, string> = {
  requirement: '需求确认',
  proposal: '方案推荐',
  promotion: '促单',
  signing: '签约',
};

/** 每个阶段的 AI 洞察、赢单概率、下一步行动与待办清单（驱动 SalesFlow 富交互） */
const STEP_META: Record<
  SalesFlowStep,
  { probability: number; ai_insight: string; next_action: string; checklist: string[] }
> = {
  requirement: {
    probability: 25,
    ai_insight: 'AI 已从历史会话中识别预算区间与决策链，客户处于需求澄清期，核心关注「获客效率」与「实施周期」。',
    next_action: '与对接人确认预算与决策流程，预约一次需求调研会',
    checklist: ['确认预算区间', '梳理决策链 / 关键决策人', '明确期望上线时间', '记录 3 个核心痛点'],
  },
  proposal: {
    probability: 52,
    ai_insight: '基于客户画像，推荐「标准版 + AI 助手」组合，同行业客户平均 6 个月内回本，建议突出 ROI 与标杆案例。',
    next_action: '发送定制方案与报价，预约方案讲解会并邀请决策人参加',
    checklist: ['输出定制方案 PPT', '附同行业标杆案例', '生成智能报价', '邀请决策人参会'],
  },
  promotion: {
    probability: 74,
    ai_insight: '客户已多次查看报价，AI 判断处于决策窗口期，建议用限时优惠 + 名额稀缺制造紧迫感推动签约。',
    next_action: '推送限时优惠并锁定签约时间，处理最后的价格与条款异议',
    checklist: ['确认最终折扣审批', '推送限时优惠', '解决付款方式异议', '锁定签约时间窗'],
  },
  signing: {
    probability: 90,
    ai_insight: '进入签约阶段，合同条款已对齐，建议引导客户走电子签约缩短回款周期，并提前规划交付与培训。',
    next_action: '生成电子合同并引导线上签署，安排实施交付负责人对接',
    checklist: ['生成电子合同', '法务条款确认', '客户完成电子签', '排期实施与培训'],
  },
};

const OWNERS = ['张敏', '李航', '王磊', '陈悦', '刘洋'];

const flowStateMap = new Map<number, SalesFlow>();
const quoteStore = new Map<number, Quote>();
const contractStore = new Map<number, Contract>();

function industryFactor(company: string): number {
  if (company.includes('科技') || company.includes('信息')) return 1.3;
  if (company.includes('购') || company.includes('零售')) return 1.1;
  return 1.0;
}

/** 依据客户 AI 评分估算商机金额 */
function dealValueFor(customerId: number): number {
  const customer = MOCK_CUSTOMERS.find((c) => c.customer_id === customerId);
  const score = customer?.ai_score ?? 0.5;
  return Math.round((60000 + score * 240000) / 1000) * 1000;
}

function probabilityFor(step: SalesFlowStep, status: SalesFlow['status']): number {
  if (status === 'completed') return 100;
  if (status === 'failed') return 0;
  return STEP_META[step].probability;
}

function nowIso(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 86400000).toISOString();
}

export function getOrCreateFlow(customerId: number): SalesFlow {
  let flow = flowStateMap.get(customerId);
  if (flow) return flow;
  const customer = MOCK_CUSTOMERS.find((c) => c.customer_id === customerId);
  const owner = OWNERS[customerId % OWNERS.length];
  flow = {
    id: `flow_${customerId}`,
    customer_id: customerId,
    customer_name: customer?.display_name ?? `客户${customerId}`,
    current_step: 'requirement',
    status: 'idle',
    started_at: nowIso(-3),
    updated_at: nowIso(),
    steps_completed: [],
    deal_value: dealValueFor(customerId),
    win_probability: STEP_META.requirement.probability,
    expected_close_date: nowIso(21).slice(0, 10),
    owner,
    next_action: STEP_META.requirement.next_action,
    ai_insight: STEP_META.requirement.ai_insight,
    checklist: STEP_META.requirement.checklist,
    timeline: [
      { step: 'requirement', label: STEP_LABELS.requirement, at: nowIso(-3), note: '流程启动，进入需求确认阶段' },
    ],
  };
  flowStateMap.set(customerId, flow);
  return flow;
}

function syncStepMeta(flow: SalesFlow): SalesFlow {
  const meta = STEP_META[flow.current_step];
  flow.win_probability = probabilityFor(flow.current_step, flow.status);
  flow.next_action = flow.status === 'completed' ? '已签约成交，转入交付与客户成功流程' : meta.next_action;
  flow.ai_insight = meta.ai_insight;
  flow.checklist = meta.checklist;
  return flow;
}

export function startAutoFlow(customerId: number, step?: SalesFlowStep): SalesFlow {
  const flow = getOrCreateFlow(customerId);
  flow.status = 'running';
  if (step) flow.current_step = step;
  flow.updated_at = nowIso();
  syncStepMeta(flow);
  flowStateMap.set(customerId, flow);
  return flow;
}

export function advanceFlow(customerId: number): SalesFlow {
  const flow = getOrCreateFlow(customerId);
  flow.status = 'running';
  const idx = FLOW_STEPS.indexOf(flow.current_step);
  if (!flow.steps_completed.includes(flow.current_step)) {
    flow.steps_completed.push(flow.current_step);
  }
  const ts = nowIso();
  if (idx < FLOW_STEPS.length - 1) {
    const next = FLOW_STEPS[idx + 1];
    flow.current_step = next;
    flow.timeline = [
      ...(flow.timeline ?? []),
      { step: next, label: STEP_LABELS[next], at: ts, note: `AI 推进至「${STEP_LABELS[next]}」阶段` },
    ];
  } else {
    flow.status = 'completed';
    flow.timeline = [
      ...(flow.timeline ?? []),
      { step: 'signing', label: '已成交', at: ts, note: '客户完成签约，商机赢单' } as SalesFlowTimelineEntry,
    ];
  }
  flow.updated_at = ts;
  syncStepMeta(flow);
  flowStateMap.set(customerId, flow);
  return flow;
}

export function generateQuote(customerId: number): Quote {
  const customer = MOCK_CUSTOMERS.find((c) => c.customer_id === customerId);
  const score = customer?.ai_score ?? 0.5;
  const basePrice = Math.round(5000 + score * 15000);
  const quote: Quote = {
    id: `quote_${customerId}_${Date.now()}`,
    customer_id: customerId,
    items: [
      { name: '标准版 CRM 坐席', quantity: 10, unit_price: basePrice, total: basePrice * 10 },
      { name: 'AI 助手模块', quantity: 1, unit_price: Math.round(basePrice * 0.3), total: Math.round(basePrice * 0.3) },
      { name: '实施与培训', quantity: 1, unit_price: 8000, total: 8000 },
    ],
    subtotal: 0,
    discount: score > 0.7 ? 0.1 : 0.05,
    total: 0,
    valid_until: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10),
    created_at: new Date().toISOString(),
  };
  quote.subtotal = quote.items.reduce((s, i) => s + i.total, 0);
  quote.total = Math.round(quote.subtotal * (1 - quote.discount));
  quoteStore.set(customerId, quote);
  return quote;
}

export function generateContract(customerId: number, quoteId?: string): Contract {
  const quote = quoteStore.get(customerId) ?? generateQuote(customerId);
  const contract: Contract = {
    id: `contract_${customerId}_${Date.now()}`,
    customer_id: customerId,
    quote_id: quoteId ?? quote.id,
    status: 'pending_sign',
    title: `客来来 CRM 服务合同 - ${MOCK_CUSTOMERS.find((c) => c.customer_id === customerId)?.company ?? ''}`,
    content_preview: `本合同金额为 ¥${quote.total.toLocaleString()}，包含 CRM 标准版及 AI 模块，服务有效期 12 个月，含实施与培训，自双方签署之日起生效。`,
    sign_url: `https://sign.kellai.com/mock/${customerId}`,
    created_at: new Date().toISOString(),
  };
  contractStore.set(customerId, contract);
  return contract;
}

export function getLTVForecast(customerId: number): LTVForecast {
  const customer = MOCK_CUSTOMERS.find((c) => c.customer_id === customerId);
  const base = 50000;
  const indFactor = industryFactor(customer?.company ?? '');
  const scoreFactor = 0.8 + (customer?.ai_score ?? 0.5) * 0.4;
  const ltv = Math.round(base * indFactor * scoreFactor);
  return {
    customer_id: customerId,
    predicted_ltv: ltv,
    confidence: 0.75 + (customer?.ai_score ?? 0.5) * 0.2,
    factors: [
      { name: '行业系数', impact: indFactor },
      { name: 'AI 意向评分', impact: scoreFactor },
      { name: '渠道质量', impact: 1.05 },
    ],
    recommendation: ltv > 80000 ? '高价值客户，建议优先跟进并安排专属顾问' : '标准跟进流程，关注需求确认阶段',
  };
}

/** 不同周期的业绩系数：周/月/季/年 */
const PERIOD_PROFILE: Record<string, { target: number; actual: number; deals: number; momentum: number; label: string }> = {
  week: { target: 125000, actual: 96000, deals: 4, momentum: 8.1, label: '本周' },
  month: { target: 500000, actual: 342000, deals: 12, momentum: 5.2, label: '本月' },
  quarter: { target: 1500000, actual: 1124000, deals: 38, momentum: 11.6, label: '本季度' },
  year: { target: 6000000, actual: 4380000, deals: 152, momentum: 18.4, label: '本年' },
};

function buildReps(scale: number): SalesRep[] {
  const raw = [
    { name: '张敏', revenue: 0.31, deals: 0.28, win_rate: 42 },
    { name: '李航', revenue: 0.26, deals: 0.24, win_rate: 38 },
    { name: '王磊', revenue: 0.2, deals: 0.22, win_rate: 35 },
    { name: '陈悦', revenue: 0.14, deals: 0.16, win_rate: 31 },
    { name: '刘洋', revenue: 0.09, deals: 0.1, win_rate: 27 },
  ];
  return raw
    .map((r, i) => ({
      id: i + 1,
      name: r.name,
      revenue: Math.round((scale * r.revenue) / 1000) * 1000,
      target: Math.round((scale * 0.24) / 1000) * 1000,
      deals: Math.max(1, Math.round((PERIOD_PROFILE.month.deals * 3) * r.deals)),
      win_rate: r.win_rate,
      rank: i + 1,
    }))
    .sort((a, b) => b.revenue - a.revenue)
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

function buildTrend(period: string, target: number, actual: number) {
  if (period === 'year') {
    return ['Q1', 'Q2', 'Q3', 'Q4'].map((p, i) => ({
      period: p,
      target: Math.round(target / 4),
      actual: i < 2 ? Math.round((actual / 1.6) * (i === 0 ? 0.7 : 0.9)) : 0,
    }));
  }
  if (period === 'quarter') {
    return ['第1月', '第2月', '第3月'].map((p, i) => ({
      period: p,
      target: Math.round(target / 3),
      actual: i < 2 ? Math.round((actual / 1.8) * (i === 0 ? 0.85 : 1.05)) : 0,
    }));
  }
  if (period === 'week') {
    return ['周一', '周二', '周三', '周四', '周五'].map((p, i) => ({
      period: p,
      target: Math.round(target / 5),
      actual: i < 4 ? Math.round((actual / 3.4) * [0.9, 1.1, 0.8, 1.0][i]) : 0,
    }));
  }
  return ['第1周', '第2周', '第3周', '第4周'].map((p, i) => ({
    period: p,
    target: Math.round(target / 4),
    actual: i < 3 ? Math.round((actual / 2.6) * [0.85, 1.05, 0.95][i]) : 0,
  }));
}

export function getSalesPerformance(period = 'month'): SalesPerformance {
  const prof = PERIOD_PROFILE[period] ?? PERIOD_PROFILE.month;
  const completion = Math.round((prof.actual / prof.target) * 1000) / 10;
  const avg = Math.round(prof.actual / prof.deals);
  const weeklyTarget = period === 'month' ? 30 : period === 'quarter' ? 90 : period === 'year' ? 360 : 8;
  return {
    period,
    revenue_target: prof.target,
    revenue_actual: prof.actual,
    completion_rate: completion,
    deals_closed: prof.deals,
    avg_deal_size: avg,
    momentum_pct: prof.momentum,
    win_rate: 38,
    pipeline_value: Math.round(prof.target * 1.8),
    forecast: Math.round(prof.actual * 1.32),
    reps: buildReps(prof.actual),
    revenue_trend: buildTrend(period, prof.target, prof.actual),
    goals: [
      {
        id: 'g1',
        title: `${prof.label}签约目标`,
        target: weeklyTarget,
        actual: prof.deals,
        unit: '单',
        breakdown: [
          { period: '第1周', target: 8, actual: 3, progress: 37.5 },
          { period: '第2周', target: 8, actual: 4, progress: 50 },
          { period: '第3周', target: 7, actual: 3, progress: 42.9 },
          { period: '第4周', target: 7, actual: 2, progress: 28.6 },
        ],
      },
    ],
  };
}

export function getAttribution(): AttributionReport {
  return {
    date_range: '2026-06-01 ~ 2026-06-12',
    total_revenue: 342000,
    channels: [
      { channel: 'wechat', channel_label: '微信', leads: 45, conversions: 5, revenue: 119700, contribution_pct: 35 },
      { channel: 'douyin', channel_label: '抖音', leads: 38, conversions: 3, revenue: 85500, contribution_pct: 25 },
      { channel: 'wework', channel_label: '企业微信', leads: 28, conversions: 2, revenue: 68400, contribution_pct: 20 },
      { channel: 'email', channel_label: '邮件', leads: 22, conversions: 2, revenue: 68400, contribution_pct: 20 },
    ],
  };
}

export function getFunnelTrace(customerId?: number): FunnelTrace {
  const stages = [
    { stage: 'no_contact', stage_label: '未接触' },
    { stage: 'connected', stage_label: '已建联' },
    { stage: 'requirement', stage_label: '需求采集' },
    { stage: 'quoted', stage_label: '已报价' },
    { stage: 'signed', stage_label: '已签' },
  ];
  const nodes = stages.map((s, i) => ({
    ...s,
    timestamp: new Date(Date.now() - (stages.length - i) * 86400000 * 2).toISOString(),
    duration_hours: 48,
  }));
  const edges = stages.slice(0, -1).map((s, i) => ({
    from_stage: s.stage,
    to_stage: stages[i + 1].stage,
    conversion_rate: [100, 72, 58, 35, 22][i] ?? 20,
  }));
  return {
    customer_id: customerId,
    nodes,
    edges,
    overall_conversion: 22,
  };
}

export function getScriptHint(customerId: number, stage: string): SalesScriptHint {
  const hints: Record<string, string[]> = {
    quoted: ['您好，关于上次报价方案，我们有专属优惠可以进一步沟通', '方案已根据您的需求定制，本周签约可享 95 折'],
    negotiating: ['理解您的顾虑，我们可以灵活调整付款方式', '竞品对比方面，我们的 AI 模块是独家优势'],
    pending_sign: ['合同已准备好，电子签约 5 分钟完成', '有任何条款疑问随时沟通，我们支持微调'],
    proposal: ['根据您的行业特点，推荐标准版 + AI 模块组合', '同类客户平均 ROI 在 6 个月内回本'],
  };
  const scripts = hints[stage] ?? ['感谢关注，请问目前最关注的功能点是？'];
  return {
    customer_id: customerId,
    stage,
    stage_label: STEP_LABELS[stage as SalesFlowStep] ?? stage,
    suggestion: `当前处于关键销售节点，建议使用以下话术促进转化`,
    scripts,
  };
}

export function getStoredQuote(customerId: number): Quote | undefined {
  return quoteStore.get(customerId);
}

export function getStoredContract(customerId: number): Contract | undefined {
  return contractStore.get(customerId);
}

export { FLOW_STEPS, STEP_LABELS };
