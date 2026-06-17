import { useState, useMemo } from 'react';
import { Search, Copy, ChevronDown, Lock, Terminal } from 'lucide-react';
import { clsx } from 'clsx';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery } from '../hooks/useApiQuery';
import { getAPIDocs } from '../api/openPlatform';
import { toastStore } from '../stores/toast';
import type { ApiEndpointDoc } from '../types';

const BASE_URL = 'http://127.0.0.1:8790/api/kellai';
const METHODS = ['ALL', 'GET', 'POST', 'PUT', 'DELETE'];

const METHOD_TONE: Record<string, string> = {
  GET: 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300',
  POST: 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300',
  PUT: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  DELETE: 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300',
};

export default function APIDocs() {
  const [search, setSearch] = useState('');
  const [method, setMethod] = useState('ALL');
  const [expanded, setExpanded] = useState<string | null>(null);

  const query = useApiQuery<{ endpoints: ApiEndpointDoc[] }>(['open', 'docs'], () => getAPIDocs());
  const endpoints = query.data?.endpoints ?? [];

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return endpoints.filter(
      (e) =>
        (method === 'ALL' || e.method === method) &&
        (!kw || e.path.toLowerCase().includes(kw) || e.description.toLowerCase().includes(kw))
    );
  }, [endpoints, method, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, ApiEndpointDoc[]>();
    for (const e of filtered) {
      const cat = e.category ?? '其他';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(e);
    }
    return [...map.entries()];
  }, [filtered]);

  const copy = (text: string, label: string) =>
    navigator.clipboard?.writeText(text).then(() => toastStore.success(`${label}已复制`));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">API 文档</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">客来来开放平台接口参考与调用示例</p>
      </div>

      {/* Base URL + 认证 */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <span className="text-sm font-medium text-gray-700 dark:text-slate-200">Base URL</span>
        <code className="flex-1 truncate rounded bg-gray-100 px-2 py-1 text-sm text-gray-600 dark:bg-slate-900 dark:text-slate-300">{BASE_URL}</code>
        <button type="button" onClick={() => copy(BASE_URL, 'Base URL')} className="flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400">
          <Copy className="h-3.5 w-3.5" /> 复制
        </button>
        <span className="flex items-center gap-1 text-xs text-gray-400"><Lock className="h-3 w-3" /> 需 Bearer Token 鉴权</span>
      </div>

      {/* 搜索 + 方法过滤 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索接口路径或描述..."
            className="w-full rounded-lg border py-2 pl-10 pr-4 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        <div className="flex gap-1.5">
          {METHODS.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMethod(m)}
              className={clsx(
                'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                method === m ? 'bg-gray-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-300'
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {query.isLoading ? (
        <Loading variant="skeleton" rows={5} text="加载文档..." />
      ) : grouped.length === 0 ? (
        <Empty title="未找到接口" description="调整搜索或方法筛选" />
      ) : (
        <div className="space-y-6">
          {grouped.map(([cat, eps]) => (
            <div key={cat}>
              <h2 className="mb-2 text-sm font-semibold text-gray-500 dark:text-slate-400">{cat}</h2>
              <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
                {eps.map((ep) => {
                  const key = `${ep.method}-${ep.path}`;
                  const isOpen = expanded === key;
                  return (
                    <div key={key} className="border-b last:border-0 dark:border-slate-700">
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : key)}
                        className="flex w-full items-start gap-4 px-6 py-4 text-left hover:bg-gray-50 dark:hover:bg-slate-700/50"
                      >
                        <span className={clsx('mt-0.5 shrink-0 rounded px-2 py-0.5 font-mono text-xs font-bold', METHOD_TONE[ep.method] ?? 'bg-gray-100 text-gray-600')}>
                          {ep.method}
                        </span>
                        <div className="min-w-0 flex-1">
                          <code className="text-sm font-medium text-gray-900 dark:text-slate-100">{ep.path}</code>
                          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">{ep.description}</p>
                        </div>
                        {ep.auth_required && <Lock className="mt-1 h-3.5 w-3.5 shrink-0 text-gray-300 dark:text-slate-600" />}
                        <ChevronDown className={clsx('mt-1 h-4 w-4 shrink-0 text-gray-400 transition-transform', isOpen && 'rotate-180')} />
                      </button>
                      {isOpen && ep.sample && (
                        <div className="px-6 pb-4">
                          <div className="relative rounded-lg bg-gray-900 p-4">
                            <div className="mb-2 flex items-center gap-1 text-xs text-gray-400">
                              <Terminal className="h-3.5 w-3.5" /> cURL 示例
                              <button
                                type="button"
                                onClick={() => copy(ep.sample!.replace(/\{base\}/g, BASE_URL), '示例')}
                                className="ml-auto flex items-center gap-1 text-gray-400 hover:text-white"
                              >
                                <Copy className="h-3.5 w-3.5" /> 复制
                              </button>
                            </div>
                            <pre className="overflow-x-auto text-xs leading-relaxed text-green-300">{ep.sample.replace(/\{base\}/g, BASE_URL)}</pre>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
