import { useState, useMemo } from 'react';
import {
  AlertTriangle,
  TrendingUp,
  Users,
  RefreshCw,
  ExternalLink,
  Smile,
  Meh,
  Frown,
  Hash,
  Bell,
  Loader2,
} from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery } from '../hooks/useApiQuery';
import { getSentiment, getSentimentOverview } from '../api/scout';
import { formatTimeAgo } from '../utils/format';
import type { SentimentItem, SentimentOverview } from '../types';

const TYPE_ICONS = { hotspot: TrendingUp, competitor: Users, opportunity: AlertTriangle } as const;
const TYPE_LABEL = { hotspot: '行业热点', competitor: '竞品动态', opportunity: '商机预警' } as const;

const SEVERITY_COLORS = {
  high: 'border-red-300 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10',
  medium: 'border-amber-300 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10',
  low: 'border-gray-200 bg-gray-50 dark:border-slate-700 dark:bg-slate-800',
};

const SENTIMENT_META = {
  positive: { icon: Smile, label: '正面', tone: 'text-green-600 dark:text-green-400' },
  neutral: { icon: Meh, label: '中性', tone: 'text-gray-500 dark:text-slate-400' },
  negative: { icon: Frown, label: '负面', tone: 'text-red-600 dark:text-red-400' },
} as const;

const TYPE_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'hotspot', label: '行业热点' },
  { id: 'competitor', label: '竞品动态' },
  { id: 'opportunity', label: '商机预警' },
];

const SENTIMENT_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'positive', label: '正面' },
  { id: 'neutral', label: '中性' },
  { id: 'negative', label: '负面' },
];

