import { useState, useEffect, useMemo } from 'react';
import {
  Search,
  Star,
  Send,
  Loader2,
  MessageCircle,
  ExternalLink,
  Users,
  MapPin,
  RefreshCw,
  UserPlus,
  Sparkles,
  Radar,
  TrendingUp,
  CheckCircle2,
} from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { scanComments, autoDM, matchScript, getScoutTrace, scoreIntent, convertLead } from '../api/scout';
import { useScoutStore } from '../stores/scoutStore';
import { toastStore } from '../stores/toast';
import { formatTimeAgo } from '../utils/format';
import type { ScoutTarget, ScoutTrace, IntentScore, ScoutLeadStatus } from '../types';

const PLATFORMS = [
  { id: 'all', label: '全部平台' },
  { id: 'douyin', label: '抖音' },
  { id: 'xiaohongshu', label: '小红书' },
  { id: 'weibo', label: '微博' },
  { id: 'kuaishou', label: '快手' },
];

const INTENT_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'high', label: '高意向' },
  { id: 'medium', label: '中意向' },
  { id: 'low', label: '低意向' },
];

const STATUS_META: Record<ScoutLeadStatus, { label: string; tone: string }> = {
  new: { label: '新线索', tone: 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300' },
  contacted: { label: '已触达', tone: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300' },
  replied: { label: '已回复', tone: 'bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300' },
  converted: { label: '已转化', tone: 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300' },
  ignored: { label: '已忽略', tone: 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-slate-400' },
};

function IntentStars({ score }: { score: number }) {
  const level = score >= 70 ? 5 : score >= 55 ? 4 : score >= 40 ? 3 : score >= 25 ? 2 : 1;
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={clsx('h-3.5 w-3.5', i < level ? 'fill-amber-400 text-amber-400' : 'text-gray-300 dark:text-slate-600')} />
      ))}
    </div>
  );
}

