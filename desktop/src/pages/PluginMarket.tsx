import { useState } from 'react';
import { Star, Download, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { getPlugins, installPlugin } from '../api/openPlatform';
import { toastStore } from '../stores/toast';
import type { Plugin } from '../types';

export default function PluginMarket() {
  const [category, setCategory] = useState('all');

  const query = useApiQuery<Plugin[]>(['open', 'plugins'], () => getPlugins());

  const installMutation = useApiMutation(
    (id: string) => installPlugin(id),
    {
      onSuccess: () => {
        toastStore.success('插件已安装');
        query.refetch();
      },
    }
  );

  const plugins = (query.data ?? []).filter(
    (p) => category === 'all' || p.category === category
  );

  const categories = ['all', ...new Set((query.data ?? []).map((p) => p.category))];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">插件市场</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">第三方开发者插件</p>
      </div>

      <div className="flex gap-2">
        {categories.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={clsx(
              'rounded-full px-3 py-1 text-sm',
              category === c ? 'bg-blue-600 text-white' : 'border hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700'
            )}
          >
            {c === 'all' ? '全部' : c}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {plugins.map((p) => (
          <div
            key={p.id}
            className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800"
          >
            <h3 className="font-semibold">{p.name}</h3>
            <p className="mt-1 text-sm text-gray-600 dark:text-slate-400">{p.description}</p>
            <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1"><Star className="h-3 w-3 fill-amber-400 text-amber-400" /> {p.rating}</span>
              <span>{p.installs} 安装</span>
              <span>{p.price === 0 ? '免费' : `¥${p.price}`}</span>
            </div>
            <button
              type="button"
              onClick={() => installMutation.mutate(p.id)}
              disabled={p.installed || installMutation.isPending}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {installMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {p.installed ? '已安装' : '安装'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
