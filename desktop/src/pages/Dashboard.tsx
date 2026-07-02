import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Clock, MessageCircle, Sparkles, Layers, Handshake, TrendingUp, Users, Timer, PlayCircle, Loader2, ClipboardCheck, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { useApiMutation, useApiQuery, useQueryClient } from '../hooks/useApiQuery';
import {
  getReminders,
  getRecentMessages,
  getFunnelSummary,
  simulateCustomerBehavior,
  runLlmFullFlowTest,
  runClosedLoopAudit,
  getLatestClosedLoopAudit,
  type CustomerBehaviorSimulationResult,
  type LLMFullFlowTestResult,
  type ClosedLoopAuditResult,
} from '../api/dashboard';
import { toastStore } from '../stores/toast';
import { useAdvancedPanelStore } from '../stores/advancedPanel';
import { unwrapApiResponse } from '../utils/format';
import type { FollowUpReminder } from '../api/ai';

/* ---------- 类型定义 ---------- */

/** 待办 / AI 提醒项 */
interface ReminderItem {
  id: string;
  customerId: string;
  customerName: string;
  stage: string;
  lastFollowUpAt: string;
  suggestedAction: string;
}

/** 消息 / 线索动态项 */
interface MessageItem {
  id: string;
  content: string;
  channelType: string;
  customerName: string;
  createdAt: string;
}

/** 漏斗阶段概览 */
interface FunnelStage {
  id: string;
  name: string;
  count: number;
  percentage: number;
}

