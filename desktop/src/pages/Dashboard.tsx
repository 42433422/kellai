import { useNavigate } from 'react-router-dom';
import { Clock, MessageCircle, Sparkles, Layers } from 'lucide-react';
import { useApiQuery } from '../hooks/useApiQuery';
import { getReminders, getRecentMessages, getFunnelSummary } from '../api/dashboard';
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
    (s) => s.id === 'no_contact' || s.id === 'new' || s.id === 'lead'
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
  tone?: 'blue' | 'cyan' | 'indigo' | 'amber';
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
  // 漏斗里"累计客户数"——KpiTile 用这个做大数字
  const funnelTotalClients = funnelStages.reduce((sum, s) => sum + (s.count ?? 0), 0);

  /* ---- 渲染 ---- */
  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">工作台</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          欢迎回来，这是您的业务概览
        </p>
      </div>

      {/* 4 个等权重方形 KpiTile：
          - 今日待办 / 线索动态 / 漏斗概览 / AI 建议
          - 都只显示关键数字 + 入口，不在 dashboard 展开
          - 一行 4 个 (lg+)，两行 2 个 (sm)，叠成 1 列 (<sm)
          - 整页不滚动
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
    </div>
  );
}
