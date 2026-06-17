import { useState, useMemo } from 'react';
import { Star, Download, Loader2, Search, BadgeCheck, Sparkles, Check } from 'lucide-react';
import { clsx } from 'clsx';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { getPlugins, installPlugin } from '../api/openPlatform';
import { toastStore } from '../stores/toast';
import type { Plugin } from '../types';

const CATEGORY_LABEL: Record<string, string> = {
  all: '全部',
  channel: '渠道',
  sales: '销售',
  analytics: '分析',
  service: '售后',
  other: '其他',
};

type SortKey = 'installs' | 'rating' | 'updated';
const SORTS: { id: SortKey; label: string }[] = [
  { id: 'installs', label: '安装量' },
  { id: 'rating', label: '评分' },
  { id: 'updated', label: '最近更新' },
];

export default function PluginMarket() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('installs');
  const [installedOnly, setInstalledOnly] = useState(false);

  const query = useApiQuery<Plugin[]>(['open', 'plugins'], () => getPlugins());

  const installMutation = useApiMutation(
    (id: string) => installPlugin(id),
    {
      onSuccess: () => {
        toastStore.success('插件已安装');
        queryClient.invalidateQueries({ queryKey: ['open', 'plugins'] });
      },
    }
  );

  const all = query.data ?? [];
  const categories = useMemo(() => ['all', ...new Set(all.map((p) => p.category))], [all]);
  const featured = useMemo(() => all.filter((p) => p.featured), [all]);

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return all
      .filter((p) => category === 'all' || p.category === category)
      .filter((p) => !installedOnly || p.installed)
      .filter((p) => !kw || p.name.toLowerCase().includes(kw) || p.description.toLowerCase().includes(kw) || (p.tags ?? []).some((t) => t.toLowerCase().includes(kw)))
      .sort((a, b) => {
        if (sort === 'installs') return b.installs - a.installs;
        if (sort === 'rating') return b.rating - a.rating;
        return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
      });
  }, [all, category, installedOnly, search, sort]);

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">插件市场</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">扩展客来来能力，一键安装第三方开发者插件</p>
      </div>

      {/* 精选 */}
      {featured.length > 0 && !search && category === 'all' && !installedOnly && (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-slate-200">
            <Sparkles className="h-4 w-4 text-amber-500" /> 精选推荐
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {featured.map((p) => (
              <div key={p.id} className="flex items-start gap-3 rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-4 dark:border-amber-500/20 dark:from-amber-500/10 dark:to-slate-800">
                <span className="text-2xl">{p.icon ?? '🧩'}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1">
                    <h3 className="truncate font-semibold text-gray-900 dark:text-slate-100">{p.name}</h3>
                    {p.publisher_verified && <BadgeCheck className="h-4 w-4 shrink-0 text-blue-500" />}
                  </div>
                  <p className="line-clamp-2 text-xs text-gray-500 dark:text-slate-400">{p.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 工具条 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索插件、功能或标签..."
            className="w-full rounded-lg border py-2 pl-10 pr-4 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>按{s.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setInstalledOnly((v) => !v)}
          className={clsx(
            'flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm',
            installedOnly ? 'border-blue-500 bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-300' : 'hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700'
          )}
        >
          <Check className="h-4 w-4" /> 已安装
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {categories.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={clsx(
              'rounded-full px-3 py-1 text-sm transition-colors',
              category === c ? 'bg-blue-600 text-white' : 'border hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700'
            )}
          >
            {CATEGORY_LABEL[c] ?? c}
          </button>
        ))}
      </div>

      {query.isLoading ? (
        <Loading variant="skeleton" rows={6} text="加载插件..." />
      ) : filtered.length === 0 ? (
        <Empty title="未找到插件" description="尝试更换搜索词或分类" />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filtered.map((p) => (
            <div key={p.id} className="flex flex-col rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
              <div className="flex items-start gap-3">
                <span className="text-2xl">{p.icon ?? '🧩'}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1">
                    <h3 className="truncate font-semibold text-gray-900 dark:text-slate-100">{p.name}</h3>
                    {p.publisher_verified && <BadgeCheck className="h-4 w-4 shrink-0 text-blue-500" />}
                  </div>
                  <p className="text-xs text-gray-400">{p.author} · v{p.version ?? '1.0.0'}</p>
                </div>
              </div>
              <p className="mt-2 line-clamp-2 flex-1 text-sm text-gray-600 dark:text-slate-400">{p.description}</p>
              {p.tags && p.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.tags.map((t) => (
                    <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500 dark:bg-slate-700 dark:text-slate-300">{t}</span>
                  ))}
                </div>
              )}
              <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
                <span className="flex items-center gap-1"><Star className="h-3 w-3 fill-amber-400 text-amber-400" /> {p.rating}</span>
                <span>{p.installs.toLocaleString()} 安装</span>
                <span className={clsx('ml-auto font-medium', p.price === 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-900 dark:text-slate-100')}>
                  {p.price === 0 ? '免费' : `¥${p.price}/月`}
                </span>
              </div>
              <button
                type="button"
                onClick={() => installMutation.mutate(p.id)}
                disabled={p.installed || installMutation.isPending}
                className={clsx(
                  'mt-4 flex w-full items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium',
                  p.installed
                    ? 'cursor-default bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-slate-500'
                    : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
                )}
              >
                {installMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : p.installed ? <Check className="h-4 w-4" /> : <Download className="h-4 w-4" />}
                {p.installed ? '已安装' : '安装'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
