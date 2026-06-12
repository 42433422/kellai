import { MOCK_CUSTOMERS } from './customers';
import type {
  SalesFlow,
  SalesFlowStep,
  Quote,
  Contract,
  LTVForecast,
  SalesPerformance,
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

const flowStateMap = new Map<number, SalesFlow>();
const quoteStore = new Map<number, Quote>();
const contractStore = new Map<number, Contract>();

function industryFactor(company: string): number {
  if (company.includes('科技') || company.includes('信息')) return 1.3;
  if (company.includes('购') || company.includes('零售')) return 1.1;
  return 1.0;
}

export function getOrCreateFlow(customerId: number): SalesFlow {
  let flow = flowStateMap.get(customerId);
  if (flow) return flow;
  const customer = MOCK_CUSTOMERS.find((c) => c.customer_id === customerId);
  flow = {
    id: `flow_${customerId}`,
    customer_id: customerId,
    customer_name: customer?.display_name ?? `客户${customerId}`,
    current_step: 'requirement',
    status: 'idle',
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    steps_completed: [],
  };
  flowStateMap.set(customerId, flow);
  return flow;
}

export function startAutoFlow(customerId: number, step?: SalesFlowStep): SalesFlow {
  const flow = getOrCreateFlow(customerId);
  flow.status = 'running';
  if (step) flow.current_step = step;
  flow.updated_at = new Date().toISOString();
  flowStateMap.set(customerId, flow);
  return flow;
}

export function advanceFlow(customerId: number): SalesFlow {
  const flow = getOrCreateFlow(customerId);
  const idx = FLOW_STEPS.indexOf(flow.current_step);
  if (!flow.steps_completed.includes(flow.current_step)) {
    flow.steps_completed.push(flow.current_step);
  }
  if (idx < FLOW_STEPS.length - 1) {
    flow.current_step = FLOW_STEPS[idx + 1];
  } else {
    flow.status = 'completed';
  }
  flow.updated_at = new Date().toISOString();
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
    content_preview: `本合同金额为 ¥${quote.total.toLocaleString()}，包含 CRM 标准版及 AI 模块，有效期 12 个月。`,
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

export function getSalesPerformance(period = 'month'): SalesPerformance {
  return {
    period,
    revenue_target: 500000,
    revenue_actual: 342000,
    completion_rate: 68.4,
    deals_closed: 12,
    avg_deal_size: 28500,
    goals: [
      {
        id: 'g1',
        title: 'Q2 签约目标',
        target: 30,
        actual: 12,
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
