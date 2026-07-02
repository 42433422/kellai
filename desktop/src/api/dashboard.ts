import api from './client';

export { getReminders, type FollowUpReminder } from './ai';

/** 获取最近消息 / 线索动态 */
export const getRecentMessages = async (limit = 10) => {
  await api.post('/api/kellai/channels/sync-inbox', { limit }, { skipErrorToast: true, skipLoading: true }).catch(() => undefined);
  return api.get('/api/kellai/messages', { params: { limit } });
};

/** 漏斗阶段概览（与 Dashboard.tsx 一致） */
interface FunnelStage {
  id: string;
  name: string;
  count: number;
  percentage: number;
}

/** 漏斗概览响应（后端返回对象，包含 stages 数组） */
interface FunnelSummaryResponse {
  stages?: Array<{ id: string; name: string; count: number; percentage?: number }>;
  stage_definitions?: Array<{ id: string; label: string; count: number }>;
  total_clients?: number;
  counts?: Record<string, number>;
}

/** 标准化漏斗阶段：将后端返回的对象转换为前端需要的 FunnelStage[] */
function normalizeFunnelStages(data: unknown): FunnelStage[] {
  if (!data || typeof data !== 'object') return [];

  const d = data as FunnelSummaryResponse;

  // 后端返回 { stages: [...] }
  if (Array.isArray(d.stages)) {
    return d.stages.map((s) => ({
      id: s.id,
      name: s.name || s.id,
      count: s.count ?? 0,
      percentage: s.percentage ?? 0,
    }));
  }

  // 后端返回 { stage_definitions: [...] }
  if (Array.isArray(d.stage_definitions)) {
    return d.stage_definitions.map((s) => ({
      id: s.id,
      name: s.label || s.id,
      count: s.count ?? 0,
      percentage: 0,
    }));
  }

  // 如果数据本身是数组（防御性编程）
  if (Array.isArray(data)) {
    return (data as Array<{ id: string; name: string; count: number; percentage?: number }>).map((s) => ({
      id: s.id,
      name: s.name || s.id,
      count: s.count ?? 0,
      percentage: s.percentage ?? 0,
    }));
  }

  return [];
}

/** 获取漏斗概览数据 */
export const getFunnelSummary = () =>
  api.get('/api/kellai/pipeline/funnel');

/** 演示：模拟客户行为并跑完整闭环 */
export const simulateCustomerBehavior = (count = 5) =>
  api.post('/api/kellai/demo/simulate-customer-behavior', { count });

export interface CustomerBehaviorSimulationResult {
  created: number;
  scenario_set: string;
  passed: boolean;
  summary: {
    total: number;
    passed: number;
    failed: number;
    synced: number;
  };
  scenario_results: Array<{
    key: string;
    label: string;
    channel_type: string;
    stored_channel: string;
    customer_id: number;
    expected_stage: string;
    final_stage: string;
    stage_label: string;
    ai_score: number;
    next_action: string;
    passed: boolean;
  }>;
}

export interface LLMFullFlowTestResult {
  simulation_id: string;
  mode: 'llm' | 'scripted_fallback' | 'llm_required_not_ready';
  llm_ready: boolean;
  llm_used: boolean;
  llm_customer_turns?: number;
  llm_agent_turns?: number;
  provider: string;
  model: string;
  customer_id: number;
  contact_name: string;
  channel_type: string;
  turns_run: number;
  target_stage: string;
  target_stage_label: string;
  final_stage: string;
  final_stage_label: string;
  ai_score: number;
  next_action: string;
  passed: boolean;
  failure_reason?: string;
  summary: string;
  assertions: Array<{ key: string; label: string; passed: boolean; required: boolean; value?: unknown }>;
}

export interface ClosedLoopAuditResult {
  audit_id: string;
  passed: boolean;
  require_llm: boolean;
  target_stage: string;
  target_stage_label: string;
  checked_at: string;
  summary: {
    total: number;
    passed: number;
    failed_required: number;
    skipped_optional: number;
  };
  llm_status: {
    provider?: string;
    model?: string;
    ready?: boolean;
    connected?: boolean;
    message?: string;
  };
  benchmark_profile?: {
    name: string;
    summary: {
      total: number;
      passed: number;
      failed_required: number;
      skipped_optional: number;
    };
    dimensions: Array<{
      key: string;
      label: string;
      required: boolean;
      passed: boolean;
      evidence_keys?: string[];
    }>;
    failed_required_labels?: string[];
  };
  audit_customer_id: number;
  failure_reason?: string;
  checks: Array<{
    key: string;
    label: string;
    status: 'passed' | 'failed' | 'skipped';
    passed: boolean;
    required: boolean;
    details?: Record<string, unknown>;
  }>;
}

/** LLM 全流程客户模拟测试：客户多轮进线 + 销售回复 + 漏斗断言 */
export const runLlmFullFlowTest = (payload?: {
  turns?: number;
  target_stage?: string;
  channel_type?: string;
  scenario?: string;
  use_llm?: boolean;
  auto_reply?: boolean;
  require_llm?: boolean;
}) =>
  api.post('/api/kellai/demo/llm-full-flow-test', {
    turns: 5,
    target_stage: 'signed',
    channel_type: 'douyin',
    use_llm: true,
    auto_reply: true,
    require_llm: true,
    ...(payload ?? {}),
  });

/** 产品级功能闭环验收：客户、消息、AI、漏斗、渠道、运营和真实 LLM 成交链路 */
export const runClosedLoopAudit = (payload?: {
  require_llm?: boolean;
  target_stage?: string;
}) =>
  api.post('/api/kellai/demo/closed-loop-audit', {
    require_llm: true,
    target_stage: 'signed',
    ...(payload ?? {}),
  });

/** 读取最近一次产品级功能闭环验收报告，页面刷新后仍可复核交付状态 */
export const getLatestClosedLoopAudit = () =>
  api.get('/api/kellai/demo/closed-loop-audit/latest', { skipErrorToast: true });

export { normalizeFunnelStages };
