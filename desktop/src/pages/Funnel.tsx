import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter, LayoutGrid, GitBranch } from 'lucide-react';
import { clsx } from 'clsx';
import ChannelLogo from '../components/ChannelLogo';
import SimpleBarChart from '../components/SimpleBarChart';
import type { FunnelStage, ClientSummary, FunnelTrace } from '../types';
import { getFunnelData, updatePipelineStage } from '../api/funnel';
import { getFunnelTrace } from '../api/sales';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { toastStore } from '../stores/toast';

/** 漏斗阶段定义（从左到右） */
const STAGE_ORDER = [
  { id: 'no_contact', label: '未接触' },
  { id: 'connected', label: '已建联' },
  { id: 'requirement', label: '需求采集' },
  { id: 'submitted', label: '已提交' },
  { id: 'quoted', label: '已报价' },
  { id: 'negotiating', label: '议价' },
  { id: 'pending_sign', label: '待签' },
  { id: 'signed', label: '已签' },
  { id: 'delivering', label: '交付中' },
  { id: 'delivered', label: '已交付' },
];

/** 渠道来源图标映射 */
const CHANNEL_ICONS: Record<string, { label: string }> = {
  wework: { label: '企微' },
  phone: { label: '电话' },
  douyin: { label: '抖音' },
  miniapp: { label: '小程序' },
  pdd: { label: '拼多多' },
  taobao: { label: '淘宝' },
  jd: { label: '京东' },
  alibaba: { label: '1688' },
  whatsapp: { label: 'WhatsApp' },
  telegram: { label: 'Telegram' },
  line: { label: 'LINE' },
  email: { label: '邮件' },
  sms: { label: '短信' },
  web: { label: '网页' },
};

/** AI 评分颜色类名：红→黄→绿 */
function getScoreColor(score: number): string {
  if (score < 0.4) return 'text-red-500';
  if (score < 0.7) return 'text-yellow-500';
  return 'text-green-500';
}

/** AI 评分条背景渐变 */
function getScoreGradient(score: number): string {
  if (score < 0.4) return 'linear-gradient(90deg, #ef4444, #f97316)';
  if (score < 0.7) return 'linear-gradient(90deg, #f97316, #eab308)';
  return 'linear-gradient(90deg, #eab308, #22c55e)';
}

/** 骨架屏卡片 */
function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-lg bg-white p-3 shadow-sm dark:bg-slate-800">
      <div className="h-4 w-3/4 rounded bg-gray-200 dark:bg-slate-700" />
      <div className="mt-2 h-2 w-full rounded bg-gray-100 dark:bg-slate-700/60" />
      <div className="mt-2 h-3 w-1/2 rounded bg-gray-100 dark:bg-slate-700/60" />
      <div className="mt-2 flex gap-1">
        <div className="h-4 w-10 rounded bg-gray-100 dark:bg-slate-700/60" />
        <div className="h-4 w-10 rounded bg-gray-100 dark:bg-slate-700/60" />
      </div>
    </div>
  );
}