/** AI 建议项（独立数据源） */
interface AISuggestion {
  id: string;
  title: string;
  description: string;
  customerName?: string;
  priority: 'high' | 'medium' | 'low';
  action: string;
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function formatAuditCheckDetail(item: ClosedLoopAuditResult['checks'][number]): string {
  if (item.passed) return '';
  const details = item.details ?? {};
  const parts: string[] = [];
  const probeError = asText(details.probe_error);
  const failureReason = asText(details.failure_reason);
  const message = asText(details.message);
  const mode = asText(details.mode);
  const finalStage = asText(details.final_stage);
  const customerTurns = asText(details.llm_customer_turns);
  const agentTurns = asText(details.llm_agent_turns);

  if (probeError) parts.push(`探测失败：${probeError}`);
  if (failureReason && failureReason !== probeError) parts.push(`原因：${failureReason}`);
  if (message && !parts.some((part) => part.includes(message))) parts.push(`状态：${message}`);
  if (mode) parts.push(`模式：${mode}`);
  if (finalStage) parts.push(`最终阶段：${finalStage}`);
  if (customerTurns || agentTurns) parts.push(`LLM 回合：客户 ${customerTurns || '0'} / 销售 ${agentTurns || '0'}`);

  return parts.slice(0, 3).join(' · ');
}

function llmAuditStatusLabel(status?: ClosedLoopAuditResult['llm_status']): string {
  if (status?.connected) return '已连通';
  if (status?.ready) return '未连通';
  return '未配置';
}

/* ========== 主组件 ========== */

/** 基于业务数据生成 AI 建议 */
function generateAISuggestions(reminders: ReminderItem[], funnelStages: FunnelStage[]): AISuggestion[] {
  const suggestions: AISuggestion[] = [];

  // 根据漏斗数据生成建议
  const totalClients = funnelStages.reduce((sum, s) => sum + s.count, 0);
  const lostStage = funnelStages.find((s) => s.id === 'closed_lost' || s.id === 'deal');
  if (lostStage && lostStage.count > 0) {
    const rate = Math.round((lostStage.count / Math.max(totalClients, 1)) * 100);
    suggestions.push({
      id: 'suggestion-winrate',
      title: '成交率分析',
      description: `当前成交率为 ${rate}%，建议重点跟进"已报价"阶段的客户，提供限时优惠方案推动签约。`,
      priority: 'high',
      action: '查看漏斗',
    });
  }

  // 根据待办生成建议
  if (reminders.length > 3) {
    const highPriorityReminders = reminders.slice(0, 2);
    suggestions.push({
      id: 'suggestion-priority',
      title: '优先跟进提醒',
      description: `有 ${reminders.length} 个客户待跟进，建议优先联系 ${highPriorityReminders.map((r) => r.customerName).join('、')}。`,
      priority: 'high',
      action: '去跟进',
    });
  }

  // 根据漏斗阶段分布生成建议
  const earlyStage = funnelStages.filter(
    (s) => s.id === 'idle' || s.id === 'no_contact' || s.id === 'new' || s.id === 'lead'
  );
  const earlyCount = earlyStage.reduce((sum, s) => sum + s.count, 0);
  if (earlyCount > 5) {
    suggestions.push({
      id: 'suggestion-early-stage',
      title: '新线索激活',
      description: `有 ${earlyCount} 个线索处于早期阶段，建议发送欢迎消息并了解需求。`,
      priority: 'medium',
      action: '激活线索',
    });
  }

  // 默认建议
  if (suggestions.length === 0) {
    suggestions.push({
      id: 'suggestion-default-1',
      title: '客户跟进节奏',
      description: '建议保持每 2-3 天与客户沟通一次，避免客户流失。',
      priority: 'low',
      action: '查看客户',
    });
    suggestions.push({
      id: 'suggestion-default-2',
      title: '完善客户画像',
      description: 'AI 画像可以帮助您更好地了解客户需求，提升转化效率。',
      priority: 'low',
      action: '前往 AI 助手',
    });
  }

  return suggestions;
}

/** 正方形快捷入口：图标 + 标题 + 关键数字 + 跳转按钮
 *  用在 dashboard 下方 3 个 tile，展示关键指标，点击跳到对应完整页面
 *  moduleId 透传到 data-module-id，教程 demoDashboard 用它做锚点 */
function KpiTile({
  title,
  icon: Icon,
  metric,
  unit,
  hint,
  to,
  tone = 'blue',
  moduleId,
  dataTour,
}: {
  title: string;
  icon: React.ElementType;
  metric: number | string;
  unit?: string;
  hint?: string;
  to: string;
  tone?: 'blue' | 'cyan' | 'indigo' | 'amber' | 'green' | 'rose' | 'violet' | 'orange';
  /** 透传 data-module-id，新手教程 demoDashboard 靠它定位 */
  moduleId?: string;
  /** 透传 data-tour，旧的教程锚点（如果还有别处用到） */
  dataTour?: string;
}) {
  const navigate = useNavigate();
  // 不同 tone 配不同 icon 背景色 / icon 颜色
  const toneMap: Record<string, { bg: string; icon: string; arrow: string }> = {
    blue:   { bg: 'bg-blue-50',   icon: 'text-blue-600',   arrow: 'text-blue-600' },
    cyan:   { bg: 'bg-cyan-50',   icon: 'text-cyan-600',   arrow: 'text-cyan-600' },
    indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', arrow: 'text-indigo-600' },
    amber:  { bg: 'bg-amber-50',  icon: 'text-amber-600',  arrow: 'text-amber-600' },
    green:  { bg: 'bg-green-50',  icon: 'text-green-600',  arrow: 'text-green-600' },
    rose:   { bg: 'bg-rose-50',   icon: 'text-rose-600',   arrow: 'text-rose-600' },
    violet: { bg: 'bg-violet-50', icon: 'text-violet-600', arrow: 'text-violet-600' },
    orange: { bg: 'bg-orange-50', icon: 'text-orange-600', arrow: 'text-orange-600' },
  };
  const t = toneMap[tone] ?? toneMap.blue!;
  return (
    <button
      type="button"
      onClick={() => navigate(to)}
      data-module-id={moduleId}
      data-tour={dataTour}
      className="group relative flex aspect-square w-full max-w-[200px] mx-auto flex-col items-center justify-center gap-1.5 overflow-hidden rounded-xl border border-gray-200/80 bg-white p-4 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 dark:border-slate-700 dark:bg-slate-800"
      aria-label={`${title}：${metric}${unit ?? ''}，点击查看详情`}
    >
      {/* icon 圆形背景 */}
      <div className={`flex h-10 w-10 items-center justify-center rounded-full ${t.bg} dark:bg-slate-700/50`}>
        <Icon className={`h-5 w-5 ${t.icon} dark:text-slate-200`} />
      </div>
      {/* 标题 */}
      <h3 className="mt-0.5 text-[12px] font-semibold text-gray-700 dark:text-slate-200">
        {title}
      </h3>
      {/* 大数字 + 单位 */}
      <div className="flex items-baseline gap-1">
        <span className="text-[26px] font-bold leading-none tracking-tight text-gray-900 dark:text-white">
          {metric}
        </span>
        {unit && (
          <span className="text-[11px] font-medium text-gray-500 dark:text-slate-400">
            {unit}
          </span>
        )}
      </div>
      {/* 副标题 */}
      {hint && (
        <p className="text-[10px] text-gray-400 dark:text-slate-500">{hint}</p>
      )}
      {/* 底部"打开 →"小字，平时透明，hover 时浮现 */}
      <span
        className={`mt-0.5 text-[10px] font-medium ${t.arrow} opacity-0 transition-opacity duration-150 group-hover:opacity-100`}
      >
        打开详情 →
      </span>
    </button>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [simulationResult, setSimulationResult] = useState<CustomerBehaviorSimulationResult | null>(null);
  const [flowTestResult, setFlowTestResult] = useState<LLMFullFlowTestResult | null>(null);
  const [auditResult, setAuditResult] = useState<ClosedLoopAuditResult | null>(null);
  const [internalToolsEnabled] = useState(() => {
    try {
      return window.localStorage.getItem('kellai:internalTools') === '1';
    } catch {
      return false;
    }
  });
  const advancedOpen = useAdvancedPanelStore((s) => s.open);
  const showInternalTools = advancedOpen && internalToolsEnabled;
  /* ---- React Query 数据获取 ---- */

  // 待办提醒
  const remindersQuery = useApiQuery<ReminderItem[]>(
    ['dashboard', 'reminders'],
    async () => {
      const list = await getReminders();
      // 后端 FollowUpReminder → 业务侧 ReminderItem 字段映射
      return list.map((r: FollowUpReminder) => ({
        id: `reminder-${r.customer_id}`,
        customerId: String(r.customer_id),
        customerName: r.display_name || `客户${r.customer_id}`,
        stage: r.stage,
        lastFollowUpAt: `${r.hours_since_last_contact}h`,
        suggestedAction: r.suggested_action,
      }));
    },
    { retry: 0 }
  );

  // 线索动态
  const messagesQuery = useApiQuery<MessageItem[]>(
    ['dashboard', 'recentMessages'],
    async () => {
      const res = await getRecentMessages(10);
      const data = unwrapApiResponse<MessageItem[] | { items: MessageItem[] }>(res);
      if (Array.isArray(data)) return data;
      if (data && Array.isArray((data as { items: MessageItem[] }).items)) {
        return (data as { items: MessageItem[] }).items;
      }
      return [];
    },
    { retry: 0 }
  );

  // 漏斗概览
  const funnelQuery = useApiQuery<FunnelStage[]>(
    ['dashboard', 'funnelSummary'],
    async () => {
      const res = await getFunnelSummary();
      const data = unwrapApiResponse(res);
      // 后端返回 { stages: [...], total_clients, counts, stage_definitions }
      // 前端期望 FunnelStage[] 数组
      if (!data) return [];
      if (Array.isArray(data)) return data;
      // 提取 stages 数组
      const stages = (data as any)?.stages ?? [];
      return (Array.isArray(stages) ? stages : []).map((s: any, idx: number) => ({
        id: s.id || s.stage || `stage-${idx}`,
        name: s.name || s.label || s.id || s.stage || `阶段 ${idx + 1}`,
        count: s.count ?? 0,
        percentage: s.percentage ?? 0,
      }));
    },
    { retry: 0 }
  );

  const reminders = remindersQuery.data ?? [];
  const messages = messagesQuery.data ?? [];
  const funnelStages = funnelQuery.data ?? [];
  const aiSuggestions = generateAISuggestions(reminders, funnelStages);
  const latestAuditQuery = useApiQuery<ClosedLoopAuditResult | null>(
    ['dashboard', 'closedLoopAudit', 'latest'],
    async () => {
      const res = await getLatestClosedLoopAudit();
      return unwrapApiResponse<ClosedLoopAuditResult | null>(res) ?? null;
    },
    { retry: 0, enabled: showInternalTools }
  );
  const visibleAuditResult = showInternalTools ? auditResult ?? latestAuditQuery.data ?? null : null;
  // 漏斗里"累计客户数"——KpiTile 用这个做大数字
  const funnelTotalClients = funnelStages.reduce((sum, s) => sum + (s.count ?? 0), 0);

  // 签约客户数：signed + closed_won + deal 阶段
  const signedCount = funnelStages
    .filter((s) => ['signed', 'closed_won', 'deal'].includes(s.id))
    .reduce((sum, s) => sum + s.count, 0);

  // 成交率：签约 / 总客户
  const winRate = funnelTotalClients > 0 ? Math.round((signedCount / funnelTotalClients) * 100) : 0;

  // 跟进中：排除未接触和已签约/流失的阶段
  const inProgressStages = [
    'connected',
    'intake',
    'intake_done',
    'requirement',
    'submitted',
    'quoted',
    'negotiating',
    'contract_pending',
    'pending_sign',
    'contacted',
    'interested',
    'intention',
    'proposal',
    'negotiation',
    'qualified',
  ];
  const inProgressCount = funnelStages
    .filter((s) => inProgressStages.includes(s.id))
    .reduce((sum, s) => sum + s.count, 0);

  // 平均跟进时长：从 reminders 的 hours_since_last_contact 取均值
  const avgFollowUpHours = reminders.length > 0
    ? Math.round(reminders.reduce((sum, r) => sum + parseInt(r.lastFollowUpAt) || 0, 0) / reminders.length)
    : 0;

  const simulateMutation = useApiMutation(
    () => simulateCustomerBehavior(5),
    {
      onSuccess: (payload) => {
        const result = unwrapApiResponse<CustomerBehaviorSimulationResult>(payload);
        setSimulationResult(result);
        if (result.passed) {
          toastStore.success(`已生成 ${result.summary.total} 个模拟客户场景`);
        } else {
          toastStore.error(`模拟客户场景 ${result.summary.failed} 项未达预期`);
        }
        queryClient.invalidateQueries({ queryKey: ['dashboard'] });
        queryClient.invalidateQueries({ queryKey: ['messages', 'list'] });
        queryClient.invalidateQueries({ queryKey: ['funnel', 'data'] });
        queryClient.invalidateQueries({ queryKey: ['customers'] });
      },
      onError: () => toastStore.error('模拟客户行为失败'),
    }
  );

  const fullFlowMutation = useApiMutation(
    () => runLlmFullFlowTest({ turns: 5, target_stage: 'signed', use_llm: true, auto_reply: true, require_llm: true }),
    {
      onSuccess: (payload) => {
        const result = unwrapApiResponse<LLMFullFlowTestResult>(payload);
        setFlowTestResult(result);
        if (result.passed) {
          toastStore.success('LLM 全流程测试通过');
        } else {
          toastStore.error(result.failure_reason || 'LLM 全流程测试未通过');
        }
        queryClient.invalidateQueries({ queryKey: ['dashboard'] });
        queryClient.invalidateQueries({ queryKey: ['messages', 'list'] });
        queryClient.invalidateQueries({ queryKey: ['funnel', 'data'] });
        queryClient.invalidateQueries({ queryKey: ['customers'] });
      },
      onError: () => toastStore.error('LLM 全流程测试失败'),
    }
  );

  const auditMutation = useApiMutation(
    () => runClosedLoopAudit({ require_llm: true, target_stage: 'signed' }),
    {
      onSuccess: (payload) => {
        const result = unwrapApiResponse<ClosedLoopAuditResult>(payload);
        setAuditResult(result);
        if (result.passed) {
          toastStore.success('功能闭环验收通过');
        } else {
          toastStore.error(result.failure_reason || '功能闭环验收未通过');
        }
        queryClient.invalidateQueries({ queryKey: ['dashboard'] });
        queryClient.invalidateQueries({ queryKey: ['messages', 'list'] });
        queryClient.invalidateQueries({ queryKey: ['funnel', 'data'] });
        queryClient.invalidateQueries({ queryKey: ['customers'] });
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'closedLoopAudit', 'latest'] });
      },
      onError: () => toastStore.error('功能闭环验收失败'),
    }
  );

  const advancedActionBusy = simulateMutation.isPending || fullFlowMutation.isPending || auditMutation.isPending;
  const topReminder = reminders[0];
  const topSuggestion = aiSuggestions[0];

  /* ---- 渲染 ---- */
  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0" data-tour="dashboard-customer-workbench">
      {/* 页面标题 */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">客户经营工作台</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
            统一查看线索、跟进、漏斗进展和 AI 建议
          </p>
        </div>
      </div>

      {showInternalTools && (
        <div
          data-testid="advanced-function-dock"
          className="fixed bottom-5 left-4 right-4 z-40 flex flex-col gap-2 rounded-xl border border-slate-200 bg-white/95 p-3 shadow-2xl shadow-slate-900/15 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95 dark:shadow-black/30 md:left-[17rem] md:right-auto md:w-[min(92vw,520px)] md:flex-row"
        >
          <button
            type="button"
            onClick={() => simulateMutation.mutate()}
            disabled={advancedActionBusy}
            data-tour="dashboard-simulate-customer"
            data-testid="advanced-simulate-button"
            className="flex min-w-0 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-wait disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
          >
            {simulateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
            模拟客户行为
          </button>
          <button
            type="button"
            onClick={() => auditMutation.mutate()}
            disabled={advancedActionBusy}
            data-testid="advanced-audit-button"
            className="flex min-w-0 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:cursor-wait disabled:text-emerald-300 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300 dark:hover:bg-emerald-950/50"
          >
            {auditMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
            功能闭环验收
          </button>
          <button
            type="button"
            onClick={() => fullFlowMutation.mutate()}
            disabled={advancedActionBusy}
            data-tour="dashboard-llm-full-flow"
            data-testid="advanced-llm-flow-button"
            className="flex min-w-0 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-wait disabled:bg-slate-400 dark:bg-blue-600 dark:hover:bg-blue-500"
          >
            {fullFlowMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            LLM 全流程测试
          </button>
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-blue-600 dark:text-blue-300">今日经营简报</p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                {reminders.length > 0 ? `${reminders.length} 个客户需要跟进` : '客户跟进节奏正常'}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
                当前累计 {funnelTotalClients} 位客户，{inProgressCount} 位正在推进，已签约 {signedCount} 位。
                {topReminder ? ` 建议优先处理 ${topReminder.customerName}：${topReminder.suggestedAction}` : ' 可以继续查看漏斗和消息动态。'}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <button
                type="button"
                onClick={() => navigate('/messages')}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
              >
                查看消息
              </button>
              <button
                type="button"
                onClick={() => navigate('/funnel')}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                查看漏斗
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-5 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/20">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-amber-600 shadow-sm ring-1 ring-amber-200 dark:bg-slate-900 dark:ring-amber-900/70">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-950 dark:text-white">{topSuggestion?.title || 'AI 建议'}</p>
              <p className="mt-1 text-sm leading-6 text-slate-700 dark:text-slate-300">
                {topSuggestion?.description || 'AI 会根据客户阶段、消息内容和跟进节奏生成下一步动作。'}
              </p>
              <button
                type="button"
                onClick={() => navigate('/ai')}
                className="mt-3 text-sm font-medium text-amber-700 hover:text-amber-800 dark:text-amber-300 dark:hover:text-amber-200"
              >
                查看 AI 助手
              </button>
            </div>
          </div>
        </div>
      </section>

      {showInternalTools && simulationResult && (
        <div
          className={`rounded-xl border p-4 shadow-sm ${
            simulationResult.passed
              ? 'border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/60 dark:bg-emerald-950/30'
              : 'border-amber-200 bg-amber-50/80 dark:border-amber-900/60 dark:bg-amber-950/30'
          }`}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                {simulationResult.passed ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                )}
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  模拟客户行为{simulationResult.passed ? '通过' : '部分未达预期'}
                </h2>
              </div>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                已生成 {simulationResult.created} 条进线，覆盖 {simulationResult.summary.total} 个真实客户场景，通过 {simulationResult.summary.passed} 个。
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/messages')}
              className="w-fit rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 transition-colors hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700"
            >
              查看消息
            </button>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {simulationResult.scenario_results.map((item) => (
              <div
                key={item.key}
                className="rounded-lg bg-white/80 px-3 py-2 text-sm ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-700"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate font-medium text-slate-900 dark:text-slate-100">{item.label}</p>
                  {item.passed ? (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle className="h-4 w-4 shrink-0 text-amber-600" />
                  )}
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {item.channel_type} · 期望 {item.expected_stage} · 实际 {item.stage_label || item.final_stage}
                </p>
                <p className="mt-1 truncate text-xs text-slate-600 dark:text-slate-300">
                  #{item.customer_id || 0} · {Math.round((item.ai_score || 0) * 100)}% · {item.next_action || '未生成动作'}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {showInternalTools && flowTestResult && (
        <div
          className={`rounded-xl border p-4 shadow-sm ${
            flowTestResult.passed
              ? 'border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/60 dark:bg-emerald-950/30'
              : 'border-amber-200 bg-amber-50/80 dark:border-amber-900/60 dark:bg-amber-950/30'
          }`}
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Sparkles className={`h-4 w-4 ${flowTestResult.passed ? 'text-emerald-600' : 'text-amber-600'}`} />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  LLM 全流程测试{flowTestResult.passed ? '通过' : '未通过'}
                </h2>
              </div>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                {flowTestResult.summary}
              </p>
              {flowTestResult.failure_reason && (
                <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                  失败原因：{flowTestResult.failure_reason}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => navigate('/messages')}
              className="w-fit rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 transition-colors hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700"
            >
              查看对话
            </button>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">客户</p>
              <p className="font-medium text-slate-900 dark:text-slate-100">#{flowTestResult.customer_id}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">最终阶段</p>
              <p className="font-medium text-slate-900 dark:text-slate-100">{flowTestResult.final_stage_label}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">AI 分数</p>
              <p className="font-medium text-slate-900 dark:text-slate-100">{Math.round(flowTestResult.ai_score * 100)}%</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">LLM</p>
              <p className="font-medium text-slate-900 dark:text-slate-100">
                {flowTestResult.llm_used ? flowTestResult.provider || '已启用' : flowTestResult.llm_ready ? '未命中' : '未配置'}
              </p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300">
            <span className="rounded-full bg-white px-2 py-1 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
              客户 LLM 回合：{flowTestResult.llm_customer_turns ?? 0}
            </span>
            <span className="rounded-full bg-white px-2 py-1 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
              销售 LLM 回合：{flowTestResult.llm_agent_turns ?? 0}
            </span>
          </div>
        </div>
      )}

      {showInternalTools && visibleAuditResult && (
        <div
          className={`rounded-xl border p-4 shadow-sm ${
            visibleAuditResult.passed
              ? 'border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/60 dark:bg-emerald-950/30'
              : 'border-rose-200 bg-rose-50/80 dark:border-rose-900/60 dark:bg-rose-950/30'
          }`}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                {visibleAuditResult.passed ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-rose-600" />
                )}
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  功能闭环验收{visibleAuditResult.passed ? '通过' : '未通过'}
                </h2>
              </div>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                已检查 {visibleAuditResult.summary.total} 项，通过 {visibleAuditResult.summary.passed} 项，关键失败 {visibleAuditResult.summary.failed_required} 项。
              </p>
              {visibleAuditResult.failure_reason && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <p className="text-xs font-medium text-rose-700 dark:text-rose-300">
                    失败项：{visibleAuditResult.failure_reason}
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate('/settings?tab=ai')}
                    className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 dark:border-rose-900/60 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-rose-950/30"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    打开 AI 设置
                  </button>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 dark:text-slate-300 sm:grid-cols-4">
              <span className="rounded-lg bg-white px-2.5 py-2 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
                客户 #{visibleAuditResult.audit_customer_id || 0}
              </span>
              <span className="rounded-lg bg-white px-2.5 py-2 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
                目标 {visibleAuditResult.target_stage_label}
              </span>
              <span className="rounded-lg bg-white px-2.5 py-2 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
                LLM {llmAuditStatusLabel(visibleAuditResult.llm_status)}
              </span>
              <span className="rounded-lg bg-white px-2.5 py-2 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
                可选跳过 {visibleAuditResult.summary.skipped_optional}
              </span>
            </div>
          </div>
          {visibleAuditResult.benchmark_profile && (
            <div className="mt-4 rounded-lg bg-white/80 px-3 py-3 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-700">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {visibleAuditResult.benchmark_profile.name}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    对标覆盖 {visibleAuditResult.benchmark_profile.summary.passed}/{visibleAuditResult.benchmark_profile.summary.total}，关键缺口 {visibleAuditResult.benchmark_profile.summary.failed_required}
                  </p>
                </div>
                {visibleAuditResult.benchmark_profile.failed_required_labels?.length ? (
                  <span className="w-fit rounded-full bg-rose-100 px-2.5 py-1 text-xs font-medium text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">
                    缺口：{visibleAuditResult.benchmark_profile.failed_required_labels.join('、')}
                  </span>
                ) : (
                  <span className="w-fit rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                    对标通过
                  </span>
                )}
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {visibleAuditResult.benchmark_profile.dimensions.map((item) => (
                  <div
                    key={item.key}
                    className="flex items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-2 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    {item.passed ? (
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 shrink-0 text-rose-600" />
                    )}
                    <span className="min-w-0 truncate">{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {visibleAuditResult.checks.map((item) => {
              const detail = formatAuditCheckDetail(item);
              return (
                <div
                  key={item.key}
                  className="flex items-start gap-2 rounded-lg bg-white/80 px-3 py-2 text-sm ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-700"
                >
                  {item.passed ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : item.required ? (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                  ) : (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                  )}
                  <div className="min-w-0">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{item.label}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {item.required ? '关键项' : '可选项'} · {item.status}
                    </p>
                    {detail && (
                      <p className="mt-1 text-xs leading-relaxed text-rose-700 dark:text-rose-300">
                        {detail}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 4 个等权重方形 KpiTile：
          - 今日待办 / 线索动态 / 漏斗概览 / AI 建议
          - 都只显示关键数字 + 入口，不在 dashboard 展开
          - 一行 4 个 (lg+)，两行 2 个 (sm)，叠成 1 列 (<sm)
          每个 tile 带 data-module-id，给教程 demoDashboard 当锚点 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          title="今日待办"
          icon={Clock}
          metric={reminders.length}
          unit="条"
          hint="待跟进客户"
          to="/customers"
          tone="blue"
          moduleId="dashboard-todo"
          dataTour="dashboard-todo"
        />
        <KpiTile
          title="线索动态"
          icon={MessageCircle}
          metric={messages.length}
          unit="条"
          hint="近 24h 互动"
          to="/messages"
          tone="cyan"
          moduleId="dashboard-messages"
          dataTour="dashboard-messages"
        />
        <KpiTile
          title="漏斗概览"
          icon={Layers}
          metric={funnelTotalClients}
          unit="位"
          hint={`${funnelStages.length} 个阶段`}
          to="/funnel"
          tone="indigo"
          moduleId="dashboard-funnel"
          dataTour="dashboard-funnel"
        />
        <KpiTile
          title="AI 建议"
          icon={Sparkles}
          metric={aiSuggestions.length}
          unit="条"
          hint="智能提醒"
          to="/ai"
          tone="amber"
          moduleId="dashboard-ai"
          dataTour="dashboard-ai"
        />
      </div>

      {/* 第二行 4 个 KpiTile：签约 / 成交率 / 跟进中 / 平均跟进时长 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          title="签约客户"
          icon={Handshake}
          metric={signedCount}
          unit="位"
          hint="已签约成交"
          to="/funnel"
          tone="green"
          moduleId="dashboard-signed"
        />
        <KpiTile
          title="成交率"
          icon={TrendingUp}
          metric={winRate}
          unit="%"
          hint="签约/总客户"
          to="/sales/performance"
          tone="rose"
          moduleId="dashboard-winrate"
        />
        <KpiTile
          title="跟进中"
          icon={Users}
          metric={inProgressCount}
          unit="位"
          hint="活跃推进中"
          to="/customers"
          tone="violet"
          moduleId="dashboard-inprogress"
        />
        <KpiTile
          title="平均跟进"
          icon={Timer}
          metric={avgFollowUpHours}
          unit="h"
          hint="距上次跟进"
          to="/ai"
          tone="orange"
          moduleId="dashboard-avgfollowup"
        />
      </div>
    </div>
  );
}