export default function ScoutHunter() {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState('');
  const [platform, setPlatform] = useState('all');
  const [intentFilter, setIntentFilter] = useState('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dmMessage, setDmMessage] = useState('');
  const { setHighIntentQueue } = useScoutStore();

  const scanQuery = useApiQuery<ScoutTarget[]>(
    ['scout', 'scan', keyword, platform],
    () => scanComments(keyword || undefined, platform),
    { enabled: true }
  );

  const targets = useMemo(() => scanQuery.data ?? [], [scanQuery.data]);
  const visibleTargets = useMemo(
    () => (intentFilter === 'all' ? targets : targets.filter((t) => t.intent_level === intentFilter)),
    [targets, intentFilter]
  );
  const selected = targets.find((t) => t.id === selectedId) ?? null;

  const intentQuery = useApiQuery<IntentScore>(
    ['scout', 'intent', selected?.id],
    () => scoreIntent(selected!.comment),
    { enabled: !!selected }
  );

  const traceQuery = useApiQuery<ScoutTrace>(
    ['scout', 'trace', selectedId],
    () => getScoutTrace(selectedId!),
    { enabled: !!selectedId }
  );

  const dmMutation = useApiMutation(
    ({ targetId, message }: { targetId: string; message: string }) => autoDM(targetId, message),
    {
      onSuccess: (r) => {
        toastStore.success(r.message);
        queryClient.invalidateQueries({ queryKey: ['scout', 'scan'] });
      },
    }
  );

  const scriptMutation = useApiMutation(
    (comment: string) => matchScript(comment),
    { onSuccess: (r) => { if (r.scripts[0]) setDmMessage(r.scripts[0]); } }
  );

  const convertMutation = useApiMutation(
    (targetId: string) => convertLead(targetId),
    {
      onSuccess: (r) => {
        toastStore.success(r.message);
        queryClient.invalidateQueries({ queryKey: ['scout', 'scan'] });
      },
    }
  );

  // 同步高意向队列（修复旧实现读取 stale 数据的问题）
  useEffect(() => {
    setHighIntentQueue(targets.filter((t) => t.intent_level === 'high'));
  }, [targets, setHighIntentQueue]);

  const stats = useMemo(() => {
    return {
      total: targets.length,
      high: targets.filter((t) => t.intent_level === 'high').length,
      contacted: targets.filter((t) => t.status === 'contacted' || t.status === 'replied').length,
      converted: targets.filter((t) => t.status === 'converted').length,
    };
  }, [targets]);

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">猎手巡检台</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">AI 跨平台扫描评论区，识别并触达高意向客户</p>
      </div>

      <KpiGrid
        cols={4}
        items={[
          { title: '巡检线索', value: stats.total, icon: Radar },
          { title: '高意向', value: stats.high, icon: TrendingUp, trend: { value: `${stats.total ? Math.round((stats.high / stats.total) * 100) : 0}% 占比`, positive: true } },
          { title: '已触达', value: stats.contacted, icon: MessageCircle },
          { title: '已转化', value: stats.converted, icon: CheckCircle2 },
        ]}
      />

      {/* 过滤条 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索关键词 / 行业..."
            className="w-full rounded-lg border py-2 pl-10 pr-4 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        >
          {PLATFORMS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => scanQuery.refetch()}
          disabled={scanQuery.isFetching}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {scanQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          开始巡检
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {INTENT_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setIntentFilter(f.id)}
            className={clsx(
              'rounded-full px-3 py-1 text-xs font-medium transition-colors',
              intentFilter === f.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-300'
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 线索列表 */}
        <div className="space-y-3 lg:col-span-2">
          {scanQuery.isLoading ? (
            <Loading variant="skeleton" rows={4} text="巡检中..." />
          ) : scanQuery.isError ? (
            <Empty title="巡检失败" description="请稍后重试" />
          ) : visibleTargets.length === 0 ? (
            <Empty title="未发现匹配线索" description="尝试更换关键词、平台或意向筛选" />
          ) : (
            visibleTargets.map((t) => (
              <div
                key={t.id}
                onClick={() => setSelectedId(t.id)}
                className={clsx(
                  'cursor-pointer rounded-xl border p-4 transition-colors dark:bg-slate-800',
                  selectedId === t.id ? 'border-blue-500 bg-blue-50/50 dark:border-blue-400' : 'border-gray-200 hover:border-gray-300 dark:border-slate-700'
                )}
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="truncate text-xs text-gray-500">{PLATFORMS.find((p) => p.id === t.platform)?.label ?? t.platform} · {t.post_title}</span>
                  <IntentStars score={t.intent_score} />
                </div>
                <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{t.comment}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                  <span className="font-medium text-gray-600 dark:text-slate-300">@{t.author}</span>
                  {t.followers !== undefined && <span className="flex items-center gap-1"><Users className="h-3 w-3" />{(t.followers / 1000).toFixed(1)}k</span>}
                  {t.region && <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{t.region}</span>}
                  {t.industry && <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-slate-700">{t.industry}</span>}
                  {t.status && <span className={clsx('rounded px-1.5 py-0.5', STATUS_META[t.status].tone)}>{STATUS_META[t.status].label}</span>}
                </div>
                <p className="mt-1.5 text-xs text-gray-400">{t.reason} · {formatTimeAgo(t.scanned_at)}</p>
                <div className="mt-3 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); scriptMutation.mutate(t.comment); setSelectedId(t.id); }}
                    className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                  >
                    匹配话术
                  </button>
                  {t.source_url && (
                    <a
                      href={t.source_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-slate-300"
                    >
                      <ExternalLink className="h-3 w-3" /> 原帖
                    </a>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* 右侧操作面板 */}
        <div className="space-y-4">
          {!selected ? (
            <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-400 dark:border-slate-600">
              选择左侧线索，查看意向分析并触达
            </div>
          ) : (
            <>
              {/* 意向分析 */}
              <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-slate-200">
                  <Sparkles className="h-4 w-4 text-blue-500" /> AI 意向分析
                </h3>
                {intentQuery.isLoading ? (
                  <Loading variant="spinner" size="sm" text="分析中..." />
                ) : intentQuery.data ? (
                  <>
                    <div className="mb-2 flex items-end gap-2">
                      <span className="text-3xl font-bold text-gray-900 dark:text-slate-100">{intentQuery.data.score}</span>
                      <span className="mb-1 text-xs text-gray-400">/ 100</span>
                      <span
                        className={clsx(
                          'mb-1 ml-auto rounded-full px-2 py-0.5 text-xs font-medium',
                          intentQuery.data.level === 'high' ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300'
                            : intentQuery.data.level === 'medium' ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300'
                            : 'bg-gray-100 text-gray-500 dark:bg-slate-700'
                        )}
                      >
                        {intentQuery.data.level === 'high' ? '高意向' : intentQuery.data.level === 'medium' ? '中意向' : '低意向'}
                      </span>
                    </div>
                    {intentQuery.data.keywords.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {intentQuery.data.keywords.map((k) => (
                          <span key={k} className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">{k}</span>
                        ))}
                      </div>
                    )}
                    <p className="text-xs text-gray-500 dark:text-slate-400">{intentQuery.data.reason}</p>
                  </>
                ) : null}
              </div>

              {/* 自动私信 */}
              <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-slate-200">
                  <MessageCircle className="h-4 w-4" /> 自动私信触达
                </h3>
                <textarea
                  value={dmMessage}
                  onChange={(e) => setDmMessage(e.target.value)}
                  rows={4}
                  className="mb-2 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                  placeholder="输入或匹配话术..."
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => scriptMutation.mutate(selected.comment)}
                    disabled={scriptMutation.isPending}
                    className="rounded-lg border px-3 py-2 text-xs hover:bg-gray-50 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
                  >
                    匹配话术
                  </button>
                  <button
                    type="button"
                    onClick={() => dmMutation.mutate({ targetId: selected.id, message: dmMessage })}
                    disabled={!dmMessage || dmMutation.isPending}
                    className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-green-600 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    {dmMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    发送私信
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => convertMutation.mutate(selected.id)}
                  disabled={convertMutation.isPending || selected.status === 'converted'}
                  className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-blue-300 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-500/30 dark:text-blue-300 dark:hover:bg-blue-500/10"
                >
                  <UserPlus className="h-4 w-4" />
                  {selected.status === 'converted' ? '已转入 CRM' : '转入 CRM 客户库'}
                </button>
              </div>

              {/* 来源追踪 */}
              {traceQuery.data && (
                <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                  <h3 className="mb-3 text-sm font-semibold text-gray-700 dark:text-slate-200">来源追踪</h3>
                  <ol className="space-y-2">
                    {traceQuery.data.steps.map((s, i) => (
                      <li key={i} className="border-l-2 border-blue-400 pl-3">
                        <p className="text-sm font-medium text-gray-800 dark:text-slate-200">{s.action}</p>
                        <p className="text-xs text-gray-500">{s.result}</p>
                        <p className="text-[11px] text-gray-400">{formatTimeAgo(s.timestamp)}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