/** 骨架屏列 */
function SkeletonColumn() {
  return (
    <div className="w-[280px] shrink-0 rounded-lg bg-gray-50 p-3 dark:bg-slate-800/50">
      <div className="mb-3 flex items-center justify-between">
        <div className="h-4 w-20 animate-pulse rounded bg-gray-200 dark:bg-slate-700" />
        <div className="h-5 w-6 animate-pulse rounded-full bg-gray-200 dark:bg-slate-700" />
      </div>
      <div className="space-y-2">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}

/** 可拖拽的客户卡片 */
function DraggableClientCard({ client }: { client: ClientSummary }) {
  const [dragging, setDragging] = useState(false);
  const navigate = useNavigate();

  const handleDragStart = (e: React.DragEvent) => {
    setDragging(true);
    // 通过 dataTransfer 传递客户数据
    e.dataTransfer.setData('application/json', JSON.stringify(client));
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragEnd = () => {
    setDragging(false);
  };

  return (
    <div
      draggable
      role="article"
      data-customer-id={client.customer_id}
      aria-label={`客户卡片：${client.display_name || client.username}`}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      className={clsx(
        'cursor-grab rounded-lg bg-white p-3 shadow-sm transition-all hover:shadow-md active:cursor-grabbing dark:bg-slate-800 dark:shadow-none dark:hover:bg-slate-700',
        dragging && 'opacity-50'
      )}
    >
      {/* 客户名称（可点击跳转详情） */}
      <button
        onClick={() => navigate(`/customers/${client.customer_id}`)}
        aria-label={`查看客户 ${client.display_name || client.username} 详情`}
        className="text-left text-sm font-bold text-gray-900 hover:text-blue-600 hover:underline dark:text-slate-100 dark:hover:text-blue-400"
      >
        {client.display_name || client.username}
      </button>

      {/* AI 评分条 */}
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.max(client.ai_score * 100, 2)}%`,
              background: getScoreGradient(client.ai_score),
            }}
          />
        </div>
        <span className={clsx('text-[10px] font-medium', getScoreColor(client.ai_score))}>
          {Math.round(client.ai_score * 100)}
        </span>
      </div>

      {/* 最近动态（一行灰色小字，截断显示） */}
      {client.last_message_preview && (
        <p className="mt-1 truncate text-xs text-gray-400 dark:text-slate-500">
          {client.last_message_preview}
        </p>
      )}

      {/* 底部：渠道来源图标 + AI 标签 */}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex gap-1">
          {client.channel_sources?.slice(0, 3).map((ch) => {
            const chInfo = CHANNEL_ICONS[ch];
            if (!chInfo) return null;
            return (
              <span key={ch} title={chInfo.label} className="text-gray-400 hover:text-gray-600 dark:text-slate-500 dark:hover:text-slate-300">
                <ChannelLogo type={ch} size={12} />
              </span>
            );
          })}
        </div>
        <div className="flex gap-1">
          {client.ai_tags?.slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-600 dark:bg-blue-500/20 dark:text-blue-300"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * 漏斗看板主页面
 * 使用 React Query 加载漏斗数据 + useMutation 更新阶段
 */
export default function Funnel() {
  const queryClient = useQueryClient();
  const [viewMode, setViewMode] = useState<'board' | 'trace'>('board');
  const [searchText, setSearchText] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [scoreFilter, setScoreFilter] = useState('');
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);

  // 监听新手教程的"漏斗移动"事件，强制重新拉取漏斗数据，
  // 保证 demo 调用的 stage 变更能立即反映在 UI 上
  useEffect(() => {
    const onMove = () => {
      queryClient.invalidateQueries({ queryKey: ['funnel', 'data'] });
    };
    window.addEventListener("kellai:onboarding:funnel-moved", onMove as EventListener);
    return () => window.removeEventListener("kellai:onboarding:funnel-moved", onMove as EventListener);
  }, [queryClient]);

  /* ---- React Query：获取漏斗数据 ---- */
  const {
    data: stages = [],
    isLoading: loading,
    isError,
  } = useApiQuery<FunnelStage[]>(
    ['funnel', 'data'],
    async () => {
      const res = await getFunnelData(50);
      const data = unwrap<FunnelStage[] | { stages: FunnelStage[] }>(res);
      if (Array.isArray(data)) return data;
      if (data && Array.isArray((data as { stages: FunnelStage[] }).stages)) {
        return (data as { stages: FunnelStage[] }).stages;
      }
      // API 未返回数据时使用空阶段结构
      return STAGE_ORDER.map((s) => ({
        id: s.id,
        label: s.label,
        count: 0,
        clients: [],
      }));
    },
    {
      // 失败时也使用空结构，不抛错
      retry: false,
    }
  );

  const traceQuery = useApiQuery<FunnelTrace>(
    ['sales', 'funnel-trace'],
    () => getFunnelTrace(),
    { enabled: viewMode === 'trace' }
  );

  /* ---- React Query Mutation：更新客户阶段 ---- */
  const updateStageMutation = useApiMutation<
    unknown,
    { customerId: number; targetStageId: string; client: ClientSummary; sourceStageId: string; previousStages: FunnelStage[] }
  >(
    ({ customerId, targetStageId }) => updatePipelineStage(customerId, targetStageId),
    {
      onSuccess: (_data, vars) => {
        const targetLabel =
          STAGE_ORDER.find((s) => s.id === vars.targetStageId)?.label ?? vars.targetStageId;
        toastStore.success(`已移至「${targetLabel}」阶段`);
        // 重新拉取最新漏斗数据，确保与服务器一致
        queryClient.invalidateQueries({ queryKey: ['funnel', 'data'] });
      },
      onError: (_err, _vars, context) => {
        // 回滚乐观更新
        const previous = (context as { previousStages?: FunnelStage[] } | undefined)?.previousStages;
        if (previous) {
          queryClient.setQueryData(['funnel', 'data'], previous);
        }
        toastStore.error('移动失败，请重试');
      },
    }
  );

  /** 构建每列的客户列表（应用搜索和筛选） */
  const getFilteredClients = useCallback(
    (stageId: string): ClientSummary[] => {
      const stage = stages.find((s) => s.id === stageId);
      if (!stage) return [];

      return stage.clients.filter((c) => {
        // 搜索过滤
        if (searchText) {
          const keyword = searchText.toLowerCase();
          const name = (c.display_name || c.username).toLowerCase();
          if (!name.includes(keyword)) return false;
        }
        // 渠道过滤
        if (channelFilter && !(c.channel_sources || []).includes(channelFilter)) return false;
        // AI 评分过滤
        if (scoreFilter === 'high' && c.ai_score < 0.7) return false;
        if (scoreFilter === 'mid' && (c.ai_score < 0.4 || c.ai_score >= 0.7)) return false;
        if (scoreFilter === 'low' && c.ai_score >= 0.4) return false;
        return true;
      });
    },
    [stages, searchText, channelFilter, scoreFilter]
  );

  /** 拖拽经过 */
  const handleDragOver = useCallback((e: React.DragEvent, stageId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverStage(stageId);
  }, []);

  /** 拖拽离开 */
  const handleDragLeave = useCallback(() => {
    setDragOverStage(null);
  }, []);

  /** 放置客户到新阶段 */
  const handleDrop = useCallback(
    (e: React.DragEvent, targetStageId: string) => {
      e.preventDefault();
      setDragOverStage(null);

      // 从 dataTransfer 读取客户数据
      let client: ClientSummary | null = null;
      try {
        const raw = e.dataTransfer.getData('application/json');
        if (raw) client = JSON.parse(raw);
      } catch {
        /* 忽略解析错误 */
      }

      if (!client) return;
      // 拖到同一阶段，忽略
      if (client.stage === targetStageId) return;

      const sourceStageId = client.stage;
      // 乐观更新：先更新本地状态
      const previousStages = queryClient.getQueryData<FunnelStage[]>(['funnel', 'data']) ?? stages;
      queryClient.setQueryData<FunnelStage[]>(['funnel', 'data'], (prev) => {
        const base = prev ?? previousStages;
        return base.map((stage) => {
          if (stage.id === sourceStageId) {
            return {
              ...stage,
              count: Math.max(stage.count - 1, 0),
              clients: stage.clients.filter((c) => c.customer_id !== client!.customer_id),
            };
          }
          if (stage.id === targetStageId) {
            return {
              ...stage,
              count: stage.count + 1,
              clients: [...stage.clients, { ...client!, stage: targetStageId }],
            };
          }
          return stage;
        });
      });

      // 触发 mutation
      updateStageMutation.mutate({
        customerId: client.customer_id,
        targetStageId,
        client,
        sourceStageId,
        previousStages,
      });
    },
    [queryClient, stages, updateStageMutation]
  );

  return (
    <div className="flex h-full flex-col">
      {/* 视图切换 */}
      <div className="mb-4 flex gap-2">
        <button
          type="button"
          onClick={() => setViewMode('board')}
          className={clsx(
            'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
            viewMode === 'board' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 dark:bg-slate-800 dark:text-slate-300'
          )}
        >
          <LayoutGrid className="h-4 w-4" /> 看板视图
        </button>
        <button
          type="button"
          onClick={() => setViewMode('trace')}
          className={clsx(
            'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
            viewMode === 'trace' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 dark:bg-slate-800 dark:text-slate-300'
          )}
        >
          <GitBranch className="h-4 w-4" /> 全链路追踪
        </button>
      </div>

      {viewMode === 'trace' && traceQuery.data && (
        <div className="mb-4 rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold">线索到成交全链路 · 整体转化率 {traceQuery.data.overall_conversion}%</h3>
          <div className="mb-6 flex flex-wrap gap-4">
            {traceQuery.data.nodes.map((n, i) => (
              <div key={n.stage} className="flex items-center gap-2">
                <div className="rounded-lg bg-blue-50 px-3 py-2 text-sm dark:bg-blue-500/20">
                  <p className="font-medium">{n.stage_label}</p>
                  <p className="text-xs text-gray-500">{new Date(n.timestamp).toLocaleDateString('zh-CN')}</p>
                </div>
                {i < traceQuery.data!.nodes.length - 1 && <span className="text-gray-400">→</span>}
              </div>
            ))}
          </div>
          <SimpleBarChart
            items={traceQuery.data.edges.map((e) => ({
              label: `${e.from_stage} → ${e.to_stage}`,
              value: e.conversion_rate,
            }))}
            unit="%"
          />
        </div>
      )}

      {viewMode === 'board' && (
      <>
      {/* 搜索与筛选栏 */}
      <div className="mb-4 flex items-center gap-3">
        {/* 搜索框 */}
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <Search className="h-4 w-4 text-gray-400 dark:text-slate-500" />
          <input
            type="text"
            placeholder="搜索客户名称..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            aria-label="搜索客户名称"
            className="w-48 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400 dark:text-slate-200 dark:placeholder:text-slate-500"
          />
        </div>

        {/* 渠道来源筛选 */}
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <Filter className="h-4 w-4 text-gray-400 dark:text-slate-500" />
          <select
            value={channelFilter}
            onChange={(e) => setChannelFilter(e.target.value)}
            aria-label="渠道来源筛选"
            className="bg-transparent text-sm text-gray-700 outline-none dark:bg-slate-800 dark:text-slate-200"
          >
            <option value="">全部渠道</option>
            <option value="wework">企微</option>
            <option value="phone">电话</option>
            <option value="douyin">抖音</option>
            <option value="miniapp">小程序</option>
          </select>
        </div>

        {/* AI 评分筛选 */}
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <Filter className="h-4 w-4 text-gray-400 dark:text-slate-500" />
          <select
            value={scoreFilter}
            onChange={(e) => setScoreFilter(e.target.value)}
            aria-label="AI评分筛选"
            className="bg-transparent text-sm text-gray-700 outline-none dark:bg-slate-800 dark:text-slate-200"
          >
            <option value="">全部评分</option>
            <option value="high">高 (≥70)</option>
            <option value="mid">中 (40-70)</option>
            <option value="low">低 (&lt;40)</option>
          </select>
        </div>
      </div>

      {/* 看板区域：水平滚动（新手教程锚点） */}
      <div data-tour="funnel-board" className="flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex gap-3 pb-4" style={{ minWidth: STAGE_ORDER.length * 296 }}>
          {loading
            ? STAGE_ORDER.map((s) => <SkeletonColumn key={s.id} />)
            : STAGE_ORDER.map((stageDef) => {
                const clients = getFilteredClients(stageDef.id);
                return (
                  <div
                    key={stageDef.id}
                    data-stage-id={stageDef.id}
                    onDragOver={(e) => handleDragOver(e, stageDef.id)}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleDrop(e, stageDef.id)}
                    className={clsx(
                      'w-[280px] shrink-0 rounded-lg p-3 transition-colors',
                      dragOverStage === stageDef.id
                        ? 'border-2 border-dashed border-blue-400 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-500/10'
                        : 'bg-gray-50/80 dark:bg-slate-800/40'
                    )}
                  >
                    {/* 列头：阶段名 + 客户数量 */}
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-sm font-semibold text-gray-700 dark:text-slate-200">
                        {stageDef.label}
                      </span>
                      <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-slate-700 dark:text-slate-300">
                        {clients.length}
                      </span>
                    </div>

                    {/* 客户卡片列表，可滚动 */}
                    <div className="max-h-[calc(100vh-220px)] space-y-2 overflow-y-auto pr-1">
                      {clients.map((client) => (
                        <DraggableClientCard key={client.customer_id} client={client} />
                      ))}
                      {clients.length === 0 && (
                        <div className="rounded-lg border-2 border-dashed border-gray-200 py-6 text-center text-xs text-gray-400 dark:border-slate-700 dark:text-slate-500">
                          {isError ? '加载失败' : '暂无客户'}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
        </div>
      </div>
      </>
      )}
    </div>
  );
}

/**
 * 后端响应解包：可能是 AxiosResponse / ApiResponse / 原始数据
 */
function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'data' in (payload as Record<string, unknown>)) {
    const inner = (payload as { data: unknown }).data;
    if (inner && typeof inner === 'object' && 'data' in (inner as Record<string, unknown>)) {
      return (inner as { data: T }).data;
    }
    return inner as T;
  }
  return payload as T;
}