export default function SentimentMonitor() {
  const [typeFilter, setTypeFilter] = useState('all');
  const [sentimentFilter, setSentimentFilter] = useState('all');

  const listQuery = useApiQuery<SentimentItem[]>(['scout', 'sentiment'], () => getSentiment());
  const overviewQuery = useApiQuery<SentimentOverview>(['scout', 'sentiment-overview'], () => getSentimentOverview());

  const items = listQuery.data ?? [];
  const overview = overviewQuery.data;

  const visible = useMemo(
    () =>
      items.filter(
        (i) =>
          (typeFilter === 'all' || i.type === typeFilter) &&
          (sentimentFilter === 'all' || i.sentiment === sentimentFilter)
      ),
    [items, typeFilter, sentimentFilter]
  );

  const trendMax = Math.max(1, ...(overview?.volume_trend ?? []).map((v) => v.count));
  const kwMax = Math.max(1, ...(overview?.top_keywords ?? []).map((k) => k.count));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">舆情监控</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">行业热点、竞品动态、情感分析与商机预警</p>
        </div>
        <button
          type="button"
          onClick={() => { listQuery.refetch(); overviewQuery.refetch(); }}
          disabled={listQuery.isFetching}
          className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          {listQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} 刷新
        </button>
      </div>

      {overview && (
        <>
          <KpiGrid
            cols={4}
            items={[
              { title: '监控声量', value: overview.total.toLocaleString(), icon: TrendingUp, trend: { value: `环比 +${overview.volume_change}%`, positive: true } },
              { title: '正面占比', value: `${overview.positive_pct}%`, icon: Smile, className: 'border-green-200 dark:border-green-500/20' },
              { title: '中性占比', value: `${overview.neutral_pct}%`, icon: Meh },
              { title: '负面占比', value: `${overview.negative_pct}%`, icon: Frown, className: 'border-red-200 dark:border-red-500/20' },
            ]}
          />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* 声量趋势 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800 lg:col-span-2">
              <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">近 7 日声量趋势</h3>
              <div className="flex h-40 items-end justify-around gap-2">
                {overview.volume_trend.map((v) => (
                  <div key={v.date} className="flex flex-1 flex-col items-center gap-1">
                    <div className="flex w-full justify-center">
                      <div className="w-2/3 rounded-t bg-blue-500 transition-all" style={{ height: `${(v.count / trendMax) * 128}px`, minHeight: 4 }} title={`${v.count} 条`} />
                    </div>
                    <span className="text-xs text-gray-500">{v.date}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* 热门关键词 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
                <Hash className="h-4 w-4 text-gray-400" /> 热门关键词
              </h3>
              <div className="space-y-2">
                {overview.top_keywords.map((k) => (
                  <div key={k.word}>
                    <div className="mb-0.5 flex justify-between text-xs">
                      <span className="text-gray-600 dark:text-slate-300">{k.word}</span>
                      <span className="text-gray-400">{k.count}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                      <div className="h-full rounded-full bg-blue-400" style={{ width: `${(k.count / kwMax) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 监控词配置 */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <span className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-slate-200">
              <Bell className="h-4 w-4 text-amber-500" /> 监控词
            </span>
            {overview.watch_terms.map((w) => (
              <span key={w} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-600 dark:bg-slate-700 dark:text-slate-300">
                {w}
              </span>
            ))}
            <button type="button" className="rounded-full border border-dashed border-gray-300 px-2.5 py-1 text-xs text-gray-400 hover:border-blue-400 hover:text-blue-500 dark:border-slate-600">
              + 添加监控词
            </button>
          </div>
        </>
      )}

      {/* 过滤 */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-wrap gap-2">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setTypeFilter(f.id)}
              className={clsx('rounded-full px-3 py-1 text-xs font-medium transition-colors', typeFilter === f.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-300')}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="h-4 w-px bg-gray-200 dark:bg-slate-700" />
        <div className="flex flex-wrap gap-2">
          {SENTIMENT_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setSentimentFilter(f.id)}
              className={clsx('rounded-full px-3 py-1 text-xs font-medium transition-colors', sentimentFilter === f.id ? 'bg-gray-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-300')}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      {listQuery.isLoading ? (
        <Loading variant="skeleton" rows={3} text="加载舆情..." />
      ) : visible.length === 0 ? (
        <Empty title="暂无匹配舆情" description="调整筛选条件试试" />
      ) : (
        <div className="space-y-4">
          {visible.map((item) => {
            const Icon = TYPE_ICONS[item.type];
            const sentiment = item.sentiment ? SENTIMENT_META[item.sentiment] : null;
            const SentimentIcon = sentiment?.icon;
            return (
              <div key={item.id} className={clsx('rounded-xl border p-4', SEVERITY_COLORS[item.severity])}>
                <div className="mb-2 flex items-center gap-2">
                  <Icon className="h-5 w-5 text-gray-500 dark:text-slate-400" />
                  <span className="font-semibold text-gray-900 dark:text-slate-100">{item.title}</span>
                  <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] text-gray-500 dark:bg-slate-700 dark:text-slate-300">{TYPE_LABEL[item.type]}</span>
                  {sentiment && SentimentIcon && (
                    <span className={clsx('flex items-center gap-1 text-xs font-medium', sentiment.tone)}>
                      <SentimentIcon className="h-3.5 w-3.5" /> {sentiment.label}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-gray-400">{formatTimeAgo(item.timestamp)}</span>
                </div>
                <p className="text-sm text-gray-600 dark:text-slate-400">{item.summary}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                  {item.volume !== undefined && (
                    <span>声量 {item.volume.toLocaleString()}{item.volume_change !== undefined && <span className="text-green-600 dark:text-green-400"> (+{item.volume_change}%)</span>}</span>
                  )}
                  {item.source && <span>来源：{item.source}</span>}
                  {item.keywords && item.keywords.map((k) => (
                    <span key={k} className="rounded bg-white/70 px-1.5 py-0.5 dark:bg-slate-700">#{k}</span>
                  ))}
                  {item.url && (
                    <a href={item.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400">
                      <ExternalLink className="h-3 w-3" /> 查看原文
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
